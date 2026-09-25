"""Guard the invariant the release-integrity gate depends on.

`release-integrity.yml` declares the repository manifest twice, once under
`workflow_call` and once under `workflow_dispatch`, because GitHub Actions has no way to
share a default between the two entry points. The nightly schedule reaches the workflow
through `uses:`, so it only ever reads the `workflow_call` copy. A half-applied manifest
edit would therefore leave the nightly gate checking an outdated list while looking
green, which is exactly the silent failure the gate exists to catch.

These tests run under plain `unittest` with no third-party dependencies, matching the
runner used by `.github/workflows/profile-contract.yml`. They read the workflow as text
rather than parsing it with a YAML library.

Not asserted on purpose: the exact repository or package count. That number changes
whenever a repository starts or stops publishing, and pinning it here would turn a
legitimate manifest edit into a red build.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_release_integrity as cri  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "release-integrity.yml"
NIGHTLY = ROOT / ".github" / "workflows" / "release-integrity-nightly.yml"

INPUT_KEY = "      repositories:"
# `>-` is a folded block scalar: newlines collapse to single spaces and the trailing
# newline is stripped. Any other indicator would change how the manifest is read.
DEFAULT_MARKER = "        default: >-"
VALUE_INDENT = " " * 10


def folded_repository_defaults(text: str) -> list[str]:
    """Return the folded value of every `repositories` input default in ``text``."""
    lines = text.splitlines()
    values: list[str] = []
    for index, line in enumerate(lines):
        if line != INPUT_KEY:
            continue
        marker = next(
            (i for i in range(index + 1, len(lines)) if lines[i] == DEFAULT_MARKER),
            None,
        )
        if marker is None:
            continue
        folded: list[str] = []
        for candidate in lines[marker + 1 :]:
            if not candidate.startswith(VALUE_INDENT):
                break
            folded.append(candidate.strip())
        values.append(" ".join(folded))
    return values


def load_manifest(text: str) -> list[dict]:
    """Parse one folded default into the manifest the checker expects."""
    return json.loads(text)


class RepositoryManifestTests(unittest.TestCase):
    def setUp(self):
        self.workflow_text = WORKFLOW.read_text(encoding="utf-8")
        self.defaults = folded_repository_defaults(self.workflow_text)

    def test_both_entry_points_declare_a_default(self):
        self.assertEqual(
            2,
            len(self.defaults),
            "expected one `repositories` default for workflow_call and one for "
            "workflow_dispatch; the two entry points must not drift apart",
        )

    def test_the_two_defaults_are_identical(self):
        self.assertEqual(
            self.defaults[0],
            self.defaults[1],
            "the workflow_call and workflow_dispatch repository defaults differ; the "
            "nightly gate only reads the workflow_call one",
        )

    def test_every_default_is_valid_manifest_json(self):
        for index, default in enumerate(self.defaults):
            with self.subTest(default=index):
                manifest = load_manifest(default)
                self.assertIsInstance(manifest, list)
                self.assertTrue(manifest, "the manifest must not be empty")
                for entry in manifest:
                    self.assertIsInstance(entry, dict)
                    self.assertTrue(entry["repository"].startswith("dcc-mcp/"))
                    self.assertTrue(entry["packages"], f"{entry['repository']} has no packages")

    def test_repositories_and_packages_are_unique(self):
        manifest = load_manifest(self.defaults[0])
        repositories = [entry["repository"] for entry in manifest]
        packages = [package for entry in manifest for package in entry["packages"]]
        self.assertEqual(len(repositories), len(set(repositories)), "duplicate repository")
        self.assertEqual(len(packages), len(set(packages)), "duplicate package")

    def test_the_checker_accepts_the_folded_default(self):
        targets = cri.parse_manifest(self.defaults[0])
        self.assertTrue(targets)
        self.assertEqual(
            len(load_manifest(self.defaults[0])),
            len({target.repository for target in targets}),
            "the checker read a different number of repositories than the manifest holds",
        )

    def test_nightly_does_not_override_the_manifest(self):
        nightly_text = NIGHTLY.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"^\s{4}with:\s*$", nightly_text, re.MULTILINE),
            "release-integrity-nightly.yml now passes inputs, so it no longer inherits "
            "the built-in manifest",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
