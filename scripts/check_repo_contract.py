#!/usr/bin/env python3
"""Check a repository against the dcc-mcp repository contract.

The pass/fail criteria live under ``contract/``. This script only implements the
mechanics; both this CI gate and the ``vx-repo-contract`` skill read those files, so
a rule is never defined twice. Two contracts ship side by side and are selected
with ``--contract``:

    contract/repo_contract.json     R0xx, configuration and documentation contract
                                    for every repository (PIP-3741).
    contract/adapter_contract.json  A0xx, Python adapter package contract: interface
                                    rules plus code-convention rules (PIP-4104).

Rules (repo_contract.json)
--------------------------
    R001 no-root-artifacts       no build/test artifacts at the repository root
    R002 justfile-lowercase      `justfile`, never `Justfile`
    R003 agents-md-exists        AGENTS.md is present
    R004 vx-toml-parses          vx.toml parses and only uses known tables
    R005 tools-version-format    [tools] pins are stable/latest/X[.Y[.Z]]
    R006 root-allowlist          every top-level entry is allowlisted
    R007 no-scripts-with-justfile no [scripts] entry forwards to just or shadows a recipe
    R008 agents-derived-symlink  CLAUDE.md & friends are symlinks or generated
    R009 tools-no-latest         [tools] pins are concrete, not `latest`
    R010 llms-txt-fresh          llms.txt exists when a generator exists
    R011 no-tracked-agent-dirs   nothing is tracked under an agents_ide_dir

Rules (adapter_contract.json)
-----------------------------
    A001 no-deprecated-install-sop-alias    no reference to Core's deprecated alias
    A002 no-hand-rolled-report-schema-version  read the report schema version from Core
    A003 core-floor-declared                a declared Core dep pins a lower bound
    A012 core-floor-baseline                the declared floor is at/above the org baseline
    A004 ruff-line-length                   [tool.ruff] line-length is the baseline
    A005 requires-python-declared           project.requires-python is declared
    A006 pre-commit-config-exists           .pre-commit-config.yaml is present
    A013 doctor-module-present              install adapters ship a doctor self-check
    A014 report-validates-against-schema    a real report is validated once

A007–A012 are unassigned: the Install SOP interface family was numbered A010–A014
by its owning issue (PIP-4106) before A001–A006 existed, and the three rules that
overlapped A001–A003 were superseded by them rather than renumbered.

Profiles
--------
    baseline  the rules every repository satisfies today.
    strict    every rule. Rules still being rolled out report as warnings so that a
              repository can adopt the gate before it is clean; promote them with
              ``--error-rule`` or fail the job on warnings with ``--fail-on warning``.

Exit codes
----------
    0  no finding at or above --fail-on
    1  at least one finding at or above --fail-on
    2  the check could not be performed (bad path, unreadable contract, ...)
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = ROOT / "contract" / "repo_contract.json"
ADAPTER_CONTRACT_PATH = ROOT / "contract" / "adapter_contract.json"

SEVERITY_ORDER = {"notice": 0, "warning": 1, "error": 2}
SEVERITY_ALIASES = {"warn": "warning", "err": "error"}
MAX_PROVENANCE_SCAN_LINES = 10
# R011 reports each tracked file, so cap the output: a whole skill tree should
# still fail, but not by printing the same finding two hundred times.
MAX_TRACKED_AGENT_FILES = 20
GIT_LS_FILES_TIMEOUT_SECONDS = 30

JUSTFILE_NAMES = ("justfile", ".justfile", "JUSTFILE", "Justfile")


class ContractError(Exception):
    """Raised when the check cannot be performed."""


@dataclass(frozen=True)
class Finding:
    rule_id: str
    rule_name: str
    severity: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class Contract:
    path: Path
    data: dict[str, Any]
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Contract":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ContractError(f"cannot read contract {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ContractError(f"contract {path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            raise ContractError(f"contract {path} has no `rules` array")
        rules = {}
        for rule in data["rules"]:
            rule_id = rule.get("id")
            if not rule_id:
                raise ContractError(f"contract {path} has a rule without an id")
            severity = SEVERITY_ALIASES.get(rule.get("severity"), rule.get("severity"))
            if severity not in SEVERITY_ORDER:
                raise ContractError(
                    f"contract {path}: rule {rule_id} has unknown severity "
                    f"{rule.get('severity')!r}; expected one of {sorted(SEVERITY_ORDER)}"
                )
            rule = dict(rule, severity=severity)
            rules[rule_id] = rule
        if not rules:
            raise ContractError(f"contract {path} defines no rules")
        return cls(path=path, data=data, rules=rules)

    def value(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


# --------------------------------------------------------------------------- toml


def _strip_comment(value: str) -> str:
    """Remove a trailing ``#`` comment that sits outside quotes."""
    quote = ""
    for index, char in enumerate(value):
        if quote:
            if char == "\\" and quote == '"':
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            return value[:index].strip()
    return value.strip()


INLINE_VERSION_RE = re.compile(r"""version\s*=\s*["']([^"']*)["']""")


def _unwrap_inline_table(raw: str) -> str:
    """Reduce ``{ version = "1.2.3", os = ["windows"] }`` to its version string.

    ``[tools]`` entries may be declared as inline tables when they carry extra
    fields such as ``os``. For the contract only the pinned version matters.
    """
    if not raw.startswith("{"):
        return raw
    match = INLINE_VERSION_RE.search(raw)
    return match.group(1) if match else raw


def _coerce(raw: str) -> Any:
    """Return the value of a scalar, keeping version numbers as written.

    Numbers are deliberately left as text: ``python = 3.11`` must stay ``"3.11"``
    so that a version check sees exactly what the author typed rather than a
    float that has been through a binary round trip.
    """
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return raw


def _consume_multiline_value(
    lines: list[str], index: int, value: str
) -> tuple[str, int]:
    """Join a TOML multi-line string or array onto one logical value.

    Returns the joined text and the index of the last line that belongs to the
    value, so the caller can skip the continuation lines instead of reporting
    them as unparseable.
    """
    stripped = value.strip()
    for delimiter in ("'''", '"""'):
        if not stripped.startswith(delimiter):
            continue
        if delimiter in stripped[len(delimiter) :]:
            return value, index
        collected = [value]
        cursor = index + 1
        while cursor < len(lines):
            collected.append(lines[cursor])
            if delimiter in lines[cursor]:
                return "\n".join(collected), cursor
            cursor += 1
        return "\n".join(collected), len(lines) - 1
    if not stripped.startswith("["):
        return value, index
    # An array may span lines (`dependencies = [...]`). Join it, dropping the
    # trailing comments line by line so that a comment cannot swallow the rest
    # of the array, and stop as soon as the brackets balance. The opening line
    # carries the `value` the caller already split off, so it needs the same
    # comment stripping as every continuation line: a `dependencies = [  # note`
    # head would otherwise parse as the bare `[` and drop the whole array.
    collected: list[str] = []
    depth = 0
    quote = ""
    cursor = index
    while cursor < len(lines):
        line = _strip_comment(lines[cursor] if cursor != index else value)
        collected.append(line)
        for char in line:
            if quote:
                if char == quote:
                    quote = ""
            elif char in "\"'":
                quote = char
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
        if depth <= 0:
            break
        cursor += 1
    return "\n".join(collected), cursor


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split on `separator`, ignoring separators inside quotes and brackets."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    depth = 0
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _parse_string_array(raw: str) -> list[str] | None:
    """Parse a TOML array of strings into a list.

    Returns ``None`` when the text is not a single bracketed array, so that a
    value the parser does not understand is left alone rather than mangled.
    """
    text = raw.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    items = []
    for chunk in _split_top_level(text[1:-1]):
        chunk = _strip_comment(chunk).strip()
        if not chunk:
            continue
        items.append(_coerce(chunk))
    return items


def parse_vx_toml(text: str) -> tuple[dict[str, Any], list[tuple[int, str]]]:
    """Parse the TOML subset used by ``vx.toml``.

    Returns the parsed mapping plus the lines that could not be understood. The
    parser is deliberately lenient: it never raises, because a syntax error is a
    reportable finding rather than a crash.
    """
    data: dict[str, Any] = {}
    unparsed: list[tuple[int, str]] = []
    table: str | None = None
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        lineno = index + 1
        line = raw.strip()
        if not line or line.startswith("#"):
            index += 1
            continue
        if line.startswith("[") and line.endswith("]") and not line.startswith("[["):
            table = line[1:-1].strip().strip("\"'")
            data.setdefault(table, {})
            index += 1
            continue
        if "=" not in line:
            unparsed.append((lineno, raw))
            index += 1
            continue
        key, _, value = line.partition("=")
        value, index = _consume_multiline_value(lines, index, value)
        key = key.strip().strip("\"'")
        if not key:
            unparsed.append((lineno, raw))
            index += 1
            continue
        target = data if table is None else data.setdefault(table, {})
        value = _coerce(_unwrap_inline_table(_strip_comment(value.strip())))
        if isinstance(value, str) and value.startswith("["):
            array = _parse_string_array(value)
            if array is not None:
                value = array
        target[key] = value
        index += 1
    return data, unparsed


# --------------------------------------------------------------------- utilities


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _top_level_entries(root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    dirs: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if entry.name == ".git":
            continue
        (dirs if entry.is_dir() else files).append(entry)
    return files, dirs


def _find_justfile(files: Sequence[Path]) -> Path | None:
    by_name = {path.name: path for path in files}
    for name in JUSTFILE_NAMES:
        if name in by_name:
            return by_name[name]
    return None


def _justfile_recipes(path: Path) -> set[str]:
    recipes: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return recipes
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("@"):
            continue
        if line[:1].isspace():
            continue
        head = re.split(r"\s*(?::=|\+=|:|\s)", stripped, maxsplit=1)[0]
        if head and re.fullmatch(r"[A-Za-z0-9_@\-]+", head):
            recipes.add(head.lstrip("@"))
    return recipes


# ------------------------------------------------------------------ source scan


def _iter_source_files(root: Path, contract: Contract) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Walk the repository for in-scope source files.

    Returns the files to parse plus the ones that were deliberately skipped, so
    that a blind spot is reported instead of silently shrinking the gate.
    """
    suffixes = tuple(contract.value("scan_suffixes", [".py"]))
    exclude_dirs = set(contract.value("scan_exclude_dirs", []))
    exclude_globs = contract.value("scan_exclude_globs", [])
    max_files = int(contract.value("scan_max_files", 20000))
    max_bytes = int(contract.value("scan_max_file_bytes", 2000000))
    files: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in exclude_dirs and not name.startswith(".")
        )
        for name in sorted(filenames):
            if not name.endswith(suffixes):
                continue
            path = Path(dirpath) / name
            relative = _rel(root, path)
            if _matches_any(relative, exclude_globs):
                continue
            if len(files) >= max_files:
                truncated = True
                skipped.append((path, f"beyond scan_max_files ({max_files})"))
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                skipped.append((path, f"unreadable: {exc}"))
                continue
            if size > max_bytes:
                skipped.append((path, f"{size} bytes exceeds scan_max_file_bytes"))
                continue
            files.append(path)
    if truncated:
        print(
            f"::warning title=Repo contract::stopped scanning at scan_max_files ({max_files})",
            file=sys.stderr,
        )
    return files, skipped


def _source_modules(
    root: Path, contract: Contract
) -> tuple[list[tuple[Path, ast.Module]], list[tuple[Path, str]]]:
    """Parse every in-scope source file once.

    A file that cannot be read or parsed is reported as skipped rather than
    crashed on: one odd file must not take the whole gate down, and a silent
    skip would make the gate weaker than it looks.
    """
    files, skipped = _iter_source_files(root, contract)
    modules: list[tuple[Path, ast.Module]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            skipped.append((path, f"unreadable: {exc}"))
            continue
        try:
            modules.append((path, ast.parse(text, filename=str(path))))
        except (SyntaxError, ValueError) as exc:
            skipped.append((path, f"not parseable as Python: {exc}"))
    return modules, skipped


def _prepare_scan(
    root: Path, contract: Contract, ctx: dict, rule: dict
) -> tuple[list[tuple[Path, ast.Module]], list[Finding]]:
    """Return the parsed modules plus the scan notices, emitted only once.

    Several rules share one parse of the tree. The skip notices belong to the
    run rather than to any single rule, so they ride along with whichever rule
    asks first and are emitted exactly once.
    """
    if "modules" not in ctx:
        ctx["modules"], skipped = _source_modules(root, contract)
        ctx["scan_notices"] = [
            Finding(rule["id"], rule["name"], "notice", _rel(root, path), f"skipped: {reason}")
            for path, reason in skipped
        ]
        ctx["scan_notices_pending"] = True
    if ctx.get("scan_notices_pending"):
        ctx["scan_notices_pending"] = False
        return ctx["modules"], ctx["scan_notices"]
    return ctx["modules"], []


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _source_texts(
    modules: Sequence[tuple[Path, ast.Module]]
) -> list[tuple[Path, str]]:
    """Return the scanned sources as (path, text) for the rules that read text.

    A013 and A014 look for names anywhere in a module, including in a literal or
    a workflow file, which is a text question rather than a syntax question. The
    text is not cached in ``ctx``: a repository this gate scans is small enough
    that a second read costs far less than a cache that can go stale.
    """
    return [(path, _read_text(path) or "") for path, _ in modules]


def _has_install_sop_surface(
    root: Path, contract: Contract, sources: Sequence[tuple[Path, str]]
) -> bool:
    """True when the repository assembles an Install SOP report at all.

    A013 and A014 are about the report, so they are skipped for the ~42 adapters
    that have no install capability rather than reported. Two signals count: a
    source file that touches one of the Core symbols a report assembler has to
    touch, or a module named for installation -- the second catches an adapter
    that has not yet adopted the shared symbols.
    """
    symbols = [symbol for symbol in contract.value("install_sop_symbols", []) if symbol]
    if symbols:
        pattern = re.compile(
            "|".join(r"\b" + re.escape(symbol) + r"\b" for symbol in symbols)
        )
        for _path, text in sources:
            if pattern.search(text):
                return True
    for pattern in contract.value("install_source_globs", []):
        if any(root.glob(pattern)):
            return True
    return False


def _dotted_name(node: ast.AST) -> str:
    """Return `dcc_mcp_core.deployment.X` for a Name/Attribute chain, else ''."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    """Map a local name onto the module it was imported as.

    `import dcc_mcp_core.deployment as deployment` binds a name that no longer
    looks like the provider, so a dotted-name check alone would miss it.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            aliases[bound] = alias.name
    return aliases


def _resolve_dotted(dotted: str, aliases: dict[str, str]) -> str:
    """Rewrite the head of a dotted name through the module alias map."""
    head, _, rest = dotted.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{rest}" if rest else resolved


def _assignment_targets(node: ast.AST) -> list[ast.Name]:
    if isinstance(node, ast.Assign):
        return [target for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign):
        return [node.target] if isinstance(node.target, ast.Name) else []
    if isinstance(node, ast.AugAssign):
        return [node.target] if isinstance(node.target, ast.Name) else []
    return []


def _int_constant(node: ast.AST) -> int | None:
    """Return the value of an integer literal, or None for anything else."""
    # `ast.Num` is the Python 3.7 spelling of `ast.Constant`. It is reached
    # lazily and only on 3.7, because merely touching it on 3.12+ emits a
    # DeprecationWarning; the organisation's Python 3.7 red line (PIP-2519)
    # runs to 2026-12-31.
    if sys.version_info >= (3, 8):
        if not isinstance(node, ast.Constant):
            return None
        value = node.value
    else:
        legacy: Any = getattr(ast, "Num", ())
        if not (legacy and isinstance(node, legacy)):
            return None
        value = node.n
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _pyproject(contract: Contract, ctx: dict) -> dict[str, Any]:
    """Parse pyproject.toml once per run with the shared lenient parser."""
    if "pyproject" not in ctx:
        path = Path(ctx["root"]) / contract.value("pyproject_file", "pyproject.toml")
        ctx["pyproject"] = (
            parse_vx_toml(path.read_text(encoding="utf-8", errors="replace"))[0]
            if path.is_file()
            else {}
        )
    return ctx["pyproject"]


def _value(data: dict[str, Any], name: str) -> Any:
    """Resolve a dotted path against a parsed pyproject.toml.

    ``[tool.ruff]`` arrives as the literal key ``tool.ruff``, while
    ``dependencies`` under ``[project]`` arrives nested two levels down, so a
    flat lookup is tried first and a nested walk second.
    """
    if name in data:
        return data[name]
    current: Any = data
    for part in name.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    table = _value(data, name)
    return table if isinstance(table, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str):
        return [value]
    return []


def _requirement_strings(value: Any) -> list[str]:
    """Flatten a dependency table into PEP 508 requirement strings.

    ``[project.dependencies]`` is a list of strings, while poetry spells the
    same thing as a table of ``name = spec`` entries. A rule that promises to
    read both tables has to flatten the table form too, or the poetry half of
    that promise inspects nothing and reports no finding at all.
    """
    if not isinstance(value, dict):
        return _string_list(value)
    requirements: list[str] = []
    for name, spec in value.items():
        if isinstance(spec, str):
            requirements.append(f"{name} {spec}" if spec else name)
        elif isinstance(spec, list):
            # Poetry allows several constraints: `dcc-mcp-core = [">=0.20.40", "<1"]`.
            constraints = [item for item in spec if isinstance(item, str)]
            if constraints:
                requirements.append(f"{name} {','.join(constraints)}")
        elif isinstance(spec, dict) and isinstance(spec.get("version"), str):
            requirements.append(f"{name} {spec['version']}")
    return requirements


def _version_tuple(value: str) -> tuple[int, ...]:
    """Parse the leading numeric part of a version, ignoring any pre-release."""
    numbers: list[int] = []
    for part in re.split(r"[.\-+]", str(value).strip()):
        if not part.isdigit():
            break
        numbers.append(int(part))
    return tuple(numbers)


def _version_cmp(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Compare release tuples, padding the shorter one with zeros."""
    width = max(len(left), len(right))
    a = tuple(list(left) + [0] * (width - len(left)))
    b = tuple(list(right) + [0] * (width - len(right)))
    return (a > b) - (a < b)


def _floor_versions(requirement: str, operators: Sequence[str]) -> list[str]:
    """Every version a requirement pins as a lower bound.

    Upper bounds are ignored because ``core_floor_operators`` never contains
    ``<``; the operators are matched longest-first so that ``>=`` wins over the
    ``>`` it starts with.
    """
    versions: list[str] = []
    for operator in sorted(operators, key=len, reverse=True):
        pattern = re.escape(operator) + r"\s*([0-9][0-9A-Za-z.\-+]*)"
        versions.extend(match.group(1) for match in re.finditer(pattern, requirement))
    return versions


# ------------------------------------------------------------------------- rules


def check_no_root_artifacts(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R001"]
    patterns = contract.value("forbidden_artifact_globs", [])
    findings = []
    files, _ = ctx["files"], ctx["dirs"]
    for path in files:
        if path.name == ".gitignore":
            continue
        if _matches_any(path.name, patterns):
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    rule["severity"],
                    _rel(root, path),
                    (
                        f"build artifact `{path.name}` is committed at the repository root; "
                        "add it to .gitignore and remove the tracked file"
                    ),
                )
            )
    return findings


def check_justfile_lowercase(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R002"]
    files = ctx["files"]
    findings = []
    for path in files:
        if path.name.lower() == "justfile" and path.name != "justfile":
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    rule["severity"],
                    _rel(root, path),
                    (
                        f"`{path.name}` must be lowercase `justfile`; just only auto-discovers "
                        "`justfile` or `.justfile`, so a capitalised name breaks case-sensitive CI"
                    ),
                )
            )
    return findings


def check_agents_md_exists(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R003"]
    source = contract.value("agents_source_file", "AGENTS.md")
    if (root / source).is_file():
        return []
    return [
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            source,
            f"`{source}` is missing; it is the single source of truth for agent instructions",
        )
    ]


def check_vx_toml_parses(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R004"]
    vx_toml = root / "vx.toml"
    if not vx_toml.is_file():
        return []
    text = vx_toml.read_text(encoding="utf-8", errors="replace")
    parsed, unparsed = parse_vx_toml(text)
    findings = []
    for lineno, raw in unparsed:
        findings.append(
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                "vx.toml",
                f"line {lineno} is not valid TOML: `{raw.strip()}`",
            )
        )
    known = set(contract.value("vx_toml_known_tables", []))
    for table in parsed:
        # `[tools.pwsh]` is a sub-table of `[tools]`, not an unknown top-level table.
        if table.split(".", 1)[0] not in known:
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    "warning",
                    "vx.toml",
                    f"unknown table `[{table}]`; expected one of {sorted(known)}",
                )
            )
    ctx["vx"] = parsed
    return findings


def check_tools_version_format(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R005"]
    vx: dict[str, Any] = ctx.get("vx") or {}
    tools = vx.get("tools")
    if not isinstance(tools, dict):
        return []
    pattern = re.compile(contract.value("tools_version_pattern", r"^.+$"))
    sentinels = contract.value("tools_delegation_sentinels", {})
    if not isinstance(sentinels, dict):
        sentinels = {}
    findings = []
    for name in sorted(tools):
        value = tools[name]
        if isinstance(value, str) and pattern.match(value):
            continue
        # A delegation sentinel is an ownership declaration, not a version: another
        # manager owns the toolchain and vx deliberately keeps its hands off. vx can
        # still resolve the pin (to "ask the other manager"), so R005 accepts it --
        # but only for the tool that declares it, never as a blanket escape hatch.
        declared = sentinels.get(name) if isinstance(value, str) else None
        if isinstance(declared, list) and value in declared:
            continue
        findings.append(
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                "vx.toml",
                (
                    f"[tools] {name} = {value!r} is not a recognised pin; use `stable`, "
                    "`latest`, or a numeric X, X.Y, X.Y.Z"
                ),
            )
        )
    return findings


def check_root_allowlist(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R006"]
    allow = contract.value("root_allowlist", {})
    allowed_files = set(allow.get("files", []))
    allowed_dirs = set(allow.get("dirs", []))
    deprecated = contract.value("root_deprecated", {})
    extra = set(ctx.get("allow_extra") or ())
    deny = contract.value("root_deny_globs", [])
    deny_exceptions = set(contract.value("root_deny_exceptions", []))
    findings = []
    for path in list(ctx["files"]) + list(ctx["dirs"]):
        name = path.name
        if name in allowed_files or name in allowed_dirs or name in extra:
            continue
        if name not in deny_exceptions and _matches_any(name, deny):
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    "error",
                    _rel(root, path),
                    (
                        f"`{name}` is a stray top-level file; ad-hoc reports and scripts belong "
                        "under docs/ or scripts/, not at the repository root"
                    ),
                )
            )
            continue
        hint = deprecated.get(name)
        if hint:
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    "warning",
                    _rel(root, path),
                    f"`{name}` is deprecated: {hint}",
                )
            )
            continue
        kind = "directory" if path.is_dir() else "file"
        findings.append(
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                _rel(root, path),
                (
                    f"top-level {kind} `{name}` is not on the contract allowlist; move it "
                    "under docs/, delete it, or allow it with --allow-extra"
                ),
            )
        )
    return findings


def _normalise_recipe_name(name: str, separators: Sequence[str]) -> str:
    """Fold the separators that just and vx treat as interchangeable."""
    folded = name
    for sep in separators:
        folded = folded.replace(sep, "-")
    return folded.lower()


def _script_forwards_to_just(command: Any, commands: Sequence[str]) -> str | None:
    """Return the recipe a [scripts] value delegates to, or None.

    A script may be a single line or a triple-quoted block; only the leading
    command matters, so leading whitespace and the block delimiters are stripped
    before matching. Nothing after the recipe name is considered: `just test --
    --nocapture` still forwards to `test`.
    """
    if not isinstance(command, str):
        return None
    text = command.strip()
    for fence in ('"""', "'''"):
        if text.startswith(fence):
            text = text[len(fence) :]
        if text.endswith(fence):
            text = text[: -len(fence)]
    for line in text.splitlines():
        stripped = line.strip().strip('"').strip("'").strip()
        if not stripped:
            continue
        for prefix in sorted(commands, key=len, reverse=True):
            if stripped == prefix:
                return ""
            lead = prefix + " "
            if stripped.startswith(lead):
                recipe = stripped[len(lead) :].split(None, 1)[0].strip('"').strip("'")
                return recipe
        break
    return None


def check_no_scripts_with_justfile(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R007"]
    justfile = ctx.get("justfile")
    if justfile is None:
        return []
    vx: dict[str, Any] = ctx.get("vx") or {}
    scripts = vx.get("scripts")
    if not isinstance(scripts, dict) or not scripts:
        return []
    commands = contract.value("scripts_just_forward_commands", ["just", "vx just"])
    if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
        commands = ["just", "vx just"]
    separators = contract.value("scripts_recipe_name_separators", ["-", "_"])
    if not isinstance(separators, list) or not all(
        isinstance(item, str) and item for item in separators
    ):
        separators = ["-", "_"]
    recipes = {
        _normalise_recipe_name(name, separators) for name in _justfile_recipes(justfile)
    }
    findings = []
    for name in sorted(scripts):
        command = scripts[name]
        forwarded = _script_forwards_to_just(command, commands)
        if forwarded is not None:
            reason = (
                f"forwards to `{forwarded or 'just'}`"
                if forwarded
                else "forwards to just itself"
            )
        elif _normalise_recipe_name(name, separators) in recipes:
            reason = f"shares the name of justfile recipe `{name}`"
        else:
            continue
        findings.append(
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                "vx.toml",
                (
                    f"[scripts] {name} = {command!r} duplicates `{justfile.name}`: {reason}; "
                    "run the recipe from the justfile or drop it from [scripts]"
                ),
            )
        )
    return findings


def check_agents_derived_symlink(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R008"]
    source = contract.value("agents_source_file", "AGENTS.md")
    derived = contract.value("agents_derived_files", [])
    marker = contract.value("agents_provenance_marker", "")
    findings = []
    for name in derived:
        path = root / name
        if not path.exists():
            continue
        if path.is_symlink():
            target = ""
            try:
                target = path.resolve().name
            except OSError:
                target = ""
            if target != source:
                findings.append(
                    Finding(
                        rule["id"],
                        rule["name"],
                        rule["severity"],
                        name,
                        f"`{name}` is a symlink to `{target or '?'}`, expected `{source}`",
                    )
                )
            continue
        if not path.is_file():
            continue
        try:
            head = "\n".join(
                path.read_text(encoding="utf-8", errors="replace").splitlines()[
                    :MAX_PROVENANCE_SCAN_LINES
                ]
            )
        except OSError:
            head = ""
        if marker and marker.lower() in head.lower():
            continue
        findings.append(
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                name,
                (
                    f"`{name}` is a hand-maintained copy; make it a symlink to `{source}` or "
                    f"generate it with a `{marker}` header"
                ),
            )
        )
    for name in contract.value("agents_ide_dirs", []):
        path = root / name
        if path.is_dir() and not path.is_symlink():
            if _tracked_files_under(root, name):
                # R011 reports each tracked file at error severity. Warning about
                # the directory as well would only duplicate the finding.
                continue
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    "warning",
                    name,
                    (
                        f"agent directory `{name}/` is committed; generate it from `{source}` "
                        "at setup time and keep it out of version control"
                    ),
                )
            )
    return findings


def _tracked_files_under(root: Path, rel: str) -> list[str]:
    """Files version-controlled under ``rel``, relative to ``root``.

    Prefers ``git ls-files`` so that untracked output sitting inside an ignored
    agent directory is not reported — "present on disk" and "committed" are not
    the same thing once the directory is ignored. Falls back to a filesystem
    walk when the target is not a git working tree (a tarball export, or the
    temp directories the contract tests build), where every file present is the
    best available approximation of the tracked set.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--", rel],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GIT_LS_FILES_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        proc = None
    if proc is not None and proc.returncode == 0:
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    path = root / rel
    if not path.is_dir():
        return []
    return sorted(
        item.relative_to(root).as_posix() for item in path.rglob("*") if item.is_file()
    )


def check_no_tracked_agent_dirs(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R011"]
    findings = []
    for name in contract.value("agents_ide_dirs", []):
        path = root / name
        if not path.is_dir() or path.is_symlink():
            continue
        tracked = _tracked_files_under(root, name)
        if not tracked:
            continue
        for rel_file in tracked[:MAX_TRACKED_AGENT_FILES]:
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    rule["severity"],
                    rel_file,
                    (
                        f"`{rel_file}` is tracked under the agent/IDE directory `{name}/`; "
                        f"add `/{name}/` to .gitignore and untrack it, or move the asset to "
                        "a committed path outside the agent directories"
                    ),
                )
            )
        hidden = len(tracked) - MAX_TRACKED_AGENT_FILES
        if hidden > 0:
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    rule["severity"],
                    name + "/",
                    f"... and {hidden} more tracked file(s) under `{name}/`",
                )
            )
    return findings


def check_tools_no_latest(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R009"]
    vx: dict[str, Any] = ctx.get("vx") or {}
    tools = vx.get("tools")
    if not isinstance(tools, dict):
        return []
    allowed = set(contract.value("tools_latest_allowed", []))
    findings = []
    for name in sorted(tools):
        if tools[name] == "latest" and name not in allowed:
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    rule["severity"],
                    "vx.toml",
                    (
                        f"[tools] {name} = \"latest\" makes the build unreproducible; pin a "
                        "concrete version"
                    ),
                )
            )
    return findings


def check_llms_txt_fresh(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R010"]
    generators = []
    for candidate in contract.value("llms_generator_paths", []):
        if (root / candidate).exists():
            generators.append(candidate)
    justfile = ctx.get("justfile")
    recipes = contract.value("llms_justfile_recipes", [])
    if justfile is not None and recipes:
        found = _justfile_recipes(justfile) & set(recipes)
        for recipe in sorted(found):
            generators.append(f"{justfile.name}:{recipe}")
    if not generators:
        return []
    if (root / "llms.txt").is_file():
        return []
    return [
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            "llms.txt",
            (
                "`llms.txt` is missing although the repository ships a generator "
                f"({', '.join(generators)}); run it and commit the result"
            ),
        )
    ]


def check_no_deprecated_install_sop_alias(
    root: Path, contract: Contract, ctx: dict
) -> list[Finding]:
    """A001 — adapter code must not reference a deprecated Core symbol.

    Three reference shapes are reported: an import from the provider package, a
    module-qualified attribute access, and a local rebinding (the
    ``except ImportError:`` fallback that exists only to support the import, and
    the ``__all__`` re-export that keeps the deprecated name in the adapter's
    own public surface). Comments and docstrings are invisible here because the
    check runs on the syntax tree, not on text.

    Files under `provider_package_dirs` are exempt: the provider is allowed to
    define and re-export the deprecated alias, its consumers are not.
    """
    rule = contract.rules["A001"]
    symbols = contract.value("deprecated_symbols", {})
    if not isinstance(symbols, dict) or not symbols:
        return []
    prefixes = tuple(contract.value("provider_modules", []))
    provider_globs = contract.value("provider_package_dirs", [])
    modules, notices = _prepare_scan(root, contract, ctx, rule)
    findings = list(notices)
    for path, tree in modules:
        relative = _rel(root, path)
        if _matches_any(relative, provider_globs):
            continue
        hits: dict[str, list[int]] = {}
        aliases = _module_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not any(
                    module == prefix or module.startswith(prefix + ".") for prefix in prefixes
                ):
                    continue
                for alias in node.names:
                    if alias.name in symbols:
                        hits.setdefault(alias.name, []).append(node.lineno)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in symbols:
                        hits.setdefault(alias.name, []).append(node.lineno)
            elif isinstance(node, ast.Attribute):
                if node.attr not in symbols:
                    continue
                dotted = _resolve_dotted(_dotted_name(node), aliases)
                if any(
                    dotted == prefix or dotted.startswith(prefix + ".") for prefix in prefixes
                ):
                    hits.setdefault(node.attr, []).append(node.lineno)
            else:
                for target in _assignment_targets(node):
                    if target.id in symbols:
                        hits.setdefault(target.id, []).append(node.lineno)
        for symbol in sorted(hits):
            lines = ", ".join(f"L{lineno}" for lineno in sorted(set(hits[symbol])))
            findings.append(
                Finding(
                    rule["id"],
                    rule["name"],
                    rule["severity"],
                    relative,
                    (
                        f"`{symbol}` is a deprecated dcc-mcp-core alias ({lines}); "
                        f"{symbols[symbol]}"
                    ),
                )
            )
    return findings


def check_no_hand_rolled_report_schema_version(
    root: Path, contract: Contract, ctx: dict
) -> list[Finding]:
    """A002 — the report schema version is a value Core already publishes.

    A module-level ``*_REPORT_SCHEMA_VERSION = 2`` is a second source of truth
    for the schema ``const``. It is reported as a warning only: converging a
    repository on ``install_sop_report_schema_version()`` first needs its Core
    floor raised to >=0.20.40, which is PIP-4101's job, not this gate's.
    """
    rule = contract.rules["A002"]
    globs = contract.value("hand_rolled_schema_version_globs", [])
    modules, notices = _prepare_scan(root, contract, ctx, rule)
    findings = list(notices)
    for path, tree in modules:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = getattr(node, "value", None)
            if value is None:
                continue
            number = _int_constant(value)
            if number is None:
                continue
            for target in _assignment_targets(node):
                if not _matches_any(target.id, globs):
                    continue
                findings.append(
                    Finding(
                        rule["id"],
                        rule["name"],
                        rule["severity"],
                        _rel(root, path),
                        (
                            f"`{target.id} = {number}` (L{node.lineno}) hard-codes the report "
                            "schema version; read it from "
                            "`install_sop_report_schema_version()` once the Core floor is "
                            ">=0.20.40 (PIP-4101)"
                        ),
                    )
                )
    return findings


def check_core_floor_declared(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A003 — a declared Core dependency pins a lower bound.

    Only the runtime dependency tables are read. Extras are excluded on purpose:
    `dcc-mcp-core[test]` in a dev extra is a self-reference, not a deployment
    requirement. A repository that declares no Core dependency at all is out of
    scope for an adapter contract and is skipped rather than failed.

    Both spellings of a dependency table are flattened first: `[project.dependencies]`
    is a list of requirement strings, `[tool.poetry.dependencies]` is a table of
    `name = spec` entries.
    """
    rule = contract.rules["A003"]
    data = _pyproject(contract, ctx)
    names = {name.lower() for name in contract.value("core_distributions", [])}
    tables = contract.value("core_dependency_tables", [])
    operators = tuple(contract.value("core_floor_operators", [">="]))
    name = contract.value("pyproject_file", "pyproject.toml")
    findings = []
    seen = False
    for table_name in tables:
        for requirement in _requirement_strings(_value(data, table_name)):
            distribution = re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0].strip()
            if distribution.lower() not in names:
                continue
            seen = True
            if not any(operator in requirement for operator in operators):
                findings.append(
                    Finding(
                        rule["id"],
                        rule["name"],
                        rule["severity"],
                        name,
                        (
                            f"[{table_name}] `{requirement}` pins no lower bound; declare one "
                            f"with {', '.join(operators)} so a resolve cannot silently pick "
                            "any installed Core"
                        ),
                    )
                )
    if not seen:
        return []
    return findings


def check_core_floor_baseline(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A012 — the declared Core floor is at or above the organisation baseline.

    A003 already fails a Core dependency that pins no bound at all, so this rule
    stays silent in that case: one gap, one finding. What it adds is the ratchet.
    The floor a repository has to *declare* and the floor the organisation has
    agreed to *sit at* are different numbers, and only the second one moves the
    fleet.

    ``core_floor_baseline`` is the highest floor any adapter already declares, so
    the target is reachable on the day the rule lands rather than aspirational —
    a baseline nobody meets is noise, not a signal. ``core_floor_target`` is where
    the shared Install SOP API becomes unconditionally available; sitting above
    the baseline but short of the target is a notice, which is reported but can
    never fail a run.
    """
    rule = contract.rules["A012"]
    baseline_value = contract.value("core_floor_baseline")
    target_value = contract.value("core_floor_target")
    if not baseline_value and not target_value:
        return []
    data = _pyproject(contract, ctx)
    names = {name.lower() for name in contract.value("core_distributions", [])}
    tables = contract.value("core_dependency_tables", [])
    operators = list(contract.value("core_floor_operators", [">="]))
    name = contract.value("pyproject_file", "pyproject.toml")

    declared = False
    best: tuple[tuple[int, ...], str] | None = None
    for table_name in tables:
        for requirement in _requirement_strings(_value(data, table_name)):
            distribution = re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0].strip()
            if distribution.lower() not in names:
                continue
            declared = True
            for version in _floor_versions(requirement, operators):
                parsed = _version_tuple(version)
                if parsed and (best is None or _version_cmp(parsed, best[0]) > 0):
                    best = (parsed, version)
    if not declared or best is None:
        # No Core dependency at all (out of scope), or A003 is already reporting
        # the missing bound.
        return []

    baseline = _version_tuple(baseline_value) if baseline_value else None
    target = _version_tuple(target_value) if target_value else None
    if baseline and _version_cmp(best[0], baseline) < 0:
        return [
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                name,
                (
                    f"declared Core floor `{best[1]}` is below the organisation baseline "
                    f"`{baseline_value}`; the fleet spans 54 patch versions from "
                    ">=0.18.2 (dcc-mcp-powerpoint) to >=0.20.36"
                ),
            )
        ]
    if target and _version_cmp(best[0], target) < 0:
        return [
            Finding(
                rule["id"],
                rule["name"],
                "notice",
                name,
                (
                    f"declared Core floor `{best[1]}` meets the baseline "
                    f"`{baseline_value}` but is below the target `{target_value}`; "
                    "`install_sop_report_schema_version()` and "
                    "`validate_install_sop_report()` are only present from 0.20.40"
                ),
            )
        ]
    return []


def _line_length_finding(
    rule: dict, path: str, target: object, declared: object
) -> list[Finding]:
    """The single verdict A004 renders, wherever line-length was declared.

    ``path`` is the file the setting was read from, so the finding points at the
    file a contributor actually has to edit.
    """
    if declared is None:
        return [
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                path,
                (
                    f"declares no line-length; set `line-length = {target}` to match "
                    "the organisation baseline"
                ),
            )
        ]
    try:
        value = int(str(declared).strip())
    except ValueError:
        return [
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                path,
                f"line-length = {declared!r} is not an integer",
            )
        ]
    if value == int(target):
        return []
    return [
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            path,
            (
                f"line-length = {value}; converge on {target} (core, maya, blender, houdini, "
                "nuke, zbrush and substance3d-* already use it)"
            ),
        )
    ]


def check_ruff_line_length(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A004 — the ruff line-length converges on one value.

    The setting is read the way ruff itself resolves it: a standalone
    ``ruff.toml`` (or ``.ruff.toml``) wins, and only then does the
    ``[tool.ruff]`` table in pyproject.toml apply. A repository that moves its
    configuration into ``ruff.toml`` would otherwise be reported as "declares no
    line-length" when the setting is simply in the other file.

    Two gaps belong to other rules and are deliberately left silent here:
    a missing pyproject.toml is A005's, and a repository with no ruff
    configuration at all is A021's. One gap, one finding.
    """
    rule = contract.rules["A004"]
    target = contract.value("ruff_line_length_target", 120)
    table_name = contract.value("ruff_line_length_table", "tool.ruff")
    name = contract.value("pyproject_file", "pyproject.toml")

    for standalone in contract.value("ruff_standalone_configs", []):
        path = root / standalone
        if not path.is_file():
            continue
        settings = parse_vx_toml(_read_text(path) or "")[0]
        declared = settings.get("line-length")
        declared = None if isinstance(declared, dict) else declared
        return _line_length_finding(rule, standalone, target, declared)

    data = _pyproject(contract, ctx)
    if not data:
        # A005 already reports the missing pyproject.toml; piling a second
        # finding on it would say the same thing twice.
        return []
    table = _table(data, table_name)
    if not table:
        # No [tool.ruff] table and no standalone file: A021 owns that gap.
        return []
    return _line_length_finding(rule, name, target, table.get("line-length"))


def check_requires_python_declared(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A005 — project.requires-python is declared (visibility only).

    The value is deliberately not checked. Host-side constraints differ
    legitimately and the organisation Python 3.7 red line runs to 2026-12-31.
    """
    rule = contract.rules["A005"]
    table_name = contract.value("requires_python_table", "project")
    key = contract.value("requires_python_key", "requires-python")
    name = contract.value("pyproject_file", "pyproject.toml")
    data = _pyproject(contract, ctx)
    if not data:
        return [
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                name,
                "no pyproject.toml, so the Python support range is invisible to pip",
            )
        ]
    table = _table(data, table_name)
    if str(table.get(key, "")).strip():
        return []
    return [
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            name,
            (
                f"[{table_name}] does not declare {key}; pip will install this package on any "
                "interpreter the wheel accepts"
            ),
        )
    ]


def check_pre_commit_config_exists(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A006 — .pre-commit-config.yaml exists, so ruff runs before the push."""
    rule = contract.rules["A006"]
    candidates = contract.value("pre_commit_configs", [".pre-commit-config.yaml"])
    if any((root / candidate).is_file() for candidate in candidates):
        return []
    return [
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            candidates[0] if candidates else ".pre-commit-config.yaml",
            (
                "no pre-commit configuration; the ruff settings in pyproject.toml then run only "
                "in CI, after the push"
            ),
        )
    ]


def _install_sop_sources(
    root: Path, contract: Contract, ctx: dict, rule: dict
) -> tuple[list[tuple[Path, str]] | None, list[Finding]]:
    """Scan once, then answer whether this repository is in scope.

    The sources are ``None`` when the repository has no Install SOP surface, so
    that both report rules stay silent for the adapters that never install
    anything. The scan notices are returned either way: a skipped file is a blind
    spot for the whole run, not for one rule.
    """
    modules, notices = _prepare_scan(root, contract, ctx, rule)
    sources = _source_texts(modules)
    if not _has_install_sop_surface(root, contract, sources):
        return None, notices
    return sources, notices


def check_doctor_module_present(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A013 — an adapter that installs ships a `doctor` self-check module.

    The doctor is where an adapter assembles its Install SOP report and, ideally,
    validates it before it is published. 8 of the 50 swept adapters have one, so
    this is a convergence warning rather than a baseline error: the gate reports
    the gap instead of blocking a release.

    Known boundary: the module is matched by name, so a `doctor` that does not
    validate a report satisfies the rule, and `install_preflight_docs.py` matches
    `src/**/install*.py` even though it only documents a preflight. Both are
    acceptable at warning severity, where the finding is a starting point.
    """
    rule = contract.rules["A013"]
    sources, notices = _install_sop_sources(root, contract, ctx, rule)
    if sources is None:
        return list(notices)
    for pattern in contract.value("a013_doctor_module_globs", []):
        if any(root.glob(pattern)):
            return list(notices)
    anchor = "src"
    for pattern in contract.value("install_source_globs", []):
        matches = sorted(root.glob(pattern))
        if matches:
            anchor = _rel(root, matches[0])
            break
    return [
        *notices,
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            anchor,
            (
                "this adapter provides install capability but ships no `doctor` "
                "self-check module; add one that assembles the Install SOP report and "
                "validates it with `validate_install_sop_report()` (8 of 50 adapters had "
                "one when the rule was written)"
            ),
        ),
    ]


def check_report_validates_against_schema(
    root: Path, contract: Contract, ctx: dict
) -> list[Finding]:
    """A014 — a real report is validated with `validate_install_sop_report()`.

    A schema nobody checks is a claim, not a contract: every adapter in the
    PIP-3990 incident shipped a schema and none of them ran a report through it,
    which is how the wrong value reached a release. The validation has to live in
    a test or in a CI workflow, because those are the only places that run before
    the artefact is published.

    Known boundary: the symbol is matched as text, so an occurrence in a comment
    or in a `TODO` satisfies the rule. That trades a false negative for a false
    positive on a warning-severity rule, which is the same trade the ratchet plan
    makes everywhere.
    """
    rule = contract.rules["A014"]
    sources, notices = _install_sop_sources(root, contract, ctx, rule)
    if sources is None:
        return list(notices)
    symbols = [name for name in contract.value("a014_validator_symbols", []) if name]
    if symbols:
        pattern = re.compile("|".join(r"\b" + re.escape(name) + r"\b" for name in symbols))
        for path_glob in contract.value("a014_scan_globs", []):
            for path in sorted(root.glob(path_glob)):
                text = _read_text(path)
                if text and pattern.search(text):
                    return list(notices)
    return [
        *notices,
        Finding(
            rule["id"],
            rule["name"],
            rule["severity"],
            "tests",
            (
                "no test or CI workflow validates a real report with "
                "`validate_install_sop_report()`; schema compliance is only claimed, and "
                "that is how the PIP-3990 defect reached a release"
            ),
        ),
    ]


RULES: dict[str, Callable[[Path, Contract, dict], list[Finding]]] = {
    "R001": check_no_root_artifacts,
    "R002": check_justfile_lowercase,
    "R003": check_agents_md_exists,
    "R004": check_vx_toml_parses,
    "R005": check_tools_version_format,
    "R006": check_root_allowlist,
    "R007": check_no_scripts_with_justfile,
    "R008": check_agents_derived_symlink,
    "R009": check_tools_no_latest,
    "R010": check_llms_txt_fresh,
    "R011": check_no_tracked_agent_dirs,
    "A001": check_no_deprecated_install_sop_alias,
    "A002": check_no_hand_rolled_report_schema_version,
    "A003": check_core_floor_declared,
    "A012": check_core_floor_baseline,
    "A004": check_ruff_line_length,
    "A005": check_requires_python_declared,
    "A006": check_pre_commit_config_exists,
    "A013": check_doctor_module_present,
    "A014": check_report_validates_against_schema,
}


def all_rules() -> dict[str, Callable[..., list[Finding]]]:
    """Every rule the checker can dispatch, across every contract.

    ``RULES`` stays exactly the rule set of contract/repo_contract.json so that
    "every contract rule has an implementation" keeps a precise meaning. Rules
    for other contracts live in their own modules -- the adapter families under
    ``adapter_contract_rules`` -- and are imported here rather than at module
    scope, because those modules import ``Finding`` and ``Contract`` back out of
    this one and a module-level import would be a cycle.
    """
    from adapter_contract_rules import ADAPTER_RULES

    return {**RULES, **ADAPTER_RULES}


# ----------------------------------------------------------------------- driver


def resolve_plan(
    contract: Contract,
    profile: str,
    add_rules: Sequence[str],
    skip_rules: Sequence[str],
    severity_overrides: dict[str, str],
) -> dict[str, tuple[Callable[..., list[Finding]], str]]:
    """Resolve which rules run and at what severity."""
    selected: set[str] = set()
    for rule_id, rule in contract.rules.items():
        if profile == "all" or profile in rule.get("profiles", []):
            selected.add(rule_id)
    selected.update(add_rules)
    selected.difference_update(skip_rules)
    unknown = (set(add_rules) | set(skip_rules) | set(severity_overrides)) - set(contract.rules)
    if unknown:
        raise ContractError(
            f"unknown rule id(s): {', '.join(sorted(unknown))}; "
            f"known: {', '.join(sorted(contract.rules))}"
        )
    plan = {}
    for rule_id in sorted(selected):
        rule = contract.rules[rule_id]
        handler = all_rules().get(rule_id)
        if handler is None:
            raise ContractError(
                f"contract defines rule {rule_id} but no checker implements it"
            )
        plan[rule_id] = (handler, severity_overrides.get(rule_id, rule["severity"]))
    return plan


def run_checks(
    root: Path, contract: Contract, plan: dict[str, tuple[Callable[..., list[Finding]], str]],
    allow_extra: Sequence[str],
) -> list[Finding]:
    files, dirs = _top_level_entries(root)
    ctx: dict[str, Any] = {
        "root": root,
        "files": files,
        "dirs": dirs,
        "justfile": _find_justfile(files),
        "allow_extra": list(allow_extra),
    }
    vx_toml = root / "vx.toml"
    ctx["vx"] = (
        parse_vx_toml(vx_toml.read_text(encoding="utf-8", errors="replace"))[0]
        if vx_toml.is_file()
        else {}
    )

    findings: list[Finding] = []
    for rule_id, (handler, severity) in plan.items():
        default_severity = contract.rules[rule_id]["severity"]
        for finding in handler(root, contract, ctx):
            # A rule may report an individual finding softer than its own severity
            # (for example a deprecation hint). Only findings sitting at the rule's
            # configured severity follow --error-rule / --warn-rule.
            effective = severity if finding.severity == default_severity else finding.severity
            findings.append(
                Finding(
                    finding.rule_id,
                    finding.rule_name,
                    effective,
                    finding.path,
                    finding.message,
                )
            )
    findings.sort(key=lambda item: (-SEVERITY_ORDER[item.severity], item.rule_id, item.path))
    return findings


# ----------------------------------------------------------------------- output


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def emit_github(findings: Sequence[Finding], stream=None) -> None:
    # Resolved at call time so that tests can redirect sys.stderr.
    stream = stream if stream is not None else sys.stderr
    for finding in findings:
        print(
            f"::{finding.severity} file={_escape(finding.path)},"
            f"title=Repo contract {finding.rule_id}::{finding.rule_id} "
            f"{finding.rule_name}: {_escape(finding.message)}",
            file=stream,
        )


def emit_text(findings: Sequence[Finding], stream=None) -> None:
    stream = stream if stream is not None else sys.stdout
    if not findings:
        print("repo contract: no findings", file=stream)
        return
    for finding in findings:
        print(
            f"[{finding.severity.upper():7}] {finding.rule_id} {finding.rule_name} "
            f"({finding.path}): {finding.message}",
            file=stream,
        )


def emit_summary(findings: Sequence[Finding], fail_on: str, stream=None) -> None:
    stream = stream if stream is not None else sys.stderr
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    errors = counts.get("error", 0)
    warnings = counts.get("warning", 0)
    print(
        f"repo contract: {errors} error(s), {warnings} warning(s); failing on {fail_on}",
        file=stream,
    )


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Read the org-wide sweep manifest and expand it into matrix entries."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"cannot read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("repositories"), list):
        raise ContractError(f"manifest {path} has no `repositories` array")

    defaults: dict[str, Any] = data.get("defaults") or {}
    entries = []
    for item in data["repositories"]:
        if not isinstance(item, dict) or not item.get("repository"):
            raise ContractError(f"manifest {path} has an entry without a `repository`")
        merged = dict(defaults, **item)
        repository = merged["repository"]
        entries.append(
            {
                "key": repository.replace("/", "-"),
                "repository": repository,
                "profile": str(merged.get("profile", "baseline")),
                "rules": ",".join(merged.get("rules") or []),
                "skip_rules": ",".join(merged.get("skip_rules") or []),
                "error_rules": ",".join(merged.get("error_rules") or []),
                "allow_extra": ",".join(merged.get("allow_extra") or []),
                "fail_on": str(merged.get("fail_on", "error")),
            }
        )
    if not entries:
        raise ContractError(f"manifest {path} lists no repositories")
    keys = [entry["key"] for entry in entries]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ContractError(f"manifest {path} has duplicate entries: {', '.join(duplicates)}")
    return entries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a repository against the dcc-mcp repository contract.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        default=".",
        help="repository root to check (default: current directory)",
    )
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT_PATH),
        help=f"path to repo_contract.json (default: {DEFAULT_CONTRACT_PATH})",
    )
    parser.add_argument(
        "--profile",
        choices=("baseline", "strict", "all"),
        default="baseline",
        help="rule set to run (default: baseline)",
    )
    parser.add_argument(
        "--rule",
        action="append",
        default=[],
        metavar="ID",
        help="add a rule outside the selected profile (repeatable)",
    )
    parser.add_argument(
        "--skip-rule",
        action="append",
        default=[],
        metavar="ID",
        help="skip a rule from the selected profile (repeatable)",
    )
    parser.add_argument(
        "--error-rule",
        action="append",
        default=[],
        metavar="ID",
        help="promote a rule to error severity (repeatable)",
    )
    parser.add_argument(
        "--warn-rule",
        action="append",
        default=[],
        metavar="ID",
        help="demote a rule to warning severity (repeatable)",
    )
    parser.add_argument(
        "--allow-extra",
        default="",
        help="comma-separated top-level entries tolerated by the root allowlist",
    )
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "none"),
        default="error",
        help="lowest severity that fails the run (default: error)",
    )
    parser.add_argument(
        "--format",
        choices=("github", "text", "json"),
        default="github",
        help="output format (default: github)",
    )
    parser.add_argument(
        "--emit-contract",
        action="store_true",
        help="print the machine-readable contract and exit",
    )
    parser.add_argument(
        "--emit-matrix",
        metavar="MANIFEST",
        help="print a GitHub Actions matrix built from a sweep manifest and exit",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="print the rules in the selected profile and exit",
    )
    return parser


def _split_ids(values: Iterable[str]) -> list[str]:
    """Accept both `--rule R006 --rule R008` and `--rule R006,R008`."""
    return [item.strip() for value in values for item in value.split(",") if item.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        contract = Contract.load(Path(args.contract))
    except ContractError as exc:
        print(f"::error title=Repo contract::{exc}", file=sys.stderr)
        return 2

    if args.emit_contract:
        print(json.dumps(contract.data, indent=2, sort_keys=False))
        return 0

    if args.emit_matrix:
        try:
            entries = load_manifest(Path(args.emit_matrix))
        except ContractError as exc:
            print(f"::error title=Repo contract::{exc}", file=sys.stderr)
            return 2
        print(json.dumps({"include": entries}, indent=2))
        return 0

    overrides: dict[str, str] = {}
    for rule_id in _split_ids(args.error_rule):
        overrides[rule_id] = "error"
    for rule_id in _split_ids(args.warn_rule):
        overrides[rule_id] = "warning"

    try:
        plan = resolve_plan(
            contract,
            args.profile,
            _split_ids(args.rule),
            _split_ids(args.skip_rule),
            overrides,
        )
    except ContractError as exc:
        print(f"::error title=Repo contract::{exc}", file=sys.stderr)
        return 2

    if args.list_rules:
        for rule_id, (_, severity) in plan.items():
            rule = contract.rules[rule_id]
            print(f"{rule_id}  {severity:7}  {rule['name']}: {rule['summary']}")
        return 0

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"::error title=Repo contract::{root} is not a directory", file=sys.stderr)
        return 2

    allow_extra = [item.strip() for item in args.allow_extra.split(",") if item.strip()]
    findings = run_checks(root, contract, plan, allow_extra)

    if args.format == "json":
        print(json.dumps([finding.as_dict() for finding in findings], indent=2))
    elif args.format == "text":
        emit_text(findings)
    else:
        emit_github(findings)

    emit_summary(findings, args.fail_on)

    if args.fail_on == "none":
        return 0
    threshold = SEVERITY_ORDER[args.fail_on]
    if any(SEVERITY_ORDER[finding.severity] >= threshold for finding in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
