"""Tests for scripts/check_repo_contract.py.

The tests drive the real CLI entry point against throwaway fixture repositories so
that exit codes, severity resolution, and the emitted findings are all covered.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_repo_contract import (  # noqa: E402
    ADAPTER_CONTRACT_PATH,
    DEFAULT_CONTRACT_PATH,
    RULES,
    Contract,
    main,
    parse_vx_toml,
)

CONTRACT = str(DEFAULT_CONTRACT_PATH)
ADAPTER_CONTRACT = str(ADAPTER_CONTRACT_PATH)
ALL_CONTRACTS = (CONTRACT, ADAPTER_CONTRACT)


def run_cli(root: Path, *args: str, contract: str = CONTRACT) -> tuple[int, list[dict]]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--root", str(root), "--contract", contract, "--format", "json", *args])
    payload = stdout.getvalue().strip()
    return code, (json.loads(payload) if payload else [])


class FixtureRepo:
    """A throwaway repository root."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def write(self, relative: str, content: str = "x\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def mkdir(self, relative: str) -> Path:
        path = self.root / relative
        path.mkdir(parents=True, exist_ok=True)
        return path

    def symlink(self, relative: str, target: str) -> bool:
        """Create a symlink, returning False when the platform refuses."""
        try:
            (self.root / relative).symlink_to(target)
        except (OSError, NotImplementedError):
            return False
        return True

    def clean(self, **kwargs) -> None:
        """Write the smallest set of files that passes the baseline profile."""
        self.write("AGENTS.md", "# AGENTS\n")
        self.write("README.md", "# repo\n")
        self.write(".gitignore", "target/\n")
        self.write("justfile", "default:\n    @echo ok\n")

    def cleanup(self) -> None:
        self._dir.cleanup()


class ContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def ids(self, findings: list[dict]) -> set[str]:
        return {item["rule_id"] for item in findings}

    def severities(self, findings: list[dict], rule_id: str) -> set[str]:
        return {item["severity"] for item in findings if item["rule_id"] == rule_id}


class TestContractFile(ContractTestCase):
    def test_every_rule_has_an_implementation(self) -> None:
        for path in ALL_CONTRACTS:
            with self.subTest(contract=path):
                contract = Contract.load(Path(path))
                self.assertEqual(set(contract.rules) - set(RULES), set())

    def test_every_implementation_is_declared_by_a_contract(self) -> None:
        declared: set[str] = set()
        for path in ALL_CONTRACTS:
            declared |= set(Contract.load(Path(path)).rules)
        self.assertEqual(set(RULES) - declared, set())

    def test_the_two_contracts_do_not_share_rule_ids(self) -> None:
        repo_rules = set(Contract.load(Path(CONTRACT)).rules)
        adapter_rules = set(Contract.load(Path(ADAPTER_CONTRACT)).rules)
        self.assertEqual(repo_rules & adapter_rules, set())
        self.assertTrue(repo_rules)
        self.assertTrue(adapter_rules)

    def test_every_rule_ids_are_unique_and_ordered(self) -> None:
        for path in ALL_CONTRACTS:
            with self.subTest(contract=path):
                contract = Contract.load(Path(path))
                ids = [rule["id"] for rule in contract.data["rules"]]
                self.assertEqual(len(ids), len(set(ids)))

    def test_severities_are_normalised(self) -> None:
        for path in ALL_CONTRACTS:
            with self.subTest(contract=path):
                contract = Contract.load(Path(path))
                for rule_id, rule in contract.rules.items():
                    self.assertIn(rule["severity"], {"error", "warning", "notice"}, rule_id)

    def test_adapter_contract_baseline_is_enforceable_immediately(self) -> None:
        """The two baseline rules need no Core floor bump to satisfy."""
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        baseline = {
            rule_id for rule_id, rule in contract.rules.items() if "baseline" in rule["profiles"]
        }
        self.assertEqual(baseline, {"A001", "A003"})
        self.assertEqual(contract.rules["A001"]["severity"], "error")
        self.assertEqual(contract.rules["A003"]["severity"], "error")

    def test_line_length_rule_is_a_strict_warning(self) -> None:
        contract = Contract.load(Path(ADAPTER_CONTRACT))
        self.assertEqual(contract.rules["A004"]["severity"], "warning")
        self.assertEqual(contract.rules["A004"]["profiles"], ["strict"])
        self.assertEqual(contract.value("ruff_line_length_target"), 120)

    def test_emit_contract_round_trips(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["--contract", CONTRACT, "--emit-contract"]), 0)
        self.assertEqual(json.loads(stdout.getvalue()), json.loads(Path(CONTRACT).read_text(encoding="utf-8")))

    def test_comma_separated_rule_ids_are_accepted(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nnode = "latest"\n')
        _, findings = run_cli(
            self.repo.root, "--profile", "strict", "--rule", "R009,R010", "--error-rule", "R009"
        )
        self.assertIn("R009", self.ids(findings))

    def test_bad_contract_path_exits_two(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["--contract", "does-not-exist.json", "--list-rules"]), 2)

    def test_unknown_rule_id_exits_two(self) -> None:
        self.repo.clean()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["--root", str(self.repo.root), "--contract", CONTRACT, "--rule", "R999"]), 2)

    def test_missing_root_exits_two(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["--root", str(self.repo.root / "nope"), "--contract", CONTRACT])
        self.assertEqual(code, 2)


class TestVxTomlParser(unittest.TestCase):
    def test_reads_tables_comments_and_scalars(self) -> None:
        parsed, unparsed = parse_vx_toml(
            "\n".join(
                [
                    "# leading comment",
                    "[tools]",
                    'just = "latest"   # trailing comment',
                    "node = 22",
                    "python = 3.11",
                    "",
                    "[settings]",
                    "auto_install = true",
                ]
            )
        )
        self.assertEqual(unparsed, [])
        self.assertEqual(parsed["tools"]["just"], "latest")
        self.assertEqual(parsed["tools"]["node"], "22")
        self.assertEqual(parsed["tools"]["python"], "3.11")
        self.assertIs(parsed["settings"]["auto_install"], True)

    def test_keeps_unquoted_versions_as_written(self) -> None:
        parsed, _ = parse_vx_toml("[tools]\nrust = 1.90.0\n")
        self.assertEqual(parsed["tools"]["rust"], "1.90.0")

    def test_dotted_sub_table_is_its_own_key(self) -> None:
        parsed, _ = parse_vx_toml('[tools.pwsh]\nversion = "7.4.13"\n')
        self.assertEqual(parsed["tools.pwsh"]["version"], "7.4.13")

    def test_reports_unparseable_lines(self) -> None:
        _, unparsed = parse_vx_toml("[tools]\nthis is not toml\n")
        self.assertEqual(len(unparsed), 1)
        self.assertEqual(unparsed[0][0], 2)

    def test_multi_line_string_is_one_value(self) -> None:
        parsed, unparsed = parse_vx_toml(
            "\n".join(
                [
                    "[scripts]",
                    "build = '''",
                    "python packaging/build.py --mode native",
                    "'''",
                    'other = "x"',
                ]
            )
        )
        self.assertEqual(unparsed, [])
        self.assertIn("packaging/build.py", parsed["scripts"]["build"])
        self.assertEqual(parsed["scripts"]["other"], "x")

    def test_escaped_quotes_inside_a_string(self) -> None:
        parsed, unparsed = parse_vx_toml(
            '[env]\nUE_5_ROOT = "C:\\\\Program Files\\\\Epic Games\\\\UE_5.7"\n'
        )
        self.assertEqual(unparsed, [])
        self.assertIn("Epic Games", parsed["env"]["UE_5_ROOT"])

    def test_project_table_is_known(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[project]\nname = "demo"\n\n[tools]\nnode = "22"\n')
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_inline_table_reduces_to_its_version(self) -> None:
        parsed, unparsed = parse_vx_toml(
            '[tools]\nrcedit = { version = "latest", os = ["windows"] }\n'
            'msvc = { version = "14.42", os = ["windows"] }\n'
        )
        self.assertEqual(unparsed, [])
        self.assertEqual(parsed["tools"]["rcedit"], "latest")
        self.assertEqual(parsed["tools"]["msvc"], "14.42")

    def test_inline_table_without_a_version_is_left_alone(self) -> None:
        parsed, _ = parse_vx_toml('[tools]\nfoo = { os = ["windows"] }\n')
        self.assertTrue(parsed["tools"]["foo"].startswith("{"))

    def test_project_table_is_known(self) -> None:
        parsed, _ = parse_vx_toml('[project]\nname = "demo"\n\n[tools]\nnode = "22"\n')
        self.assertEqual(parsed["project"]["name"], "demo")
        self.assertEqual(parsed["tools"]["node"], "22")

    def test_ignores_array_of_tables_headers(self) -> None:
        # Not supported, but it must not be reported as a value line either.
        _, unparsed = parse_vx_toml("[[bin]]\nname = \"vx\"\n")
        self.assertEqual([line for _, line in unparsed], ["[[bin]]"])


class TestProfiles(ContractTestCase):
    def test_baseline_only_runs_the_first_five_rules(self) -> None:
        self.repo.clean()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["--root", str(self.repo.root), "--contract", CONTRACT, "--profile", "baseline", "--list-rules"]), 0)
        self.assertEqual(
            set(line.split()[0] for line in stdout.getvalue().strip().splitlines()),
            {"R001", "R002", "R003", "R004", "R005"},
        )

    def test_strict_runs_every_rule(self) -> None:
        self.repo.clean()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main(["--root", str(self.repo.root), "--contract", CONTRACT, "--profile", "strict", "--list-rules"])
        self.assertEqual(
            len(stdout.getvalue().strip().splitlines()),
            len(Contract.load(Path(CONTRACT)).rules),
        )

    def test_clean_fixture_passes_strict_with_zero_findings(self) -> None:
        self.repo.clean()
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0, findings)
        self.assertEqual(findings, [], findings)

    def test_error_rule_promotes_a_warning(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nnode = "latest"\n')
        _, baseline = run_cli(self.repo.root, "--profile", "strict", "--rule", "R009")
        self.assertEqual(self.severities(baseline, "R009"), {"warning"})
        code, promoted = run_cli(
            self.repo.root, "--profile", "strict", "--rule", "R009", "--error-rule", "R009"
        )
        self.assertEqual(self.severities(promoted, "R009"), {"error"})
        self.assertEqual(code, 1)

    def test_fail_on_warning_turns_warnings_green_to_red(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nnode = "latest"\n')
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict", "--rule", "R009")[0], 0)
        code, _ = run_cli(
            self.repo.root, "--profile", "strict", "--rule", "R009", "--fail-on", "warning"
        )
        self.assertEqual(code, 1)

    def test_fail_on_none_never_fails(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        self.assertEqual(run_cli(self.repo.root, "--fail-on", "none")[0], 0)

    def test_skip_rule_removes_a_finding(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        self.assertEqual(run_cli(self.repo.root)[0], 1)
        self.assertEqual(run_cli(self.repo.root, "--skip-rule", "R001")[0], 0)


class TestR001Artifacts(ContractTestCase):
    def test_flags_known_artifacts(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        self.repo.write("audit-result.json", "{}")
        self.repo.write("clippy_check.txt", "")
        self.repo.write("module.rcgu.o", "")
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 1)
        self.assertIn("R001", self.ids(findings))
        self.assertEqual(len(findings), 4)

    def test_ignores_artifacts_below_the_root(self) -> None:
        self.repo.clean()
        self.repo.write("target/module.o", "")
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_coveragerc_is_configuration_not_an_artifact(self) -> None:
        self.repo.clean()
        self.repo.write(".coveragerc", "[run]\n")
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_message_names_the_gitignore_fix(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        _, findings = run_cli(self.repo.root, "--format", "json")
        self.assertIn(".gitignore", findings[0]["message"])


class TestR002JustfileCase(ContractTestCase):
    def test_capital_justfile_is_an_error(self) -> None:
        self.repo.clean()
        (self.repo.root / "justfile").unlink()
        self.repo.write("Justfile", "default:\n")
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 1)
        self.assertIn("R002", self.ids(findings))

    def test_lowercase_justfile_passes(self) -> None:
        self.repo.clean()
        self.assertNotIn("R002", self.ids(run_cli(self.repo.root)[1]))

    def test_dot_justfile_passes(self) -> None:
        self.repo.clean()
        (self.repo.root / "justfile").unlink()
        self.repo.write(".justfile", "default:\n")
        self.assertEqual(run_cli(self.repo.root)[0], 0)


class TestR003AgentsMd(ContractTestCase):
    def test_missing_agents_md_fails(self) -> None:
        self.repo.clean()
        (self.repo.root / "AGENTS.md").unlink()
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 1)
        self.assertIn("R003", self.ids(findings))


class TestR004VxToml(ContractTestCase):
    def test_unparseable_line_is_an_error(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", "[tools]\nthis is not toml\n")
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 1)
        self.assertEqual(self.severities(findings, "R004"), {"error"})

    def test_unknown_table_is_a_warning(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", "[nonsense]\nfoo = \"bar\"\n")
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 0)
        self.assertEqual(self.severities(findings, "R004"), {"warning"})

    def test_sub_table_of_a_known_table_is_accepted(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nnode = "22"\n\n[tools.pwsh]\nversion = "7.4.13"\n')
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_repository_without_vx_toml_passes(self) -> None:
        self.repo.clean()
        self.assertEqual(run_cli(self.repo.root)[0], 0)


class TestR005ToolPins(ContractTestCase):
    def test_accepts_numeric_channels_and_latest(self) -> None:
        self.repo.clean()
        self.repo.write(
            "vx.toml",
            '[tools]\nrust = "1.95"\npython = 3.12\nnode = "22"\njust = "latest"\nfoo = "stable"\n',
        )
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_rejects_a_bare_channel_name(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nrust = "nightly-2026-01-01"\n')
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 1)
        self.assertIn("R005", self.ids(findings))

    def test_unquoted_versions_are_read_as_written(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", "[tools]\npython = 3.11\n")
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_accepts_a_delegation_sentinel_on_its_own_tool(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nrust = "rustup-managed"\n')
        self.assertEqual(run_cli(self.repo.root)[0], 0)

    def test_sentinel_is_not_accepted_on_another_tool(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\npython = "rustup-managed"\n')
        code, findings = run_cli(self.repo.root)
        self.assertEqual(code, 1)
        self.assertIn("R005", self.ids(findings))


class TestR006RootAllowlist(ContractTestCase):
    def test_unknown_top_level_file_warns(self) -> None:
        self.repo.clean()
        self.repo.write("scratch-notes.md", "hello\n")
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0)
        self.assertEqual(self.severities(findings, "R006"), {"warning"})

    def test_stray_report_is_an_error_even_in_the_soft_rule(self) -> None:
        self.repo.clean()
        self.repo.write("MIGRATION_SUMMARY.md", "# summary\n")
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 1)
        self.assertEqual(self.severities(findings, "R006"), {"error"})

    def test_stray_root_python_script_is_an_error(self) -> None:
        self.repo.clean()
        self.repo.write("bootstrap_maya.py", "print('hi')\n")
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 1)
        self.assertEqual(findings[0]["path"], "bootstrap_maya.py")

    def test_build_config_python_files_are_allowed(self) -> None:
        self.repo.clean()
        self.repo.write("noxfile.py", "import nox\n")
        self.repo.write("setup.py", "from setuptools import setup\n")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)

    def test_deprecated_entry_warns_with_a_migration_hint(self) -> None:
        self.repo.clean()
        self.repo.write(".travis.yml", "language: python\n")
        _, findings = run_cli(self.repo.root, "--profile", "strict")
        r006 = [item for item in findings if item["rule_id"] == "R006"]
        self.assertEqual(self.severities(r006, "R006"), {"warning"})
        self.assertIn("deprecated", r006[0]["message"])

    def test_allow_extra_silences_a_known_exception(self) -> None:
        self.repo.clean()
        self.repo.write("brand", "")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)
        self.repo.write("scratch-notes.md", "hello\n")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)
        self.assertEqual(
            run_cli(self.repo.root, "--profile", "strict", "--allow-extra", "scratch-notes.md")[0],
            0,
        )

    def test_git_directory_is_never_reported(self) -> None:
        self.repo.clean()
        self.repo.mkdir(".git")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)


class TestR007ScriptsVsJustfile(ContractTestCase):
    def test_scripts_next_to_a_justfile_warns_per_entry(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[scripts]\nci = "just ci"\ntest = "just test"\n')
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0)
        r007 = [item for item in findings if item["rule_id"] == "R007"]
        self.assertEqual(len(r007), 2)

    def test_scripts_without_a_justfile_are_allowed(self) -> None:
        self.repo.clean()
        (self.repo.root / "justfile").unlink()
        self.repo.write("vx.toml", '[scripts]\ncheck = "prek run --all-files"\n')
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)

    def test_empty_scripts_table_is_not_reported(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", "[scripts]\n")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)


class TestR008AgentsDerived(ContractTestCase):
    def test_hand_maintained_copy_warns(self) -> None:
        self.repo.clean()
        self.repo.write("CLAUDE.md", "# hand written\n")
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0)
        self.assertEqual(self.severities(findings, "R008"), {"warning"})

    def test_symlink_to_agents_md_passes(self) -> None:
        self.repo.clean()
        if not self.repo.symlink("CLAUDE.md", "AGENTS.md"):
            self.skipTest("symlinks are not permitted on this platform")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)

    def test_symlink_to_somewhere_else_warns(self) -> None:
        self.repo.clean()
        self.repo.write("OTHER.md", "# other\n")
        if not self.repo.symlink("CLAUDE.md", "OTHER.md"):
            self.skipTest("symlinks are not permitted on this platform")
        _, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertIn("R008", self.ids(findings))

    def test_generated_file_with_provenance_marker_passes(self) -> None:
        self.repo.clean()
        self.repo.write(
            "CLAUDE.md",
            "<!-- generated from AGENTS.md by `vx ai setup`; do not edit -->\n# CLAUDE\n",
        )
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)

    def test_committed_ide_directory_warns(self) -> None:
        self.repo.clean()
        self.repo.mkdir(".claude")
        _, findings = run_cli(self.repo.root, "--profile", "strict")
        r008 = [item for item in findings if item["rule_id"] == "R008"]
        self.assertTrue(r008)
        self.assertIn(".claude", r008[0]["path"])


class TestR009LatestPins(ContractTestCase):
    def test_latest_on_a_build_toolchain_warns(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\nnode = "latest"\ncmake = "latest"\n')
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0)
        r009 = [item for item in findings if item["rule_id"] == "R009"]
        self.assertEqual({item["message"].split()[1] for item in r009}, {"node", "cmake"})

    def test_latest_is_tolerated_on_the_allowlist(self) -> None:
        self.repo.clean()
        self.repo.write("vx.toml", '[tools]\njust = "latest"\nuv = "latest"\nmaturin = "latest"\n')
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)


class TestR010LlmsTxt(ContractTestCase):
    def test_generator_without_llms_txt_warns(self) -> None:
        self.repo.clean()
        self.repo.write("scripts/generate_llms_txt.py", "print('gen')\n")
        code, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertEqual(code, 0)
        self.assertIn("R010", self.ids(findings))

    def test_generator_with_llms_txt_passes(self) -> None:
        self.repo.clean()
        self.repo.write("scripts/generate_llms_txt.py", "print('gen')\n")
        self.repo.write("llms.txt", "# repo\n")
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)

    def test_no_generator_needs_no_llms_txt(self) -> None:
        self.repo.clean()
        self.assertEqual(run_cli(self.repo.root, "--profile", "strict")[0], 0)

    def test_justfile_recipe_counts_as_a_generator(self) -> None:
        self.repo.clean()
        self.repo.write("justfile", "default:\n    @echo ok\n\nllms-txt:\n    python scripts/gen.py\n")
        _, findings = run_cli(self.repo.root, "--profile", "strict")
        self.assertIn("R010", self.ids(findings))


class TestAnnotationOutput(ContractTestCase):
    def test_github_format_marks_the_file_and_rule(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            main(["--root", str(self.repo.root), "--contract", CONTRACT, "--format", "github"])
        output = stderr.getvalue()
        self.assertIn("::error file=coverage.json,title=Repo contract R001::", output)
        self.assertIn("R001 no-root-artifacts", output)

    def test_text_format_is_human_readable(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main(["--root", str(self.repo.root), "--contract", CONTRACT, "--format", "text"])
        self.assertIn("[ERROR  ] R001 no-root-artifacts (coverage.json)", stdout.getvalue())

    def test_findings_are_sorted_errors_first(self) -> None:
        self.repo.clean()
        self.repo.write("coverage.json", "{}")
        self.repo.write("scratch-notes.md", "x\n")
        _, findings = run_cli(self.repo.root, "--profile", "strict")
        severities = [item["severity"] for item in findings]
        self.assertEqual(severities, sorted(severities, key=lambda s: s != "error"))


class AdapterContractTestCase(ContractTestCase):
    """Shared fixtures for the A0xx adapter contract."""

    def adapter_clean(self, **ruff: str) -> None:
        """A minimal Python adapter package that satisfies the strict profile."""
        self.repo.clean()
        body = "".join(f"{key} = {value}\n" for key, value in ruff.items())
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'requires-python = ">=3.9"\n'
            'dependencies = ["dcc-mcp-core>=0.20.40,<1.0.0"]\n'
            "\n[tool.ruff]\n"
            f"line-length = {ruff.get('line-length', 120)}\n"
            f"{body}",
        )
        self.repo.write("src/dcc_mcp_demo/__init__.py", "")
        self.repo.write(".pre-commit-config.yaml", "repos: []\n")

    def findings_for(self, rule_id: str, findings: list[dict]) -> list[dict]:
        return [item for item in findings if item["rule_id"] == rule_id]


class TestA001DeprecatedAlias(AdapterContractTestCase):
    def test_clean_adapter_passes_baseline(self) -> None:
        self.adapter_clean()
        code, findings = run_cli(
            self.repo.root, "--profile", "baseline", contract=ADAPTER_CONTRACT
        )
        self.assertEqual(code, 0, findings)

    def test_import_from_the_provider_is_an_error(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            "from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_VERSION\n",
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 1)
        self.assertEqual(self.severities(findings, "A001"), {"error"})
        self.assertEqual(findings[0]["path"], "src/dcc_mcp_demo/install.py")

    def test_guarded_import_and_its_fallback_are_both_reported(self) -> None:
        """The fallback exists only to support the import; both must go."""
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            "try:\n"
            "    from dcc_mcp_core.deployment import (\n"
            "        INSTALL_EXIT_OK,\n"
            "        INSTALL_SOP_SCHEMA_VERSION,\n"
            "    )\n"
            "except ImportError:\n"
            "    INSTALL_EXIT_OK = 0\n"
            "    INSTALL_SOP_SCHEMA_VERSION = 1\n",
        )
        _, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        hits = self.findings_for("A001", findings)
        self.assertEqual(len(hits), 1)
        self.assertIn("L2", hits[0]["message"])
        self.assertIn("L8", hits[0]["message"])

    def test_module_qualified_attribute_access_is_reported(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            "import dcc_mcp_core.deployment as deployment\n"
            "REVISION = deployment.INSTALL_SOP_SCHEMA_VERSION\n",
        )
        _, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(len(self.findings_for("A001", findings)), 1)

    def test_a_mention_in_a_comment_or_docstring_is_not_a_reference(self) -> None:
        """The six adapters that document *why* the alias is wrong are clean."""
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            '"""Core exports ``INSTALL_SOP_SCHEMA_VERSION``; never use it."""\n'
            "# INSTALL_SOP_SCHEMA_VERSION is the artifact revision, not the report field.\n"
            'NAME = "INSTALL_SOP_SCHEMA_VERSION"\n',
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)
        self.assertEqual(self.findings_for("A001", findings), [])

    def test_a_similar_but_different_name_is_not_reported(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            "from dcc_mcp_core.deployment import _DEPRECATED_INSTALL_SOP_SCHEMA_VERSION\n"
            "from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_REVISION\n",
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)

    def test_test_directories_are_out_of_scope(self) -> None:
        """The guard tests must be able to name the alias they guard against."""
        self.adapter_clean()
        self.repo.write(
            "tests/test_install_lifecycle.py",
            "def test_alias_is_ignored(monkeypatch):\n"
            '    monkeypatch.setattr(install, "INSTALL_SOP_SCHEMA_VERSION", 2)\n',
        )
        self.repo.write(
            "src/dcc_mcp_demo/tests/test_helpers.py",
            "from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_VERSION\n",
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)
        self.assertEqual(self.findings_for("A001", findings), [])

    def test_the_provider_may_define_and_export_the_alias(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "python/dcc_mcp_core/deployment/install_sop.py",
            "INSTALL_SOP_SCHEMA_VERSION = 2\n"
            "from dcc_mcp_core.deployment.install_sop import INSTALL_SOP_SCHEMA_VERSION\n",
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)

    def test_an_unparseable_file_is_reported_as_a_blind_spot(self) -> None:
        self.adapter_clean()
        self.repo.write("src/dcc_mcp_demo/broken.py", "def oops(:\n")
        _, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        notices = [item for item in findings if item["severity"] == "notice"]
        self.assertEqual(len(notices), 1)
        self.assertIn("broken.py", notices[0]["path"])


class TestA002HandRolledSchemaVersion(AdapterContractTestCase):
    def test_hard_coded_report_schema_version_warns(self) -> None:
        self.adapter_clean()
        self.repo.write("src/dcc_mcp_demo/install.py", "FALLBACK_REPORT_SCHEMA_VERSION = 1\n")
        code, findings = run_cli(
            self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT
        )
        self.assertEqual(code, 0)
        hits = self.findings_for("A002", findings)
        self.assertEqual(len(hits), 1)
        self.assertIn("FALLBACK_REPORT_SCHEMA_VERSION = 1", hits[0]["message"])

    def test_an_unrelated_schema_constant_is_not_reported(self) -> None:
        self.adapter_clean()
        self.repo.write("src/dcc_mcp_demo/receipt.py", "RECEIPT_SCHEMA_VERSION = 3\n")
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A002", findings), [])

    def test_a_non_integer_value_is_not_a_hard_coded_version(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            'FALLBACK_REPORT_SCHEMA_VERSION = "1"\nFALLBACK_REPORT_SCHEMA_VERSION_2 = True\n',
        )
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A002", findings), [])

    def test_a_schema_version_read_from_core_is_not_reported(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "src/dcc_mcp_demo/install.py",
            "from dcc_mcp_core.deployment import install_sop_report_schema_version\n"
            "REPORT_SCHEMA_VERSION = install_sop_report_schema_version()\n",
        )
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A002", findings), [])


class TestA003CoreFloor(AdapterContractTestCase):
    def test_a_declared_lower_bound_passes(self) -> None:
        self.adapter_clean()
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)

    def test_an_unversioned_core_dependency_is_an_error(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'requires-python = ">=3.9"\n'
            "dependencies = [\n"
            '    "dcc-mcp-core",\n'
            '    "pydantic>=2",\n'
            "]\n",
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 1)
        self.assertEqual(self.severities(findings, "A003"), {"error"})

    def test_a_multiline_dependency_array_is_read(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            "dependencies = [\n"
            '    "dcc-mcp-core>=0.20.36",   # same batch as dcc-mcp-server\n'
            '    "pydantic>=2",\n'
            "]\n",
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)

    def test_a_repository_without_core_is_out_of_scope(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'requires-python = ">=3.9"\n'
            'dependencies = ["pydantic>=2"]\n',
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)

    def test_a_self_reference_in_an_extra_is_out_of_scope(self) -> None:
        """`dcc-mcp-core[test]` in a dev extra is not a deployment requirement."""
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-core"\n'
            'requires-python = ">=3.7"\n'
            'dependencies = ["dcc-mcp-server>=0.18.17,<1.0.0"]\n'
            "\n[project.optional-dependencies]\n"
            'dev = ["dcc-mcp-core[test]"]\n',
        )
        code, findings = run_cli(self.repo.root, contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0, findings)


class TestA004LineLength(AdapterContractTestCase):
    def test_the_baseline_value_passes(self) -> None:
        self.adapter_clean()
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A004", findings), [])

    def test_a_divergent_value_warns(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'requires-python = ">=3.9"\n'
            'dependencies = ["dcc-mcp-core>=0.20.40"]\n'
            "\n[tool.ruff]\n"
            "line-length = 100\n",
        )
        code, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0)
        hits = self.findings_for("A004", findings)
        self.assertEqual(len(hits), 1)
        self.assertIn("line-length = 100", hits[0]["message"])
        self.assertIn("120", hits[0]["message"])

    def test_an_undeclared_value_is_reported_as_undeclared(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'requires-python = ">=3.9"\n'
            'dependencies = ["dcc-mcp-core>=0.20.40"]\n',
        )
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        hits = self.findings_for("A004", findings)
        self.assertEqual(len(hits), 1)
        self.assertIn("declares no line-length", hits[0]["message"])

    def test_a_repository_without_pyproject_is_left_to_a005(self) -> None:
        self.repo.clean()
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A004", findings), [])


class TestA005RequiresPython(AdapterContractTestCase):
    def test_a_declared_range_passes(self) -> None:
        self.adapter_clean()
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A005", findings), [])

    def test_any_declared_value_is_accepted(self) -> None:
        """The rule is about visibility; the host owns the value."""
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'requires-python = ">=3.10"\n'
            'dependencies = ["dcc-mcp-core>=0.20.40"]\n'
            "\n[tool.ruff]\nline-length = 120\n",
        )
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A005", findings), [])

    def test_a_missing_declaration_warns(self) -> None:
        self.adapter_clean()
        self.repo.write(
            "pyproject.toml",
            "[project]\n"
            'name = "dcc-mcp-demo"\n'
            'dependencies = ["dcc-mcp-core>=0.20.40"]\n'
            "\n[tool.ruff]\nline-length = 120\n",
        )
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        hits = self.findings_for("A005", findings)
        self.assertEqual(len(hits), 1)
        self.assertIn("requires-python", hits[0]["message"])


class TestA006PreCommit(AdapterContractTestCase):
    def test_a_pre_commit_config_passes(self) -> None:
        self.adapter_clean()
        _, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(self.findings_for("A006", findings), [])

    def test_a_missing_config_warns(self) -> None:
        self.adapter_clean()
        (self.repo.root / ".pre-commit-config.yaml").unlink()
        code, findings = run_cli(self.repo.root, "--profile", "strict", contract=ADAPTER_CONTRACT)
        self.assertEqual(code, 0)
        hits = self.findings_for("A006", findings)
        self.assertEqual(len(hits), 1)
        self.assertIn(".pre-commit-config.yaml", hits[0]["path"])


class TestMatrix(unittest.TestCase):
    def write_manifest(self, payload: dict) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return Path(handle.name)

    def emit(self, payload: dict) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--contract", CONTRACT, "--emit-matrix", str(self.write_manifest(payload))])
        return code, (json.loads(stdout.getvalue()) if stdout.getvalue().strip() else {})

    def test_defaults_are_applied_to_every_entry(self) -> None:
        code, matrix = self.emit(
            {
                "defaults": {"profile": "baseline", "fail_on": "error"},
                "repositories": [{"repository": "dcc-mcp/dcc-mcp-core"}],
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            matrix["include"],
            [
                {
                    "key": "dcc-mcp-dcc-mcp-core",
                    "repository": "dcc-mcp/dcc-mcp-core",
                    "profile": "baseline",
                    "rules": "",
                    "skip_rules": "",
                    "error_rules": "",
                    "allow_extra": "",
                    "fail_on": "error",
                }
            ],
        )

    def test_per_repository_overrides_win(self) -> None:
        code, matrix = self.emit(
            {
                "defaults": {"profile": "baseline"},
                "repositories": [
                    {
                        "repository": "loonghao/vx",
                        "profile": "strict",
                        "error_rules": ["R008"],
                        "allow_extra": [".beads"],
                    }
                ],
            }
        )
        entry = matrix["include"][0]
        self.assertEqual(entry["profile"], "strict")
        self.assertEqual(entry["error_rules"], "R008")
        self.assertEqual(entry["allow_extra"], ".beads")

    def test_rejects_duplicate_repositories(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "--contract",
                    CONTRACT,
                    "--emit-matrix",
                    str(
                        self.write_manifest(
                            {"repositories": [{"repository": "a/b"}, {"repository": "a/b"}]}
                        )
                    ),
                ]
            )
        self.assertEqual(code, 2)

    def test_rejects_an_empty_manifest(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(
                ["--contract", CONTRACT, "--emit-matrix", str(self.write_manifest({"repositories": []}))]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
