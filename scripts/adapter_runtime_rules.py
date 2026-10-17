"""Declarative runtime boundary checks; never import or install an adapter.

Policy values live in adapter_contract.json. These checks validate source
declarations, not a built wheel's import closure or host acceptance.
"""

from __future__ import annotations

import re
from pathlib import Path

from check_repo_contract import Contract, Finding

try:
    import tomllib
except ImportError:  # Existing rules can still run on older check interpreters.
    tomllib = None


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _finding(contract: Contract, rule_id: str, message: str) -> Finding:
    rule = contract.rules[rule_id]
    return Finding(rule_id, rule["name"], rule["severity"], contract.value("pyproject_file"), message)


def _load(root: Path, contract: Contract, ctx: dict) -> tuple[dict, str | None]:
    if "runtime_pyproject" not in ctx:
        path = root / contract.value("pyproject_file")
        data, error = {}, None
        if path.is_file():
            if tomllib is None:
                error = "runtime policy checks require Python 3.11+ (stdlib tomllib); no dependencies were installed"
            else:
                try:
                    with path.open("rb") as handle:
                        data = tomllib.load(handle)
                    for parts in (("project",), ("tool",), ("tool", "poetry")):
                        value = data
                        for part in parts:
                            value = value.get(part, {})
                        if not isinstance(value, dict):
                            raise ValueError(f"{'.'.join(parts)} must be a table")
                except (OSError, ValueError) as exc:
                    error = f"cannot validate runtime policy: {exc}"
        ctx["runtime_pyproject"] = data, error
    return ctx["runtime_pyproject"]


def _policy(data: dict, contract: Contract) -> dict:
    value = data
    for key in contract.value("runtime_policy_table"):
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, dict) else {}


def _applicable(data: dict, contract: Contract) -> bool:
    name = data.get("project", {}).get("name", data.get("tool", {}).get("poetry", {}).get("name", ""))
    return isinstance(name, str) and canonical_name(name).startswith(contract.value("runtime_adapter_name_prefix")) and canonical_name(name) not in contract.value("runtime_provider_distributions")


def _dependencies(data: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Read mandatory PEP 621 and Poetry dependencies without resolving markers.

    Marked dependencies remain mandatory on some target. Development/build and
    explicit optional groups are intentionally excluded. Dynamic metadata is
    reported, never silently treated as an empty dependency list.
    """
    project = data.get("project", {})
    errors: list[str] = []
    result: list[tuple[str, str]] = []
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list):
        errors.append("project.dynamic must be an array")
        dynamic = []
    if "dependencies" in dynamic:
        errors.append("dynamic project.dependencies requires built METADATA validation; static closure is unknown")
    requirements = project.get("dependencies", [])
    if not isinstance(requirements, list):
        errors.append("project.dependencies must be an array of requirement strings")
        requirements = []
    for requirement in requirements:
        match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?=\s|\[|[<>=!~@;]|$)", requirement) if isinstance(requirement, str) else None
        if match is None:
            errors.append(f"cannot identify dependency {requirement!r}")
        else:
            result.append((canonical_name(match.group(1)), requirement))
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if not isinstance(poetry, dict):
        errors.append("tool.poetry.dependencies must be a table")
    else:
        for name, value in poetry.items():
            if name.lower() == "python" or (isinstance(value, dict) and value.get("optional") is True):
                continue
            requirement = name
            if isinstance(value, dict) and "extras" in value:
                extras = value["extras"]
                if not isinstance(extras, list) or not all(isinstance(extra, str) for extra in extras):
                    errors.append(f"cannot identify Poetry extras for {name}")
                elif extras:
                    requirement += "[" + ",".join(extras) + "]"
            result.append((canonical_name(name), requirement))
    return result, errors


def check_runtime_mode(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    data, error = _load(root, contract, ctx)
    if error:
        return [_finding(contract, "A030", error)]
    if not _applicable(data, contract):
        return []
    policy = _policy(data, contract)
    mode = policy.get("mode")
    if mode not in contract.value("runtime_modes"):
        return [_finding(contract, "A030", "declare [tool.dcc-mcp.runtime].mode as host or external from the actual adapter process; mixed packages need separately audited runtime boundaries")]
    return []


def check_host_dependencies(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    data, error = _load(root, contract, ctx)
    if error or not _applicable(data, contract) or _policy(data, contract).get("mode") != "host":
        return []
    dependencies, errors = _dependencies(data)
    allowed = {canonical_name(name) for name in contract.value("runtime_host_distributions")}
    findings = [_finding(contract, "A031", error) for error in errors]
    for name, requirement in dependencies:
        if name not in allowed:
            findings.append(_finding(contract, "A031", f"host adapter requires third-party distribution {requirement!r}; use stdlib/host APIs or first-party Core, and keep build/dev or external optional features separate"))
        else:
            extras_match = re.match(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*\[([^\]]+)\]", requirement)
            if extras_match:
                extras = {canonical_name(extra.strip()) for extra in extras_match.group(1).split(",")}
                supported = set(contract.value("runtime_host_extras").get(name, []))
                if extras - supported:
                    findings.append(_finding(contract, "A031", f"host dependency activates unaudited extras: {requirement!r}"))
    return findings


def check_external_runtime(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    data, error = _load(root, contract, ctx)
    if error or not _applicable(data, contract):
        return []
    policy = _policy(data, contract)
    if policy.get("mode") != "external":
        return []
    findings = []
    if policy.get("provider") != contract.value("runtime_external_provider"):
        findings.append(_finding(contract, "A032", "external adapter must declare provider = 'dcc-mcp-runtime'; this declaration does not prove a deployable interpreter exists"))
    dependencies, errors = _dependencies(data)
    findings.extend(_finding(contract, "A032", error) for error in errors)
    reasons = policy.get("third-party-reasons", {})
    reasons = {canonical_name(name): reason for name, reason in reasons.items()} if isinstance(reasons, dict) else {}
    first_party = {canonical_name(name) for name in contract.value("runtime_external_distributions")}
    for name, requirement in dependencies:
        reason = reasons.get(name)
        if name not in first_party and (not isinstance(reason, str) or not reason.strip()):
            findings.append(_finding(contract, "A032", f"external dependency {requirement!r} needs a third-party-reasons entry explaining its host bridge purpose; it belongs in the shared runtime's versioned dependency set"))
    return findings


RUNTIME_RULES = {"A030": check_runtime_mode, "A031": check_host_dependencies, "A032": check_external_runtime}
