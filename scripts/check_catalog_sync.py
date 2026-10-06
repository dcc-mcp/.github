#!/usr/bin/env python3
"""Compare the curated catalog against the ground truth it claims to describe.

The public install catalog is what ``dcc-mcp-cli`` searches and what the website
quotes, so an entry that goes stale does not fail a build: it quietly tells users
that a working adapter cannot be installed. This check makes that drift visible by
comparing four sources against each other:

* ``dcc-mcp-catalog.yml`` on the default branch -- the curated source;
* ``install-catalog.json`` on the ``install-catalog`` branch -- the payload that
  was actually attested and published;
* the GitHub Releases API -- what each repository has actually shipped;
* the PyPI JSON API -- what users can actually ``pip install``.

Drift classes:

* ``stale_false_negative``      - the catalog offers no install block while the
  package is installable from PyPI. Users are told "cannot install" about
  something that installs.
* ``quarantined``               - the entry has a ``policy.installation`` of
  ``not_available``. The publisher drops the install block and records a reason
  when release validation fails, so the reason is the *only* place the failure
  survives; it is carried through verbatim.
* ``missing_entry``             - the package is on PyPI but the catalog has no
  entry at all, so ``dcc-mcp-cli search`` cannot find it. Reported as
  ``installable`` or ``not_installable``.
* ``stale_pin``                 - the entry pins a version older than the newest
  PyPI release.
* ``source_published_divergence`` - the source and the published payload disagree
  on whether an entry is installable. Editing the source alone never changes what
  users see; only a republish does.

The check is deliberately fail-open: it exists to be read, not to block a
release. Exit codes:

    0 - no drift was found, or drift was found while --fail-on is none
    1 - drift was found and --fail-on says it matters
    2 - the check could not be performed (bad input, unreachable API, ...)

``--fail-on`` defaults to ``none`` so adopting this in a nightly sweep cannot
start failing an unrelated pipeline. Raise it to ``missing_entry`` or ``any``
when the backlog has been cleared.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

DEFAULT_OWNER = "dcc-mcp"
DEFAULT_CATALOG_REPO = "dcc-mcp-core"
DEFAULT_CATALOG_PATH = "dcc-mcp-catalog.yml"
DEFAULT_PUBLISHED_BRANCH = "install-catalog"
DEFAULT_PUBLISHED_PATH = "install-catalog.json"
DEFAULT_TIMEOUT_SECONDS = 30.0

# Entries that describe shared infrastructure or a remote connector rather than a
# DCC adapter. They legitimately have no PyPI package of their own, so no PyPI
# lookup is attempted and they are excluded from the adapter count.
INFRASTRUCTURE = frozenset(
    {
        "dcc-mcp-core",
        "dcc-mcp-office",
        "dcc-mcp-runtime",
        "dcc-mcp-agent-plugins",
        "dcc-mcp-cache-inspector",
        "autodesk-product-help",
    }
)

# Catalog name -> PyPI project, when the two differ. The catalog carries
# `dcc-mcp-PowerPoint` while PyPI normalises the project to `dcc-mcp-powerpoint`,
# so the fallback guess is only used when no explicit mapping exists.
PACKAGE_ALIASES = {
    "dcc-mcp-PowerPoint": "dcc-mcp-powerpoint",
}

QUARANTINE_MARKER = "Release validation failed"

STATE_IN_SYNC = "in_sync"
STATE_STALE_FALSE_NEGATIVE = "stale_false_negative"
STATE_QUARANTINED = "quarantined"
STATE_MISSING_ENTRY = "missing_entry"
STATE_STALE_PIN = "stale_pin"
STATE_SOURCE_PUBLISHED_DIVERGENCE = "source_published_divergence"
STATE_CORRECTLY_UNAVAILABLE = "correctly_unavailable"

# Only these mean "somebody has to do something". `in_sync` and
# `correctly_unavailable` are the healthy outcomes and must never fail a run.
DRIFT_STATES = frozenset(
    {
        STATE_STALE_FALSE_NEGATIVE,
        STATE_QUARANTINED,
        STATE_MISSING_ENTRY,
        STATE_STALE_PIN,
        STATE_SOURCE_PUBLISHED_DIVERGENCE,
    }
)

FAIL_ON_CHOICES = ("none", "missing_entry", "any")

_VERSION_SPLIT = re.compile(r"[._-]")
_LEADING_DIGITS = re.compile(r"[0-9]+")


class CheckError(RuntimeError):
    """Raised when the check itself cannot be performed."""


@dataclass
class Finding:
    """One entry that drifted from the ground truth."""

    name: str
    state: str
    message: str
    pypi_version: str | None = None
    catalog_version: str | None = None
    github_release: str | None = None
    reason: str | None = None
    installable: bool | None = None
    in_source: bool = True
    in_published: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CatalogSnapshot:
    """A catalog reduced to the fields this check compares."""

    entries: list[dict[str, Any]]

    def names(self) -> set[str]:
        return {entry.get("name", "") for entry in self.entries if entry.get("name")}

    def install_available(self) -> set[str]:
        return {entry["name"] for entry in self.entries if entry.get("name") and entry.get("install")}

    def entry(self, name: str) -> dict[str, Any] | None:
        for entry in self.entries:
            if entry.get("name") == name:
                return entry
        return None


def parse_version(value: str) -> tuple[int, ...]:
    """Return a comparable tuple for a version string.

    Numeric components sort numerically, so 0.10.0 is newer than 0.9.31. A
    non-numeric component (``rc1``) is dropped rather than compared as text,
    which would make ``1.0.0rc1`` sort above ``1.0.0``.
    """
    parts: list[int] = []
    for part in _VERSION_SPLIT.split(value.strip()):
        # A component may carry a suffix (`0rc1`, `2post1`). Take its leading digits
        # so `1.0.0rc1` keeps all three numeric components; discarding the component
        # outright would make it compare as 1.0 and sort below 1.0.0.
        match = _LEADING_DIGITS.match(part)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def package_for(name: str) -> str | None:
    """Return the PyPI project name for a catalog entry, or None for infrastructure."""
    if name in INFRASTRUCTURE:
        return None
    return PACKAGE_ALIASES.get(name, name)


def fetch_json(url: str, timeout: float) -> Any:
    """GET ``url`` and parse the body as JSON. ``None`` on 404."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise CheckError(f"{url} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CheckError(f"could not fetch {url}: {exc}") from exc


def pypi_version(package: str, timeout: float, version: str | None = None) -> dict[str, Any] | None:
    """Return PyPI metadata for ``package``, or None when it does not exist.

    A specific ``version`` is requested when the caller needs that exact release's
    artifacts; the unpinned URL is used otherwise so the answer is the newest
    release PyPI serves.
    """
    url = f"https://pypi.org/pypi/{package}/json"
    if version:
        url = f"https://pypi.org/pypi/{package}/{version}/json"
    return fetch_json(url, timeout)


def run_gh(args: Sequence[str], timeout: float, what: str) -> str:
    """Run a ``gh`` command and return its stdout, or raise ``CheckError``."""
    try:
        completed = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise CheckError("the `gh` CLI is required but was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError(f"`gh {' '.join(args)}` timed out after {timeout}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise CheckError(f"could not {what}: {detail}")
    return completed.stdout


def gh_json(args: Sequence[str], timeout: float, what: str) -> Any:
    """Run a ``gh`` command and parse its stdout as JSON."""
    try:
        return json.loads(run_gh(args, timeout, what))
    except json.JSONDecodeError as exc:
        raise CheckError(f"could not parse the response of {what}") from exc


def fetch_source_catalog(
    repository: str, path: str, timeout: float, ref: str = ""
) -> CatalogSnapshot:
    """Load the curated catalog from the repository default branch.

    Read through the API rather than a checkout so the script stays usable from a
    workflow that never clones ``dcc-mcp-core``.
    """
    reference = ref or ""
    args = ["api", f"repos/{repository}/contents/{path}"]
    if reference:
        args.append(f"?ref={reference}")
    payload = gh_json(args, timeout, f"read {repository}:{path}")
    if isinstance(payload, dict) and payload.get("encoding") == "base64":
        import base64

        text = base64.b64decode(payload.get("content") or "").decode("utf-8")
    else:
        raise CheckError(f"unexpected payload reading {repository}:{path}")
    return parse_catalog_yaml(text)


def parse_catalog_yaml(text: str) -> CatalogSnapshot:
    """Parse the catalog YAML with the stdlib only.

    The curated file is a two-key document (``version`` plus a flat list of
    ``entries``) whose every value is a scalar, list of scalars, or one nested
    ``install``/``python_path`` mapping. A tiny targeted reader keeps this script
    stdlib-only, which the repository contract requires, instead of pulling PyYAML
    into a gate that has no dependency manifest.
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section: str | None = None

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            section = None
            stripped = stripped[2:].strip()
        if current is None:
            continue
        if stripped in ("install:", "policy:"):
            # Both blocks are flat mappings nested one level under an entry, so the
            # parser tracks which one the following `key: value` lines belong to.
            section = stripped[:-1]
            current[section] = {}
            continue
        if not stripped.startswith("- ") and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                value = value.strip('"').strip("'")
            target = current[section] if section else current
            if value:
                target[key] = value
            else:
                target[key] = None
    return CatalogSnapshot(entries=[entry for entry in entries if entry.get("name")])


def fetch_published_catalog(
    repository: str, branch: str, path: str, timeout: float
) -> CatalogSnapshot:
    """Load the published payload, unwrapping its attestation envelope.

    ``install-catalog.json`` is an envelope whose ``catalog`` member holds the
    entries as a *JSON-encoded string*, not as an object, so the payload has to be
    decoded twice.
    """
    payload = gh_json(
        ["api", f"repos/{repository}/contents/{path}?ref={branch}"],
        timeout,
        f"read {repository}:{path} on {branch}",
    )
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise CheckError(f"unexpected payload reading {repository}:{path} on {branch}")
    import base64

    envelope = json.loads(base64.b64decode(payload.get("content") or "").decode("utf-8"))
    inner = envelope.get("catalog")
    if isinstance(inner, str):
        inner = json.loads(inner)
    if not isinstance(inner, dict):
        raise CheckError(f"{path} does not hold a catalog object")
    entries = inner.get("entries")
    if not isinstance(entries, list):
        raise CheckError(f"{path} has no entries list")
    return CatalogSnapshot(entries=[entry for entry in entries if isinstance(entry, dict) and entry.get("name")])


def organization_repositories(owner: str, timeout: float) -> list[str]:
    """Return every non-archived source repository of ``owner`` as bare names."""
    payload = gh_json(
        [
            "api",
            f"orgs/{owner}/repos?per_page=100&type=sources",
            "--paginate",
        ],
        timeout,
        f"list repositories of {owner}",
    )
    if not isinstance(payload, list):
        raise CheckError(f"unexpected payload listing repositories of {owner}")
    return sorted(
        item["name"]
        for item in payload
        if isinstance(item, dict) and item.get("name") and not item.get("archived")
    )


def latest_release(repository: str, timeout: float) -> str | None:
    """Return the tag name of the newest stable release, or None when there is none."""
    try:
        payload = gh_json(
            ["api", f"repos/{repository}/releases/latest"], timeout, f"read the latest release of {repository}"
        )
    except CheckError:
        return None
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name") or payload.get("tagName")
    return tag if isinstance(tag, str) else None


def compare_source_published(
    source: CatalogSnapshot, published: CatalogSnapshot
) -> list[Finding]:
    """Report entries whose installability differs between source and publication."""
    source_available = source.install_available()
    published_available = published.install_available()
    findings: list[Finding] = []
    for name in sorted((source_available ^ published_available) & source.names() & published.names()):
        in_source = name in source_available
        findings.append(
            Finding(
                name=name,
                state=STATE_SOURCE_PUBLISHED_DIVERGENCE,
                message=(
                    f"{name} is installable in the source catalog but not in the published one; "
                    "editing the source does not change what users see until the catalog is republished"
                    if in_source
                    else f"{name} is installable in the published catalog but not in the source one"
                ),
                in_source=True,
                in_published=True,
            )
        )
    return findings


def evaluate_entry(
    name: str,
    published: CatalogSnapshot,
    package: str | None,
    timeout: float,
) -> Finding | None:
    """Compare one catalog entry against PyPI and GitHub."""
    entry = published.entry(name)
    if entry is None:
        return None

    policy = entry.get("policy") if isinstance(entry.get("policy"), dict) else {}
    installation = policy.get("installation")
    reason = policy.get("reason")
    catalog_version = entry.get("version")
    has_install = bool(entry.get("install"))

    # Quarantine first: the publisher already decided this entry is broken, and the
    # reason is the only surviving record of why. Surfacing it as a plain
    # "unavailable" would hide the very signal this check exists to expose.
    if installation == "not_available":
        quarantined = QUARANTINE_MARKER in (reason or "")
        if quarantined:
            metadata = pypi_version(package, timeout) if package else None
            newest = (metadata or {}).get("info", {}).get("version") if metadata else None
            return Finding(
                name=name,
                state=STATE_QUARANTINED,
                message=(
                    f"{name} was quarantined by release validation and is published as "
                    f"not installable; pinned {catalog_version or 'unknown'}, PyPI has {newest or 'no release'}"
                ),
                pypi_version=newest,
                catalog_version=catalog_version,
                reason=reason,
                installable=False,
            )

    if package is None:
        return None

    metadata = pypi_version(package, timeout)
    newest = metadata.get("info", {}).get("version") if isinstance(metadata, dict) else None

    if not has_install:
        if newest:
            return Finding(
                name=name,
                state=STATE_STALE_FALSE_NEGATIVE,
                message=f"{name} has no install block but {package} {newest} is on PyPI",
                pypi_version=newest,
                catalog_version=catalog_version,
                installable=True,
            )
        return None

    if newest and catalog_version and parse_version(newest) > parse_version(catalog_version or ""):
        return Finding(
            name=name,
            state=STATE_STALE_PIN,
            message=f"{name} pins {catalog_version} but PyPI has {newest}",
            pypi_version=newest,
            catalog_version=catalog_version,
            installable=True,
        )
    return None


def evaluate_missing(
    repository: str,
    source: CatalogSnapshot,
    published: CatalogSnapshot,
    timeout: float,
) -> Finding | None:
    """Report a repository that ships to PyPI but has no catalog entry."""
    name = repository
    if name in source.names() or name in published.names():
        return None
    if name in INFRASTRUCTURE:
        return None

    package = package_for(name)
    metadata = pypi_version(package, timeout) if package else None
    newest = metadata.get("info", {}).get("version") if isinstance(metadata, dict) else None
    if newest is None:
        return None

    return Finding(
        name=name,
        state=STATE_MISSING_ENTRY,
        message=f"{name} ships {package} {newest} to PyPI but has no catalog entry, so `dcc-mcp-cli search` cannot find it",
        pypi_version=newest,
        github_release=latest_release(f"{DEFAULT_OWNER}/{repository}", timeout),
        installable=True,
        in_source=False,
        in_published=False,
    )


def render_text(report: dict[str, Any]) -> str:
    """Render the drift report as text."""
    findings: list[dict[str, Any]] = report["findings"]
    counts: dict[str, int] = report["counts"]
    lines = [
        f"Catalog drift: {len(findings)} finding(s) across "
        f"{report['published']['entries']} published entries "
        f"({report['published']['install_available']} install available).",
        "",
    ]
    if not findings:
        lines.append("OK - the catalog agrees with PyPI and GitHub.")
        return "\n".join(lines)

    lines.append("Counts: " + ", ".join(f"{state}={count}" for state, count in sorted(counts.items())))
    lines.append("")
    for state in sorted({finding["state"] for finding in findings}):
        lines.append(f"{state}:")
        for finding in findings:
            if finding["state"] != state:
                continue
            lines.append(f"  {finding['name']}")
            lines.append(f"      {finding['message']}")
            if finding.get("reason"):
                lines.append(f"      reason: {finding['reason']}")
            if finding.get("github_release"):
                lines.append(f"      release: {finding['github_release']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the curated install catalog against PyPI and GitHub releases.",
    )
    parser.add_argument("--owner", default=DEFAULT_OWNER, help=f"organization to sweep (default: {DEFAULT_OWNER})")
    parser.add_argument(
        "--catalog-repository",
        default=DEFAULT_CATALOG_REPO,
        help=f"repository holding the catalog (default: {DEFAULT_CATALOG_REPO})",
    )
    parser.add_argument("--catalog-path", default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--catalog-ref", default="", help="git ref of the source catalog (default: default branch)")
    parser.add_argument("--published-branch", default=DEFAULT_PUBLISHED_BRANCH)
    parser.add_argument("--published-path", default=DEFAULT_PUBLISHED_PATH)
    parser.add_argument(
        "--repositories",
        default="",
        help="comma-separated repository names to sweep instead of every repository of --owner",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--fail-on",
        choices=FAIL_ON_CHOICES,
        default="none",
        help="none (default, fail-open), missing_entry, or any drift",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        source = fetch_source_catalog(
            f"{args.owner}/{args.catalog_repository}", args.catalog_path, args.timeout, args.catalog_ref
        )
        published = fetch_published_catalog(
            f"{args.owner}/{args.catalog_repository}", args.published_branch, args.published_path, args.timeout
        )

        findings: list[Finding] = []
        findings.extend(compare_source_published(source, published))

        for name in sorted(published.names()):
            finding = evaluate_entry(name, published, package_for(name), args.timeout)
            if finding is not None:
                findings.append(finding)

        repositories = (
            [item.strip() for item in args.repositories.split(",") if item.strip()]
            if args.repositories
            else organization_repositories(args.owner, args.timeout)
        )
        for repository in repositories:
            finding = evaluate_missing(repository, source, published, args.timeout)
            if finding is not None:
                findings.append(finding)

        counts: dict[str, int] = {}
        for finding in findings:
            counts[finding.state] = counts.get(finding.state, 0) + 1

        report = {
            "measured_at": None,
            "owner": args.owner,
            "source": {
                "entries": len(source.entries),
                "install_available": len(source.install_available()),
            },
            "published": {
                "entries": len(published.entries),
                "install_available": len(published.install_available()),
            },
            "counts": counts,
            "findings": [finding.as_dict() for finding in findings],
        }

        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            print(render_text(report))

        if not findings:
            return 0
        if args.fail_on == "any":
            return 1
        if args.fail_on == "missing_entry" and counts.get(STATE_MISSING_ENTRY):
            return 1
        # Fail-open: drift is reported for a human to read, never silently merged
        # into a release gate.
        return 0
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
