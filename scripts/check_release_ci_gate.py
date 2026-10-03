#!/usr/bin/env python3
"""Tell "CI is green" apart from "CI never ran" on a release pull request.

``gh pr checks`` and the ``statusCheckRollup`` field collapse three very different
situations into the same empty result:

* the pull request genuinely has no CI configured;
* CI was triggered but is still queued or running;
* CI was triggered by an actor GitHub does not trust, so the run is parked in the
  manual approval queue instead of executing.

The third case is the dangerous one. GitHub reports it as a run with
``status=completed``, ``conclusion=action_required`` and **zero jobs**, so an
automation that reads ``mergeable`` and looks for a red check sees neither red nor
green: it sees nothing at all, and merges a release that no CI ever validated.

A fourth shape is just as silent. When a pull request is merged while a run is still
parked in the approval queue, GitHub flips that run to ``conclusion=failure`` -- while
it still has zero jobs. So a "red" release pull request is frequently not a failing
test at all; it is only the approval request being invalidated by the merge. Reading it
as "CI failed" is as wrong as reading it as "CI passed", and the two directions of
error pull in opposite directions.

This check therefore never infers a verdict from ``conclusion`` alone. It counts
**jobs**: a run with zero jobs produced no evidence, whatever its conclusion says.

Verdicts:

* ``green``       - every run completed successfully and at least one job ran.
* ``red``         - a run concluded as a failure *and* it actually ran jobs.
* ``pending``     - a run has not finished yet.
* ``no_evidence`` - no run produced a single job. Never mergeable.

``no_evidence`` carries a ``reason``: ``awaiting_approval`` (a run sits in the
approval queue), ``approval_invalidated`` (a zero-job failure, typically the merge
that overtook the pending approval), or ``no_runs`` (nothing was ever triggered).

Two modes:

* ``--pr`` evaluates the merge gate for one pull request (default: every repository
  in ``--org`` is left alone, only the named pull request is read).
* without ``--pr`` it sweeps every repository of ``--org`` (or ``--repositories``)
  and lists the runs that are parked in the approval queue or ended with zero jobs.

Exit codes:
    0 - no ``no_evidence`` finding, and no red/pull-request finding when
        ``--fail-on`` asks for one
    1 - at least one finding at or above the requested ``--fail-on`` level
    2 - the check could not be performed (bad input, unreachable API, ...)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

DEFAULT_ORG = "dcc-mcp"
DEFAULT_PER_PAGE = 100
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_BRANCH_PREFIX = "release-please--"

VERDICT_GREEN = "green"
VERDICT_RED = "red"
VERDICT_PENDING = "pending"
VERDICT_NO_EVIDENCE = "no_evidence"

MERGEABLE_VERDICTS = frozenset({VERDICT_GREEN})

# Conclusions that mean "this run did not succeed". ``action_required`` is listed for
# completeness; it is detected by name before the conclusion is ever consulted.
UNSUCCESSFUL_CONCLUSIONS = frozenset(
    {
        "action_required",
        "failure",
        "cancelled",
        "timed_out",
        "startup_failure",
        "neutral",
        "skipped",
    }
)

REASON_AWAITING_APPROVAL = "awaiting_approval"
REASON_APPROVAL_INVALIDATED = "approval_invalidated"
REASON_NO_RUNS = "no_runs"

STATUS_OK = "ok"
STATUS_FAIL = "fail"

FAIL_ON_CHOICES = ("none", "red", "no_evidence")


class CheckError(RuntimeError):
    """Raised when the check itself cannot be performed."""


@dataclass
class Run:
    """One workflow run, reduced to what the gate needs.

    Mutable on purpose: ``job_count`` is filled in by a second API call.
    """

    id: int
    name: str
    status: str
    conclusion: str | None
    event: str
    head_branch: str
    head_sha: str
    actor: str
    created_at: str
    html_url: str
    job_count: int | None = None

    @property
    def finished(self) -> bool:
        return self.status == "completed"

    @property
    def awaiting_approval(self) -> bool:
        return self.conclusion == "action_required"

    @property
    def produced_evidence(self) -> bool:
        """Whether the run executed at least one job.

        A run with zero jobs has produced no evidence, whatever its conclusion says.
        """
        return bool(self.job_count)


@dataclass
class GateResult:
    """Merge-gate verdict for one pull request."""

    repository: str
    pr_number: int
    title: str
    url: str
    state: str
    head_sha: str
    verdict: str
    reason: str | None
    message: str
    merge_allowed: bool
    runs: list[dict[str, Any]] = field(default_factory=list)
    rollup: list[dict[str, Any]] = field(default_factory=list)
    merge_commit: str | None = None
    merge_commit_evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanFinding:
    """One run that is parked in the approval queue or ended with zero jobs."""

    repository: str
    run_id: int
    name: str
    conclusion: str | None
    event: str
    head_branch: str
    head_sha: str
    actor: str
    created_at: str
    html_url: str
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_gh(args: Sequence[str], timeout: float, what: str) -> str:
    """Run a ``gh`` command and return its stdout, or raise ``CheckError``."""
    command = ["gh", *args]
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
        raise CheckError(f"`gh {' '.join(args)}` timed out after {timeout}s") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise CheckError(f"could not {what}: {detail}")
    return completed.stdout


def gh_json(args: Sequence[str], timeout: float, what: str) -> Any:
    """Run a ``gh`` command and parse its stdout as JSON."""
    return json.loads(run_gh(args, timeout, what))


def workflow_runs(
    repository: str,
    timeout: float,
    head_sha: str | None = None,
    per_page: int = DEFAULT_PER_PAGE,
) -> list[Run]:
    """Return the most recent workflow runs of ``repository``.

    Restricted to ``head_sha`` when given. Runs are returned newest first, as GitHub
    returns them; the caller must not assume any further ordering.
    """
    query = f"per_page={per_page}"
    if head_sha:
        query = f"head_sha={head_sha}&{query}"
    payload = gh_json(
        ["api", f"repos/{repository}/actions/runs?{query}"],
        timeout,
        f"list workflow runs of {repository}",
    )
    return [
        Run(
            id=item["id"],
            name=item.get("name") or "",
            status=item.get("status") or "",
            conclusion=item.get("conclusion"),
            event=item.get("event") or "",
            head_branch=item.get("head_branch") or "",
            head_sha=item.get("head_sha") or "",
            actor=(item.get("actor") or {}).get("login") or "",
            created_at=item.get("created_at") or "",
            html_url=item.get("html_url") or "",
        )
        for item in payload.get("workflow_runs", [])
    ]


def attach_job_counts(repository: str, runs: Iterable[Run], timeout: float) -> None:
    """Fill in ``run.job_count`` for every run, in place.

    One request per run. ``None`` is left in place when the count cannot be read, so
    an unreadable count degrades to "no evidence" rather than to "green".
    """
    for run in runs:
        try:
            payload = gh_json(
                ["api", f"repos/{repository}/actions/runs/{run.id}/jobs", "--jq", ".total_count"],
                timeout,
                f"count jobs of run {run.id}",
            )
        except CheckError:
            run.job_count = None
            continue
        run.job_count = int(payload) if isinstance(payload, (int, str)) and str(payload).isdigit() else None


def pull_request(repository: str, number: int, timeout: float) -> dict[str, Any]:
    """Return the pull request plus its check rollup."""
    return gh_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repository,
            "--json",
            "number,title,state,headRefOid,mergeCommit,url,isDraft,mergeable,statusCheckRollup",
        ],
        timeout,
        f"read pull request {repository}#{number}",
    )


def evaluate_runs(runs: Sequence[Run]) -> tuple[str, str | None, str]:
    """Return ``(verdict, reason, message)`` for the runs of one head commit."""
    if not runs:
        return (
            VERDICT_NO_EVIDENCE,
            REASON_NO_RUNS,
            "No workflow run was ever triggered for this head commit.",
        )

    if any(run.awaiting_approval for run in runs):
        parked = [run for run in runs if run.awaiting_approval]
        return (
            VERDICT_NO_EVIDENCE,
            REASON_AWAITING_APPROVAL,
            f"{len(parked)} run(s) are parked in the GitHub approval queue and have "
            "executed zero jobs. There is no CI evidence for this head commit. "
            "Approve the run, or push the branch from an account with write access.",
        )

    if any(not run.finished for run in runs):
        return (
            VERDICT_PENDING,
            None,
            f"{sum(1 for run in runs if not run.finished)} run(s) have not finished yet.",
        )

    # A run that finished without ever starting a job is not evidence and is not a test
    # result either. It blocks on its own, before any real failure is considered,
    # because "CI green plus one workflow that silently never ran" is not a green pull
    # request: it is a pull request where part of the suite was never executed.
    silent = [
        run
        for run in runs
        if run.conclusion in UNSUCCESSFUL_CONCLUSIONS and not run.produced_evidence
    ]
    if silent:
        names = ", ".join(f"{run.name} ({run.conclusion})" for run in silent)
        return (
            VERDICT_NO_EVIDENCE,
            REASON_APPROVAL_INVALIDATED,
            f"{len(silent)} run(s) finished with zero jobs: {names}. A zero-job "
            "'failure' is not a failing test - it is a workflow that never ran, most "
            "often an approval request invalidated by the merge.",
        )

    if not any(run.produced_evidence for run in runs):
        conclusions = sorted({run.conclusion or "unknown" for run in runs})
        return (
            VERDICT_NO_EVIDENCE,
            REASON_NO_RUNS,
            f"No run executed a single job (conclusion(s): {', '.join(conclusions)}), "
            "so this head commit has no CI evidence at all.",
        )

    broken = [run for run in runs if run.conclusion in UNSUCCESSFUL_CONCLUSIONS]
    if broken:
        names = ", ".join(f"{run.name} ({run.conclusion})" for run in broken)
        return (VERDICT_RED, None, f"Run(s) executed jobs and did not succeed: {names}.")

    return (
        VERDICT_GREEN,
        None,
        f"All {len(runs)} run(s) completed successfully with jobs.",
    )


def check_pr(repository: str, number: int, timeout: float, per_page: int) -> GateResult:
    """Evaluate the merge gate of one pull request against its exact head commit."""
    pr = pull_request(repository, number, timeout)
    head_sha = pr.get("headRefOid") or ""
    if not head_sha:
        raise CheckError(f"{repository}#{number} has no head commit")

    runs = workflow_runs(repository, timeout, head_sha=head_sha, per_page=per_page)
    attach_job_counts(repository, runs, timeout)
    verdict, reason, message = evaluate_runs(runs)

    rollup = [
        {
            "name": entry.get("name"),
            "status": entry.get("status"),
            "conclusion": entry.get("conclusion"),
        }
        for entry in (pr.get("statusCheckRollup") or [])
    ]

    merge_commit = (pr.get("mergeCommit") or {}).get("oid")
    merge_evidence: list[dict[str, Any]] = []
    if merge_commit and verdict != VERDICT_GREEN:
        # Context only, never a substitute for the head-commit verdict: the release
        # artifacts are cut from the merge commit, so knowing whether *that* commit was
        # validated is what decides whether an already-published release must be rolled
        # back. It does not make merging without evidence acceptable.
        for run in workflow_runs(repository, timeout, head_sha=merge_commit, per_page=per_page):
            merge_evidence.append(
                {
                    "name": run.name,
                    "conclusion": run.conclusion,
                    "event": run.event,
                    "html_url": run.html_url,
                }
            )

    return GateResult(
        repository=repository,
        pr_number=int(pr.get("number") or number),
        title=pr.get("title") or "",
        url=pr.get("url") or "",
        state=pr.get("state") or "",
        head_sha=head_sha,
        verdict=verdict,
        reason=reason,
        message=message,
        merge_allowed=verdict in MERGEABLE_VERDICTS,
        runs=[asdict(run) for run in runs],
        rollup=rollup,
        merge_commit=merge_commit,
        merge_commit_evidence=merge_evidence,
    )


def open_release_prs(
    repository: str, timeout: float, branch_prefix: str
) -> list[dict[str, Any]]:
    """Return the open pull requests of ``repository`` on a release branch."""
    payload = gh_json(
        [
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--limit",
            "50",
            "--json",
            "number,title,headRefName,headRefOid,url",
        ],
        timeout,
        f"list open pull requests of {repository}",
    )
    if not isinstance(payload, list):
        raise CheckError(f"unexpected payload listing pull requests of {repository}")
    return [
        pr
        for pr in payload
        if (pr.get("headRefName") or "").startswith(branch_prefix)
    ]


def org_repositories(org: str, timeout: float) -> list[str]:
    """Return every non-archived repository of ``org`` as ``org/name``."""
    payload = gh_json(
        [
            "repo",
            "list",
            org,
            "--limit",
            "1000",
            "--json",
            "name,isArchived",
            "--jq",
            "[.[] | select(.isArchived == false) | .name]",
        ],
        timeout,
        f"list repositories of {org}",
    )
    if not isinstance(payload, list):
        raise CheckError(f"unexpected payload listing repositories of {org}")
    return [f"{org}/{name}" for name in payload if isinstance(name, str)]


def scan_repository(
    repository: str,
    timeout: float,
    per_page: int,
    branch_prefix: str,
) -> list[ScanFinding]:
    """Return the silent runs of one repository.

    Two kinds are reported: runs parked in the approval queue (any branch), and runs
    that finished with zero jobs on a ``branch_prefix`` branch, which is the shape a
    pending approval leaves behind once it is invalidated by a merge.
    """
    runs = workflow_runs(repository, timeout, per_page=per_page)
    findings: list[ScanFinding] = []

    parked = [run for run in runs if run.awaiting_approval]
    for run in parked:
        findings.append(
            ScanFinding(
                repository=repository,
                run_id=run.id,
                name=run.name,
                conclusion=run.conclusion,
                event=run.event,
                head_branch=run.head_branch,
                head_sha=run.head_sha,
                actor=run.actor,
                created_at=run.created_at,
                html_url=run.html_url,
                kind=REASON_AWAITING_APPROVAL,
            )
        )
    if parked:
        return findings

    # Only worth the extra request per run when the branch is a release branch, so an
    # org-wide sweep stays bounded.
    candidates = [
        run
        for run in runs
        if run.finished
        and run.event == "pull_request"
        and run.conclusion in {"failure", "cancelled", "timed_out", "startup_failure"}
        and run.head_branch.startswith(branch_prefix)
    ]
    if not candidates:
        return findings
    attach_job_counts(repository, candidates, timeout)
    for run in candidates:
        if run.produced_evidence:
            continue
        findings.append(
            ScanFinding(
                repository=repository,
                run_id=run.id,
                name=run.name,
                conclusion=run.conclusion,
                event=run.event,
                head_branch=run.head_branch,
                head_sha=run.head_sha,
                actor=run.actor,
                created_at=run.created_at,
                html_url=run.html_url,
                kind=REASON_APPROVAL_INVALIDATED,
            )
        )
    return findings


def approve_runs(findings: Sequence[ScanFinding], timeout: float) -> list[str]:
    """Approve every parked run and return a human-readable log line per attempt."""
    log: list[str] = []
    for finding in findings:
        if finding.kind != REASON_AWAITING_APPROVAL:
            continue
        try:
            run_gh(
                [
                    "api",
                    "--method",
                    "POST",
                    f"repos/{finding.repository}/actions/runs/{finding.run_id}/approve",
                ],
                timeout,
                f"approve run {finding.run_id}",
            )
        except CheckError as exc:
            log.append(f"{finding.repository} run {finding.run_id}: NOT approved - {exc}")
            continue
        log.append(f"{finding.repository} run {finding.run_id}: approved")
    return log


def render_scan_text(findings: Sequence[ScanFinding], scanned: int) -> str:
    """Render the sweep result as text."""
    if not findings:
        return f"OK - no silent CI runs across {scanned} repositories."

    lines = [f"FAIL - {len(findings)} silent CI run(s) across {scanned} repositories:", ""]
    for finding in findings:
        label = {
            REASON_AWAITING_APPROVAL: "parked in approval queue",
            REASON_APPROVAL_INVALIDATED: "finished with zero jobs",
        }.get(finding.kind, finding.kind)
        lines.append(
            f"  {finding.repository}#{finding.run_id} {finding.name} - {label} "
            f"(conclusion={finding.conclusion})"
        )
        lines.append(f"      branch : {finding.head_branch}")
        lines.append(f"      sha    : {finding.head_sha}")
        lines.append(f"      actor  : {finding.actor}")
        lines.append(f"      created: {finding.created_at}")
        lines.append(f"      {finding.html_url}")
    return "\n".join(lines)


def render_gate_text(result: GateResult) -> str:
    """Render one pull-request verdict as text."""
    decision = "MERGE ALLOWED" if result.merge_allowed else "DO NOT MERGE"
    lines = [
        f"{decision} - {result.repository}#{result.pr_number} {result.title}",
        f"      verdict : {result.verdict}"
        + (f" ({result.reason})" if result.reason else ""),
        f"      head    : {result.head_sha}",
        f"      state   : {result.state}",
        f"      message : {result.message}",
    ]
    if result.rollup:
        lines.append(f"      rollup  : {len(result.rollup)} entry/entries")
    else:
        lines.append("      rollup  : EMPTY - `gh pr checks` reports nothing, which is the silent symptom")
    if result.merge_commit_evidence:
        lines.append(f"      merge commit {result.merge_commit} (context only, not a substitute):")
        for run in result.merge_commit_evidence:
            lines.append(f"        - {run['name']}: {run['conclusion']} ({run['event']})")
    lines.append(f"      {result.url}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Distinguish 'CI is green' from 'CI never ran' on a release pull request.",
    )
    parser.add_argument("--org", default=DEFAULT_ORG, help=f"organization to sweep (default: {DEFAULT_ORG})")
    parser.add_argument(
        "--repositories",
        default="",
        help="comma-separated org/repo list to sweep instead of every repository of --org",
    )
    parser.add_argument(
        "--pr",
        default="",
        help="evaluate the merge gate of one pull request, as org/repo#123",
    )
    parser.add_argument(
        "--branch-prefix",
        default=DEFAULT_BRANCH_PREFIX,
        help=f"release branch prefix for zero-job detection (default: {DEFAULT_BRANCH_PREFIX})",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=DEFAULT_PER_PAGE,
        help=f"runs fetched per repository in sweep mode (default: {DEFAULT_PER_PAGE})",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--fail-on",
        choices=FAIL_ON_CHOICES,
        default="no_evidence",
        help="severity that makes the run exit 1 (default: no_evidence)",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="approve the parked runs found by the sweep (off by default)",
    )
    parser.add_argument(
        "--open-prs",
        action="store_true",
        help="sweep the open release pull requests instead of raw runs and report a "
        "merge verdict for each (this is what a release window runs before merging)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.pr:
            if "#" not in args.pr:
                raise CheckError(f"--pr must look like org/repo#123, got {args.pr!r}")
            repository, _, number = args.pr.partition("#")
            result = check_pr(repository, int(number), args.timeout, args.per_page)
            if args.format == "json":
                print(json.dumps(result.as_dict(), indent=2))
            else:
                print(render_gate_text(result))
            if result.verdict == VERDICT_NO_EVIDENCE:
                return 1
            if result.verdict == VERDICT_RED and args.fail_on in {"red", "no_evidence"}:
                return 1
            return 0

        repositories = (
            [item.strip() for item in args.repositories.split(",") if item.strip()]
            if args.repositories
            else org_repositories(args.org, args.timeout)
        )
        if args.open_prs:
            results: list[GateResult] = []
            for repository in repositories:
                for pr in open_release_prs(repository, args.timeout, args.branch_prefix):
                    results.append(
                        check_pr(repository, int(pr["number"]), args.timeout, args.per_page)
                    )
            if args.format == "json":
                print(
                    json.dumps(
                        {"scanned": len(repositories), "pull_requests": [r.as_dict() for r in results]},
                        indent=2,
                    )
                )
            else:
                if not results:
                    print(f"OK - no open release pull request across {len(repositories)} repositories.")
                for result in results:
                    print(render_gate_text(result))
                    print()
            blocked = [r for r in results if r.verdict == VERDICT_NO_EVIDENCE]
            red = [r for r in results if r.verdict == VERDICT_RED]
            if blocked:
                return 1
            if red and args.fail_on in {"red", "no_evidence"}:
                return 1
            return 0

        findings: list[ScanFinding] = []
        for repository in repositories:
            findings.extend(scan_repository(repository, args.timeout, args.per_page, args.branch_prefix))

        approval_log: list[str] = []
        if args.approve:
            approval_log = approve_runs(findings, args.timeout)

        if args.format == "json":
            print(
                json.dumps(
                    {
                        "scanned": len(repositories),
                        "findings": [finding.as_dict() for finding in findings],
                        "approvals": approval_log,
                    },
                    indent=2,
                )
            )
        else:
            print(render_scan_text(findings, len(repositories)))
            for line in approval_log:
                print(f"  {line}")

        if not findings:
            return 0
        return 1
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
