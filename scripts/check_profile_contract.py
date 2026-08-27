#!/usr/bin/env python3
"""Validate visible profile semantics, identity ownership, and safe links."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "profile_contract.json"
VOLATILE_GUIDANCE_RE = re.compile(
    r"(?:clawhub@\d|pip install|openclaw skills install)", re.IGNORECASE
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
ESCAPED_HTML_RE = re.compile(
    r"(?:<!--|<\s*/?\s*(?:script|style|template|noscript|span|div|section)\b)",
    re.IGNORECASE,
)
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


class VisibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.hidden_text: list[str] = []
        self.links: list[str] = []
        self.visible_links: list[str] = []
        self._stack: list[tuple[str, bool]] = []

    @property
    def hidden(self) -> bool:
        return bool(self._stack and self._stack[-1][1])

    @staticmethod
    def _element_is_hidden(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in ALWAYS_HIDDEN_TAGS:
            return True
        normalized = {name.lower(): value for name, value in attrs}
        if "hidden" in normalized:
            return True
        aria_hidden = normalized.get("aria-hidden")
        if aria_hidden is not None and aria_hidden.strip().lower() == "true":
            return True
        style = normalized.get("style") or ""
        declarations = {}
        for declaration in style.split(";"):
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            declarations[name.strip().lower()] = (
                value.strip().lower().replace("!important", "").strip()
            )
        return (
            declarations.get("display") == "none"
            or declarations.get("visibility") == "hidden"
        )

    def add_link(self, value: str, hidden: bool | None = None) -> None:
        self.links.append(value)
        if not (self.hidden if hidden is None else hidden):
            self.visible_links.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        hidden = self.hidden or self._element_is_hidden(tag, attrs)
        if tag not in VOID_TAGS:
            self._stack.append((tag, hidden))
        for name, value in attrs:
            if name.lower() in {"href", "src"} and value is not None:
                self.add_link(value, hidden)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        hidden = self.hidden or self._element_is_hidden(tag.lower(), attrs)
        for name, value in attrs:
            if name.lower() in {"href", "src"} and value is not None:
                self.add_link(value, hidden)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if ESCAPED_HTML_RE.search(data):
            nested = VisibleHtmlParser()
            nested.feed(data)
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
            if not parser.hidden and ESCAPED_HTML_RE.search(child.content):
                parser.feed(child.content)
            else:
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

    parsed = urlsplit(link)
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
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read(1)
                if 200 <= response.status < 400:
                    return None
                last_error = f"HTTP {response.status}"
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
