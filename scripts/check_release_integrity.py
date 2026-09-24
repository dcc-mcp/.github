#!/usr/bin/env python3
"""Compare the newest GitHub release tag of a repository with the version on PyPI.

A repository/package pair is *consistent* when the newest GitHub release tag, with a
leading ``v`` stripped, equals the version reported by
``https://pypi.org/pypi/<package>/json``.

Two kinds of mismatch are tolerated and reported as warnings instead of failures:

* the release was published less than ``--grace-minutes`` ago, because a PyPI upload
  lands minutes after the GitHub release is created;
* the PyPI version is *newer* than the newest stable GitHub release, which happens
  when a pre-release was uploaded to PyPI but ``releases/latest`` still points at the
  previous stable release.

Any other mismatch means the release pipeline produced a GitHub release without a
matching PyPI upload and is reported as a failure.

Exit codes:
    0 - every pair is consistent, or only tolerated mismatches were found
    1 - at least one pair is inconsistent
    2 - the check could not be performed (bad input, unreachable API, ...)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
DEFAULT_TIMEOUT_SECONDS = 30.0

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"

FAILING_STATUSES = frozenset({STATUS_FAIL})


class CheckError(RuntimeError):
    """Raised when the check itself cannot be performed."""


@dataclass(frozen=True)
class Target:
    """A single repository/package pair to compare."""

    repository: str
    package: str

    @property
    def key(self) -> str:
        return f"{self.repository}:{self.package}"


@dataclass(frozen=True)
class Result:
    """Outcome of comparing one repository/package pair."""

    repository: str
    package: str
    status: str
    message: str
    release_tag: str | None = None
    release_published_at: str | None = None
    pypi_version: str | None = None

    @property
    def key(self) -> str:
        return f"{self.repository}:{self.package}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_tag(tag: str) -> str:
    """Strip a leading ``v``/``V`` and surrounding whitespace from a release tag."""
    return tag.strip().lstrip("vV").strip()


def parse_version(value: str) -> tuple[int, ...]:
    """Return a comparable numeric tuple for a version string.

    Non numeric parts (``rc``, ``dev``, ``post``, ...) collapse to ``0``; ordering is
    only used to decide whether PyPI is ahead of GitHub, never to decide equality.
    """
    cleaned = (value or "").strip().lstrip("vV")
    if not cleaned:
        return ()
    parts: list[int] = []
    for chunk in re.split(r"[.+\-_]", cleaned):
        match = re.match(r"\d+", chunk)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts)


def compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Return -1/0/1 comparing two version tuples, padding the shorter one with zeros."""
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def latest_release(repository: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any] | None:
    """Return the newest published GitHub release for ``repository``.

    Returns ``None`` when the repository has no published release.
    """
    command = [
        "gh",
        "release",
        "view",
        "--repo",
        repository,
        "--json",
        "tagName,publishedAt,isPrerelease,isDraft",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment problem
        raise CheckError("the `gh` CLI is required but was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError(f"`gh release view --repo {repository}` timed out") from exc

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        lowered = message.lower()
        if "no published releases" in lowered or "not found" in lowered or "404" in lowered:
            # `/releases/latest` answers 404 both for "this repository has no release" and for
            # "this repository does not exist / the token cannot see it". Treating both as an
            # absent release would turn a typo in the manifest, a renamed repository, or a
            # narrowed token into a permanently green check - exactly the silent failure this
            # gate exists to catch. Only the reachable-and-empty case may be skipped.
            _require_reachable(repository, timeout)
            return None
        raise CheckError(f"could not read the latest release of {repository}: {message}")

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CheckError(f"`gh release view --repo {repository}` returned invalid JSON") from exc


def _require_reachable(repository: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Raise ``CheckError`` unless ``repository`` exists and is visible to the token.

    Used to tell the two meanings of a 404 from ``/releases/latest`` apart.
    """
    try:
        probe = subprocess.run(
            ["gh", "api", f"repos/{repository}", "--jq", ".full_name"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CheckError(f"timed out checking whether {repository} is reachable") from exc

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip()
        raise CheckError(
            f"{repository} is not reachable, so its release state cannot be verified: {detail}"
        )


def pypi_version(package: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str | None:
    """Return the version of ``package`` published on PyPI, or ``None`` if absent."""
    request = urllib.request.Request(
        PYPI_JSON_URL.format(package=package),
        headers={"User-Agent": "dcc-mcp-release-integrity/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise CheckError(f"PyPI returned HTTP {exc.code} for {package}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CheckError(f"PyPI is unreachable for {package}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(f"PyPI returned invalid JSON for {package}") from exc

    version = (payload.get("info") or {}).get("version")
    return str(version) if version else None


def parse_published_at(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp as returned by the GitHub API."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate(target: Target, grace_minutes: float = 0.0, now: datetime | None = None) -> Result:
    """Compare the newest GitHub release of ``target.repository`` with ``target.package``."""
    now = now or datetime.now(timezone.utc)

    release = latest_release(target.repository)
    if not release or not release.get("tagName"):
        return Result(
            repository=target.repository,
            package=target.package,
            status=STATUS_SKIP,
            message="no published GitHub release to compare against",
        )

    tag = str(release["tagName"])
    released_version = normalize_tag(tag)
    published_at = parse_published_at(release.get("publishedAt"))
    published = release.get("publishedAt")

    version = pypi_version(target.package)

    if version is None:
        grace_left = _grace_left(published_at, now, grace_minutes)
        if grace_left is not None and grace_left > 0:
            return Result(
                repository=target.repository,
                package=target.package,
                status=STATUS_WARN,
                message=(
                    f"release {tag} has no PyPI upload yet; "
                    f"{grace_left:.0f} min of grace period left"
                ),
                release_tag=tag,
                release_published_at=published,
                pypi_version=None,
            )
        return Result(
            repository=target.repository,
            package=target.package,
            status=STATUS_FAIL,
            message=f"release {tag} is not published on PyPI as {target.package}",
            release_tag=tag,
            release_published_at=published,
            pypi_version=None,
        )

    if version == released_version:
        return Result(
            repository=target.repository,
            package=target.package,
            status=STATUS_OK,
            message=f"PyPI {target.package} {version} matches release {tag}",
            release_tag=tag,
            release_published_at=published,
            pypi_version=version,
        )

    grace_left = _grace_left(published_at, now, grace_minutes)
    if grace_left is not None and grace_left > 0:
        return Result(
            repository=target.repository,
            package=target.package,
            status=STATUS_WARN,
            message=(
                f"release {tag} vs PyPI {target.package} {version}; "
                f"{grace_left:.0f} min of grace period left"
            ),
            release_tag=tag,
            release_published_at=published,
            pypi_version=version,
        )

    if compare_versions(parse_version(version), parse_version(released_version)) > 0:
        return Result(
            repository=target.repository,
            package=target.package,
            status=STATUS_WARN,
            message=(
                f"PyPI {target.package} {version} is ahead of the newest stable release {tag}; "
                "a pre-release upload is not tracked by releases/latest"
            ),
            release_tag=tag,
            release_published_at=published,
            pypi_version=version,
        )

    return Result(
        repository=target.repository,
        package=target.package,
        status=STATUS_FAIL,
        message=f"release {tag} is not on PyPI: {target.package} is still at {version}",
        release_tag=tag,
        release_published_at=published,
        pypi_version=version,
    )


def _grace_left(published_at: datetime | None, now: datetime, grace_minutes: float) -> float | None:
    """Return the remaining grace period in minutes, or ``None`` when not applicable."""
    if grace_minutes <= 0 or published_at is None:
        return None
    elapsed = (now - published_at).total_seconds() / 60.0
    if elapsed > grace_minutes:
        return None
    return grace_minutes - elapsed


# --------------------------------------------------------------------------------------
# manifest handling
# --------------------------------------------------------------------------------------


def parse_manifest(raw: str) -> list[Target]:
    """Parse a manifest (JSON text or a path to a JSON file) into targets."""
    text = raw.strip()
    if not text:
        raise CheckError("the repository manifest is empty")

    path = None
    if "\n" not in text and not text.lstrip().startswith(("[", "{")):
        path = text
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise CheckError(f"could not read the manifest file {path}: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckError(f"the repository manifest is not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        data = data.get("repositories", [])
    if not isinstance(data, list):
        raise CheckError("the repository manifest must be a list or an object with 'repositories'")

    targets: list[Target] = []
    for index, entry in enumerate(data):
        if isinstance(entry, str):
            repository, package = entry, entry.rsplit("/", 1)[-1]
        elif isinstance(entry, dict):
            repository = str(entry.get("repository", "")).strip()
            packages = entry.get("packages")
            if packages is None:
                packages = [repository.rsplit("/", 1)[-1]]
            if not repository or not isinstance(packages, list) or not packages:
                raise CheckError(
                    f"manifest entry {index} needs a 'repository' and a non-empty 'packages' list"
                )
            for package in packages:
                targets.append(Target(repository=repository, package=str(package).strip()))
            continue
        else:
            raise CheckError(f"manifest entry {index} must be a string or an object")
        targets.append(Target(repository=repository, package=package))

    if not targets:
        raise CheckError("the repository manifest does not contain any repository")
    return targets


def matrix_payload(targets: Sequence[Target]) -> dict[str, Any]:
    """Return a GitHub Actions matrix definition for ``targets``."""
    return {
        "include": [
            {"repository": t.repository, "package": t.package, "key": t.key} for t in targets
        ]
    }


# --------------------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------------------


_STATUS_LABEL = {
    STATUS_OK: "PASS",
    STATUS_WARN: "WARN",
    STATUS_FAIL: "FAIL",
    STATUS_SKIP: "SKIP",
}


def render_table(results: Sequence[Result]) -> str:
    """Render results as a GitHub-flavoured Markdown table."""
    lines = [
        "| Status | Repository | Package | Release tag | PyPI version |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| {status} | `{repo}` | `{package}` | {tag} | {pypi} |".format(
                status=_STATUS_LABEL.get(result.status, result.status.upper()),
                repo=result.repository,
                package=result.package,
                tag=f"`{result.release_tag}`" if result.release_tag else "-",
                pypi=f"`{result.pypi_version}`" if result.pypi_version else "-",
            )
        )
    return "\n".join(lines)


def write_step_summary(results: Sequence[Result]) -> None:
    """Append a Markdown summary when running inside GitHub Actions."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## Release integrity\n\n")
            handle.write(render_table(results))
            handle.write("\n")
            for result in results:
                if result.status in (STATUS_WARN, STATUS_FAIL, STATUS_SKIP):
                    handle.write(f"- **{_STATUS_LABEL[result.status]}** {result.key}: {result.message}\n")
            handle.write("\n")
    except OSError:  # pragma: no cover - summary is best effort
        pass


def emit_annotations(results: Sequence[Result]) -> None:
    """Emit workflow commands so mismatches surface in the Actions UI.

    These go to stderr so that stdout remains a clean, parseable stream for ``--json``
    consumers. The Actions runner picks workflow commands up from the log either way.
    """
    for result in results:
        if result.status == STATUS_FAIL:
            print(f"::error title=Release integrity::{result.key}: {result.message}", file=sys.stderr)
        elif result.status == STATUS_WARN:
            print(f"::warning title=Release integrity::{result.key}: {result.message}", file=sys.stderr)
        elif result.status == STATUS_SKIP:
            print(f"::notice title=Release integrity::{result.key}: {result.message}", file=sys.stderr)


def report(results: Sequence[Result], as_json: bool) -> None:
    """Print the results and write the Actions summary."""
    if as_json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        print(render_table(results))
        for result in results:
            print(f"[{_STATUS_LABEL.get(result.status, result.status).upper():4}] {result.key}: {result.message}")


def results_from(targets: Iterable[Target], grace_minutes: float) -> list[Result]:
    return [evaluate(target, grace_minutes=grace_minutes) for target in targets]


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare the newest GitHub release tag of a repository with PyPI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest",
        help="JSON text, or a path to a JSON file, listing the repositories to check.",
    )
    parser.add_argument("--repository", help="Check a single repository (needs --package).")
    parser.add_argument("--package", help="PyPI package name to compare against --repository.")
    parser.add_argument(
        "--grace-minutes",
        type=float,
        default=30.0,
        help="Tolerate a mismatch this soon after the release was published (default: 30).",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON results.")
    parser.add_argument(
        "--emit-matrix",
        action="store_true",
        help="Print a GitHub Actions matrix for the manifest and exit.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on tolerated mismatches (warnings) as well.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.repository:
            if not args.package:
                raise CheckError("--repository requires --package")
            targets = [Target(repository=args.repository.strip(), package=args.package.strip())]
        elif args.manifest:
            targets = parse_manifest(args.manifest)
        else:
            raise CheckError("provide either --manifest or --repository with --package")

        if args.emit_matrix:
            print(json.dumps(matrix_payload(targets)))
            return 0

        results = results_from(targets, args.grace_minutes)
    except CheckError as exc:
        print(f"::error title=Release integrity::{exc}", file=sys.stderr)
        return 2

    emit_annotations(results)
    report(results, args.as_json)
    write_step_summary(results)

    failed = any(r.status in FAILING_STATUSES for r in results)
    warned = any(r.status == STATUS_WARN for r in results)
    if failed or (args.strict and warned):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
