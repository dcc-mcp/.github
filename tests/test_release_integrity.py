"""Unit tests for scripts/check_release_integrity.py.

These tests run under plain `unittest` with no third-party dependencies, matching the
runner used by `.github/workflows/profile-contract.yml`. No test touches the network:
the GitHub and PyPI lookups are always replaced with stubs.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_integrity as cri  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
REPO = "o/r"
PKG = "pkg"


def release(tag, minutes_ago):
    """A release published ``minutes_ago`` before the frozen NOW constant."""
    published = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return {"tagName": tag, "publishedAt": published}


def release_now(tag, minutes_ago):
    """A release published ``minutes_ago`` before the real clock, for CLI tests."""
    published = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"tagName": tag, "publishedAt": published.isoformat().replace("+00:00", "Z")}


class VersionHelpersTest(unittest.TestCase):
    def test_normalize_tag_strips_prefix(self):
        self.assertEqual(cri.normalize_tag("v0.3.7"), "0.3.7")
        self.assertEqual(cri.normalize_tag("0.3.7"), "0.3.7")
        self.assertEqual(cri.normalize_tag("V1.2.3"), "1.2.3")
        self.assertEqual(cri.normalize_tag(" v2.0.0 "), "2.0.0")

    def test_compare_versions_is_numeric(self):
        cases = [
            ("0.3.7", "0.3.7", 0),
            ("0.3.7", "0.3.1", 1),
            ("0.3.1", "0.3.7", -1),
            ("0.10.0", "0.9.31", 1),
            ("1.0.0", "1.0.0rc1", 0),
            ("1.0.1", "1.0.0", 1),
        ]
        for left, right, expected in cases:
            with self.subTest(left=left, right=right):
                actual = cri.compare_versions(cri.parse_version(left), cri.parse_version(right))
                self.assertEqual(actual, expected)

    def test_empty_version_comparison(self):
        self.assertEqual(cri.parse_version(""), ())


class ManifestTest(unittest.TestCase):
    def test_expands_packages(self):
        manifest = json.dumps(
            [
                {"repository": "dcc-mcp/dcc-mcp-unreal", "packages": ["dcc-mcp-unreal"]},
                {
                    "repository": "dcc-mcp/dcc-mcp-core",
                    "packages": ["dcc-mcp-core", "dcc-mcp-server", "dcc-mcp-core-semantic"],
                },
            ]
        )
        pairs = [(t.repository, t.package) for t in cri.parse_manifest(manifest)]
        self.assertEqual(
            pairs,
            [
                ("dcc-mcp/dcc-mcp-unreal", "dcc-mcp-unreal"),
                ("dcc-mcp/dcc-mcp-core", "dcc-mcp-core"),
                ("dcc-mcp/dcc-mcp-core", "dcc-mcp-server"),
                ("dcc-mcp/dcc-mcp-core", "dcc-mcp-core-semantic"),
            ],
        )

    def test_accepts_object_form(self):
        manifest = json.dumps({"repositories": [{"repository": "o/r", "packages": ["pkg"]}]})
        self.assertEqual(cri.parse_manifest(manifest), [cri.Target("o/r", "pkg")])

    def test_accepts_a_file_path(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            handle.write(json.dumps({"repositories": [{"repository": "o/r", "packages": ["pkg"]}]}))
            path = handle.name
        self.assertEqual(cri.parse_manifest(path), [cri.Target("o/r", "pkg")])

    def test_defaults_package_to_repository_name(self):
        self.assertEqual(cri.parse_manifest(json.dumps([{"repository": "o/r"}])), [cri.Target("o/r", "r")])

    def test_rejects_unusable_entries(self):
        bad = [
            "{not json",
            "   ",
            json.dumps([{"packages": ["pkg"]}]),
            json.dumps([{"repository": "o/r", "packages": []}]),
            json.dumps([42]),
        ]
        for manifest in bad:
            with self.subTest(manifest=manifest):
                with self.assertRaises(cri.CheckError):
                    cri.parse_manifest(manifest)

    def test_matrix_payload_shape(self):
        payload = cri.matrix_payload([cri.Target("o/r", "pkg")])
        self.assertEqual(payload["include"][0], {"repository": "o/r", "package": "pkg", "key": "o/r:pkg"})


class EvaluateTest(unittest.TestCase):
    def evaluate(self, tag, minutes_ago, pypi, grace=30.0):
        target = cri.Target(REPO, PKG)
        with mock.patch.object(cri, "latest_release", lambda _repo: release(tag, minutes_ago)):
            with mock.patch.object(cri, "pypi_version", lambda _pkg: pypi):
                return cri.evaluate(target, grace_minutes=grace, now=NOW)

    def test_matching_versions_pass(self):
        result = self.evaluate("v0.3.7", 600, "0.3.7")
        self.assertEqual(result.status, cri.STATUS_OK)
        self.assertEqual(result.pypi_version, "0.3.7")

    def test_stale_pypi_fails(self):
        result = self.evaluate("v0.3.7", 600, "0.3.1")
        self.assertEqual(result.status, cri.STATUS_FAIL)
        self.assertIn("0.3.1", result.message)

    def test_grace_period_tolerates_a_missing_upload(self):
        result = self.evaluate("v0.3.7", 5, "0.3.1")
        self.assertEqual(result.status, cri.STATUS_WARN)
        self.assertIn("grace", result.message)

    def test_grace_period_expires(self):
        self.assertEqual(self.evaluate("v0.3.7", 31, "0.3.1").status, cri.STATUS_FAIL)

    def test_grace_period_ignores_unparseable_timestamp(self):
        stub = {"tagName": "v0.3.7", "publishedAt": "nope"}
        with mock.patch.object(cri, "latest_release", lambda _r: stub):
            with mock.patch.object(cri, "pypi_version", lambda _p: "0.3.1"):
                result = cri.evaluate(cri.Target(REPO, PKG), grace_minutes=30, now=NOW)
        self.assertEqual(result.status, cri.STATUS_FAIL)

    def test_missing_package_fails_after_grace(self):
        self.assertEqual(self.evaluate("v0.3.7", 600, None).status, cri.STATUS_FAIL)
        self.assertEqual(self.evaluate("v0.3.7", 5, None).status, cri.STATUS_WARN)

    def test_prerelease_ahead_of_stable_warns(self):
        result = self.evaluate("v0.20.34", 600, "0.21.0rc1")
        self.assertEqual(result.status, cri.STATUS_WARN)
        self.assertIn("ahead", result.message)

    def test_no_release_skips(self):
        with mock.patch.object(cri, "latest_release", lambda _r: None):
            with mock.patch.object(cri, "pypi_version", lambda _p: "0.3.7"):
                result = cri.evaluate(cri.Target(REPO, PKG), grace_minutes=30, now=NOW)
        self.assertEqual(result.status, cri.STATUS_SKIP)

    def test_semver_ordering_beats_string_ordering(self):
        """0.10.0 must sort above 0.9.31, which a plain string compare gets wrong."""
        self.assertEqual(self.evaluate("v0.9.31", 600, "0.10.0").status, cri.STATUS_WARN)


class CliTest(unittest.TestCase):
    def run_cli(self, argv, release_stub=None, pypi_stub=None):
        out, err = io.StringIO(), io.StringIO()
        patchers = []
        if release_stub is not None:
            patchers.append(mock.patch.object(cri, "latest_release", release_stub))
        if pypi_stub is not None:
            patchers.append(mock.patch.object(cri, "pypi_version", pypi_stub))
        for patcher in patchers:
            patcher.start()
        try:
            with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
                code = cri.main(argv)
        finally:
            for patcher in patchers:
                patcher.stop()
        return code, out.getvalue(), err.getvalue()

    def test_emits_matrix(self):
        manifest = json.dumps([{"repository": "o/r", "packages": ["pkg"]}])
        code, out, _ = self.run_cli(["--manifest", manifest, "--emit-matrix"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["include"][0]["key"], "o/r:pkg")

    def test_reports_failure_exit_code(self):
        argv = ["--repository", REPO, "--package", PKG, "--json"]
        code, out, _ = self.run_cli(argv, lambda _r: release_now("v0.3.7", 600), lambda _p: "0.3.1")
        self.assertEqual(code, 1)
        self.assertIn("::error", out)
        payload = json.loads(out[out.index("["):])
        self.assertEqual(payload[0]["status"], cri.STATUS_FAIL)

    def test_strict_fails_on_warnings(self):
        def stub_release(_repo):
            return release_now("v0.3.7", 5)

        argv = ["--repository", REPO, "--package", PKG]
        self.assertEqual(self.run_cli(argv, stub_release, lambda _p: "0.3.1")[0], 0)
        self.assertEqual(self.run_cli(argv + ["--strict"], stub_release, lambda _p: "0.3.1")[0], 1)

    def test_requires_repository_and_package(self):
        self.assertEqual(self.run_cli(["--repository", REPO])[0], 2)

    def test_reports_unusable_input(self):
        code, _, err = self.run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("error", err)


class ReportingTest(unittest.TestCase):
    def test_render_table_marks_statuses(self):
        table = cri.render_table(
            [
                cri.Result("o/r", "pkg", cri.STATUS_OK, "fine", "v1.0.0", None, "1.0.0"),
                cri.Result("o/r", "pkg2", cri.STATUS_FAIL, "bad", "v1.0.0", None, "0.9.0"),
            ]
        )
        self.assertIn("| PASS | `o/r` |", table)
        self.assertIn("| FAIL | `o/r` |", table)

    def test_result_key(self):
        self.assertEqual(cri.Result("o/r", "pkg", cri.STATUS_OK, "fine").key, "o/r:pkg")

    def test_no_network_is_reached_by_the_suite(self):
        """The stubs are always installed, so an accidental lookup would raise."""

        def _boom(*_args, **_kwargs):
            raise AssertionError("tests must not perform network calls")

        with mock.patch.object(cri, "latest_release", _boom):
            with mock.patch.object(cri, "pypi_version", _boom):
                with self.assertRaises(AssertionError):
                    cri.evaluate(cri.Target(REPO, PKG), grace_minutes=30, now=NOW)


if __name__ == "__main__":
    unittest.main()
