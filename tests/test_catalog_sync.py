"""Unit tests for scripts/check_catalog_sync.py.

These tests run under plain `unittest` with no third-party dependencies. No test
touches the network: the GitHub and PyPI lookups are always replaced with stubs.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_catalog_sync as ccs  # noqa: E402

# A catalog entry for an adapter whose PyPI release is newer than the pin.
SOURCE_YAML = """
version: "1"
entries:
  - name: "dcc-mcp-maya"
    description: "Maya adapter"
    dcc: ["maya"]
    version: "0.9.22"
    install:
      type: pip
      pip_package: "dcc-mcp-maya"
      url: "https://files.pythonhosted.org/packages/ab/cd/dcc_mcp_maya-0.9.22-py3-none-any.whl"
      sha256: "aa" * 32

  - name: "dcc-mcp-PowerPoint"
    description: "PowerPoint adapter"
    version: "0.1.0"

  - name: "dcc-mcp-kdenlive"
    description: "Kdenlive adapter"
    version: "0.1.0"
    install:
      type: pip
      pip_package: "dcc-mcp-kdenlive"
      url: "https://github.com/dcc-mcp/dcc-mcp-kdenlive/releases/download/v0.1.0/x.whl"
      sha256: "bb" * 32

  - name: "dcc-mcp-core"
    description: "Core library"
    dcc: []
"""


def published_entry(name, version=None, install=None, policy=None):
    entry = {"name": name}
    if version is not None:
        entry["version"] = version
    if install is not None:
        entry["install"] = install
    if policy is not None:
        entry["policy"] = policy
    return entry


def snapshot(*entries):
    return ccs.CatalogSnapshot(entries=list(entries))


class ParseVersionTest(unittest.TestCase):
    def test_compares_numerically(self):
        self.assertGreater(ccs.parse_version("0.10.0"), ccs.parse_version("0.9.31"))

    def test_ignores_a_non_numeric_suffix(self):
        # 1.0.0rc1 must not sort above 1.0.0, which a plain string compare gets wrong.
        self.assertEqual(ccs.parse_version("1.0.0rc1"), ccs.parse_version("1.0.0"))

    def test_handles_empty_input(self):
        self.assertEqual(ccs.parse_version(""), ())


class ParseCatalogYamlTest(unittest.TestCase):
    def test_reads_entries_and_install_blocks(self):
        parsed = ccs.parse_catalog_yaml(SOURCE_YAML)
        self.assertEqual(parsed.names(), {"dcc-mcp-maya", "dcc-mcp-PowerPoint", "dcc-mcp-kdenlive", "dcc-mcp-core"})

    def test_install_block_marks_availability(self):
        parsed = ccs.parse_catalog_yaml(SOURCE_YAML)
        self.assertEqual(
            parsed.install_available(),
            {"dcc-mcp-maya", "dcc-mcp-kdenlive"},
        )

    def test_nested_keys_do_not_leak_into_the_entry(self):
        entry = ccs.parse_catalog_yaml(SOURCE_YAML).entry("dcc-mcp-maya")
        self.assertEqual(entry["version"], "0.9.22")
        self.assertEqual(entry["install"]["pip_package"], "dcc-mcp-maya")
        self.assertNotIn("pip_package", entry)

    def test_parses_a_policy_block(self):
        yaml_text = """
version: "1"
entries:
  - name: "dcc-mcp-broken"
    description: "broken"
    policy:
      installation: "not_available"
      reason: "Release validation failed; installation is unavailable."
"""
        entry = ccs.parse_catalog_yaml(yaml_text).entry("dcc-mcp-broken")
        self.assertEqual(entry["policy"]["installation"], "not_available")
        self.assertIn("Release validation failed", entry["policy"]["reason"])

    def test_ignores_comments_and_blank_lines(self):
        parsed = ccs.parse_catalog_yaml("# a comment\n\nversion: \"1\"\nentries:\n  - name: \"x\"\n")
        self.assertEqual(parsed.names(), {"x"})


class PackageForTest(unittest.TestCase):
    def test_infrastructure_has_no_package(self):
        self.assertIsNone(ccs.package_for("dcc-mcp-core"))
        self.assertIsNone(ccs.package_for("dcc-mcp-office"))

    def test_mixed_case_name_maps_to_the_pypi_project(self):
        # The catalog writes `dcc-mcp-PowerPoint`; PyPI normalises it to lowercase.
        self.assertEqual(ccs.package_for("dcc-mcp-PowerPoint"), "dcc-mcp-powerpoint")

    def test_ordinary_names_pass_through(self):
        self.assertEqual(ccs.package_for("dcc-mcp-maya"), "dcc-mcp-maya")


class EvaluateEntryTest(unittest.TestCase):
    def evaluate(self, entry, pypi_version, release=None):
        # The metadata dict shape PyPI returns: the newest version lives under `info`.
        metadata = {"info": {"version": pypi_version}} if pypi_version else None
        published = snapshot(entry)
        with mock.patch.object(ccs, "pypi_version", lambda _pkg, _t, version=None: metadata):
            with mock.patch.object(ccs, "latest_release", lambda _repo, _t: release):
                return ccs.evaluate_entry(entry["name"], published, ccs.package_for(entry["name"]), 1.0)

    def test_in_sync_entry_produces_no_finding(self):
        entry = published_entry("dcc-mcp-maya", version="0.9.22", install={"type": "pip"})
        self.assertIsNone(self.evaluate(entry, "0.9.22"))

    def test_missing_install_block_with_pypi_release_is_a_false_negative(self):
        entry = published_entry("dcc-mcp-PowerPoint", version="0.1.0")
        finding = self.evaluate(entry, "0.2.3")
        self.assertEqual(finding.state, ccs.STATE_STALE_FALSE_NEGATIVE)
        self.assertTrue(finding.installable)
        self.assertEqual(finding.pypi_version, "0.2.3")

    def test_no_install_block_and_no_pypi_release_is_correctly_unavailable(self):
        entry = published_entry("dcc-mcp-material-maker", version="0.4.0")
        self.assertIsNone(self.evaluate(entry, None))

    def test_stale_pin_is_reported(self):
        entry = published_entry("dcc-mcp-maya", version="0.9.22", install={"type": "pip"})
        finding = self.evaluate(entry, "0.9.34")
        self.assertEqual(finding.state, ccs.STATE_STALE_PIN)
        self.assertEqual(finding.catalog_version, "0.9.22")
        self.assertEqual(finding.pypi_version, "0.9.34")

    def test_quarantine_carries_the_reason_through(self):
        # The reason is the only surviving record of why the publisher dropped the
        # install block, so losing it would hide the very signal this check exists for.
        entry = published_entry(
            "dcc-mcp-kdenlive",
            version="0.1.0",
            policy={
                "installation": "not_available",
                "reason": "Release validation failed; installation is unavailable until a successful catalog refresh.",
            },
        )
        finding = self.evaluate(entry, "0.1.2")
        self.assertEqual(finding.state, ccs.STATE_QUARANTINED)
        self.assertIn("Release validation failed", finding.reason)
        self.assertEqual(finding.pypi_version, "0.1.2")

    def test_infrastructure_entries_are_never_reported(self):
        entry = published_entry("dcc-mcp-core", version="0.20.41")
        self.assertIsNone(self.evaluate(entry, "0.20.41"))


class EvaluateMissingTest(unittest.TestCase):
    def evaluate(self, repository, pypi_version, release=None, source=None, published=None):
        metadata = {"info": {"version": pypi_version}} if pypi_version else None
        source = source if source is not None else snapshot()
        published = published if published is not None else snapshot()
        with mock.patch.object(ccs, "pypi_version", lambda _pkg, _t, version=None: metadata):
            with mock.patch.object(ccs, "latest_release", lambda _repo, _t: release):
                return ccs.evaluate_missing(repository, source, published, 1.0)

    def test_pypi_only_repository_is_a_missing_entry(self):
        finding = self.evaluate("dcc-mcp-autocad", "0.1.2", release="v0.1.2")
        self.assertEqual(finding.state, ccs.STATE_MISSING_ENTRY)
        self.assertTrue(finding.installable)
        self.assertFalse(finding.in_source)
        self.assertEqual(finding.github_release, "v0.1.2")

    def test_repository_without_a_pypi_release_is_ignored(self):
        # dcc-mcp-kicad is in development and has shipped nothing, so there is
        # nothing for a user to install and nothing to report.
        self.assertIsNone(self.evaluate("dcc-mcp-kicad", None))

    def test_in_catalog_repository_is_not_missing(self):
        published = snapshot(published_entry("dcc-mcp-maya", version="0.9.22", install={}))
        self.assertIsNone(self.evaluate("dcc-mcp-maya", "0.9.34", published=published))

    def test_infrastructure_repository_is_not_reported_as_an_adapter(self):
        self.assertIsNone(self.evaluate("dcc-mcp-runtime", "0.2.0"))


class CompareSourcePublishedTest(unittest.TestCase):
    def test_divergence_is_reported(self):
        source = snapshot(published_entry("dcc-mcp-kdenlive", version="0.1.0", install={"type": "pip"}))
        published = snapshot(
            published_entry(
                "dcc-mcp-kdenlive",
                version="0.1.0",
                policy={"installation": "not_available", "reason": "x"},
            )
        )
        findings = ccs.compare_source_published(source, published)
        self.assertEqual([f.name for f in findings], ["dcc-mcp-kdenlive"])
        self.assertEqual(findings[0].state, ccs.STATE_SOURCE_PUBLISHED_DIVERGENCE)

    def test_agreeing_catalogs_produce_no_findings(self):
        source = snapshot(published_entry("dcc-mcp-maya", version="0.9.22", install={"type": "pip"}))
        self.assertEqual(ccs.compare_source_published(source, source), [])

    def test_entry_missing_from_one_side_is_not_divergence(self):
        # Divergence is about the *same* entry changing installability. A new entry
        # is a different class of change and is reported by evaluate_missing.
        source = snapshot(published_entry("dcc-mcp-new", version="1.0.0", install={"type": "pip"}))
        published = snapshot()
        self.assertEqual(ccs.compare_source_published(source, published), [])


class RenderTextTest(unittest.TestCase):
    def test_reports_a_clean_catalog(self):
        report = {
            "findings": [],
            "counts": {},
            "published": {"entries": 41, "install_available": 33},
        }
        self.assertIn("OK", ccs.render_text(report))

    def test_renders_every_state_and_the_reason(self):
        report = {
            "findings": [
                {
                    "name": "dcc-mcp-kdenlive",
                    "state": ccs.STATE_QUARANTINED,
                    "message": "quarantined",
                    "reason": "Release validation failed",
                    "pypi_version": "0.1.2",
                    "catalog_version": "0.1.0",
                    "github_release": None,
                    "installable": False,
                    "in_source": True,
                    "in_published": True,
                }
            ],
            "counts": {ccs.STATE_QUARANTINED: 1},
            "published": {"entries": 41, "install_available": 33},
        }
        rendered = ccs.render_text(report)
        self.assertIn(ccs.STATE_QUARANTINED, rendered)
        self.assertIn("Release validation failed", rendered)


class MainTest(unittest.TestCase):
    """End-to-end exit codes, with every network call replaced.

    `organization_repositories` must be stubbed too. Without `--repositories` the
    sweep enumerates the org through `gh`, which needs a token a plain unittest
    run does not have -- and a test that silently depends on the developer's
    authenticated `gh` passes locally only to fail in CI.
    """

    def run_main(self, argv, entry_finding=None):
        source = snapshot(published_entry("dcc-mcp-maya", version="0.9.22", install={"type": "pip"}))
        finding = entry_finding or (lambda _n, _s, _p, _t: None)
        with mock.patch.object(ccs, "fetch_source_catalog", lambda *a, **k: source):
            with mock.patch.object(ccs, "fetch_published_catalog", lambda *a, **k: source):
                with mock.patch.object(ccs, "evaluate_entry", finding):
                    with mock.patch.object(ccs, "evaluate_missing", lambda *a, **k: None):
                        with mock.patch.object(ccs, "organization_repositories", lambda *a, **k: []):
                            return ccs.main(argv)

    def test_clean_run_exits_zero(self):
        self.assertEqual(self.run_main(["--format", "json"]), 0)

    def test_fail_open_is_the_default(self):
        # The check exists to be read, not to block. Drift must not fail a pipeline
        # that adopted it before the backlog was cleared.
        def finding(_n, _s, _p, _t):
            return ccs.Finding(name="x", state=ccs.STATE_STALE_PIN, message="m")

        self.assertEqual(self.run_main(["--format", "json"], finding), 0)

    def test_fail_on_any_reports_drift(self):
        def finding(_n, _s, _p, _t):
            return ccs.Finding(name="x", state=ccs.STATE_STALE_PIN, message="m")

        self.assertEqual(self.run_main(["--format", "json", "--fail-on", "any"], finding), 1)

    def test_fail_on_missing_entry_ignores_a_stale_pin(self):
        def finding(_n, _s, _p, _t):
            return ccs.Finding(name="x", state=ccs.STATE_STALE_PIN, message="m")

        self.assertEqual(
            self.run_main(["--format", "json", "--fail-on", "missing_entry"], finding), 0
        )

    def test_fail_on_missing_entry_catches_a_missing_entry(self):
        def finding(_n, _s, _p, _t):
            return ccs.Finding(name="x", state=ccs.STATE_MISSING_ENTRY, message="m")

        self.assertEqual(
            self.run_main(["--format", "json", "--fail-on", "missing_entry"], finding), 1
        )

    def test_unreachable_source_exits_two(self):
        def boom(*_args, **_kwargs):
            raise ccs.CheckError("boom")

        with mock.patch.object(ccs, "fetch_source_catalog", boom):
            self.assertEqual(ccs.main(["--format", "json"]), 2)

    def test_an_unexpected_failure_also_exits_two(self):
        # Exit 1 is reserved for "drift that --fail-on cares about". A crash must
        # keep its own code, or it turns into drift and -- the moment the workflow
        # honours exit 1 -- into a false red. A corrupt base64 payload raising
        # binascii.Error is exactly that case.
        import base64

        payload = {"encoding": "base64", "content": "not-valid-base64!!"}
        with mock.patch.object(ccs, "gh_json", lambda *a, **k: payload):
            self.assertEqual(ccs.main(["--format", "json"]), 2)

    def test_repository_override_skips_the_org_listing(self):
        # An explicit --repositories must never trigger an org-wide enumeration,
        # which is the expensive call in a nightly sweep.
        seen = []

        def listing(_owner, _timeout):
            seen.append("listed")
            return []

        source = snapshot(published_entry("dcc-mcp-maya", version="0.9.22", install={"type": "pip"}))
        with mock.patch.object(ccs, "fetch_source_catalog", lambda *a, **k: source):
            with mock.patch.object(ccs, "fetch_published_catalog", lambda *a, **k: source):
                with mock.patch.object(ccs, "evaluate_entry", lambda *a: None):
                    with mock.patch.object(ccs, "evaluate_missing", lambda *a, **k: None):
                        with mock.patch.object(ccs, "organization_repositories", listing):
                            ccs.main(["--format", "json", "--repositories", "dcc-mcp-maya"])
        self.assertEqual(seen, [])


class EnvelopeTest(unittest.TestCase):
    def test_unwraps_the_double_encoded_payload(self):
        # install-catalog.json is an envelope whose `catalog` member is a JSON
        # *string*, so the payload has to be decoded twice.
        import base64

        inner = json.dumps({"entries": [{"name": "dcc-mcp-maya", "version": "0.9.22", "install": {}}]})
        envelope = {"catalog": inner, "attestation": {"x": 1}}
        payload = {
            "encoding": "base64",
            "content": base64.b64encode(json.dumps(envelope).encode()).decode(),
        }
        with mock.patch.object(ccs, "gh_json", lambda *a, **k: payload):
            parsed = ccs.fetch_published_catalog("o/r", "install-catalog", "install-catalog.json", 1.0)
        self.assertEqual(parsed.names(), {"dcc-mcp-maya"})

    def test_rejects_a_payload_without_entries(self):
        import base64

        payload = {"encoding": "base64", "content": base64.b64encode(b'{"catalog": "{}"}').decode()}
        with mock.patch.object(ccs, "gh_json", lambda *a, **k: payload):
            with self.assertRaises(ccs.CheckError):
                ccs.fetch_published_catalog("o/r", "install-catalog", "install-catalog.json", 1.0)


class SourceCatalogRefTest(unittest.TestCase):
    """`--catalog-ref` must reach `gh api` as one endpoint, not a second argument.

    `gh api` accepts exactly one endpoint, so a `?ref=...` appended as its own
    argv element is rejected outright and the check dies before it reads anything.
    This path is unexercised by the nightly sweep, which passes no ref at all.
    """

    def gh_args_for(self, ref):
        import base64

        seen = []
        payload = {
            "encoding": "base64",
            "content": base64.b64encode(b'entries:\n  - name: "dcc-mcp-maya"\n').decode(),
        }

        def fake(args, _timeout, _what):
            seen.append(args)
            return payload

        with mock.patch.object(ccs, "gh_json", fake):
            ccs.fetch_source_catalog("o/r", "dcc-mcp-catalog.yml", 1.0, ref)
        return seen[0]

    def test_a_ref_is_inlined_into_the_endpoint(self):
        self.assertEqual(
            self.gh_args_for("main"),
            ["api", "repos/o/r/contents/dcc-mcp-catalog.yml?ref=main"],
        )

    def test_an_empty_ref_leaves_the_endpoint_bare(self):
        self.assertEqual(
            self.gh_args_for(""),
            ["api", "repos/o/r/contents/dcc-mcp-catalog.yml"],
        )

    def test_every_argument_stays_a_single_element(self):
        # The regression itself: a stray element is what makes `gh api` fail with
        # "accepts 1 arg(s), received 2".
        self.assertEqual(len(self.gh_args_for("some/branch")), 2)


if __name__ == "__main__":
    unittest.main()
