"""Offline tests for the warning-only organization automation inventory."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_automation_contract import (  # noqa: E402
    blob_sha,
    check,
    inventory_errors,
    main,
    schema_errors,
)


class TestAutomationContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schema = json.loads((ROOT / "contract/automation_inventory.schema.json").read_text())
        self.policy = json.loads((ROOT / "contract/automation_policy.json").read_text())
        self.snapshot = json.loads((ROOT / "contract/automation_inventory.json").read_text())
        self.path = ".github/workflows/release.yml"
        self.content = b"name: Release\non: workflow_dispatch\n"
        self.source = self.root / self.path
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(self.content)
        self.inventory = copy.deepcopy(self.snapshot)
        self.inventory["scope"]["representative_repositories"] = 1
        self.inventory["repositories"] = [
            {
                "repository": "dcc-mcp/example",
                "classification": "fixture",
                "finding": "Public workflow source only.",
                "credential_availability": "not_verified",
                "source_files": [
                    {
                        "path": self.path,
                        "blob_sha": blob_sha(self.content),
                        "url": "https://github.com/dcc-mcp/example/blob/main/" + self.path,
                        "secret_name_references": ["GITHUB_TOKEN"],
                    }
                ],
            }
        ]

    def run_check(self, repository="dcc-mcp/example"):
        return check(self.root, repository, self.inventory, self.schema, self.policy)

    def run_cli(self, *args):
        path = self.root / "inventory.json"
        path.write_text(json.dumps(self.inventory))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--inventory", str(path), "--root", str(self.root), *args])
        return code, output.getvalue()

    def assert_invalid(self):
        result = self.run_check()
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["checked_files"], 0)
        self.assertEqual({item["rule_id"] for item in result["findings"]}, {"O001"})

    def test_real_audited_snapshot_validates(self):
        self.assertEqual(inventory_errors(self.snapshot, self.schema, self.policy), [])
        self.assertEqual(len(self.snapshot["repositories"]), 15)
        self.assertEqual(set(self.snapshot["scope"]["organizations"]), set(self.policy["organizations"]))

    def test_unchanged_file_matches_git_blob(self):
        self.assertEqual(blob_sha(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
        result = self.run_check()
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["checked_files"], 1)
        self.assertEqual(result["findings"], [])

    def test_drift_is_warning_and_does_not_change_checkout_or_inventory(self):
        self.source.write_bytes(self.content + b"# comment-only changes also need re-audit\n")
        before = copy.deepcopy(self.inventory)
        result = self.run_check()
        self.assertEqual(result["findings"][0]["rule_id"], "O003")
        self.assertEqual(result["findings"][0]["severity"], "warning")
        self.assertEqual(before, self.inventory)
        self.assertTrue(self.source.read_bytes().endswith(b"re-audit\n"))

    def test_missing_file_reports_source_warning(self):
        self.source.unlink()
        result = self.run_check()
        self.assertEqual(result["findings"][0]["rule_id"], "O002")
        self.assertEqual(result["checked_files"], 0)

    def test_directory_instead_of_file_is_unreadable(self):
        self.source.unlink()
        self.source.mkdir()
        self.assertEqual(self.run_check()["findings"][0]["rule_id"], "O002")

    def test_symlink_file_and_parent_are_not_followed(self):
        self.source.unlink()
        target = self.root / "private.txt"
        target.write_text("DO-NOT-PRINT")
        try:
            self.source.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        self.assertEqual(self.run_check()["findings"][0]["rule_id"], "O002")
        self.source.unlink()
        self.source.parent.rmdir()
        alternate = self.root / "alternate"
        alternate.mkdir()
        (alternate / "release.yml").write_bytes(self.content)
        self.source.parent.symlink_to(alternate, target_is_directory=True)
        self.assertEqual(self.run_check()["findings"][0]["rule_id"], "O002")

    def test_bad_sha_and_negative_job_count_rejected(self):
        self.inventory["repositories"][0]["source_files"][0]["blob_sha"] = "main"
        self.assert_invalid()
        self.inventory = copy.deepcopy(self.snapshot)
        self.inventory["pr_evidence"][0]["runs"][0]["job_count"] = -1
        self.assert_invalid()

    def test_bool_is_not_an_integer(self):
        self.inventory["scope"]["representative_repositories"] = True
        self.assert_invalid()

    def test_unknown_fields_rejected_at_each_object_level(self):
        original = copy.deepcopy(self.inventory)
        for keys in [
            (),
            ("scope",),
            ("repositories", 0),
            ("repositories", 0, "source_files", 0),
            ("pr_evidence", 0),
            ("pr_evidence", 0, "runs", 0),
            ("findings", 0),
        ]:
            with self.subTest(keys=keys):
                self.inventory = copy.deepcopy(original)
                node = self.inventory
                for key in keys:
                    node = node[key]
                node["secret_value"] = "DO-NOT-PRINT"
                self.assert_invalid()
                self.assertNotIn("DO-NOT-PRINT", json.dumps(self.run_check()))

    def test_credential_availability_cannot_claim_verified(self):
        self.inventory["repositories"][0]["credential_availability"] = "verified"
        self.assert_invalid()

    def test_missing_required_property_rejected(self):
        del self.inventory["observed_at"]
        self.assert_invalid()

    def test_invalid_timestamp_and_uri_rejected(self):
        for timestamp in ["2026-10-12", "20261012T111000Z", "2026-13-12T11:10:00Z"]:
            self.inventory["observed_at"] = timestamp
            self.assert_invalid()
        self.inventory["observed_at"] = self.snapshot["observed_at"]
        self.inventory["repositories"][0]["source_files"][0]["url"] = "not a URI"
        self.assert_invalid()

    def test_duplicate_secret_names_rejected(self):
        self.inventory["repositories"][0]["source_files"][0]["secret_name_references"] *= 2
        self.assert_invalid()

    def test_scope_count_and_organization_keys_match(self):
        for key, value in [
            ("representative_repositories", 2),
            ("discovered_public_repositories", {}),
            ("organizations", ["outside-org"]),
        ]:
            with self.subTest(key=key):
                old = self.inventory["scope"][key]
                self.inventory["scope"][key] = value
                self.assert_invalid()
                self.inventory["scope"][key] = old

    def test_duplicate_repositories_and_sources_rejected(self):
        self.inventory["repositories"].append(copy.deepcopy(self.inventory["repositories"][0]))
        self.inventory["repositories"][1]["repository"] = "DCC-MCP/Example"
        self.inventory["scope"]["representative_repositories"] = 2
        self.assert_invalid()
        self.inventory["repositories"].pop()
        self.inventory["scope"]["representative_repositories"] = 1
        self.inventory["repositories"][0]["source_files"] *= 2
        self.assert_invalid()

    def test_unsafe_or_out_of_scope_paths_rejected(self):
        for path in [
            "/tmp/secret",
            "../secret",
            ".github/workflows/../../../secret",
            ".github//workflows/release.yml",
            ".github/workflows/./release.yml",
            ".github\\workflows\\release.yml",
            "README.md",
        ]:
            with self.subTest(path=path):
                self.inventory["repositories"][0]["source_files"][0]["path"] = path
                self.assert_invalid()

    def test_unregistered_repo_explicitly_skips_without_claiming_clean(self):
        result = self.run_check("dcc-mcp/not-yet-audited")
        self.assertEqual(result["status"], "not_in_inventory")
        self.assertEqual(result["checked_files"], 0)
        self.assertEqual(result["findings"], [])

    def test_repository_selection_is_case_insensitive(self):
        self.assertEqual(self.run_check("DCC-MCP/Example")["checked_files"], 1)

    def test_all_three_orgs_share_checker_without_network(self):
        for organization in self.policy["organizations"]:
            with self.subTest(organization=organization):
                name = organization + "/example"
                self.inventory["repositories"][0]["repository"] = name
                self.assertEqual(self.run_check(name)["checked_files"], 1)

    def test_empty_sources_are_not_claimed_to_prove_workflow_absence(self):
        self.inventory["repositories"][0]["source_files"] = []
        self.assertEqual(self.run_check()["checked_files"], 0)

    def test_validate_only_does_not_read_checkout(self):
        self.source.unlink()
        code, output = self.run_cli("--validate-only", "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "validated")

    def test_warning_does_not_fail_cli(self):
        self.source.write_bytes(b"changed")
        code, output = self.run_cli("--repository", "dcc-mcp/example", "--format", "github")
        self.assertEqual(code, 0)
        self.assertIn("::warning title=Automation contract O003::", output)
        self.assertNotIn("::error", output)

    def test_invalid_inventory_warns_and_does_not_fail_cli(self):
        self.inventory["secret_value"] = "DO-NOT-PRINT"
        code, output = self.run_cli("--validate-only", "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "invalid")
        self.assertNotIn("DO-NOT-PRINT", output)

    def test_unavailable_input_is_distinct_from_validated(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--validate-only", "--inventory", str(self.root / "missing.json"), "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "unavailable")

    def test_unsupported_schema_keyword_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            schema_errors({}, {"type": "object", "oneOf": []})
        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            schema_errors({}, {"type": "object", "properties": {"absent": {"minLength": 1}}})

    def test_repeated_check_is_identical_and_does_not_update_baseline(self):
        self.source.write_bytes(b"changed")
        first = self.run_check()
        self.assertEqual(self.run_check(), first)
        self.assertEqual(self.inventory["repositories"][0]["source_files"][0]["blob_sha"], blob_sha(self.content))

    def test_malformed_json_and_promoted_policy_remain_unavailable_warnings(self):
        malformed = self.root / "malformed.json"
        malformed.write_text('{"secret_value": "DO-NOT-PRINT"')
        policy = self.root / "policy.json"
        promoted = copy.deepcopy(self.policy)
        promoted["rules"]["drift"]["severity"] = "error"
        policy.write_text(json.dumps(promoted))
        for args in [("--inventory", str(malformed)), ("--policy", str(policy))]:
            with self.subTest(args=args):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(["--validate-only", "--format", "json", *args]), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["findings"][0]["severity"], "warning")
                self.assertNotIn("DO-NOT-PRINT", output.getvalue())

    def test_rules_are_unique_warning_only_separate_namespace(self):
        rules = list(self.policy["rules"].values())
        ids = {rule["id"] for rule in rules}
        self.assertEqual(len(ids), len(rules))
        self.assertEqual({rule["severity"] for rule in rules}, {"warning"})
        for path in ["repo_contract.json", "adapter_contract.json"]:
            existing = json.loads((ROOT / "contract" / path).read_text())
            self.assertFalse(ids & {rule["id"] for rule in existing["rules"]})


if __name__ == "__main__":
    unittest.main()
