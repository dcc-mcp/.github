"""Read-only artifact audit regressions; fixtures are never extracted or run."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_runtime_artifact import audit, main, required_without_extras  # noqa: E402


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.contract = json.loads((ROOT / "contract/adapter_contract.json").read_text())

    def archive(self, files):
        path = self.root / "adapter.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)
        return path

    def test_exact_sizes_and_sha(self):
        path = self.archive({"x.py": b"123", "y.py": b"12345"})
        report = audit(path, self.contract)
        self.assertEqual(report["archive_bytes"], path.stat().st_size)
        self.assertEqual(report["top_level_unpacked_bytes"], 8)
        self.assertEqual(report["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_host_distributions(self):
        path = self.archive({"dcc_mcp_demo.dist-info/METADATA": "Name: dcc-mcp-demo\nVersion: 1\n",
                             "dcc_mcp_core.dist-info/METADATA": "Name: dcc_mcp_core\nVersion: 1\n"})
        self.assertTrue(audit(path, self.contract, "host", "dcc-mcp-demo")["passed"])
        self.assertFalse(audit(path, self.contract, "host")["passed"])

    def test_vendored_metadata_is_not_first_party(self):
        path = self.archive({"vendor/packaging.dist-info/METADATA": "Name: packaging\nVersion: 24.0\n"})
        self.assertFalse(audit(path, self.contract, "host", "dcc-mcp-demo")["passed"])

    def test_interpreters_and_venvs_forbidden_in_adapter_archive(self):
        for name in ("bin/python3.11", "lib/libpython3.11.so.1.0", "python310.dll", ".venv/a.py", "pyvenv.cfg"):
            with self.subTest(name=name):
                path = self.archive({name: b"fixture"})
                self.assertFalse(audit(path, self.contract, "external")["passed"])
                self.assertTrue(audit(path, self.contract, "inspect")["passed"])

    def test_core_native_extension_is_not_an_interpreter(self):
        path = self.archive({"dcc_mcp_core/_core.pyd": b"fake", "python_helper.py": b"# test"})
        self.assertTrue(audit(path, self.contract, "external")["passed"])

    def test_nested_wheel_metadata_and_separate_sizes(self):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as wheel:
            wheel.writestr("packaging.dist-info/METADATA", "Name: packaging\nVersion: 24.0\n")
        path = self.archive({"wheels/packaging.whl": nested.getvalue()})
        report = audit(path, self.contract, "host", "dcc-mcp-demo")
        self.assertFalse(report["passed"])
        self.assertEqual(report["top_level_unpacked_bytes"], len(nested.getvalue()))
        self.assertEqual(report["nested_payload_unpacked_bytes"], len(b"Name: packaging\nVersion: 24.0\n"))

    def test_nested_limit_is_failure_not_silent_coverage_loss(self):
        self.contract["runtime_artifact_policy"]["max_nested_bytes"] = 1
        path = self.archive({"x.whl": b"data"})
        self.assertIn("limit", audit(path, self.contract)["findings"][0])

    def test_member_limit_reports_incomplete(self):
        self.contract["runtime_artifact_policy"]["max_members"] = 1
        path = self.archive({"a": b"a", "b": b"b"})
        self.assertFalse(audit(path, self.contract)["passed"])

    def test_metadata_limit_reports_incomplete(self):
        self.contract["runtime_artifact_policy"]["max_metadata_bytes"] = 1
        path = self.archive({"x.dist-info/METADATA": b"Name: x\nVersion: 1\n"})
        self.assertFalse(audit(path, self.contract)["passed"])

    def test_duplicate_headers_and_paths_fail(self):
        path = self.archive({"x.dist-info/METADATA": "Name: x\nName: y\nVersion: 1\n"})
        self.assertFalse(audit(path, self.contract)["passed"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("x.dist-info/METADATA", "Name: x\nVersion: 1\n")
        self.assertTrue(any("duplicate archive member" in f for f in audit(path, self.contract)["findings"]))

    def test_unsafe_path_is_detected_without_extracting(self):
        for name in ("../outside", "/absolute", "C:\\outside", "x\\..\\outside"):
            path = self.archive({name: b"data"})
            self.assertFalse(audit(path, self.contract)["passed"])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["adapter.zip"])

    def test_tar_gzip_supported(self):
        path = self.root / "adapter.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo("bin/python.exe")
            info.size = 3
            archive.addfile(info, io.BytesIO(b"123"))
        report = audit(path, self.contract, "external")
        self.assertFalse(report["passed"])
        self.assertEqual(report["top_level_unpacked_bytes"], 3)

    def test_built_mandatory_dependencies_are_enforced(self):
        path = self.archive({"demo.dist-info/METADATA": "Name: dcc-mcp-demo\nVersion: 1\nRequires-Dist: requests>=2\n"})
        self.assertFalse(audit(path, self.contract, "host", "dcc-mcp-demo")["passed"])

    def test_optional_metadata_is_separate_but_or_marker_can_be_mandatory(self):
        self.assertFalse(required_without_extras("pytest; extra == 'test'"))
        self.assertFalse(required_without_extras("pytest; python_version > '3.8' and extra == 'test'"))
        self.assertTrue(required_without_extras("pytest; python_version > '3.8' or extra == 'test'"))
        self.assertTrue(required_without_extras("pytest; extra != 'test'"))
        self.assertTrue(required_without_extras("pytest; malformed !!!"))
        self.assertFalse(required_without_extras("pytest; 'test' == extra"))

    def test_spaced_extras_are_not_a_backdoor(self):
        path = self.archive({"demo.dist-info/METADATA": "Name: dcc-mcp-demo\nVersion: 1\nRequires-Dist: dcc-mcp-core [dev]>=0.20\n"})
        self.assertFalse(audit(path, self.contract, "host", "dcc-mcp-demo")["passed"])

    def test_blank_metadata_identity_fails(self):
        path = self.archive({"x.dist-info/METADATA": "Name: x\nVersion: \n"})
        self.assertFalse(audit(path, self.contract)["passed"])

    def test_stdlib_venv_is_not_an_installed_environment(self):
        path = self.archive({"lib/venv/__init__.py": b"stdlib"})
        self.assertTrue(audit(path, self.contract, "external")["passed"])

    def test_encrypted_payload_failure_is_reported(self):
        from unittest.mock import patch
        path = self.archive({"x.dist-info/METADATA": "Name: x\nVersion: 1\n"})
        with patch.object(zipfile.ZipFile, "read", side_effect=RuntimeError("encrypted")):
            self.assertFalse(audit(path, self.contract)["passed"])

    def test_corrupt_deflate_is_reported_without_traceback(self):
        import struct
        path = self.archive({"demo.dist-info/METADATA": "Name: dcc-mcp-demo\nVersion: 1\n"})
        data = bytearray(path.read_bytes())
        name_len, extra_len = struct.unpack_from("<HH", data, 26)
        data[30 + name_len + extra_len] = 0x07
        path.write_bytes(data)
        self.assertFalse(audit(path, self.contract)["passed"])

    def test_invalid_archive_reports_incomplete(self):
        path = self.root / "broken.zip"
        path.write_bytes(b"broken")
        self.assertFalse(audit(path, self.contract)["passed"])


if __name__ == "__main__":
    unittest.main()
