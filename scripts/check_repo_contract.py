#!/usr/bin/env python3
"""Check a repository against the dcc-mcp repository contract.

The pass/fail criteria live in ``contract/repo_contract.json``. This script only
implements the mechanics; both this CI gate and the ``vx-repo-contract`` skill read
that same file, so a rule is never defined twice.

Rules
-----
    R001 no-root-artifacts       no build/test artifacts at the repository root
    R002 justfile-lowercase      `justfile`, never `Justfile`
    R003 agents-md-exists        AGENTS.md is present
    R004 vx-toml-parses          vx.toml parses and only uses known tables
    R005 tools-version-format    [tools] pins are stable/latest/X[.Y[.Z]]
    R006 root-allowlist          every top-level entry is allowlisted
    R007 no-scripts-with-justfile no vx.toml [scripts] when a justfile exists
    R008 agents-derived-symlink  CLAUDE.md & friends are symlinks or generated
    R009 tools-no-latest         [tools] pins are concrete, not `latest`
    R010 llms-txt-fresh          llms.txt exists when a generator exists

Profiles
--------
    baseline  R001-R005, the rules every repository satisfies today.
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
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = ROOT / "contract" / "repo_contract.json"

SEVERITY_ORDER = {"notice": 0, "warning": 1, "error": 2}
SEVERITY_ALIASES = {"warn": "warning", "err": "error"}
MAX_PROVENANCE_SCAN_LINES = 10

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
    """Join a TOML multi-line string onto one logical value.

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
    return value, index


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
        target[key] = _coerce(_unwrap_inline_table(_strip_comment(value.strip())))
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
    findings = []
    for name in sorted(tools):
        value = tools[name]
        if isinstance(value, str) and pattern.match(value):
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


def check_no_scripts_with_justfile(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["R007"]
    justfile = ctx.get("justfile")
    if justfile is None:
        return []
    vx: dict[str, Any] = ctx.get("vx") or {}
    scripts = vx.get("scripts")
    if not isinstance(scripts, dict) or not scripts:
        return []
    findings = []
    for name in sorted(scripts):
        command = scripts[name]
        findings.append(
            Finding(
                rule["id"],
                rule["name"],
                rule["severity"],
                "vx.toml",
                (
                    f"[scripts] {name} = {command!r} duplicates `{justfile.name}`; keep recipes "
                    "in the justfile and reserve [scripts] for repositories without one"
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
}


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
        handler = RULES.get(rule_id)
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
