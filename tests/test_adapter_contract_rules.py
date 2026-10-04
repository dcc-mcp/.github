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
