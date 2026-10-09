#!/usr/bin/env python3
"""Adapter contract rules: the code-convention family, A021 and A024.

The rules and their thresholds live in ``contract/adapter_contract.json``; this
module only implements the mechanics, exactly like ``check_repo_contract.py``
does for ``contract/repo_contract.json``. Nothing here is hardcoded -- the
line-length baseline, the file names and the table names are all contract
values, so the `vx-repo-contract` skill and this gate cannot drift apart.

The family lives in its own module because the adapter contract is still being
built out rule family by rule family (PIP-4105/4106/4107). Keeping each family
in one file means each one lands as an additive change instead of five agents
editing the middle of the same array.

Rules
-----
    A021 ruff-config-present     the repository configures ruff, and the
                                 configuration is not empty
    A024 release-please-present  release-please config and manifest exist

Only the two rules the rest of the adapter contract does not already cover.
The line-length value itself is A004's, the presence of a pre-commit hook is
A006's, and `requires-python` is A005's: each of those already exists in main,
so a second id for the same gap would give the nightly sweep two findings for
one defect and two places to ratchet. A021 and A024 fill the two holes the
existing rules leave -- a repository with no ruff configuration at all, and one
with no release-please automation.

A021 distinguishes three shapes that used to reach it as one message, because
"no configuration", "an empty table" and "a table of nothing but sub-tables" are
three different edits: an absent ``[tool.ruff]`` has to be written, an empty one
has to be filled, and a nested-only one needs its top-level settings moved up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from check_repo_contract import Contract, Finding
from check_repo_contract import parse_vx_toml as parse_toml_subset

# ``parse_vx_toml`` is the lenient TOML-subset parser the repository contract
# already uses for vx.toml. It never raises and it keeps numbers as written,
# which is what a lint-setting check wants; pyproject.toml needs nothing more
# than the tables this family reads out of it. It also returns a line-number map
# that only the repository contract needs, so callers index the parsed mapping.

# A ruff configuration, resolved from the contract's ordered list of sources.
#
# ``settings`` is None when no source declares ruff configuration at all and a
# (possibly empty) mapping when a source declares one, so "no table" and "an
# empty table" stay distinguishable -- ``_table()`` collapses both to ``{}``,
# which is what silently swallowed the empty-``[tool.ruff]`` case.
RuffConfig = tuple[str, Optional[dict[str, Any]], bool]


def _read_toml(root: Path, name: str) -> Optional[dict[str, Any]]:
    path = root / name
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return parse_toml_subset(text)[0]


def _ruff_config(root: Path, contract: Contract) -> RuffConfig:
    """Return ``(path, settings, pyproject_exists)`` for the ruff configuration.

    A standalone ``ruff.toml`` wins over ``pyproject.toml`` because that is the
    order ruff itself resolves them in -- the same order A004 now walks when it
    reads ``line-length``, so the two rules can never disagree about which file
    the setting lives in. The list order is the contract's, so ``.ruff.toml``
    beating ``ruff.toml`` is data rather than a literal baked in here.

    Settings is None when no source declares ruff configuration at all and a
    mapping otherwise; that is the gap A021 reports. The mapping keeps sub-table
    names as keys -- dropping them made a nested-only configuration look like an
    empty one -- so callers that want top-level settings filter it themselves.
    """
    for name in contract.value("ruff_standalone_configs", []):
        parsed = _read_toml(root, name)
        if parsed is None:
            continue
        return name, parsed, True

    pyproject = contract.value("pyproject_file", "pyproject.toml")
    parsed = _read_toml(root, pyproject)
    if parsed is None:
        return pyproject, None, False
    settings = _resolve_dotted(parsed, contract.value("ruff_line_length_table", "tool.ruff"))
    return pyproject, settings if isinstance(settings, dict) else None, True


def _resolve_dotted(data: dict[str, Any], name: str) -> Any:
    """Resolve a dotted table name against a leniently parsed pyproject.toml.

    The parser keeps every table header flat, so ``[tool.ruff]`` arrives as the
    literal key ``tool.ruff`` while ``[tool.ruff.lint]`` arrives as
    ``tool.ruff.lint``. The latter still means ``tool.ruff`` exists -- it just
    holds no keys of its own -- so a lookup that only matched the exact key
    called the table missing while the sub-table sat right there in the parse.
    Matching the exact key first and then any key the name prefixes keeps the
    two in agreement.
    """
    if name in data:
        return data[name]
    prefix = name + "."
    sub_tables = [key[len(prefix) :] for key in data if key.startswith(prefix)]
    if not sub_tables:
        return None
    merged: dict[str, Any] = {}
    for key in sorted(sub_tables):
        merged[key] = data[prefix + key]
    return merged


def _sub_table_keys(settings: dict[str, Any]) -> list[str]:
    """The keys of ``settings`` that are sub-tables rather than settings.

    ``_ruff_config`` keeps sub-tables in the mapping it returns, so a nested-only
    ``[tool.ruff.lint]`` arrives as a mapping of sub-table names: every value is
    a dict, while a real top-level setting never is.
    """
    return sorted(key for key, value in settings.items() if isinstance(value, dict))


def _top_level_keys(settings: dict[str, Any]) -> list[str]:
    """The keys of ``settings`` that are settings rather than sub-tables.

    Whether a configuration counts as configured is decided here rather than by
    ``if settings``, because a nested-only table is a non-empty mapping that
    still declares nothing at the top level.
    """
    return sorted(key for key, value in settings.items() if not isinstance(value, dict))


def _as_text(value: Any) -> str:
    return str(value).strip()


def _finding(rule: dict[str, Any], path: str, message: str) -> Finding:
    return Finding(rule["id"], rule["name"], rule["severity"], path, message)


# ------------------------------------------------------------------------- rules


def check_ruff_config_present(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A021 — the repository configures ruff, and the section is not empty.

    Three shapes reach this rule and they are not the same defect, so they do
    not share a message:

    * no configuration anywhere — the original gap, "add a ruff config";
    * a ``[tool.ruff]`` table that exists but holds no keys — ruff reads the
      table and finds nothing in it, which is the same outcome as the first
      case but a different edit, so it is named as an empty table;
    * a nested-only table such as ``[tool.ruff.lint]`` — the table *does*
      exist, so calling it "no ``[tool.ruff]`` section" contradicted the parse.
      Only the top-level settings are missing here.
    """
    rule = contract.rules["A021"]
    path, settings, pyproject_exists = _ruff_config(root, contract)
    if settings is None:
        if not pyproject_exists:
            # A registered adapter with no pyproject.toml at all is A005's gap:
            # one gap, one finding.
            return []
        table = contract.value("ruff_line_length_table", "tool.ruff")
        return [
            _finding(
                rule,
                path,
                (
                    f"has no [{table}] section and no standalone ruff configuration; ruff "
                    "then runs on its own defaults, so the lint rules differ between a "
                    "developer machine and CI"
                ),
            )
        ]
    if _top_level_keys(settings):
        return []
    table = contract.value("ruff_line_length_table", "tool.ruff")
    # A pyproject table is named by its section header; a standalone file has no
    # [tool.ruff] prefix to speak of, so it reports itself by file name.
    in_pyproject = path == contract.value("pyproject_file", "pyproject.toml")
    subject = f"[{table}]" if in_pyproject else f"`{path}`"
    sub_tables = _sub_table_keys(settings)
    if sub_tables:
        # [tool.ruff.lint] and friends exist, so the table is not missing -- it
        # only holds no settings of its own.
        headers = [
            f"[{table}.{key}]" if in_pyproject else f"[{key}]" for key in sub_tables
        ]
        return [
            _finding(
                rule,
                path,
                (
                    f"{subject} holds only the sub-table{'s' if len(headers) > 1 else ''} "
                    f"{', '.join(headers)} and no settings of its own, so ruff falls back "
                    "to its own defaults for everything declared at the top level"
                ),
            )
        ]
    return [
        _finding(
            rule,
            path,
            (
                f"{subject} is empty; ruff finds the file but no settings in it, so it "
                "runs on its own defaults and the lint rules differ between a developer "
                "machine and CI"
            ),
        )
    ]


def check_release_please_present(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["A024"]
    findings = []
    for name in contract.value("release_please_files", []):
        if (root / name).is_file():
            continue
        findings.append(
            _finding(
                rule,
                name,
                (
                    f"`{name}` is missing; release-please cannot version the repository, so "
                    "releases have to be cut by hand and drift from the org's scheme"
                ),
            )
        )
    return findings


ADAPTER_RULES: dict[str, Callable[..., list[Finding]]] = {
    "A021": check_ruff_config_present,
    "A024": check_release_please_present,
}
