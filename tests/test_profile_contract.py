from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "profile_contract.json"
FIXTURE_SHA256 = "2749758168cbeafcdca4403b3ad86e6f842a0569b1a671bea6a6ed1f85737cdd"


def canonical_lf(data: bytes) -> bytes:
    """Return the platform-independent byte representation frozen by the digest."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


class ProfileContractMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "profile", self.root / "profile")
        shutil.copytree(ROOT / "scripts", self.root / "scripts")
        fixture_dir = self.root / "tests" / "fixtures"
        fixture_dir.mkdir(parents=True)
        shutil.copy2(FIXTURE, fixture_dir / FIXTURE.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def profile(self, name: str) -> Path:
        return self.root / "profile" / name

    def replace(self, path: Path, old: str, new: str, count: int = -1) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, count), encoding="utf-8")

    def assert_checker_rejects(self) -> None:
        result = self.run_checker()
        output = result.stdout + result.stderr
        self.assertEqual(1, result.returncode, output)
        self.assertNotIn("Traceback", output)

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / "check_profile_contract.py")],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_checker_rejects_cleanly(self, expected: str) -> None:
        result = self.run_checker()
        output = result.stdout + result.stderr
        self.assertEqual(1, result.returncode, output)
        self.assertNotIn("Traceback", output)
        self.assertIn(expected, output)

    def test_hidden_query_term_in_html_comment_is_rejected(self) -> None:
        path = self.profile("README.md")
        self.replace(path, "**Godot MCP**", "**Godot connector**", 1)
        path.write_text(
            path.read_text(encoding="utf-8") + "\n<!-- Godot MCP -->\n",
            encoding="utf-8",
        )
        self.assert_checker_rejects()

    def test_hidden_chinese_identity_in_html_comment_is_rejected(self) -> None:
        path = self.profile("README_zh.md")
        self.replace(path, "团结引擎", "Tuanjie Engine")
        path.write_text(
            path.read_text(encoding="utf-8") + "\n<!-- 团结引擎 -->\n", encoding="utf-8"
        )
        self.assert_checker_rejects()

    def test_wrong_row_owner_with_correct_decoy_elsewhere_is_rejected(self) -> None:
        path = self.profile("README.md")
        self.replace(
            path,
            "[`dcc-mcp-godot`](https://github.com/dcc-mcp/dcc-mcp-godot)",
            "[`dcc-mcp-godot`](https://github.com/microsoft/vscode)",
            1,
        )
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n[Godot owner decoy](https://github.com/dcc-mcp/dcc-mcp-godot)\n",
            encoding="utf-8",
        )
        self.assert_checker_rejects()

    def test_duplicate_application_row_is_rejected(self) -> None:
        path = self.profile("README.md")
        marker = "| Godot | [Control Godot with AI](https://dcc-mcp.github.io/control/godot) | [`dcc-mcp-godot`](https://github.com/dcc-mcp/dcc-mcp-godot) |"
        duplicate = "| Godot | [Control Godot elsewhere](https://dcc-mcp.github.io/control/godot) | [wrong](https://github.com/microsoft/vscode) |"
        self.replace(path, marker, marker + "\n" + duplicate, 1)
        self.assert_checker_rejects()

    def test_missing_application_row_is_rejected(self) -> None:
        path = self.profile("README.md")
        marker = "| Godot | [Control Godot with AI](https://dcc-mcp.github.io/control/godot) | [`dcc-mcp-godot`](https://github.com/dcc-mcp/dcc-mcp-godot) |\n"
        self.replace(path, marker, "", 1)
        self.assert_checker_rejects()

    def test_duplicate_visible_identity_heading_is_rejected(self) -> None:
        path = self.profile("README.md")
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# DCC MCP\n", encoding="utf-8"
        )
        self.assert_checker_rejects()

    def test_unchecked_extra_profile_is_rejected(self) -> None:
        shutil.copy2(self.profile("README.md"), self.profile("README_es.md"))
        self.assert_checker_rejects()

    def test_coordinated_production_query_constant_change_is_rejected(self) -> None:
        self.replace(self.profile("README.md"), "Godot MCP", "Godot connector")
        self.replace(self.profile("README_zh.md"), "Godot MCP", "Godot connector")
        checker = self.root / "scripts" / "check_profile_contract.py"
        checker_text = checker.read_text(encoding="utf-8")
        if "Godot MCP" in checker_text:
            checker.write_text(
                checker_text.replace("Godot MCP", "Godot connector"), encoding="utf-8"
            )
        self.assert_checker_rejects()

    def test_contract_fixture_is_reviewer_independent(self) -> None:
        fixture_bytes = FIXTURE.read_bytes()
        self.assertEqual(
            FIXTURE_SHA256, hashlib.sha256(canonical_lf(fixture_bytes)).hexdigest()
        )
        crlf_bytes = fixture_bytes.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        self.assertEqual(
            FIXTURE_SHA256, hashlib.sha256(canonical_lf(crlf_bytes)).hexdigest()
        )
        contract = json.loads(fixture_bytes)
        self.assertIn("Godot MCP", contract["visible_query_terms"])
        self.assertEqual(
            [
                "Godot",
                "https://dcc-mcp.github.io/control/godot",
                "https://github.com/dcc-mcp/dcc-mcp-godot",
            ],
            contract["profiles"]["README.md"]["rows"][-1],
        )

    def test_hidden_html_never_satisfies_a_visible_query_term(self) -> None:
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        mutated = original.replace("**Godot MCP**", "**Godot connector**", 1)
        hidden_variants = (
            "<span hidden>Godot MCP</span>",
            '<DIV ArIa-HiDdEn = " TrUe "><section>Godot MCP</section></DIV>',
            "<div hidden>\n\nGodot MCP\n\n</div>",
            '<div style=" DISPLAY : none ; color: red"><span>Godot MCP</span></div>',
            '<div style="visibility : HIDDEN"><span>Godot MCP</span></div>',
            "<template><span>Godot MCP</span></template>",
            "<noscript>Godot MCP</noscript>",
            "<script>Godot MCP</script>",
            "<style>.result { content: 'Godot MCP'; }</style>",
            "&lt;span hidden&gt;Godot MCP&lt;/span&gt;",
            "&lt;script&gt;Godot MCP&lt;/script&gt;",
        )
        for variant in hidden_variants:
            with self.subTest(variant=variant):
                path.write_text(mutated + f"\n{variant}\n", encoding="utf-8")
                self.assert_checker_rejects()
        path.write_text(original, encoding="utf-8")

    def test_deceptive_hidden_required_term_is_rejected_even_when_visible(self) -> None:
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original + '\n<div aria-hidden="true"><span>Godot MCP</span></div>\n',
            encoding="utf-8",
        )
        self.assert_checker_rejects()

    def test_deceptive_escaped_comment_is_rejected_with_visible_identity(self) -> None:
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "\n&lt;!-- Godot MCP --&gt;\n", encoding="utf-8")
        self.assert_checker_rejects()

    def test_css_hidden_variants_are_rejected_with_visible_identity(self) -> None:
        variants = (
            '&lt;div style="display:/**/none"&gt;Godot MCP&lt;/div&gt;',
            '&lt;div style="display:none ! important"&gt;Godot MCP&lt;/div&gt;',
            '&lt;div style="d\\69 splay: \\6e one"&gt;Godot MCP&lt;/div&gt;',
            '&lt;div style="visibility: h\\69 dden"&gt;Godot MCP&lt;/div&gt;',
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for variant in variants:
            with self.subTest(variant=variant):
                path.write_text(original + f"\n{variant}\n", encoding="utf-8")
                self.assert_checker_rejects_cleanly(
                    "deceptive hidden identity 'Godot MCP'"
                )
        path.write_text(original, encoding="utf-8")

    def test_duplicate_visibility_declarations_fail_closed(self) -> None:
        variants = (
            "display:none!important;display:block",
            "display:none ! important;display:block",
            "display:block;display:none!important",
            "visibility:hidden!important;visibility:visible",
            "visibility:visible;visibility:hidden ! important",
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for style in variants:
            with self.subTest(style=style):
                hidden = f'&lt;div style="{style}"&gt;Godot MCP&lt;/div&gt;'
                path.write_text(original + f"\n{hidden}\n", encoding="utf-8")
                self.assert_checker_rejects_cleanly(
                    "deceptive hidden identity 'Godot MCP'"
                )
        path.write_text(original, encoding="utf-8")

    def test_malformed_escaped_comment_fails_without_traceback(self) -> None:
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "\n&lt;!-- Godot MCP --!&gt;\n", encoding="utf-8")
        self.assert_checker_rejects_cleanly("deceptive hidden identity 'Godot MCP'")

    def test_public_url_canonicalization_aliases_are_rejected(self) -> None:
        aliases = (
            "https://github.com:443/dcc-mcp",
            "https://github.com:8443/dcc-mcp",
            "https://github.com/dcc-mcp/../dcc-mcp",
            "https://github.com//dcc-mcp",
            "https://github.com./dcc-mcp",
            "https://GitHub.com/dcc-mcp",
            "https://éxample.com/support",
            "https://github.com/dcc-mcp/%2e%2e/dcc-mcp",
            "https://github.com/dcc-mcp/%2Fowner",
            "https://github.com/dcc-mcp/%5Cowner",
            "https://github.com/%64cc-mcp",
            "https://github.com/dcc-mcp/%00owner",
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for index, alias in enumerate(aliases):
            with self.subTest(alias=alias):
                path.write_text(
                    original + f"\n[Alias {index}]({alias})\n", encoding="utf-8"
                )
                self.assert_checker_rejects()
        path.write_text(original, encoding="utf-8")

    def test_malformed_and_non_domain_public_urls_are_rejected(self) -> None:
        aliases = (
            "https://example.com/%GG",
            "https://example.com/%",
            "https://example.com/%2",
            "https://127.0.0.1/",
            "https://8.8.8.8/",
            "https://[::1]/",
            "https://2130706433/",
            "https://0x7f000001/",
            "https://0177.0.0.1/",
            "https://127.1/",
            "https://localhost/",
            "https://service.local/",
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for index, alias in enumerate(aliases):
            with self.subTest(alias=alias):
                path.write_text(
                    original + f"\n[Alias {index}]({alias})\n", encoding="utf-8"
                )
                self.assert_checker_rejects_cleanly("README.md:")
        path.write_text(original, encoding="utf-8")

    def test_malformed_url_syntax_is_rejected_without_traceback(self) -> None:
        aliases = (
            ("https://[::1", "invalid URL syntax"),
            ("https://user@[::1", "invalid URL syntax"),
            ("https://[]/", "invalid URL syntax"),
            ("https://example.com:notaport/", "invalid port in link"),
            ("https://example.com:99999/", "invalid port in link"),
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for alias, reason in aliases:
            with self.subTest(alias=alias):
                anchor = f'<a href="{alias}">Malformed</a>'
                path.write_text(original + f"\n{anchor}\n", encoding="utf-8")
                self.assert_checker_rejects_cleanly(reason)
        path.write_text(original, encoding="utf-8")

    def test_local_path_canonicalization_aliases_are_rejected(self) -> None:
        aliases = (
            "%2e%2e/README.md",
            "%2e%2e%2fREADME.md",
            "%2e%2e%5cREADME.md",
            "%2Fetc/passwd",
            "C:/Windows/System32/config",
            "//server/share/file.md",
            "\\\\server\\share\\file.md",
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for index, alias in enumerate(aliases):
            with self.subTest(alias=alias):
                path.write_text(
                    original + f"\n[Local alias {index}]({alias})\n", encoding="utf-8"
                )
                self.assert_checker_rejects()
        path.write_text(original, encoding="utf-8")

    def test_query_and_fragment_aliases_are_rejected(self) -> None:
        aliases = (
            "https://github.com/dcc-mcp/core?x=1",
            "https://github.com/dcc-mcp/core#x",
            "./README_zh.md#x",
            "#x",
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        for index, alias in enumerate(aliases):
            with self.subTest(alias=alias):
                path.write_text(
                    original + f"\n[Alias {index}]({alias})\n", encoding="utf-8"
                )
                self.assert_checker_rejects()
        path.write_text(original, encoding="utf-8")

    def test_unsafe_and_ambiguous_urls_are_rejected(self) -> None:
        unsafe_urls = (
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "file:///etc/passwd",
            "mailto:support@example.com",
            "custom:payload",
            "https://user:password@example.com/support",
            "https://example.com/%0Aevil",
            "https://ｅxample.com/support",
            "https:\\example.com/support",
        )
        for index, url in enumerate(unsafe_urls):
            with self.subTest(url=url):
                path = self.profile("README.md")
                original = path.read_text(encoding="utf-8")
                path.write_text(
                    original + f"\n[Unsafe support {index}]({url})\n", encoding="utf-8"
                )
                try:
                    self.assert_checker_rejects()
                finally:
                    path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
