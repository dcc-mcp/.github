"""Regression tests for the unique checks recovered from the original PR #18."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_repo_contract import AdapterContractTestCase, run_cli, ADAPTER_CONTRACT


class PackageRuleTests(AdapterContractTestCase):
    def findings(self, rule):
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        return self.findings_for(rule, findings)

    def test_missing_manifest_and_missing_core_warn(self):
        self.assertEqual(len(self.findings("A007")), 1)
        self.repo.write("pyproject.toml", '[project]\nname="demo"\ndependencies=[]\n')
        findings = self.findings("A007")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "warning")

    def test_core_dependency_forms_and_provider_names(self):
        for body in (
            '[project]\ndependencies=["dcc-mcp-core[server]>=0.20; python_version>\'3.9\'"]',
            '[project]\ndependencies=["DCC_MCP.CORE>=0.20"]',
            '[project.optional-dependencies]\ndev=["dcc-mcp-core>=0.20"]',
            '[dependency-groups]\ntest=["dcc-mcp-core>=0.20"]',
            '[tool.poetry.dependencies]\ndcc-mcp-core="^0.20"',
            '[tool.poetry.dependencies]\ndcc-mcp-core={version="^0.20", extras=["server"]}',
            '[project]\nname="dcc-mcp-core"',
            '[tool.poetry]\nname="dcc_mcp_core"',
        ):
            with self.subTest(body=body):
                self.repo.write("pyproject.toml", body + "\n")
                self.assertEqual(self.findings("A007"), [])

    def test_malformed_manifest_warns_without_crashing(self):
        self.repo.write("pyproject.toml", 'not a manifest\n')
        self.assertEqual(len(self.findings("A007")), 1)

    def test_existing_baseline_errors_remain_enforced(self):
        self.repo.write("pyproject.toml", '[project]\ndependencies=[]\n')
        self.repo.write("src/demo.py", 'from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_VERSION\n')
        code, findings = run_cli(self.repo.root, "--profile", "baseline", contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 1)
        self.assertEqual(self.severities(findings, "A001"), {"error"})
        self.assertEqual(self.severities(findings, "A007"), {"warning"})

    def report(self, expression, prefix="", markers='"steps": []'):
        self.repo.write("src/demo/report.py", prefix + '\ndef build():\n    return {"schema_version": ' + expression + ', ' + markers + '}\n')

    def test_direct_integer_report_fields_warn(self):
        for expression in ("1", "0"):
            self.report(expression)
            findings = self.findings("A011")
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["severity"], "warning")

    def test_core_artifact_revision_import_forms_warn(self):
        for prefix, expression in (
            ('from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_REVISION\n', 'INSTALL_SOP_SCHEMA_REVISION'),
            ('from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_REVISION as revision\n', 'revision'),
            ('import dcc_mcp_core.deployment as core\n', 'core.INSTALL_SOP_SCHEMA_REVISION'),
            ('import dcc_mcp_core.deployment\n', 'dcc_mcp_core.deployment.INSTALL_SOP_SCHEMA_REVISION'),
            ('from dcc_mcp_core import deployment\n', 'deployment.INSTALL_SOP_SCHEMA_REVISION'),
        ):
            with self.subTest(expression=expression):
                self.report(expression, prefix)
                self.assertEqual(len(self.findings("A011")), 1)

    def test_canonical_source_unrelated_schema_and_comments_are_clean(self):
        self.report('install_sop_report_schema_version()', 'from dcc_mcp_core.deployment import install_sop_report_schema_version\n')
        self.assertEqual(self.findings("A011"), [])
        self.report('1', markers='"metadata": {}')
        self.assertEqual(self.findings("A011"), [])
        self.report('True')
        self.assertEqual(self.findings("A011"), [])
        self.repo.write('src/demo/report.py', '# {"schema_version": 1, "steps": []}\n')
        self.assertEqual(self.findings("A011"), [])

    def test_named_constants_stay_with_existing_a002(self):
        self.report('DEMO_REPORT_SCHEMA_VERSION', 'DEMO_REPORT_SCHEMA_VERSION = 1\n')
        self.assertEqual(self.findings("A011"), [])
        self.assertEqual(len(self.findings("A002")), 1)

    def test_shadowed_and_unrelated_imports_are_not_artifact_references(self):
        self.report('revision', 'from another_library import INSTALL_SOP_SCHEMA_REVISION as revision\n')
        self.assertEqual(self.findings("A011"), [])
        self.report('revision', 'from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_REVISION as revision\nrevision = get_schema_const()\n')
        self.assertEqual(self.findings("A011"), [])

    def test_scanner_preserves_exclusions_and_reports_parse_gaps(self):
        self.repo.write('tests/test_report.py', 'REPORT = {"schema_version": 1, "steps": []}\n')
        self.assertEqual(self.findings("A011"), [])
        self.repo.write('src/demo/report.py', 'def invalid(:\n')
        _, findings = run_cli(self.repo.root, '--profile', 'strict', contract=ADAPTER_CONTRACT)
        self.assertTrue(any('not parseable' in f['message'] for f in findings))

    def test_contract_only_edits_trigger_profile_ci_on_pr_and_push(self):
        workflow = (ROOT / '.github/workflows/profile-contract.yml').read_text()
        self.assertEqual(workflow.count('- "contract/**"'), 2)
        self.assertEqual(workflow.count('- "scripts/adapter*_rules.py"'), 2)

    def test_existing_rules_and_registry_are_unchanged(self):
        # Keep baseline error ownership explicit: A007 cannot replace A001.
        contract = json.loads(Path(ADAPTER_CONTRACT).read_text())
        rules = {rule['id']: rule for rule in contract['rules']}
        self.assertEqual(rules['A001']['name'], 'no-deprecated-install-sop-alias')
        self.assertEqual(rules['A003']['severity'], 'error')
        self.assertEqual(rules['A011']['profiles'], ['strict'])
        self.assertEqual(rules['A007']['severity'], 'warning')


if __name__ == '__main__':
    unittest.main()
