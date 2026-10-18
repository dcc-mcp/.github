"""Unit tests for scripts/check_release_ci_gate.py.

These tests run under plain `unittest` with no third-party dependencies, matching the
runner used by `.github/workflows/profile-contract.yml`. No test touches the network:
the verdict logic is exercised with synthetic runs, and the `gh` calls that are touched
at all are stubbed.

The cases here are not invented. Every one of them is a shape observed on a real
dcc-mcp release pull request: the parked approval queue (`conclusion=action_required`,
zero jobs), and the zero-job `failure` that GitHub records when a merge overtakes a
pending approval. Both look like "no CI" to `gh pr checks`, and both used to be merged.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_ci_gate as gate  # noqa: E402


def make_run(
    name="CI",
    status="completed",
    conclusion="success",
    job_count=1,
    event="pull_request",
    branch="release-please--branches--main",
    run_id=1,
    actor="loonghao",
):
    """A synthetic run, defaulting to a healthy one with real evidence."""
    return gate.Run(
        id=run_id,
        name=name,
        status=status,
        conclusion=conclusion,
        event=event,
        head_branch=branch,
        head_sha="0" * 40,
        actor=actor,
        created_at="2026-10-02T20:28:07Z",
        html_url="https://example.invalid/run/1",
        job_count=job_count,
    )


class EvaluateRunsTest(unittest.TestCase):
    """The verdict logic, one real-world shape per test."""

    def test_no_runs_at_all_is_not_green(self):
        verdict, reason, _ = gate.evaluate_runs([])
        self.assertEqual(verdict, gate.VERDICT_NO_EVIDENCE)
        self.assertEqual(reason, gate.REASON_NO_RUNS)

    def test_parked_in_approval_queue_is_not_green(self):
        # dcc-mcp-freecad#27, dcc-mcp-unreal#228, dcc-mcp-premiere#19 before they were
        # handled: completed, conclusion=action_required, zero jobs.
        run = make_run(conclusion="action_required", job_count=0, actor="github-actions[bot]")
        verdict, reason, _ = gate.evaluate_runs([run])
        self.assertEqual(verdict, gate.VERDICT_NO_EVIDENCE)
        self.assertEqual(reason, gate.REASON_AWAITING_APPROVAL)

    def test_zero_job_failure_is_not_a_failing_test(self):
        # dcc-mcp-premiere#19 after the merge: GitHub flipped the parked run to
        # `failure` while it still had zero jobs.
        run = make_run(conclusion="failure", job_count=0, actor="github-actions[bot]")
        verdict, reason, message = gate.evaluate_runs([run])
        self.assertEqual(verdict, gate.VERDICT_NO_EVIDENCE)
        self.assertEqual(reason, gate.REASON_APPROVAL_INVALIDATED)
        self.assertIn("never ran", message)

    def test_zero_job_failure_is_reported_before_a_real_failure(self):
        # A suite that ran and failed is a different problem from a workflow that never
        # ran. The missing one is reported, because "green plus one workflow that
        # silently never ran" must not read as a healthy pull request either.
        runs = [
            make_run(name="CI", conclusion="failure", job_count=3, run_id=1),
            make_run(name="E2E", conclusion="failure", job_count=0, run_id=2),
        ]
        verdict, reason, _ = gate.evaluate_runs(runs)
        self.assertEqual(verdict, gate.VERDICT_NO_EVIDENCE)
        self.assertEqual(reason, gate.REASON_APPROVAL_INVALIDATED)

    def test_real_failure_with_jobs_is_red(self):
        run = make_run(conclusion="failure", job_count=3)
        verdict, reason, _ = gate.evaluate_runs([run])
        self.assertEqual(verdict, gate.VERDICT_RED)
        self.assertIsNone(reason)

    def test_running_workflow_is_pending(self):
        run = make_run(status="in_progress", conclusion=None, job_count=0)
        verdict, _, _ = gate.evaluate_runs([run])
        self.assertEqual(verdict, gate.VERDICT_PENDING)

    def test_all_green_with_jobs_is_mergeable(self):
        runs = [make_run(name="CI", run_id=1), make_run(name="E2E", run_id=2)]
        verdict, reason, _ = gate.evaluate_runs(runs)
        self.assertEqual(verdict, gate.VERDICT_GREEN)
        self.assertIsNone(reason)
        self.assertIn(gate.VERDICT_GREEN, gate.MERGEABLE_VERDICTS)

    def test_partial_evidence_is_not_mergeable(self):
        # CI really ran and passed; E2E was parked and then invalidated. Merging here
        # ships a version whose E2E suite never executed.
        runs = [
            make_run(name="CI", conclusion="success", job_count=4, run_id=1),
            make_run(name="E2E", conclusion="cancelled", job_count=0, run_id=2),
        ]
        verdict, _, _ = gate.evaluate_runs(runs)
        self.assertNotEqual(verdict, gate.VERDICT_GREEN)

    def test_success_with_zero_jobs_is_not_evidence(self):
        # Nothing executed, so nothing was validated - even though nothing failed.
        runs = [make_run(conclusion="success", job_count=0)]
        verdict, reason, _ = gate.evaluate_runs(runs)
        self.assertEqual(verdict, gate.VERDICT_NO_EVIDENCE)
        self.assertEqual(reason, gate.REASON_NO_RUNS)


class MergeGateTest(unittest.TestCase):
    """`no_evidence` never becomes mergeable, whatever its shape."""

    def test_only_green_is_mergeable(self):
        self.assertEqual(gate.MERGEABLE_VERDICTS, frozenset({gate.VERDICT_GREEN}))
        for verdict in (gate.VERDICT_RED, gate.VERDICT_PENDING, gate.VERDICT_NO_EVIDENCE):
            self.assertNotIn(verdict, gate.MERGEABLE_VERDICTS)


class BadInputTest(unittest.TestCase):
    def test_pr_flag_must_identify_a_pull_request(self):
        # An unusable argument must not look like a clean sweep: it exits 2, the
        # "check could not be performed" code, so a release window stops instead of
        # reading an empty result as "nothing to do".
        self.assertEqual(gate.main(["--pr", "dcc-mcp/dcc-mcp-premiere"]), 2)

    def test_pr_flag_without_a_repository_is_rejected(self):
        # The fail-open case. `gh pr view --repo ""` falls back to whatever repository
        # the current directory is in, so accepting this would silently evaluate - and
        # potentially clear - a pull request belonging to a different repository.
        self.assertEqual(gate.main(["--pr", "#19"]), 2)
        self.assertEqual(gate.main(["--pr", "/repo#19"]), 2)

    def test_pr_flag_with_a_non_numeric_number_is_rejected(self):
        # Must exit 2 ("could not be performed"), not crash with a traceback that
        # happens to exit 1 - 1 means "found a finding", which would be misread.
        self.assertEqual(gate.main(["--pr", "dcc-mcp/dcc-mcp-premiere#abc"]), 2)


def _gate_result(verdict):
    """A synthetic gate result carrying just the verdict under test."""
    return gate.GateResult(
        repository="o/r",
        pr_number=1,
        title="chore(main): release 0.0.1",
        url="https://example.invalid/pr/1",
        state="OPEN",
        head_sha="0" * 40,
        verdict=verdict,
        reason=None,
        message="",
        merge_allowed=verdict in gate.MERGEABLE_VERDICTS,
    )


def _run_main(argv):
    """Run ``main()`` and return ``(exit_code, stdout)``, swallowing the output."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        status = gate.main(argv)
    return status, buffer.getvalue()


class ExitCodeContractTest(unittest.TestCase):
    """The exit code is the contract an automation actually reads.

    A run that prints ``DO NOT MERGE`` while exiting 0 is read as clearance by exactly
    the release window this gate exists to stop, so the exit code has to agree with
    ``merge_allowed``. Verdict-level tests cannot catch a disagreement, which is how a
    ``pending`` verdict could exit 0: the verdict was right and the exit code was not.
    """

    def _status_for(self, verdict, extra=()):
        with mock.patch.object(gate, "check_pr", return_value=_gate_result(verdict)):
            status, output = _run_main(["--pr", "o/r#1", *extra])
        return status, output

    def test_green_exits_zero(self):
        self.assertEqual(self._status_for(gate.VERDICT_GREEN)[0], 0)

    def test_no_evidence_exits_one(self):
        self.assertEqual(self._status_for(gate.VERDICT_NO_EVIDENCE)[0], 1)

    def test_pending_exits_one(self):
        # A run that has not finished has validated nothing. It is not evidence, and
        # it must not read as clear.
        self.assertEqual(self._status_for(gate.VERDICT_PENDING)[0], 1)

    def test_red_exits_one_by_default(self):
        self.assertEqual(self._status_for(gate.VERDICT_RED)[0], 1)

    def test_red_is_tunable_by_fail_on_none(self):
        self.assertEqual(self._status_for(gate.VERDICT_RED, ["--fail-on", "none"])[0], 0)

    def test_missing_evidence_is_never_tunable(self):
        # --fail-on tunes a real failure only. It cannot turn the absence of CI into a
        # pass, in either of the two shapes that absence takes.
        for verdict in (gate.VERDICT_NO_EVIDENCE, gate.VERDICT_PENDING):
            with self.subTest(verdict=verdict):
                self.assertEqual(self._status_for(verdict, ["--fail-on", "none"])[0], 1)

    def test_blocked_verdicts_renders_as_do_not_merge(self):
        # The two channels must not disagree: whatever exits non-zero also has to say
        # so in the text a human reads.
        for verdict in gate.BLOCKING_VERDICTS:
            with self.subTest(verdict=verdict):
                status, output = self._status_for(verdict)
                self.assertEqual(status, 1)
                self.assertIn("DO NOT MERGE", output)


class OpenPrsExitCodeTest(unittest.TestCase):
    """The same contract for the sweep a release window runs before merging."""

    def _status_for(self, verdicts, extra=()):
        results = [_gate_result(verdict) for verdict in verdicts]
        prs = [{"number": str(index + 1)} for index in range(len(verdicts))]
        with mock.patch.object(gate, "open_release_prs", return_value=prs), mock.patch.object(
            gate, "check_pr", side_effect=results
        ):
            return _run_main(["--repositories", "o/r", "--open-prs", *extra])[0]

    def test_all_green_exits_zero(self):
        self.assertEqual(self._status_for([gate.VERDICT_GREEN, gate.VERDICT_GREEN]), 0)

    def test_one_pending_exits_one(self):
        self.assertEqual(self._status_for([gate.VERDICT_GREEN, gate.VERDICT_PENDING]), 1)

    def test_one_no_evidence_exits_one(self):
        self.assertEqual(self._status_for([gate.VERDICT_GREEN, gate.VERDICT_NO_EVIDENCE]), 1)

    def test_one_red_exits_one_by_default(self):
        self.assertEqual(self._status_for([gate.VERDICT_GREEN, gate.VERDICT_RED]), 1)

    def test_all_red_is_tunable_by_fail_on_none(self):
        self.assertEqual(self._status_for([gate.VERDICT_RED], ["--fail-on", "none"]), 0)

    def test_no_open_pull_requests_exits_zero(self):
        self.assertEqual(self._status_for([]), 0)


class PrArgumentTest(unittest.TestCase):
    def test_gate_reads_the_exact_head_commit(self):
        # The gate must evaluate the head commit, never the merge commit: the head is
        # what a merge would put on main.
        pr = {
            "number": 19,
            "title": "chore(main): release 0.6.2",
            "state": "MERGED",
            "headRefOid": "0" * 40,
            "mergeCommit": {"oid": "1" * 40},
            "url": "https://example.invalid/pr/19",
            "statusCheckRollup": [],
        }
        runs_payload = {"workflow_runs": []}
        with mock.patch.object(gate, "run_gh") as run_gh:
            run_gh.side_effect = [_json(pr), _json(runs_payload), _json(runs_payload)]
            result = gate.check_pr("dcc-mcp/dcc-mcp-premiere", 19, 5.0, 100)
        head_call = run_gh.call_args_list[1]
        self.assertIn("head_sha=" + "0" * 40, head_call.args[0][1])
        self.assertFalse(result.merge_allowed)


def _json(payload):
    return json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
