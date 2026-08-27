from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

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

    def test_escaped_unsupported_visibility_styles_fail_closed(self) -> None:
        variants = (
            "opacity:0",
            "opacity:.0",
            "opacity:0.0!important",
            "opac\\69ty:0",
            "opacity:0;opacity:1",
            "opacity:1;opacity:0",
            "filter:opacity(0)",
            "clip-path:inset(100%)",
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        mutated = original.replace("**Godot MCP**", "**Godot connector**", 1)
        self.assertNotEqual(original, mutated)
        for style in variants:
            with self.subTest(style=style):
                markup = f'&lt;p style="{style}"&gt;Godot MCP&lt;/p&gt;'
                path.write_text(mutated + f"\n{markup}\n", encoding="utf-8")
                self.assert_checker_rejects_cleanly(
                    "missing visible discovery identity 'Godot MCP'"
                )
        path.write_text(original, encoding="utf-8")

    def test_duplicate_visibility_attributes_fail_closed(self) -> None:
        variants = (
            'style="display:none" style="display:block"',
            'style="display:block" style="display:none"',
            'aria-hidden="true" aria-hidden="false"',
            'hidden="hidden" hidden=""',
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        mutated = original.replace("**Godot MCP**", "**Godot connector**", 1)
        self.assertNotEqual(original, mutated)
        for attributes in variants:
            with self.subTest(attributes=attributes):
                hidden = f"&lt;div {attributes}&gt;Godot MCP&lt;/div&gt;"
                path.write_text(mutated + f"\n{hidden}\n", encoding="utf-8")
                self.assert_checker_rejects_cleanly(
                    "missing visible discovery identity 'Godot MCP'"
                )
        path.write_text(original, encoding="utf-8")

    def test_generic_and_double_escaped_hidden_markup_fails_closed(self) -> None:
        variants = (
            '&lt;p style="display:none" style="display:block"&gt;Godot MCP&lt;/p&gt;',
            "&lt;p style='display:none' style='display:block'&gt;Godot MCP&lt;/p&gt;",
            '&lt;a aria-hidden="true" aria-hidden="false"&gt;Godot MCP&lt;/a&gt;',
            "&lt;P ARIA-HIDDEN='true' aria-hidden='false'&gt;Godot MCP&lt;/P&gt;",
            '&lt;p hidden="hidden" hidden=""&gt;Godot MCP&lt;/p&gt;',
            '&lt;p hidden="" hidden="hidden"&gt;Godot MCP&lt;/p&gt;',
            '&lt;p&gt;&lt;a style="display:none" style="display:block"&gt;Godot MCP&lt;/a&gt;&lt;/p&gt;',
            '&lt;p class="one"class="two" id="one"id="two" style=&quot;display:none&quot; style=&quot;display:block&quot;&gt;Godot MCP&lt;/p&gt;',
            '&amp;lt;p style="display:none" style="display:block"&amp;gt;Godot MCP&amp;lt;/p&amp;gt;',
            '&amp;lt;a aria-hidden="true" aria-hidden="false"&amp;gt;Godot MCP&amp;lt;/a&amp;gt;',
        )
        path = self.profile("README.md")
        original = path.read_text(encoding="utf-8")
        mutated = original.replace("**Godot MCP**", "**Godot connector**", 1)
        self.assertNotEqual(original, mutated)
        for markup in variants:
            with self.subTest(markup=markup):
                path.write_text(mutated + f"\n{markup}\n", encoding="utf-8")
                self.assert_checker_rejects_cleanly(
                    "missing visible discovery identity 'Godot MCP'"
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

    def test_redirect_targets_are_rejected_before_dispatch(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        self.assertIn("SafeRedirectHandler", checker)
        handler_type = checker["SafeRedirectHandler"]
        unsafe_targets = (
            "http://127.0.0.1/private",
            "https://127.0.0.1/private",
            "https://localhost/private",
            "https://user:password@example.com/private",
            "https://example.com:443/private",
            "https://example.com/%GG",
            "https://[::1",
            "\thttps://example.com/private",
            "https://example.com/\tprivate",
            "https://example.com/\r\nprivate",
        )
        request = urllib.request.Request("https://example.com/start")
        with mock.patch.object(
            urllib.request.HTTPRedirectHandler,
            "redirect_request",
            return_value=object(),
        ) as dispatch:
            for target in unsafe_targets:
                with self.subTest(target=target):
                    handler = handler_type()
                    with self.assertRaisesRegex(
                        urllib.error.HTTPError, "unsafe redirect"
                    ):
                        handler.redirect_request(
                            request, None, 302, "Found", {}, target
                        )
            dispatch.assert_not_called()

    def test_special_use_hostnames_are_rejected(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        validate_link = checker["validate_link"]
        profile = ROOT / "profile" / "README.md"
        hosts = (
            "service.example",
            "service.home.arpa",
            "service.onion",
            "localtest.me",
            "sub.localtest.me",
        )
        for host in hosts:
            with self.subTest(host=host):
                error, public_url = validate_link(f"https://{host}/", profile)
                self.assertIsNone(public_url)
                self.assertIsNotNone(error)
                self.assertIn("special-use hostname", error)

    @staticmethod
    def address_info(address: str):
        if ":" in address:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    def test_non_public_dns_answers_fail_before_network_io(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        self.assertIn("socket", checker)
        unsafe_addresses = (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.1.1",
            "192.0.2.1",
            "224.0.0.1",
            "0.0.0.0",
            "::1",
            "fc00::1",
            "fe80::1",
            "ff02::1",
        )
        for address in unsafe_addresses:
            with self.subTest(address=address):
                with (
                    mock.patch.object(
                        checker["socket"],
                        "getaddrinfo",
                        return_value=self.address_info(address),
                    ),
                    mock.patch.object(
                        checker["urllib"].request, "build_opener"
                    ) as opener,
                ):
                    error = checker["check_url"]("https://example.com/start")
                self.assertIsNotNone(error)
                self.assertIn("non-public address", error)
                opener.assert_not_called()

    def test_dns_address_drift_is_rejected(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        self.assertIn("socket", checker)

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return b""

            def geturl(self):
                return "https://example.com/start"

        class Opener:
            def open(self, *_args, **_kwargs):
                return Response()

        answers = [
            self.address_info("93.184.216.34"),
            self.address_info("93.184.216.35"),
        ]
        with (
            mock.patch.object(checker["socket"], "getaddrinfo", side_effect=answers),
            mock.patch.object(
                checker["urllib"].request, "build_opener", return_value=Opener()
            ) as opener,
        ):
            error = checker["check_url"]("https://example.com/start")
        self.assertIsNotNone(error)
        self.assertIn("DNS address drift", error)
        opener.assert_not_called()

    def test_mixed_public_and_non_public_dns_answers_fail_closed(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        mixed_answers = self.address_info("93.184.216.34") + self.address_info(
            "127.0.0.1"
        )
        with (
            mock.patch.object(
                checker["socket"], "getaddrinfo", return_value=mixed_answers
            ),
            mock.patch.object(checker["urllib"].request, "build_opener") as opener,
        ):
            error = checker["check_url"]("https://example.com/start")
        self.assertIsNotNone(error)
        self.assertIn("non-public address", error)
        opener.assert_not_called()

    def test_bound_https_transport_preserves_origin_identity(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        self.assertIn("BoundHTTPSConnection", checker)
        connection_type = checker["BoundHTTPSConnection"]

        class RecordingSocket:
            def __init__(self) -> None:
                self.connected_to = None
                self.sent = bytearray()

            def settimeout(self, _timeout) -> None:
                pass

            def connect(self, address) -> None:
                self.connected_to = address

            def sendall(self, data) -> None:
                self.sent.extend(data)

            def close(self) -> None:
                pass

        class RecordingContext:
            def __init__(self) -> None:
                self.server_hostname = None

            def wrap_socket(self, sock, *, server_hostname):
                self.server_hostname = server_hostname
                return sock

        transport_socket = RecordingSocket()
        tls_context = RecordingContext()
        pins = {"example.com": frozenset({"93.184.216.34"})}
        production_handler = checker["BoundHTTPSHandler"](pins)
        self.assertTrue(production_handler._context.check_hostname)
        with (
            mock.patch.object(
                checker["socket"], "socket", return_value=transport_socket
            ),
            mock.patch.object(
                checker["socket"],
                "getaddrinfo",
                side_effect=AssertionError("transport performed an independent lookup"),
            ),
        ):
            connection = connection_type(
                "example.com", pins, timeout=3, context=tls_context
            )
            connection.connect()
            connection.request("GET", "/health")

        self.assertEqual(("93.184.216.34", 443), transport_socket.connected_to)
        self.assertEqual("example.com", tls_context.server_hostname)
        self.assertIn(b"Host: example.com\r\n", bytes(transport_socket.sent))

    def test_redirect_loops_and_hop_overflow_fail_before_dispatch(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))
        self.assertIn("SafeRedirectHandler", checker)
        handler_type = checker["SafeRedirectHandler"]
        max_hops = checker["MAX_REDIRECT_HOPS"]
        request = urllib.request.Request("https://example.com/start")
        with (
            mock.patch.object(
                checker["socket"],
                "getaddrinfo",
                return_value=self.address_info("93.184.216.34"),
            ),
            mock.patch.object(
                urllib.request.HTTPRedirectHandler,
                "redirect_request",
                return_value=object(),
            ) as dispatch,
        ):
            loop_handler = handler_type()
            with self.assertRaisesRegex(urllib.error.HTTPError, "redirect loop"):
                loop_handler.redirect_request(
                    request, None, 302, "Found", {}, request.full_url
                )
            dispatch.assert_not_called()

            overflow_handler = handler_type()
            for index in range(max_hops):
                overflow_handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    f"https://example.com/hop-{index}",
                )
            dispatched = dispatch.call_count
            with self.assertRaisesRegex(urllib.error.HTTPError, "too many redirects"):
                overflow_handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    "https://example.com/overflow",
                )
            self.assertEqual(dispatched, dispatch.call_count)

    def test_final_redirect_url_is_validated(self) -> None:
        checker = runpy.run_path(str(ROOT / "scripts" / "check_profile_contract.py"))

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return b""

            def geturl(self):
                return "http://127.0.0.1/private"

        class Opener:
            def open(self, *_args, **_kwargs):
                return Response()

        with (
            mock.patch.object(
                checker["socket"],
                "getaddrinfo",
                return_value=self.address_info("93.184.216.34"),
            ),
            mock.patch.object(
                checker["urllib"].request, "urlopen", return_value=Response()
            ),
            mock.patch.object(
                checker["urllib"].request, "build_opener", return_value=Opener()
            ),
        ):
            error = checker["check_url"]("https://example.com/start")
        self.assertIsNotNone(error)
        self.assertIn("unsafe redirect", error)

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
