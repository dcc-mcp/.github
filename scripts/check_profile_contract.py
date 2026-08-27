#!/usr/bin/env python3
"""Validate visible profile semantics, identity ownership, and safe links."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "profile_contract.json"
VOLATILE_GUIDANCE_RE = re.compile(
    r"(?:clawhub@\d|pip install|openclaw skills install)", re.IGNORECASE
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
INVALID_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_ESCAPE_RE = re.compile(
    r"\\(?:([0-9A-Fa-f]{1,6})(?:[ \t\r\n\f])?|([^\r\n\f0-9A-Fa-f]))"
)
CSS_IMPORTANT_RE = re.compile(r"\s*!\s*important\s*$", re.IGNORECASE)
NUMERIC_HOST_RE = re.compile(
    r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}",
    re.IGNORECASE,
)
PUBLIC_HOST_RE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
NON_PUBLIC_DNS_SUFFIXES = (
    ".example",
    ".home.arpa",
    ".internal",
    ".invalid",
    ".lan",
    ".local",
    ".localhost",
    ".onion",
    ".test",
)
NON_PUBLIC_DNS_NAMES = {suffix.removeprefix(".") for suffix in NON_PUBLIC_DNS_SUFFIXES}
NON_PUBLIC_DNS_NAMES.add("localtest.me")
MAX_STYLE_LENGTH = 4096
MAX_REDIRECT_HOPS = 5
MAX_DNS_ADDRESSES = 16
DNS_TIMEOUT_SECONDS = 5
VISIBILITY_ATTRIBUTES = {"aria-hidden", "hidden", "style"}
VISIBLE_STYLE_VALUES = {
    "display": {
        "block",
        "contents",
        "flex",
        "flow-root",
        "grid",
        "inline",
        "inline-block",
        "inline-flex",
        "inline-grid",
        "list-item",
        "table",
    },
    "visibility": {"visible"},
}
ESCAPED_MARKUP_RE = re.compile(r"<\s*(?:!--|/?\s*[a-z][^<>]*>)", re.IGNORECASE)
MAX_ESCAPED_MARKUP_EXPANSIONS = 2
ALWAYS_HIDDEN_TAGS = {"script", "style", "template", "noscript"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


@dataclass(frozen=True)
class Cell:
    text: str
    links: tuple[str, ...]


@dataclass(frozen=True)
class ParsedProfile:
    visible_text: str
    hidden_text: str
    headings: tuple[tuple[int, str], ...]
    tables: tuple[tuple[tuple[Cell, ...], ...], ...]
    links: frozenset[str]
    visible_links: frozenset[str]


@dataclass(frozen=True)
class HtmlFrame:
    tag: str
    hidden: bool
    closed_details: bool


def decode_css_escapes(value: str) -> str | None:
    def replace(match: re.Match[str]) -> str:
        if match.group(1) is None:
            return match.group(2)
        codepoint = int(match.group(1), 16)
        if codepoint == 0 or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return "\x00"
        return chr(codepoint)

    decoded = CSS_ESCAPE_RE.sub(replace, value)
    if "\\" in decoded or CONTROL_RE.search(decoded):
        return None
    return decoded


def parse_css_declarations(style: str) -> dict[str, str] | None:
    if len(style) > MAX_STYLE_LENGTH:
        return None
    without_comments = CSS_COMMENT_RE.sub("", style)
    if "/*" in without_comments or "*/" in without_comments:
        return None

    declarations: dict[str, str] = {}
    for declaration in without_comments.split(";"):
        if not declaration.strip():
            continue
        if ":" not in declaration:
            return None
        raw_name, raw_value = declaration.split(":", 1)
        name = decode_css_escapes(raw_name)
        value = decode_css_escapes(raw_value)
        if name is None or value is None:
            return None
        normalized_name = name.strip().lower()
        normalized_value = CSS_IMPORTANT_RE.sub("", value).strip().lower()
        if not normalized_name:
            return None
        if normalized_name in declarations:
            return None
        declarations[normalized_name] = normalized_value
    return declarations


class VisibleHtmlParser(HTMLParser):
    def __init__(
        self, *, escaped_markup_budget: int = MAX_ESCAPED_MARKUP_EXPANSIONS
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.hidden_text: list[str] = []
        self.links: list[str] = []
        self.visible_links: list[str] = []
        self._stack: list[HtmlFrame] = []
        self._escaped_markup_budget = escaped_markup_budget

    @property
    def hidden(self) -> bool:
        return self._path_is_hidden()

    def _path_is_hidden(self, child_tag: str | None = None) -> bool:
        if any(frame.hidden for frame in self._stack):
            return True
        for index, frame in enumerate(self._stack):
            if not frame.closed_details:
                continue
            direct_child = (
                self._stack[index + 1].tag
                if index + 1 < len(self._stack)
                else child_tag
            )
            if direct_child != "summary":
                return True
        return False

    @staticmethod
    def _element_is_hidden(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in ALWAYS_HIDDEN_TAGS:
            return True
        normalized: dict[str, str | None] = {}
        for name, value in attrs:
            normalized_name = name.lower()
            if (
                normalized_name in VISIBILITY_ATTRIBUTES
                and normalized_name in normalized
            ):
                return True
            normalized.setdefault(normalized_name, value)
        if "hidden" in normalized:
            return True
        aria_hidden = normalized.get("aria-hidden")
        if aria_hidden is not None and aria_hidden.strip().lower() == "true":
            return True
        style = normalized.get("style") or ""
        declarations = parse_css_declarations(style)
        if declarations is None:
            return True
        return any(
            name not in VISIBLE_STYLE_VALUES or value not in VISIBLE_STYLE_VALUES[name]
            for name, value in declarations.items()
        )

    def add_link(self, value: str, hidden: bool | None = None) -> None:
        self.links.append(value)
        if not (self.hidden if hidden is None else hidden):
            self.visible_links.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        hidden = self._path_is_hidden(tag) or self._element_is_hidden(tag, attrs)
        if tag not in VOID_TAGS:
            attr_names = {name.lower() for name, _value in attrs}
            self._stack.append(
                HtmlFrame(tag, hidden, tag == "details" and "open" not in attr_names)
            )
        for name, value in attrs:
            if name.lower() in {"href", "src"} and value is not None:
                self.add_link(value, hidden)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        hidden = self._path_is_hidden(tag) or self._element_is_hidden(tag, attrs)
        for name, value in attrs:
            if name.lower() in {"href", "src"} and value is not None:
                self.add_link(value, hidden)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        candidate = data
        for _ in range(self._escaped_markup_budget + 1):
            if ESCAPED_MARKUP_RE.search(candidate):
                break
            decoded = html_unescape(candidate)
            if decoded == candidate:
                break
            candidate = decoded
        if (
            not ESCAPED_MARKUP_RE.search(candidate)
            and html_unescape(candidate) != candidate
        ):
            self.hidden_text.append(data)
            return
        if ESCAPED_MARKUP_RE.search(candidate):
            if self._escaped_markup_budget <= 0:
                self.hidden_text.append(candidate)
                return
            nested = VisibleHtmlParser(
                escaped_markup_budget=self._escaped_markup_budget - 1
            )
            nested.feed(candidate)
            nested.close()
            self.links.extend(nested.links)
            if self.hidden:
                self.hidden_text.extend(nested.text)
                self.hidden_text.extend(nested.hidden_text)
            else:
                self.text.extend(nested.text)
                self.hidden_text.extend(nested.hidden_text)
                self.visible_links.extend(nested.visible_links)
            return
        (self.hidden_text if self.hidden else self.text).append(data)

    def handle_comment(self, data: str) -> None:
        self.hidden_text.append(data)


def normalize_text(parts: list[str] | tuple[str, ...] | str) -> str:
    if isinstance(parts, str):
        return " ".join(parts.split())
    return " ".join(" ".join(parts).split())


def parse_inline(children: list[Token]) -> tuple[str, tuple[str, ...]]:
    parser = VisibleHtmlParser()
    for child in children:
        if child.type == "text":
            parser.handle_data(child.content)
        elif child.type == "code_inline":
            parser.handle_data(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parser.handle_data(" ")
        elif child.type == "link_open":
            href = child.attrGet("href")
            if href is not None:
                parser.add_link(href)
        elif child.type == "image":
            src = child.attrGet("src")
            if src is not None:
                parser.add_link(src)
            parser.handle_data(child.content)
        elif child.type == "html_inline":
            parser.feed(child.content)
    parser.close()
    return normalize_text(parser.text), tuple(parser.visible_links)


def parse_markdown(text: str) -> ParsedProfile:
    markdown = MarkdownIt("commonmark").enable("table")
    # Expose every destination as a token; the validator below fails closed.
    markdown.validateLink = lambda _url: True
    markdown.normalizeLink = lambda url: url
    tokens = markdown.parse(text)
    document = VisibleHtmlParser()
    document.feed(markdown.render(text))
    document.close()

    headings: list[tuple[int, str]] = []
    tables: list[tuple[tuple[Cell, ...], ...]] = []
    current_table: list[tuple[Cell, ...]] | None = None
    current_row: list[Cell] | None = None
    current_cell: Cell | None = None
    heading_level: int | None = None

    for token in tokens:
        if token.type == "heading_open":
            heading_level = int(token.tag[1:])
        elif token.type == "heading_close":
            heading_level = None
        elif token.type == "table_open":
            current_table = []
        elif token.type == "table_close":
            if current_table is not None:
                tables.append(tuple(current_table))
            current_table = None
        elif token.type == "tr_open":
            current_row = []
        elif token.type == "tr_close":
            if current_table is not None and current_row is not None:
                current_table.append(tuple(current_row))
            current_row = None
        elif token.type in {"th_open", "td_open"}:
            current_cell = Cell("", ())
        elif token.type in {"th_close", "td_close"}:
            if current_row is not None and current_cell is not None:
                current_row.append(current_cell)
            current_cell = None
        elif token.type == "inline":
            inline_text, inline_visible_links = parse_inline(token.children or [])
            if heading_level is not None:
                headings.append((heading_level, inline_text))
            if current_cell is not None:
                current_cell = Cell(inline_text, inline_visible_links)
    return ParsedProfile(
        visible_text=normalize_text(document.text),
        hidden_text=normalize_text(document.hidden_text),
        headings=tuple(headings),
        tables=tuple(tables),
        links=frozenset(document.links),
        visible_links=frozenset(document.visible_links),
    )


def validate_link(link: str, profile_path: Path) -> tuple[str | None, str | None]:
    if (
        not link
        or unicodedata.normalize("NFKC", link) != link
        or CONTROL_RE.search(link)
        or INVALID_PERCENT_RE.search(link)
    ):
        return f"{profile_path.name}: unsafe or non-normalized link {link!r}", None
    try:
        decoded = unquote(link, errors="strict")
    except UnicodeDecodeError:
        return f"{profile_path.name}: invalid encoded link {link!r}", None
    if (
        decoded != link
        or unicodedata.normalize("NFKC", decoded) != decoded
        or CONTROL_RE.search(decoded)
    ):
        return f"{profile_path.name}: unsafe encoded link {link!r}", None
    if "\\" in link or any(character.isspace() for character in link):
        return f"{profile_path.name}: ambiguous link {link!r}", None

    try:
        parsed = urlsplit(link)
    except ValueError:
        return f"{profile_path.name}: invalid URL syntax in link {link!r}", None
    if "?" in link or "#" in link:
        return (
            f"{profile_path.name}: query and fragment links are forbidden: {link!r}",
            None,
        )
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.netloc:
            return (
                f"{profile_path.name}: only normalized HTTPS links are allowed: {link!r}",
                None,
            )
        if parsed.username is not None or parsed.password is not None:
            return (
                f"{profile_path.name}: credentials are forbidden in links: {link!r}",
                None,
            )
        hostname = parsed.hostname
        if (
            hostname is None
            or not hostname.isascii()
            or hostname != hostname.lower()
            or hostname.endswith(".")
            or any(label.startswith("xn--") for label in hostname.split("."))
        ):
            return (
                f"{profile_path.name}: hostname must be normalized ASCII: {link!r}",
                None,
            )
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            return (
                f"{profile_path.name}: IP literal links are forbidden: {link!r}",
                None,
            )
        if NUMERIC_HOST_RE.fullmatch(hostname) or not PUBLIC_HOST_RE.fullmatch(
            hostname
        ):
            return f"{profile_path.name}: public domain required in link {link!r}", None
        if (
            hostname in NON_PUBLIC_DNS_NAMES
            or hostname.endswith(NON_PUBLIC_DNS_SUFFIXES)
            or hostname.endswith(".localtest.me")
        ):
            return (
                f"{profile_path.name}: special-use hostname forbidden in link {link!r}",
                None,
            )
        try:
            port = parsed.port
        except ValueError:
            return f"{profile_path.name}: invalid port in link {link!r}", None
        if port is not None:
            return f"{profile_path.name}: explicit ports are forbidden: {link!r}", None
        if "//" in parsed.path or any(
            segment in {".", ".."} for segment in parsed.path.split("/")
        ):
            return f"{profile_path.name}: non-canonical path in link {link!r}", None
        if parsed.netloc != hostname or urlunsplit(parsed) != link:
            return (
                f"{profile_path.name}: ambiguous or non-canonical HTTPS link {link!r}",
                None,
            )
        return None, link

    if parsed.netloc or link.startswith(("/", "//")):
        return (
            f"{profile_path.name}: repository-local link must be relative: {link!r}",
            None,
        )
    relative = link
    if not relative:
        return f"{profile_path.name}: invalid repository-local link {link!r}", None
    canonical_relative = relative[2:] if relative.startswith("./") else relative
    parts = canonical_relative.split("/")
    if (
        not canonical_relative
        or relative.startswith(("../", ".//"))
        or any(part in {"", ".", ".."} for part in parts)
        or ":" in parts[0]
    ):
        return f"{profile_path.name}: non-canonical local link {link!r}", None
    local = (profile_path.parent / canonical_relative).resolve()
    try:
        local.relative_to(ROOT.resolve())
    except ValueError:
        return f"{profile_path.name}: link escapes the repository: {link!r}", None
    if not local.exists():
        return f"{profile_path.name}: missing local target {link!r}", None
    return None, None


class RedirectPolicyError(urllib.error.HTTPError):
    """A redirect rejected before urllib can dispatch its destination request."""


def validate_raw_redirect_location(location: str) -> str | None:
    if (
        not location
        or unicodedata.normalize("NFKC", location) != location
        or CONTROL_RE.search(location)
        or INVALID_PERCENT_RE.search(location)
        or "\\" in location
        or any(character.isspace() for character in location)
    ):
        return "unsafe or non-normalized raw Location"
    return None


def resolve_public_addresses(hostname: str) -> tuple[frozenset[str] | None, str | None]:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(socket.getaddrinfo, hostname, 443, 0, socket.SOCK_STREAM)
    try:
        address_info = future.result(timeout=DNS_TIMEOUT_SECONDS)
    except FuturesTimeoutError:
        future.cancel()
        return None, f"DNS resolution timed out for {hostname}"
    except (OSError, ValueError):
        return None, f"DNS resolution failed for {hostname}"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if not address_info:
        return None, f"DNS resolution returned no addresses for {hostname}"
    if len(address_info) > MAX_DNS_ADDRESSES:
        return None, f"DNS resolution returned too many addresses for {hostname}"

    addresses: set[str] = set()
    for item in address_info:
        try:
            parsed_address = ipaddress.ip_address(item[4][0])
        except (IndexError, TypeError, ValueError):
            return None, f"DNS resolution returned an invalid address for {hostname}"
        if (
            not parsed_address.is_global
            or parsed_address.is_loopback
            or parsed_address.is_private
            or parsed_address.is_link_local
            or parsed_address.is_reserved
            or parsed_address.is_multicast
            or parsed_address.is_unspecified
        ):
            return None, f"DNS resolution returned non-public address for {hostname}"
        addresses.add(str(parsed_address))
    return frozenset(addresses), None


def pin_public_url(url: str, pinned_addresses: dict[str, frozenset[str]]) -> str | None:
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return "invalid URL syntax during DNS validation"
    if hostname is None:
        return "missing hostname during DNS validation"
    addresses, error = resolve_public_addresses(hostname)
    if error or addresses is None:
        return error or f"DNS resolution failed for {hostname}"
    previous = pinned_addresses.get(hostname)
    if previous is not None and previous != addresses:
        return f"DNS address drift for {hostname}"
    pinned_addresses[hostname] = addresses
    return None


def verify_public_url_before_io(
    url: str, pinned_addresses: dict[str, frozenset[str]]
) -> str | None:
    first_error = pin_public_url(url, pinned_addresses)
    if first_error:
        return first_error
    return pin_public_url(url, pinned_addresses)


class BoundHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose TCP peer must be an approved DNS answer."""

    def __init__(
        self,
        host: str,
        pinned_addresses: dict[str, frozenset[str]],
        port: int | None = None,
        *,
        timeout: object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        context: object | None = None,
        blocksize: int = 8192,
    ) -> None:
        super().__init__(
            host,
            port,
            timeout=timeout,
            source_address=source_address,
            context=context,
            blocksize=blocksize,
        )
        self._pinned_addresses = pinned_addresses

    def connect(self) -> None:
        if self._tunnel_host:
            raise OSError("proxy tunneling is forbidden for bound link checks")
        approved = self._pinned_addresses.get(self.host)
        if not approved:
            raise OSError(f"no approved transport addresses for {self.host}")

        last_error: OSError | None = None
        for address in sorted(approved):
            parsed_address = ipaddress.ip_address(address)
            family = socket.AF_INET6 if parsed_address.version == 6 else socket.AF_INET
            candidate = socket.socket(family, socket.SOCK_STREAM)
            try:
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    candidate.settimeout(self.timeout)
                if self.source_address:
                    candidate.bind(self.source_address)
                target = (
                    (address, self.port, 0, 0)
                    if family == socket.AF_INET6
                    else (address, self.port)
                )
                candidate.connect(target)
            except OSError as exc:
                last_error = exc
                candidate.close()
                continue
            self.sock = self._context.wrap_socket(candidate, server_hostname=self.host)
            return
        raise OSError(
            f"approved transport connection failed for {self.host}"
        ) from last_error


class BoundHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_addresses: dict[str, frozenset[str]]) -> None:
        super().__init__()
        self._pinned_addresses = pinned_addresses

    def https_open(self, request: urllib.request.Request) -> object:
        def connection_factory(host: str, **kwargs: object) -> BoundHTTPSConnection:
            return BoundHTTPSConnection(host, self._pinned_addresses, **kwargs)

        return self.do_open(connection_factory, request, context=self._context)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self, pinned_addresses: dict[str, frozenset[str]] | None = None
    ) -> None:
        super().__init__()
        self._visited: set[str] = set()
        self._redirect_count = 0
        self._pinned_addresses = (
            pinned_addresses if pinned_addresses is not None else {}
        )

    @staticmethod
    def _reject(
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        headers: object,
        reason: str,
    ) -> None:
        raise RedirectPolicyError(request.full_url, code, reason, headers, file_pointer)

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> urllib.request.Request | None:
        raw_error = validate_raw_redirect_location(new_url)
        if raw_error:
            self._reject(
                request,
                file_pointer,
                code,
                headers,
                f"unsafe redirect target {new_url!r}: {raw_error}",
            )
        try:
            target = urljoin(request.full_url, new_url)
        except ValueError:
            self._reject(
                request,
                file_pointer,
                code,
                headers,
                f"unsafe redirect target {new_url!r}: invalid URL syntax",
            )
        error, public_url = validate_link(target, PROFILE_DIR / "README.md")
        if error or public_url is None:
            self._reject(
                request,
                file_pointer,
                code,
                headers,
                f"unsafe redirect target {new_url!r}: {error or 'public URL required'}",
            )
        dns_error = verify_public_url_before_io(public_url, self._pinned_addresses)
        if dns_error:
            self._reject(
                request,
                file_pointer,
                code,
                headers,
                f"unsafe redirect target {new_url!r}: {dns_error}",
            )

        self._visited.add(request.full_url)
        if public_url in self._visited:
            self._reject(
                request,
                file_pointer,
                code,
                headers,
                f"redirect loop detected at {public_url}",
            )
        if self._redirect_count >= MAX_REDIRECT_HOPS:
            self._reject(
                request,
                file_pointer,
                code,
                headers,
                f"too many redirects before {public_url}",
            )

        self._visited.add(public_url)
        self._redirect_count += 1
        return super().redirect_request(
            request, file_pointer, code, message, headers, public_url
        )


def find_contract_table(
    parsed: ParsedProfile, heading: str, profile_name: str, failures: list[str]
) -> tuple[tuple[Cell, ...], ...] | None:
    matches = [
        table
        for table in parsed.tables
        if table and table[0] and table[0][0].text == heading
    ]
    if len(matches) != 1:
        failures.append(
            f"{profile_name}: expected exactly one {heading!r} application table, found {len(matches)}"
        )
        return None
    return matches[0]


def validate_profile(
    path: Path, expected: dict[str, object], visible_terms: list[str]
) -> tuple[list[str], set[str], list[str]]:
    failures: list[str] = []
    parsed = parse_markdown(path.read_text(encoding="utf-8"))
    identity = str(expected["identity"])
    discovery_heading = str(expected["discovery_heading"])

    if parsed.headings.count((1, identity)) != 1:
        failures.append(
            f"{path.name}: expected exactly one visible H1 identity {identity!r}"
        )
    if parsed.headings.count((2, discovery_heading)) != 1:
        failures.append(
            f"{path.name}: expected exactly one visible H2 {discovery_heading!r}"
        )
    if VOLATILE_GUIDANCE_RE.search(parsed.visible_text):
        failures.append(f"{path.name}: duplicates volatile setup guidance")
    for term in visible_terms:
        if term not in parsed.visible_text:
            failures.append(f"{path.name}: missing visible discovery identity {term!r}")
        if term in parsed.hidden_text:
            failures.append(f"{path.name}: deceptive hidden identity {term!r}")
    for required_link in expected["required_links"]:
        if required_link not in parsed.visible_links:
            failures.append(
                f"{path.name}: missing visible required link {required_link}"
            )

    identities: list[str] = []
    table = find_contract_table(
        parsed, str(expected["table_heading"]), path.name, failures
    )
    if table is not None:
        actual_rows: list[list[str]] = []
        for row in table[1:]:
            if len(row) != 3:
                failures.append(
                    f"{path.name}: application row must contain exactly three cells"
                )
                continue
            if len(row[1].links) != 1 or len(row[2].links) != 1:
                failures.append(
                    f"{path.name}: {row[0].text!r} must have exactly one guide and one owner link"
                )
                continue
            identities.append(row[0].text)
            actual_rows.append([row[0].text, row[1].links[0], row[2].links[0]])
        if actual_rows != expected["rows"]:
            failures.append(
                f"{path.name}: application guide/owner rows do not match the frozen contract"
            )

    public_urls: set[str] = set()
    for link in sorted(parsed.links):
        error, public_url = validate_link(link, path)
        if error:
            failures.append(error)
        elif public_url:
            public_urls.add(public_url)
    return failures, public_urls, identities


def check_contract() -> tuple[list[str], set[str]]:
    failures: list[str] = []
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected_profiles = contract["profiles"]
    actual_profiles = {path.name for path in PROFILE_DIR.glob("README*.md")}
    if actual_profiles != set(expected_profiles):
        failures.append(
            f"profile inventory mismatch: expected {sorted(expected_profiles)}, found {sorted(actual_profiles)}"
        )

    public_urls: set[str] = set()
    identities_by_profile: list[list[str]] = []
    for name, expected in expected_profiles.items():
        path = PROFILE_DIR / name
        if not path.is_file():
            failures.append(f"missing expected profile {name}")
            continue
        profile_failures, profile_urls, identities = validate_profile(
            path, expected, contract["visible_query_terms"]
        )
        failures.extend(profile_failures)
        public_urls.update(profile_urls)
        identities_by_profile.append(identities)
    if identities_by_profile and any(
        items != identities_by_profile[0] for items in identities_by_profile[1:]
    ):
        failures.append(
            "English and Chinese application identities are not exactly aligned"
        )
    return failures, public_urls


def check_url(url: str) -> str | None:
    error, public_url = validate_link(url, PROFILE_DIR / "README.md")
    if error or public_url != url:
        return f"{url}: unsafe initial URL: {error or 'public URL required'}"
    pinned_addresses: dict[str, frozenset[str]] = {}
    dns_error = verify_public_url_before_io(url, pinned_addresses)
    if dns_error:
        return f"{url}: {dns_error}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "dcc-mcp-profile-link-check/2.0",
            "Accept": "text/html,*/*",
        },
    )
    last_error = "unknown error"
    for attempt in range(3):
        try:
            retry_dns_error = pin_public_url(url, pinned_addresses)
            if retry_dns_error:
                return f"{url}: {retry_dns_error}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                SafeRedirectHandler(pinned_addresses),
                BoundHTTPSHandler(pinned_addresses),
            )
            with opener.open(request, timeout=30) as response:
                response.read(1)
                final_url = response.geturl()
                final_error, final_public_url = validate_link(
                    final_url, PROFILE_DIR / "README.md"
                )
                if final_error or final_public_url != final_url:
                    return (
                        f"{url}: unsafe redirect destination {final_url!r}: "
                        f"{final_error or 'public URL required'}"
                    )
                final_dns_error = pin_public_url(final_url, pinned_addresses)
                if final_dns_error:
                    return f"{url}: {final_dns_error}"
                if 200 <= response.status < 400:
                    return None
                last_error = f"HTTP {response.status}"
        except RedirectPolicyError as exc:
            return f"{url}: {exc.reason}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(
                exc.reason if isinstance(exc, urllib.error.URLError) else exc
            )
        time.sleep(attempt + 1)
    return f"{url}: {last_error}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--links", action="store_true", help="check every public profile URL"
    )
    args = parser.parse_args()

    failures, urls = check_contract()
    if args.links and not failures:
        with ThreadPoolExecutor(max_workers=8) as executor:
            failures.extend(
                error for error in executor.map(check_url, sorted(urls)) if error
            )
        print(f"Checked {len(urls)} unique public URLs.")

    if failures:
        print("Profile contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Visible profile identity, ownership, and link contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
