"""Unit tests for scripts/check_release_integrity.py (no network access)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_integrity as cri  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test accidentally reaches the network."""

    def _boom(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("tests must not perform network calls")

    monkeypatch.setattr(cri, "pypi_version", _boom)
    monkeypatch.setattr(cri, "latest_release", _boom)


# ----------------------------------------------------------------------------------
# version helpers
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("v0.3.7", "0.3.7"), ("0.3.7", "0.3.7"), ("V1.2.3", "1.2.3"), (" v2.0.0 ", "2.0.0")],
)
def test_normalize_tag(tag, expected):
    assert cri.normalize_tag(tag) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("0.3.7", "0.3.7", 0),
        ("0.3.7", "0.3.1", 1),
        ("0.3.1", "0.3.7", -1),
        ("0.10.0", "0.9.31", 1),
        ("1.0.0", "1.0.0rc1", 0),
        ("1.0.1", "1.0.0", 1),
    ],
)
def test_compare_versions(left, right, expected):
    assert cri.compare_versions(cri.parse_version(left), cri.parse_version(right)) == expected


# ----------------------------------------------------------------------------------
# manifest parsing
# ----------------------------------------------------------------------------------


def test_parse_manifest_expands_packages():
    manifest = json.dumps(
        [
            {"repository": "dcc-mcp/dcc-mcp-unreal", "packages": ["dcc-mcp-unreal"]},
            {
                "repository": "dcc-mcp/dcc-mcp-core",
                "packages": ["dcc-mcp-core", "dcc-mcp-server", "dcc-mcp-core-semantic"],
            },
        ]
    )
    targets = cri.parse_manifest(manifest)
    assert [(t.repository, t.package) for t in targets] == [
        ("dcc-mcp/dcc-mcp-unreal", "dcc-mcp-unreal"),
        ("dcc-mcp/dcc-mcp-core", "dcc-mcp-core"),
        ("dcc-mcp/dcc-mcp-core", "dcc-mcp-server"),
        ("dcc-mcp/dcc-mcp-core", "dcc-mcp-core-semantic"),
    ]


def test_parse_manifest_accepts_object_and_files(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"repositories": [{"repository": "o/r", "packages": ["pkg"]}]}))
    assert cri.parse_manifest(str(path)) == [cri.Target("o/r", "pkg")]


def test_parse_manifest_defaults_package_to_repository_name():
    assert cri.parse_manifest(json.dumps([{"repository": "o/r"}])) == [cri.Target("o/r", "r")]


def test_parse_manifest_rejects_garbage():
    with pytest.raises(cri.CheckError):
        cri.parse_manifest("{not json")
    with pytest.raises(cri.CheckError):
        cri.parse_manifest("   ")
    with pytest.raises(cri.CheckError):
        cri.parse_manifest(json.dumps([{"packages": ["pkg"]}]))
    with pytest.raises(cri.CheckError):
        cri.parse_manifest(json.dumps([{"repository": "o/r", "packages": []}]))
    with pytest.raises(cri.CheckError):
        cri.parse_manifest(json.dumps([42]))


def test_matrix_payload_shape():
    payload = cri.matrix_payload([cri.Target("o/r", "pkg")])
    assert payload["include"][0] == {"repository": "o/r", "package": "pkg", "key": "o/r:pkg"}


# ----------------------------------------------------------------------------------
# evaluation
# ----------------------------------------------------------------------------------


def _release(tag: str, minutes_ago: float) -> dict:
    """A release published ``minutes_ago`` before the frozen NOW constant."""
    published = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return {"tagName": tag, "publishedAt": published}


def _release_now(tag: str, minutes_ago: float) -> dict:
    """A release published ``minutes_ago`` before the real clock, for CLI tests."""
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"tagName": tag, "publishedAt": stamp.isoformat().replace("+00:00", "Z")}


def _evaluate(monkeypatch, tag, minutes_ago, pypi, grace=30.0):
    monkeypatch.setattr(cri, "latest_release", lambda _repo: _release(tag, minutes_ago))
    monkeypatch.setattr(cri, "pypi_version", lambda _pkg: pypi)
    return cri.evaluate(cri.Target("o/r", "pkg"), grace_minutes=grace, now=NOW)


def test_matching_versions_pass(monkeypatch):
    result = _evaluate(monkeypatch, "v0.3.7", 600, "0.3.7")
    assert result.status == cri.STATUS_OK
    assert result.pypi_version == "0.3.7"


def test_stale_pypi_fails(monkeypatch):
    result = _evaluate(monkeypatch, "v0.3.7", 600, "0.3.1")
    assert result.status == cri.STATUS_FAIL
    assert "0.3.1" in result.message


def test_grace_period_tolerates_a_missing_upload(monkeypatch):
    result = _evaluate(monkeypatch, "v0.3.7", 5, "0.3.1")
    assert result.status == cri.STATUS_WARN
    assert "grace" in result.message


def test_grace_period_expires(monkeypatch):
    assert _evaluate(monkeypatch, "v0.3.7", 31, "0.3.1").status == cri.STATUS_FAIL


def test_grace_period_ignores_unparseable_timestamp(monkeypatch):
    monkeypatch.setattr(cri, "latest_release", lambda _r: {"tagName": "v0.3.7", "publishedAt": "nope"})
    monkeypatch.setattr(cri, "pypi_version", lambda _p: "0.3.1")
    assert cri.evaluate(cri.Target("o/r", "pkg"), grace_minutes=30, now=NOW).status == cri.STATUS_FAIL


def test_missing_package_fails_after_grace(monkeypatch):
    assert _evaluate(monkeypatch, "v0.3.7", 600, None).status == cri.STATUS_FAIL
    assert _evaluate(monkeypatch, "v0.3.7", 5, None).status == cri.STATUS_WARN


def test_prerelease_ahead_of_stable_warns(monkeypatch):
    result = _evaluate(monkeypatch, "v0.20.34", 600, "0.21.0rc1")
    assert result.status == cri.STATUS_WARN
    assert "ahead" in result.message


def test_no_release_skips(monkeypatch):
    monkeypatch.setattr(cri, "latest_release", lambda _r: None)
    monkeypatch.setattr(cri, "pypi_version", lambda _p: "0.3.7")
    result = cri.evaluate(cri.Target("o/r", "pkg"), grace_minutes=30, now=NOW)
    assert result.status == cri.STATUS_SKIP


def test_semver_ordering_is_numeric(monkeypatch):
    """0.10.0 must sort above 0.9.31, which a plain string compare would get wrong."""
    result = _evaluate(monkeypatch, "v0.9.31", 600, "0.10.0")
    assert result.status == cri.STATUS_WARN


# ----------------------------------------------------------------------------------
# CLI behaviour
# ----------------------------------------------------------------------------------


def test_cli_emits_matrix(capsys):
    manifest = json.dumps([{"repository": "o/r", "packages": ["pkg"]}])
    assert cri.main(["--manifest", manifest, "--emit-matrix"]) == 0
    assert json.loads(capsys.readouterr().out)["include"][0]["key"] == "o/r:pkg"


def test_cli_reports_failure_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cri, "latest_release", lambda _r: _release_now("v0.3.7", 600))
    monkeypatch.setattr(cri, "pypi_version", lambda _p: "0.3.1")
    assert cri.main(["--repository", "o/r", "--package", "pkg", "--json"]) == 1
    out = capsys.readouterr().out
    # workflow annotations are printed before the JSON payload
    payload = json.loads(out[out.index("["):])
    assert payload[0]["status"] == cri.STATUS_FAIL
    assert "::error" in out


def test_cli_strict_fails_on_warnings(monkeypatch):
    monkeypatch.setattr(cri, "latest_release", lambda _r: _release_now("v0.3.7", 5))
    monkeypatch.setattr(cri, "pypi_version", lambda _p: "0.3.1")
    assert cri.main(["--repository", "o/r", "--package", "pkg"]) == 0
    assert cri.main(["--repository", "o/r", "--package", "pkg", "--strict"]) == 1


def test_cli_requires_package_pair():
    assert cri.main(["--repository", "o/r"]) == 2


def test_cli_reports_unusable_input(capsys):
    assert cri.main([]) == 2
    assert "error" in capsys.readouterr().err


def test_render_table_marks_statuses():
    table = cri.render_table(
        [
            cri.Result("o/r", "pkg", cri.STATUS_OK, "fine", "v1.0.0", None, "1.0.0"),
            cri.Result("o/r", "pkg2", cri.STATUS_FAIL, "bad", "v1.0.0", None, "0.9.0"),
        ]
    )
    assert "| PASS | `o/r` |" in table
    assert "| FAIL | `o/r` |" in table
