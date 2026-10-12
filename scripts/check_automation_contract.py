#!/usr/bin/env python3
"""Validate the public automation inventory and report local source-blob drift.

Stdlib only; no network, git commands, workflow execution, or credential reads.
This first-stage contract is always advisory, including invalid/unreadable input.
The JSON Schema interpreter deliberately supports only the vocabulary used by
the bundled schema and rejects unknown keywords rather than ignoring them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract"
SCHEMA_KEYWORDS = {
    "$schema",
    "title",
    "description",
    "$comment",
    "type",
    "const",
    "properties",
    "additionalProperties",
    "required",
    "items",
    "uniqueItems",
    "minimum",
    "pattern",
    "format",
}


def validate_schema(schema: dict) -> None:
    """Reject unsupported vocabulary even in optional or empty-array branches."""
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        raise ValueError(f"unsupported schema keywords: {', '.join(sorted(unknown))}")
    for child in schema.get("properties", {}).values():
        validate_schema(child)
    for keyword in ("items", "additionalProperties"):
        if isinstance(schema.get(keyword), dict):
            validate_schema(schema[keyword])


def schema_errors(value: object, schema: dict, path: str = "$") -> list[str]:
    """Validate the bundled JSON Schema subset without logging input values."""
    if path == "$":
        validate_schema(schema)
    types = schema.get("type", [])
    if isinstance(types, str):
        types = [types]
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "null": value is None,
    }
    if any(kind not in matches for kind in types):
        raise ValueError("unsupported schema type")
    if types and not any(matches[kind] for kind in types):
        return [f"{path}: expected {' or '.join(types)}"]
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: unexpected constant")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors.extend(
            f"{path}.{key}: required property missing" for key in schema.get("required", []) if key not in value
        )
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                errors.extend(schema_errors(item, properties[key], f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}.{key}: unexpected property")
            elif isinstance(additional, dict):
                errors.extend(schema_errors(item, additional, f"{path}.{key}"))
    if isinstance(value, list):
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            errors.append(f"{path}: duplicate items")
        for index, item in enumerate(value):
            errors.extend(schema_errors(item, schema.get("items", {}), f"{path}[{index}]"))
    if type(value) is int and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below minimum")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: pattern mismatch")
        fmt = schema.get("format")
        if fmt == "date-time":
            try:
                if not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value, re.IGNORECASE
                ):
                    raise ValueError("RFC 3339 timestamp required")
                dt.datetime.fromisoformat(value.upper())
            except ValueError:
                errors.append(f"{path}: invalid date-time")
        elif fmt == "uri":
            try:
                valid = bool(urlsplit(value).scheme) and not any(char.isspace() for char in value)
            except ValueError:
                valid = False
            if not valid:
                errors.append(f"{path}: invalid URI")
        elif fmt is not None:
            raise ValueError(f"unsupported schema format: {fmt}")
    return errors


def inventory_errors(inventory: dict, schema: dict, policy: dict) -> list[str]:
    errors = schema_errors(inventory, schema)
    if errors:
        return errors
    organizations = inventory["scope"]["organizations"]
    if len(set(organizations)) != len(organizations) or set(organizations) - set(policy["organizations"]):
        errors.append("$.scope.organizations: duplicate or unapproved organization")
    if set(inventory["scope"]["discovered_public_repositories"]) != set(organizations):
        errors.append("$.scope.discovered_public_repositories: organization keys differ from scope")
    if inventory["scope"]["representative_repositories"] != len(inventory["repositories"]):
        errors.append("$.scope.representative_repositories: does not match inventory length")
    seen = set()
    for index, entry in enumerate(inventory["repositories"]):
        name = entry["repository"].casefold()
        prefix = f"$.repositories[{index}]"
        if name in seen or name.split("/")[0] not in organizations:
            errors.append(f"{prefix}.repository: duplicate or outside organization scope")
        seen.add(name)
        paths = set()
        for source in entry["source_files"]:
            path = source["path"]
            parts = PurePosixPath(path)
            if (
                path in paths
                or parts.is_absolute()
                or ".." in parts.parts
                or str(parts) != path
                or "\\" in path
                or not any(fnmatch.fnmatchcase(path, pattern) for pattern in policy["source_path_patterns"])
            ):
                errors.append(f"{prefix}.source_files: duplicate or out-of-scope path")
            paths.add(path)
    return errors


def blob_sha(data: bytes) -> str:
    """Git blob object id, not a security or credential fingerprint."""
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()


def finding(policy: dict, kind: str, path: str, message: str) -> dict:
    rule = policy["rules"][kind]
    return {
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "severity": rule["severity"],
        "path": path,
        "message": message,
    }


def check(root: Path, repository: str | None, inventory: dict, schema: dict, policy: dict) -> dict:
    result = {"repository": repository, "status": "validated", "checked_files": 0, "findings": []}
    errors = inventory_errors(inventory, schema, policy)
    if errors:
        result.update(status="invalid", findings=[finding(policy, "inventory", "", error) for error in errors])
        return result
    if repository is None:
        return result
    entry = next(
        (item for item in inventory["repositories"] if item["repository"].casefold() == repository.casefold()), None
    )
    if entry is None:
        result["status"] = "not_in_inventory"
        return result
    result["status"] = "checked"
    root = root.resolve()
    for source in entry["source_files"]:
        relative = source["path"]
        path = root / relative
        # Never follow a symlink from a repository under test, even within root.
        components = [
            root.joinpath(*PurePosixPath(relative).parts[:i]) for i in range(1, len(PurePosixPath(relative).parts) + 1)
        ]
        try:
            if any(part.is_symlink() for part in components) or not path.is_file():
                raise ValueError("source missing, non-regular, or symlinked")
            actual = blob_sha(path.read_bytes())
        except (OSError, ValueError):
            result["findings"].append(
                finding(
                    policy,
                    "source",
                    relative,
                    "Audited source is missing or cannot be safely read; review the inventory.",
                )
            )
            continue
        result["checked_files"] += 1
        if actual != source["blob_sha"]:
            result["findings"].append(
                finding(
                    policy,
                    "drift",
                    relative,
                    f"Source differs from the {inventory['observed_at']} audit (expected {source['blob_sha']}, actual {actual}); re-audit before updating the baseline.",
                )
            )
    return result


def escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--repository", help="Exact owner/repository of the local checkout")
    selection.add_argument("--validate-only", action="store_true")
    parser.add_argument("--inventory", type=Path, default=CONTRACT / "automation_inventory.json")
    parser.add_argument("--schema", type=Path, default=CONTRACT / "automation_inventory.schema.json")
    parser.add_argument("--policy", type=Path, default=CONTRACT / "automation_policy.json")
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = parser.parse_args(argv)
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        if set(policy["rules"]) != {"inventory", "source", "drift"} or any(
            rule["severity"] != "warning" for rule in policy["rules"].values()
        ):
            raise ValueError("automation policy must remain warning-only")
        result = check(
            args.root,
            args.repository,
            json.loads(args.inventory.read_text(encoding="utf-8")),
            json.loads(args.schema.read_text(encoding="utf-8")),
            policy,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, re.error):
        # Do not echo malformed input, filenames, or credential-like values.
        result = {
            "repository": args.repository,
            "status": "unavailable",
            "checked_files": 0,
            "findings": [
                {
                    "rule_id": "",
                    "rule_name": "automation-contract-unavailable",
                    "severity": "warning",
                    "path": "",
                    "message": "Automation inventory, schema, or policy could not be read or validated. No drift assessment was made.",
                }
            ],
        }
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        for item in result["findings"]:
            message = f"{item['path']}: {item['message']}" if item["path"] else item["message"]
            if args.format == "github":
                print(f"::warning title=Automation contract {item['rule_id']}::{escape(message)}")
            else:
                print(f"warning {item['rule_id']}: {message}")
        print(
            f"Automation inventory: {result['status']}; {result['checked_files']} source files checked; {len(result['findings'])} warnings (advisory only)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
