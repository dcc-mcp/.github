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
    A021 ruff-config-present     the repository configures ruff at all
    A024 release-please-present  release-please config and manifest exist

Only the two rules the rest of the adapter contract does not already cover.
The line-length value itself is A004's, the presence of a pre-commit hook is
A006's, and `requires-python` is A005's: each of those already exists in main,
so a second id for the same gap would give the nightly sweep two findings for
one defect and two places to ratchet. A021 and A024 fill the two holes the
existing rules leave -- a repository with no ruff configuration at all, and one
with no release-please automation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from check_repo_contract import Contract, Finding
from check_repo_contract import parse_vx_toml as parse_toml_subset

# ``parse_vx_toml`` is the lenient TOML-subset parser the repository contract
# already uses for vx.toml. It never raises and it keeps numbers as written,
# which is what a lint-setting check wants; pyproject.toml needs nothing more
# than the tables this family reads out of it.

# A ruff configuration, resolved from the contract's ordered list of sources.
# ``settings`` is None when no source declares ruff configuration at all.
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
    the setting lives in. Settings is None when the file exists but carries no
    ruff table; that is the gap A021 reports.
    """
    for name in contract.value("ruff_standalone_configs", []):
        parsed = _read_toml(root, name)
        if parsed is None:
            continue
        # Root-level scalars only; sub-tables such as [lint] are not line-length.
        return name, {k: v for k, v in parsed.items() if not isinstance(v, dict)}, True

    pyproject = contract.value("pyproject_file", "pyproject.toml")
    parsed = _read_toml(root, pyproject)
    if parsed is None:
        return pyproject, None, False
    table = contract.value("ruff_line_length_table", "tool.ruff")
    settings = parsed.get(table)
    return pyproject, settings if isinstance(settings, dict) else None, True


def _as_text(value: Any) -> str:
    return str(value).strip()


def _finding(rule: dict[str, Any], path: str, message: str) -> Finding:
    return Finding(rule["id"], rule["name"], rule["severity"], path, message)


# ------------------------------------------------------------------------- rules


def check_ruff_config_present(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["A021"]
    path, settings, pyproject_exists = _ruff_config(root, contract)
    if settings is not None:
        return []
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
