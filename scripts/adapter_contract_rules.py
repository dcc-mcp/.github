#!/usr/bin/env python3
"""Adapter contract rules: the Python code-style family, A020-A024.

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
    A020 ruff-line-length          [tool.ruff] line-length is the org baseline
    A021 ruff-config-present       the repository configures ruff at all
    A022 pre-commit-present        a .pre-commit-config.yaml runs the checks locally
    A023 requires-python-declared  pyproject.toml declares requires-python
    A024 release-please-present    release-please config and manifest exist

A020 and A021 read the same configuration. When there is no ruff configuration
at all A021 reports it and A020 stays silent: one gap, one finding.
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
    order ruff itself resolves them in. Settings is None when the file exists
    but carries no ruff table -- A021 reports that, A020 must not double-report.
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
    table = contract.value("ruff_pyproject_table", "tool.ruff")
    settings = parsed.get(table)
    return pyproject, settings if isinstance(settings, dict) else None, True


def _as_text(value: Any) -> str:
    return str(value).strip()


def _finding(rule: dict[str, Any], path: str, message: str) -> Finding:
    return Finding(rule["id"], rule["name"], rule["severity"], path, message)


# ------------------------------------------------------------------------- rules


def check_ruff_line_length(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["A020"]
    path, settings, _ = _ruff_config(root, contract)
    if settings is None:
        return []
    baseline = contract.value("ruff_line_length", 120)
    declared = settings.get("line-length")
    if declared is None:
        return [
            _finding(
                rule,
                path,
                (
                    "declares no line-length, so ruff silently falls back to its own "
                    f"default instead of the org baseline of {baseline}; set "
                    f"line-length = {baseline} explicitly"
                ),
            )
        ]
    if _as_text(declared) != _as_text(baseline):
        return [
            _finding(
                rule,
                path,
                (
                    f"line-length = {declared}, but the org baseline is {baseline}; either "
                    f"reformat to {baseline} or record the exception in the contract so the "
                    "difference is a decision rather than drift"
                ),
            )
        ]
    return []


def check_ruff_config_present(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["A021"]
    path, settings, pyproject_exists = _ruff_config(root, contract)
    if settings is not None:
        return []
    table = contract.value("ruff_pyproject_table", "tool.ruff")
    if pyproject_exists:
        message = (
            f"has no [{table}] section; ruff then runs on its own defaults, so the "
            "lint rules differ between a developer machine and CI"
        )
    else:
        message = (
            "no ruff configuration found; add a standalone ruff.toml or a "
            f"[{table}] section in {path} so formatting and linting are decided once"
        )
    return [_finding(rule, path, message)]


def check_pre_commit_present(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["A022"]
    names = contract.value("pre_commit_config_names", [".pre-commit-config.yaml"])
    for name in names:
        if (root / name).is_file():
            return []
    expected = ", ".join(f"`{name}`" for name in names)
    return [
        _finding(
            rule,
            names[0] if names else ".pre-commit-config.yaml",
            (
                f"no pre-commit configuration ({expected}); without a hook the contract is "
                "only enforced in CI, so feedback moves from seconds to minutes"
            ),
        )
    ]


def check_requires_python_declared(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    rule = contract.rules["A023"]
    pyproject = contract.value("pyproject_file", "pyproject.toml")
    parsed = _read_toml(root, pyproject)
    if parsed is None:
        # Not a Python package; whether that is correct is the applicability
        # rule's question, not this one.
        return []
    tables = contract.value("requires_python_tables", ["project"])
    for table in tables:
        section = parsed.get(table)
        if isinstance(section, dict) and "requires-python" in section:
            return []
    return [
        _finding(
            rule,
            pyproject,
            (
                "declares no requires-python; pip then installs the package on any "
                "interpreter and the failure surfaces inside a DCC host instead of at "
                f"resolve time. Declare it in [{tables[0]}]"
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
    "A020": check_ruff_line_length,
    "A021": check_ruff_config_present,
    "A022": check_pre_commit_present,
    "A023": check_requires_python_declared,
    "A024": check_release_please_present,
}
