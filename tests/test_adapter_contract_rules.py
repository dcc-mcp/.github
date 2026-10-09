"""Tests for scripts/adapter_contract_rules.py (contract family A021/A024).

The tests drive the real CLI entry point with ``--contract`` pointed at
``contract/adapter_contract.json``, so the dispatch path, the profile selection
and the severity resolution are the ones CI actually uses.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapter_contract_rules import ADAPTER_RULES  # noqa: E402
from check_repo_contract import (  # noqa: E402
    RULES,
    Contract,
    all_rules,
    main,
)

ADAPTER_CONTRACT = str(ROOT / "contract" / "adapter_contract.json")

# The ids this module implements. contract/adapter_contract.json also holds the
# A00x families, whose handlers live in check_repo_contract.RULES, so every
# assertion below that reads "every rule" is scoped to this family rather than
# to the whole file.
FAMILY_IDS = set(ADAPTER_RULES)


def run_adapter(root: Path, *args: str, contract: str = ADAPTER_CONTRACT) -> tuple[int, list[dict]]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--root", str(root), "--contract", contract, "--format", "json", *args])
    payload = stdout.getvalue().strip()
    return code, (json.loads(payload) if payload else [])


class FixtureRepo:
    """A throwaway adapter repository root."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def write(self, relative: str, content: str = "x\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def clean(self) -> None:
        """Write the smallest adapter that passes every rule in this family."""
        self.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n'
            "[tool.ruff]\nline-length = 120\n",
        )
        self.write(".pre-commit-config.yaml", "repos: []\n")
        self.write("release-please-config.json", "{}\n")
        self.write(".release-please-manifest.json", "{}\n")

    def cleanup(self) -> None:
        self._dir.cleanup()

    def __enter__(self) -> "FixtureRepo":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()


class AdapterContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def ids(self, findings: list[dict]) -> set[str]:
        return {item["rule_id"] for item in findings}

    def family_rules(self, contract: Contract) -> dict:
        """The contract entries this module is responsible for."""
        return {rid: rule for rid, rule in contract.rules.items() if rid in FAMILY_IDS}

    def finding_for(self, findings: list[dict], rule_id: str) -> dict:
        """The finding for one rule, whichever order the run returned them in.

        The contract carries more than this family, so a fixture that strips
        pyproject.toml also trips A005 from the A00x block. Indexing findings[0]
        would then assert against the wrong rule.
        """
        for item in findings:
            if item["rule_id"] == rule_id:
                return item
        self.fail(f"no finding for {rule_id} in {self.ids(findings)}")


class TestAdapterContractFile(AdapterContractTestCase):
    def test_every_rule_has_an_implementation(self) -> None:
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        self.assertEqual(set(self.family_rules(contract)), FAMILY_IDS)

    def test_every_rule_is_dispatchable(self) -> None:
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        self.assertTrue(set(contract.rules) <= set(all_rules()))

    def test_adapter_rules_do_not_collide_with_repository_rules(self) -> None:
        self.assertTrue(set(ADAPTER_RULES).isdisjoint(set(RULES)))

    def test_rule_ids_are_unique(self) -> None:
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        ids = [rule["id"] for rule in contract.data["rules"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_rule_starts_as_a_strict_warning(self) -> None:
        # The whole family is warn-only by design: the backlog across 50
        # repositories is closed by ratchet, not by an error that breaks every
        # CI at once.
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        for rule_id, rule in self.family_rules(contract).items():
            self.assertEqual(rule["severity"], "warning", rule_id)
            self.assertEqual(rule["profiles"], ["strict"], rule_id)

    def test_baseline_profile_selects_nothing_from_this_family(self) -> None:
        # baseline holds A001 and A003 from the other family, so the assertion
        # is that no rule from this family has joined it yet.
        self.repo.clean()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--root", str(self.repo.root), "--contract", ADAPTER_CONTRACT, "--profile", "baseline", "--list-rules"])
        self.assertEqual(code, 0)
        ids = {line.split()[0] for line in stdout.getvalue().strip().splitlines()}
        self.assertEqual(ids & FAMILY_IDS, set())

    def test_list_rules_names_every_rule(self) -> None:
        self.repo.clean()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main(["--root", str(self.repo.root), "--contract", ADAPTER_CONTRACT, "--profile", "strict", "--list-rules"])
        ids = {line.split()[0] for line in stdout.getvalue().strip().splitlines()}
        self.assertEqual(ids & FAMILY_IDS, FAMILY_IDS)

    def test_clean_fixture_has_no_findings(self) -> None:
        self.repo.clean()
        code, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0, findings)
        self.assertEqual(findings, [], findings)

    def test_fail_on_warning_reports_the_backlog(self) -> None:
        # The nightly sweep runs this way to turn the warnings into a to-do list.
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\n')
        code, findings = run_adapter(self.repo.root, "--profile", "strict", "--fail-on", "warning")
        self.assertEqual(code, 1)
        self.assertIn("A024", self.ids(findings))


class TestA021RuffConfigPresent(AdapterContractTestCase):
    def test_a_tool_ruff_section_satisfies_it(self) -> None:
        self.repo.clean()
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A021", self.ids(findings))

    def test_a_pyproject_without_the_section_is_reported(self) -> None:
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\n')
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertIn("A021", self.ids(findings))
        self.assertIn("[tool.ruff]", self.finding_for(findings, "A021")["message"])

    def test_a_standalone_ruff_toml_satisfies_it(self) -> None:
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\n')
        self.repo.write("ruff.toml", "line-length = 120\n")
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A021", self.ids(findings))

    def test_a_missing_pyproject_is_left_to_a005(self) -> None:
        # A registered adapter with no pyproject.toml at all is A005's gap:
        # one gap, one finding.
        self.repo.clean()
        (self.repo.root / "pyproject.toml").unlink()
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A021", self.ids(findings))
        self.assertIn("A005", self.ids(findings))

    def test_an_empty_tool_ruff_table_is_reported(self) -> None:
        # The table exists but holds nothing, so ruff reads it and finds no
        # settings -- the same outcome as no configuration, and it used to be
        # reported as neither because _table() collapsed both to {}.
        self.repo.clean()
        self.repo.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n[tool.ruff]\n',
        )
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        message = self.finding_for(findings, "A021")["message"]
        self.assertIn("[tool.ruff] is empty", message)
        # Says which defect it is, not the old "no [tool.ruff] section".
        self.assertNotIn("has no [tool.ruff] section", message)
        # A004 stays silent: there is no line-length here to be wrong about.
        self.assertNotIn("A004", self.ids(findings))

    def test_a_nested_only_table_is_reported_as_nested_not_missing(self) -> None:
        # Only [tool.ruff.lint] exists, so tool.ruff parses as a table that
        # holds a sub-table. Calling that "no [tool.ruff] section" contradicted
        # the parse, and A004 silently agreed with the wrong message.
        self.repo.clean()
        self.repo.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n'
            '[tool.ruff.lint]\nselect = ["E"]\n',
        )
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        message = self.finding_for(findings, "A021")["message"]
        self.assertIn("[tool.ruff.lint]", message)
        self.assertIn("no settings of its own", message)
        self.assertNotIn("has no [tool.ruff] section", message)

    def test_several_nested_tables_are_all_named(self) -> None:
        self.repo.clean()
        self.repo.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n'
            '[tool.ruff.lint]\nselect = ["E"]\n\n[tool.ruff.format]\nquote-style = "double"\n',
        )
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        message = self.finding_for(findings, "A021")["message"]
        self.assertIn("[tool.ruff.format]", message)
        self.assertIn("[tool.ruff.lint]", message)

    def test_a_nested_table_plus_a_real_setting_passes(self) -> None:
        # The ordinary shape: [tool.ruff] holds line-length, [tool.ruff.lint]
        # holds the rule selection. Not a finding of any kind.
        self.repo.clean()
        self.repo.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n'
            '[tool.ruff]\nline-length = 120\n\n[tool.ruff.lint]\nselect = ["E"]\n',
        )
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A021", self.ids(findings))
        self.assertNotIn("A004", self.ids(findings))

    def test_a_nested_table_without_line_length_is_a004s_gap(self) -> None:
        # top-level settings exist, so A021 is satisfied; line-length does not,
        # so A004 speaks and A021 stays quiet. One gap, one finding.
        self.repo.clean()
        self.repo.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n'
            '[tool.ruff]\ntarget-version = "py39"\n\n[tool.ruff.lint]\nselect = ["E"]\n',
        )
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A021", self.ids(findings))
        self.assertIn("declares no line-length", self.finding_for(findings, "A004")["message"])

    def test_an_empty_standalone_file_is_reported(self) -> None:
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\nrequires-python = ">=3.9"\n')
        self.repo.write(".ruff.toml", "")
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        message = self.finding_for(findings, "A021")["message"]
        self.assertIn("`.ruff.toml` is empty", message)
        # A004 stays silent rather than reporting a line-length that is nowhere.
        self.assertNotIn("A004", self.ids(findings))

    def test_a_nested_only_standalone_file_names_its_own_sub_table(self) -> None:
        # In a standalone file the sub-table header is [lint], not
        # [tool.ruff.lint] -- the file has no [tool.ruff] prefix.
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\nrequires-python = ">=3.9"\n')
        self.repo.write(".ruff.toml", '[lint]\nselect = ["E"]\n')
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        message = self.finding_for(findings, "A021")["message"]
        self.assertIn("[lint]", message)
        self.assertNotIn("[tool.ruff.lint]", message)


class TestRuffConfigResolutionOrder(AdapterContractTestCase):
    """Ratchets on the order ruff_standalone_configs is walked in.

    ruff resolves a standalone configuration before pyproject.toml, and
    ``.ruff.toml`` before ``ruff.toml``. The order is contract data, so it can be
    edited without touching the checker -- which is exactly why a test has to
    hold it in place: a reorder is a silent behaviour change with no diff in the
    rule implementation to notice.
    """

    def test_the_contract_orders_ruff_toml_before_dot_ruff_toml(self) -> None:
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        self.assertEqual(
            contract.value("ruff_standalone_configs"), [".ruff.toml", "ruff.toml"]
        )

    def test_dot_ruff_toml_wins_when_both_standalone_files_exist(self) -> None:
        # Both files exist and disagree; only the first may be read.
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\nrequires-python = ">=3.9"\n')
        self.repo.write(".ruff.toml", "line-length = 120\n")
        self.repo.write("ruff.toml", "line-length = 100\n")
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A004", self.ids(findings), findings)
        self.assertNotIn("A021", self.ids(findings), findings)

    def test_dot_ruff_toml_wins_for_a021_too(self) -> None:
        # The same two rules must not disagree about which file is in force:
        # .ruff.toml is empty, ruff.toml is configured, and A021 reads the
        # winner, so the empty one is what gets reported.
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\nrequires-python = ">=3.9"\n')
        self.repo.write(".ruff.toml", "")
        self.repo.write("ruff.toml", "line-length = 120\n")
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertEqual(
            [item["path"] for item in findings if item["rule_id"] == "A021"], [".ruff.toml"]
        )

    def test_a_nested_only_standalone_file_declares_no_line_length(self) -> None:
        # [lint] is a sub-table, so the file declares nothing at the top level:
        # A004 must not report a line-length that is nowhere.
        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\nrequires-python = ">=3.9"\n')
        self.repo.write(".ruff.toml", '[lint]\nselect = ["E"]\n')
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A004", self.ids(findings), findings)
        self.assertIn("A021", self.ids(findings), findings)

    def test_a_standalone_config_beats_the_pyproject_table(self) -> None:
        # ruff.toml at the baseline, pyproject.toml divergent: the standalone
        # file is in force, so the pyproject value is never read.
        self.repo.clean()
        self.repo.write("ruff.toml", "line-length = 120\n")
        self.repo.write(
            "pyproject.toml",
            '[project]\nname = "demo"\nrequires-python = ">=3.9"\n\n'
            "[tool.ruff]\nline-length = 100\n",
        )
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A004", self.ids(findings), findings)

    def test_reversing_the_order_would_change_the_verdict(self) -> None:
        # The ratchet is only worth anything if the order decides something: a
        # contract with the two names swapped makes the same repository fail, so
        # the assertions above are not vacuous.
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        swapped = dict(contract.data)
        swapped["ruff_standalone_configs"] = ["ruff.toml", ".ruff.toml"]
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(swapped, handle)
            swapped_path = handle.name
        self.addCleanup(lambda: Path(swapped_path).unlink())

        self.repo.clean()
        self.repo.write("pyproject.toml", '[project]\nname = "demo"\nrequires-python = ">=3.9"\n')
        self.repo.write(".ruff.toml", "line-length = 120\n")
        self.repo.write("ruff.toml", "line-length = 100\n")
        _, findings = run_adapter(
            self.repo.root, "--profile", "strict", contract=swapped_path
        )
        self.assertEqual(
            [item["path"] for item in findings if item["rule_id"] == "A004"], ["ruff.toml"]
        )


class TestA021AndA004Agree(AdapterContractTestCase):
    """Both rules read the same table, so both must resolve it the same way.

    A004 used to read ``[tool.ruff]`` through a resolver that only matched the
    literal key, while A021 walked the dotted path, so a repository with nothing
    but ``[tool.ruff.lint]`` was "no table" to one and "a table" to the other.
    These pin the two resolutions together.
    """

    SHAPES = {
        "empty [tool.ruff]": '[project]\nname = "d"\n\n[tool.ruff]\n',
        "nested-only [tool.ruff.lint]": (
            '[project]\nname = "d"\n\n[tool.ruff.lint]\nselect = ["E"]\n'
        ),
        "[tool.ruff] with a setting": (
            '[project]\nname = "d"\n\n[tool.ruff]\nline-length = 120\n'
        ),
        "[tool.ruff] plus a sub-table": (
            '[project]\nname = "d"\n\n[tool.ruff]\nline-length = 100\n\n'
            '[tool.ruff.lint]\nselect = ["E"]\n'
        ),
    }

    def test_a004_resolves_the_table_the_way_a021_does(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from adapter_contract_rules import _resolve_dotted
        from check_repo_contract import _ruff_table, parse_vx_toml

        for shape, body in self.SHAPES.items():
            data = parse_vx_toml(body)[0]
            resolved = _resolve_dotted(data, "tool.ruff")
            self.assertEqual(
                _ruff_table(data, "tool.ruff"),
                resolved if isinstance(resolved, dict) else {},
                shape,
            )

    def test_a_nested_only_table_is_not_resolved_as_absent(self) -> None:
        # Guards the guard: if _ruff_table ever went back to matching only the
        # literal key, the assertions above would pass on an empty dict while
        # the bug was back.
        sys.path.insert(0, str(ROOT / "scripts"))
        from check_repo_contract import _ruff_table, parse_vx_toml

        data = parse_vx_toml('[project]\nname = "d"\n\n[tool.ruff.lint]\nselect = ["E"]\n')[0]
        self.assertEqual(_ruff_table(data, "tool.ruff"), {"lint": {"select": ["E"]}})

    def test_a_nested_table_with_settings_is_still_judged_by_a004(self) -> None:
        # The case that separates the two resolvers at the verdict level: a
        # nested-only table is silent under A004, but the moment a top-level
        # setting appears A004 has to judge it.
        with FixtureRepo() as repo:
            repo.write(
                "pyproject.toml",
                '[project]\nname = "d"\n\n[tool.ruff]\nline-length = 100\n\n'
                '[tool.ruff.lint]\nselect = ["E"]\n',
            )
            _, findings = run_adapter(repo.root, "--profile", "strict")
            self.assertIn("A004", {i["rule_id"] for i in findings})
        with FixtureRepo() as repo:
            repo.write(
                "pyproject.toml",
                '[project]\nname = "d"\n\n[tool.ruff.lint]\nselect = ["E"]\n',
            )
            _, findings = run_adapter(repo.root, "--profile", "strict")
            self.assertNotIn("A004", {i["rule_id"] for i in findings})

    def test_a_sub_table_is_never_read_as_the_line_length_value(self) -> None:
        # [tool.ruff.line-length] is a sub-table, not an integer. A004 filters
        # sub-tables out before reading the value, so the table's own name can
        # never be mistaken for the setting it is supposed to hold.
        sys.path.insert(0, str(ROOT / "scripts"))
        from check_repo_contract import _ruff_table, _table_settings, parse_vx_toml

        data = parse_vx_toml('[project]\nname = "d"\n\n[tool.ruff.line-length]\nfoo = 1\n')[0]
        self.assertEqual(_ruff_table(data, "tool.ruff"), {"line-length": {"foo": "1"}})
        self.assertEqual(_table_settings(_ruff_table(data, "tool.ruff")), {})

        with FixtureRepo() as repo:
            repo.write(
                "pyproject.toml",
                '[project]\nname = "d"\n\n[tool.ruff.line-length]\nfoo = 1\n',
            )
            _, findings = run_adapter(repo.root, "--profile", "strict")
            self.assertNotIn("A004", {i["rule_id"] for i in findings}, findings)
            self.assertIn("A021", {i["rule_id"] for i in findings}, findings)

    def test_a004_stays_silent_wherever_a021_speaks(self) -> None:
        for shape, body in self.SHAPES.items():
            with FixtureRepo() as repo:
                repo.write("pyproject.toml", body)
                _, findings = run_adapter(repo.root, "--profile", "strict")
                ids = {item["rule_id"] for item in findings}
                self.assertFalse({"A021", "A004"} <= ids, shape)


class TestFleetRatchet(unittest.TestCase):
    """The measured fleet counts, so a rule change cannot move them quietly.

    A021 and A004 are warning-severity convergence rules: nothing fails when they
    drift, so a semantic regression shows up only as the nightly count moving.
    These replay the distribution the sweep measured -- one synthetic repository
    per bucket -- instead of re-cloning 51 repositories in CI.

    The three shapes below are the whole fleet as measured 2026-10-09 over every
    repository in contract/adapter_repositories.json: 48 declare line-length, 3
    declare no ruff configuration at all.
    """

    # (pyproject body, expected A021 count, expected A004 count)
    LINE_LENGTH_100 = ('[project]\nname = "d"\n\n[tool.ruff]\nline-length = 100\n', 0, 1)
    LINE_LENGTH_120 = ('[project]\nname = "d"\n\n[tool.ruff]\nline-length = 120\n', 0, 0)
    NO_RUFF_CONFIG = ('[project]\nname = "d"\n', 1, 0)

    # The fleet, as counts per shape. 30 + 18 + 3 == 51, the manifest size.
    FLEET = {
        "line-length = 100": (LINE_LENGTH_100, 30),
        "line-length = 120": (LINE_LENGTH_120, 18),
        "no ruff configuration": (NO_RUFF_CONFIG, 3),
    }

    # Shapes that occur in none of the 51 repositories today, listed so the
    # ratchet also covers the boundaries the fleet does not exercise. A rule that
    # started firing on one of these would not move the counts above, so without
    # these the ratchet is blind to exactly the change this issue fixes.
    OTHER_SHAPES = {
        # The table exists and holds nothing: A021 names it, A004 stays quiet.
        "empty [tool.ruff]": ('[project]\nname = "d"\n\n[tool.ruff]\n', 1, 0),
        # Only a sub-table exists: the table is there, so A021 names the
        # sub-table and A004 has no line-length to judge.
        "nested-only [tool.ruff.lint]": (
            '[project]\nname = "d"\n\n[tool.ruff.lint]\nselect = ["E"]\n',
            1,
            0,
        ),
    }

    # The counts the nightly sweep must keep reporting.
    EXPECTED_A021 = 3
    EXPECTED_A004 = 30

    def sweep(self) -> tuple[int, int]:
        """Run the contract over the synthetic fleet, counting per rule.

        Every repository in a bucket is checked, not just the bucket's shape:
        a rule that started firing on one of the 18 clean repositories would move
        the count even though the shape did not change.
        """
        a021 = a004 = 0
        for shape, ((body, want_a021, want_a004), count) in self.FLEET.items():
            for _ in range(count):
                with FixtureRepo() as repo:
                    repo.write("pyproject.toml", body)
                    _, findings = run_adapter(repo.root, "--profile", "strict")
                    self.assertEqual(
                        len([i for i in findings if i["rule_id"] == "A021"]),
                        want_a021,
                        shape,
                    )
                    self.assertEqual(
                        len([i for i in findings if i["rule_id"] == "A004"]),
                        want_a004,
                        shape,
                    )
                    a021 += want_a021
                    a004 += want_a004
        return a021, a004

    def test_the_fleet_still_reports_a021_three_times(self) -> None:
        a021, _a004 = self.sweep()
        self.assertEqual(a021, self.EXPECTED_A021)

    def test_the_fleet_still_reports_a004_thirty_times(self) -> None:
        _a021, a004 = self.sweep()
        self.assertEqual(a004, self.EXPECTED_A004)

    def test_the_bucket_counts_still_sum_to_the_manifest(self) -> None:
        manifest = json.loads(
            (ROOT / "contract" / "adapter_repositories.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            sum(count for _shape, count in self.FLEET.values()),
            len(manifest["repositories"]),
        )

    def test_the_boundary_shapes_keep_their_verdicts(self) -> None:
        # The counts above cannot see these shapes -- no repository in the fleet
        # has one -- so the ratchet would pass while A004 started firing on a
        # nested-only table or A021 went silent on an empty one.
        for shape, (body, want_a021, want_a004) in self.OTHER_SHAPES.items():
            with FixtureRepo() as repo:
                repo.write("pyproject.toml", body)
                _, findings = run_adapter(repo.root, "--profile", "strict")
                self.assertEqual(
                    len([i for i in findings if i["rule_id"] == "A021"]), want_a021, shape
                )
                self.assertEqual(
                    len([i for i in findings if i["rule_id"] == "A004"]), want_a004, shape
                )

    def test_a021_and_a004_never_report_the_same_repository(self) -> None:
        # One gap, one finding: the 3 repositories A021 names are silent under
        # A004, and every repository A004 names has a ruff configuration.
        shapes = {
            shape: body for shape, (body, _a021, _a004) in self.OTHER_SHAPES.items()
        }
        shapes.update(
            {shape: body for shape, ((body, _a021, _a004), _c) in self.FLEET.items()}
        )
        for shape, body in shapes.items():
            with FixtureRepo() as repo:
                repo.write("pyproject.toml", body)
                _, findings = run_adapter(repo.root, "--profile", "strict")
                ids = {item["rule_id"] for item in findings}
                self.assertFalse({"A021", "A004"} <= ids, shape)


class TestA024ReleasePleasePresent(AdapterContractTestCase):
    def test_both_files_pass(self) -> None:
        self.repo.clean()
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertNotIn("A024", self.ids(findings))

    def test_each_missing_file_is_reported_once(self) -> None:
        self.repo.clean()
        (self.repo.root / "release-please-config.json").unlink()
        (self.repo.root / ".release-please-manifest.json").unlink()
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertEqual(
            [item["path"] for item in findings if item["rule_id"] == "A024"],
            [".release-please-manifest.json", "release-please-config.json"],
        )

    def test_a_missing_manifest_alone_is_reported(self) -> None:
        self.repo.clean()
        (self.repo.root / ".release-please-manifest.json").unlink()
        _, findings = run_adapter(self.repo.root, "--profile", "strict")
        self.assertIn("A024", self.ids(findings))
        self.assertEqual(len([item for item in findings if item["rule_id"] == "A024"]), 1)


if __name__ == "__main__":
    unittest.main()
