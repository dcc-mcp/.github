"""Exercise runtime policy through the same CLI/contract used by nightly CI."""

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
from check_repo_contract import main  # noqa: E402


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_policy(self, text, *, promote=False):
        (self.root / "pyproject.toml").write_text(text, encoding="utf-8")
        output = io.StringIO()
        args = ["--root", str(self.root), "--contract", str(ROOT / "contract/adapter_contract.json"),
                "--profile", "baseline", "--rule", "A030,A031,A032", "--format", "json"]
        if promote:
            args += ["--error-rule", "A030,A031,A032"]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main(args)
        return code, [f for f in json.loads(output.getvalue()) if f["rule_id"] in {"A030", "A031", "A032"}]

    def fixture(self, deps='["dcc-mcp-core>=0.20.0"]', mode="host", extra=""):
        return f'[project]\nname="dcc-mcp-demo"\ndependencies={deps}\n[tool.dcc-mcp.runtime]\nmode="{mode}"\n{extra}'

    def test_host_core_extra_and_platform_marker_allowed(self):
        for dep in ('dcc-mcp-server>=0.20.0', 'dcc_mcp_core[server]>=0.20.0', 'dcc-mcp-core>=0.20.0; sys_platform == \'win32\''):
            with self.subTest(dep=dep):
                self.assertEqual(self.run_policy(self.fixture(json.dumps([dep])))[1], [])

    def test_mandatory_third_party_is_reported_and_can_be_promoted(self):
        for dep in ('packaging>=24', 'Requests[security]>=2; sys_platform == \'win32\'', 'numpy @ https://example.invalid/numpy.whl'):
            with self.subTest(dep=dep):
                code, findings = self.run_policy(self.fixture(json.dumps([dep])), promote=True)
                self.assertEqual(code, 1)
                self.assertEqual([f["rule_id"] for f in findings], ["A031"])

    def test_unknown_mode_is_warning_until_adoption(self):
        code, findings = self.run_policy('[project]\nname="dcc-mcp-demo"\n')
        self.assertEqual(code, 0)
        self.assertEqual(findings[0]["rule_id"], "A030")

    def test_unknown_and_mixed_are_not_guessed(self):
        for mode in ("mixed", "blender", "", "external "):
            self.assertEqual(self.run_policy(self.fixture(mode=mode))[1][0]["rule_id"], "A030")

    def test_provider_packages_are_not_adapters(self):
        for name in ("dcc-mcp-core", "dcc_mcp_runtime", "demo"):
            self.assertEqual(self.run_policy(f'[project]\nname="{name}"\n')[1], [])

    def test_optional_build_and_dev_dependencies_are_separate(self):
        text = self.fixture() + '\n[project.optional-dependencies]\ndev=["pytest", "packaging"]\nfeature=["numpy"]\n[build-system]\nrequires=["hatchling"]\n[dependency-groups]\ndev=["ruff"]\n'
        self.assertEqual(self.run_policy(text)[1], [])

    def test_dynamic_dependencies_never_pass_as_empty(self):
        text = '[project]\nname="dcc-mcp-demo"\ndynamic=["dependencies"]\n[tool.dcc-mcp.runtime]\nmode="host"\n'
        self.assertIn("dynamic", self.run_policy(text)[1][0]["message"])

    def test_host_core_third_party_extras_are_not_a_backdoor(self):
        for requirement in ("dcc-mcp-core[bridge]>=0.20", "dcc-mcp-core [dev]>=0.20"):
            self.assertEqual(len(self.run_policy(self.fixture(json.dumps([requirement])))[1]), 1)
        text = self.fixture() + '\n[tool.poetry.dependencies]\ndcc-mcp-core={version=">=0.20",extras=["bridge"]}\n'
        self.assertEqual(len(self.run_policy(text)[1]), 1)

    def test_bad_toml_is_reported(self):
        self.assertEqual(self.run_policy('[project\nname="dcc-mcp-demo"')[1][0]["rule_id"], "A030")

    def test_poetry_path_dependency_is_not_silently_skipped(self):
        text = self.fixture() + '\n[tool.poetry.dependencies]\npython=">=3.9"\npackaging={path="../packaging"}\npytest={version="*",optional=true}\n'
        findings = self.run_policy(text)[1]
        self.assertEqual(len(findings), 1)
        self.assertIn("packaging", findings[0]["message"])

    def test_external_requires_official_provider(self):
        findings = self.run_policy(self.fixture(mode="external"))[1]
        self.assertEqual(findings[0]["rule_id"], "A032")

    def test_external_dependencies_need_purpose(self):
        text = self.fixture('["websocket-client>=1"]', "external", 'provider="dcc-mcp-runtime"\n')
        self.assertEqual(len(self.run_policy(text)[1]), 1)
        text += '[tool.dcc-mcp.runtime.third-party-reasons]\nwebsocket_client="OBS WebSocket protocol bridge"\n'
        self.assertEqual(self.run_policy(text)[1], [])

    def test_external_first_party_needs_no_exception(self):
        text = self.fixture('["dcc-mcp-core>=0.20.0", "dcc-mcp-runtime>=0.2"]', "external", 'provider="dcc-mcp-runtime"\n')
        self.assertEqual(self.run_policy(text)[1], [])

    def test_empty_reason_is_not_a_justification(self):
        text = self.fixture('["psutil"]', "external", 'provider="dcc-mcp-runtime"\n[tool.dcc-mcp.runtime.third-party-reasons]\npsutil=" "\n')
        self.assertEqual(len(self.run_policy(text)[1]), 1)


if __name__ == "__main__":
    unittest.main()
