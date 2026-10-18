#!/usr/bin/env python3
"""Read-only package-size and runtime-boundary audit (stdlib only).

No extraction, imports, installs or network access. ZIP/wheel and tar archives
are inspected, including bounded nested wheel/ZIP payloads. Arbitrary native
executables and compressed executable resources cannot be inspected here.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import io
import json
import lzma
import re
import sys
import tarfile
import zipfile
import zlib
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "contract" / "adapter_contract.json"


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def required_without_extras(requirement: str) -> bool:
    """Conservatively identify requirements possible with no activated extra.

    Only extra ==/!= literal atoms are resolved. Other environment atoms may
    be true on some supported target. Unsupported syntax remains required,
    never silently exempt. This is not a general PEP 508 environment evaluator.
    """
    if ";" not in requirement:
        return True
    try:
        tree = ast.parse(requirement.split(";", 1)[1].strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return True

    def possible(node):
        if isinstance(node, ast.BoolOp):
            children = [possible(value) for value in node.values]
            if isinstance(node.op, ast.And):
                return ({True} if all(True in child for child in children) else set()) | ({False} if any(False in child for child in children) else set())
            if isinstance(node.op, ast.Or):
                return ({True} if any(True in child for child in children) else set()) | ({False} if all(False in child for child in children) else set())
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = node.left, node.comparators[0]
            if isinstance(right, ast.Name) and right.id == "extra":
                left, right = right, left
            if isinstance(left, ast.Name) and left.id == "extra" and isinstance(right, ast.Constant) and isinstance(right.value, str):
                if isinstance(node.ops[0], ast.Eq):
                    return {right.value == ""}
                if isinstance(node.ops[0], ast.NotEq):
                    return {right.value != ""}
        return {False, True}
    try:
        return True in possible(tree.body)
    except RecursionError:
        return True


def audit(path: Path, contract: dict, mode: str = "inspect", adapter: str | None = None) -> dict:
    policy = contract["runtime_artifact_policy"]
    report = {"artifact": path.name, "archive_bytes": path.stat().st_size, "sha256": "",
              "mode": mode, "check_scope": "recognized archive members and declared distribution metadata only",
              "top_level_unpacked_bytes": 0, "nested_payload_unpacked_bytes": 0,
              "inspection_complete": True,
              "members": 0, "distributions": [], "interpreter_payloads": [], "environment_payloads": [],
              "largest_members": [], "findings": [], "limitations": [
                  "Archive sizes are measured bytes, not an installed footprint; nested archive expansion is reported separately.",
                  "Metadata inventories do not establish import closure, signature validity, runtime availability or real-host acceptance.",
                  "Opaque executables and unrecognized archive formats may contain hidden runtimes or vendored modules."]}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    report["sha256"] = digest.hexdigest()
    largest = []
    nested_read = 0
    unpacked_read = 0

    def finding(message: str) -> None:
        if len(report["findings"]) < policy["max_findings"]:
            report["findings"].append(message)

    def incomplete(message: str) -> None:
        report["inspection_complete"] = False
        finding(message)

    def read_member(display: str, size: int, open_member, retain: bool) -> bytes:
        """Validate every payload through EOF without buffering ordinary files.

        Reading ZIP members checks encryption, compression and CRC errors. The
        aggregate budget includes both outer members and nested expansion, and
        is checked against actual reads as well as untrusted header sizes.
        """
        nonlocal unpacked_read
        if size < 0 or size > policy["max_unpacked_bytes"] - unpacked_read:
            raise ValueError(f"expanded byte limit exceeded: {display}")
        payload = bytearray()
        measured = 0
        with open_member() as handle:
            while True:
                remaining = min(size - measured, policy["max_unpacked_bytes"] - unpacked_read)
                block = handle.read(min(64 * 1024, remaining + 1))
                if not block:
                    break
                measured += len(block)
                unpacked_read += len(block)
                if unpacked_read > policy["max_unpacked_bytes"]:
                    raise ValueError(f"expanded byte limit exceeded: {display}")
                if measured > size:
                    raise ValueError(f"member size differs from header: {display}")
                if retain:
                    payload.extend(block)
        if measured != size:
            raise ValueError(f"member size differs from header: {display}")
        return bytes(payload)

    def inspect_member(name: str, size: int, open_member, depth: int, prefix: str, seen: set) -> None:
        nonlocal nested_read
        report["members"] += 1
        if report["members"] > policy["max_members"]:
            raise ValueError("archive member limit exceeded; audit is incomplete")
        normalized = name.replace("\\", "/")
        member = PurePosixPath(normalized)
        display = prefix + normalized
        if normalized in seen:
            finding(f"duplicate archive member: {display}")
        seen.add(normalized)
        if member.is_absolute() or ".." in member.parts or re.match(r"^[A-Za-z]:", normalized):
            finding(f"unsafe member path: {display}")
        base = member.name.lower()
        is_metadata = base in policy["metadata_basenames"]
        is_nested = any(base.endswith(suffix) for suffix in policy["nested_archive_suffixes"])
        read_metadata = is_metadata and size <= policy["max_metadata_bytes"]
        read_nested = is_nested and depth < policy["max_nested_depth"] and nested_read + size <= policy["max_nested_bytes"]
        payload = read_member(display, size, open_member, read_metadata or read_nested)
        # These sizes only include payloads read to EOF and checked against the
        # declared size. An incomplete report must not be used as a total size.
        key = "top_level_unpacked_bytes" if depth == 0 else "nested_payload_unpacked_bytes"
        report[key] += size
        largest.append({"path": display, "bytes": size})
        if any(fnmatch.fnmatchcase(base, pattern) for pattern in policy["interpreter_basenames"]):
            report["interpreter_payloads"].append({"path": display, "bytes": size})
        if base in policy["environment_files"] or any(part.lower() in policy["environment_directories"] for part in member.parts[:-1]):
            report["environment_payloads"].append({"path": display, "bytes": size})
        if is_metadata:
            if not read_metadata:
                incomplete(f"metadata size limit exceeded: {display}")
            else:
                metadata = BytesParser().parsebytes(payload, headersonly=True)
                names, versions = metadata.get_all("Name", []), metadata.get_all("Version", [])
                if len(names) != 1 or len(versions) != 1 or not str(names[0]).strip() or not str(versions[0]).strip():
                    finding(f"metadata must have one Name and Version: {display}")
                else:
                    report["distributions"].append({"name": str(names[0]), "version": str(versions[0]), "path": display,
                                                    "requires_dist": metadata.get_all("Requires-Dist", [])})
        elif is_nested:
            if not read_nested:
                incomplete(f"nested archive inspection limit exceeded: {display}")
            else:
                nested_read += size
                try:
                    inspect_archive(io.BytesIO(payload), depth + 1, display + "!/")
                except (ValueError, OSError, RuntimeError, EOFError, NotImplementedError, lzma.LZMAError, zlib.error, tarfile.TarError, zipfile.BadZipFile) as exc:
                    incomplete(f"cannot inspect nested archive {display}: {exc}")

    def inspect_archive(source, depth: int, prefix: str) -> None:
        seen: set[str] = set()
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    if not member.is_dir():
                        inspect_member(member.filename, member.file_size, lambda m=member: archive.open(m), depth, prefix, seen)
        else:
            if hasattr(source, "seek"):
                source.seek(0)
                archive = tarfile.open(fileobj=source, mode="r:*")
            else:
                archive = tarfile.open(source, mode="r:*")
            with archive:
                for member in archive:
                    if member.isfile():
                        def open_member(m=member):
                            handle = archive.extractfile(m)
                            if handle is None:
                                raise ValueError(f"unreadable member {m.name}")
                            return handle
                        inspect_member(member.name, member.size, open_member, depth, prefix, seen)
                    elif member.issym() or member.islnk():
                        inspect_member(member.name, 0, io.BytesIO, depth, prefix, seen)

    try:
        inspect_archive(path, 0, "")
    except (ValueError, OSError, RuntimeError, EOFError, NotImplementedError, lzma.LZMAError, zlib.error, tarfile.TarError, zipfile.BadZipFile) as exc:
        incomplete(f"archive inspection incomplete: {exc}")
    report["largest_members"] = sorted(largest, key=lambda item: item["bytes"], reverse=True)[:policy["largest_members"]]
    if mode in ("host", "external"):
        for category in ("interpreter_payloads", "environment_payloads"):
            if report[category]:
                finding(f"adapter artifact includes {category}: use host Python or a separately distributed official shared runtime")
    if mode == "host":
        if not adapter:
            finding("host artifact enforcement requires --adapter with the exact adapter distribution name")
        allowed = {canonical_name(name) for name in contract["runtime_host_distributions"]}
        if adapter:
            allowed.add(canonical_name(adapter))
        for distribution in report["distributions"]:
            if canonical_name(distribution["name"]) not in allowed:
                finding(f"host artifact includes third-party distribution: {distribution['name']} ({distribution['path']})")
            for requirement in distribution["requires_dist"]:
                if not required_without_extras(requirement):
                    continue
                match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]+)\])?", requirement)
                if match is None:
                    finding(f"cannot identify built Requires-Dist: {requirement!r}")
                elif canonical_name(match.group(1)) not in allowed:
                    finding(f"host artifact requires third-party distribution: {requirement!r} ({distribution['name']})")
                elif match.group(2):
                    extras = {canonical_name(extra.strip()) for extra in match.group(2).split(",")}
                    supported = set(contract["runtime_host_extras"].get(canonical_name(match.group(1)), []))
                    if extras - supported:
                        finding(f"host artifact activates unaudited extras: {requirement!r}")
    report["passed"] = not report["findings"]
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--mode", choices=("inspect", "host", "external"), default="inspect")
    parser.add_argument("--adapter")
    args = parser.parse_args(argv)
    try:
        report = audit(args.artifact, json.loads(args.contract.read_text(encoding="utf-8")), args.mode, args.adapter)
    except (OSError, ValueError, KeyError) as exc:
        print(f"artifact audit unavailable: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
