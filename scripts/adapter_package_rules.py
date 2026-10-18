"""Recovered adapter-package checks, without replacing the current contract.

A007 reports registration applicability; A011 checks direct Install SOP report
fields. Existing A001/A002/A003 and their severities remain unchanged.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from check_repo_contract import (
    Contract, Finding, _dotted_name, _int_constant, _prepare_scan,
    _pyproject, _rel, _requirement_strings,
)


def _normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _entries(data: dict, prefix: str = ""):
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        yield path, value
        if isinstance(value, dict):
            yield from _entries(value, path)


def check_adapter_python_package(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A007: warn about registrations that lack a Core-linked package."""
    rule = contract.rules["A007"]
    manifest = contract.value("pyproject_file")
    config = contract.value("adapter_package_applicability")
    reason = ""
    if not (root / manifest).is_file():
        reason = "manifest is missing"
    else:
        try:
            data = _pyproject(contract, ctx)
            entries = dict(_entries(data))
            own_names = {_normalise_name(str(entries.get(key) or ""))
                         for key in config["distribution_name_keys"]}
            exempt = {_normalise_name(name) for name in config["self_distributions"]}
            if own_names & exempt:
                return []
            declared = set()
            for key, value in entries.items():
                if any(re.search(pattern, key) for pattern in config["dependency_key_patterns"]):
                    for requirement in _requirement_strings(value):
                        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
                        if match:
                            declared.add(_normalise_name(match.group(1)))
            expected = {_normalise_name(name) for name in contract.value("core_distributions")}
            if declared & expected:
                return []
            reason = "no configured Core dependency is declared"
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            reason = f"manifest could not be inspected: {exc}"
    return [Finding(rule["id"], rule["name"], rule["severity"], manifest,
                    f"adapter registration needs review: {reason}; declare the package dependency "
                    "or review its membership in contract/adapter_repositories.json")]


def _imported_name(node: ast.AST, aliases: dict[str, str]) -> str:
    dotted = _dotted_name(node)
    head, separator, tail = dotted.partition(".")
    if head not in aliases:
        return ""
    return aliases[head] + (separator + tail if separator else "")


def _string_key(node: ast.AST) -> str | None:
    if sys.version_info >= (3, 8):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
    return node.s if isinstance(node, ast.Str) else None


_SCOPE_NODES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _scope_aliases(scope: ast.AST, inherited: dict[str, str]) -> dict[str, str]:
    """Collect imports and shadowing in one lexical scope, including blocks.

    This is deliberately flow-insensitive: conflicting imports or any ordinary
    assignment to an imported name make it unresolved within that scope.
    Nested scopes cannot add imports or shadow names in their siblings.
    """
    imports: dict[str, set] = {}
    assigned = set()

    def collect(node: ast.AST) -> None:
        if node is not scope and isinstance(node, _SCOPE_NODES):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assigned.add(node.name)
            return
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                name = imported.asname or imported.name
                target = f"{node.module}.{imported.name}" if node.module and not node.level else None
                imports.setdefault(name, set()).add(target)
        elif isinstance(node, ast.Import):
            for imported in node.names:
                name = imported.asname or imported.name.split(".")[0]
                target = imported.name if imported.asname else imported.name.split(".")[0]
                imports.setdefault(name, set()).add(target)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            assigned.add(node.id)
        elif isinstance(node, ast.arg):
            assigned.add(node.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            assigned.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            assigned.add(node.name)
        for child in ast.iter_child_nodes(node):
            collect(child)

    collect(scope)
    aliases = {name: target for name, target in inherited.items()
               if name not in assigned and name not in imports}
    for name, targets in imports.items():
        if name not in assigned and len(targets) == 1 and None not in targets:
            aliases[name] = next(iter(targets))
    return aliases


def _scoped_dicts(scope: ast.AST, inherited: dict[str, str]):
    aliases = _scope_aliases(scope, inherited)
    # Class namespaces are visible in their body, not lexical closures for
    # methods or nested classes. Those inherit the enclosing non-class scope.
    child_aliases = inherited if isinstance(scope, ast.ClassDef) else aliases

    def walk(node: ast.AST):
        if node is not scope and isinstance(node, _SCOPE_NODES):
            yield from _scoped_dicts(node, child_aliases)
            return
        if isinstance(node, ast.Dict):
            yield node, aliases
        for child in ast.iter_child_nodes(node):
            yield from walk(child)

    yield from walk(scope)


def check_report_schema_version_source(root: Path, contract: Contract, ctx: dict) -> list[Finding]:
    """A011: inspect direct fields missed by A002's named-constant check.

    Resolve imports only, not arbitrary assignments or cross-file dataflow.
    That avoids duplicating A002 and prevents unrelated test constants from
    silently exempting a report that happens to use the same integer value.
    """
    rule = contract.rules["A011"]
    field = contract.value("report_schema_version_field")
    markers = set(contract.value("report_schema_marker_keys"))
    artifact_symbols = set(contract.value("report_schema_artifact_symbols"))
    modules, notices = _prepare_scan(root, contract, ctx, rule)
    findings = list(notices)
    for path, tree in modules:
        for node, aliases in _scoped_dicts(tree, {}):
            entries = {_string_key(key): value for key, value in zip(node.keys, node.values)
                       if key is not None and _string_key(key) is not None}
            if field not in entries or not markers.intersection(entries):
                continue
            value = entries[field]
            literal = _int_constant(value)
            symbol = _imported_name(value, aliases)
            if symbol in artifact_symbols:
                reason = f"uses the artifact revision `{symbol}`"
            elif literal is not None:
                reason = f"hard-codes the integer {literal}"
            else:
                continue
            findings.append(Finding(rule["id"], rule["name"], rule["severity"], _rel(root, path),
                                    f"report `{field}` (L{value.lineno}) {reason}; read the report "
                                    "schema const through install_sop_report_schema_version()"))
    return findings


PACKAGE_RULES = {
    "A007": check_adapter_python_package,
    "A011": check_report_schema_version_source,
}
