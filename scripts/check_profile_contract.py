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
from urllib.parse import unquote, urldefrag, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "profile_contract.json"
VOLATILE_GUIDANCE_RE = re.compile(
    r"(?:clawhub@\d|pip install|openclaw skills install)", re.IGNORECASE
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
SAFE_FRAGMENT_RE = re.compile(r"^#[A-Za-z0-9][A-Za-z0-9._:-]*$")


@dataclass(frozen=True)
class Cell:
    text: str
    links: tuple[str, ...]


@dataclass(frozen=True)
class ParsedProfile:
    visible_text: str
    headings: tuple[tuple[int, str], ...]
    tables: tuple[tuple[tuple[Cell, ...], ...], ...]
    links: frozenset[str]


class VisibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() in {"href", "src"} and value is not None:
                self.links.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def normalize_text(parts: list[str] | tuple[str, ...] | str) -> str:
    if isinstance(parts, str):
        return " ".join(parts.split())
    return " ".join(" ".join(parts).split())


def parse_html(value: str) -> tuple[list[str], list[str]]:
    parser = VisibleHtmlParser()
    parser.feed(value)
    parser.close()
    return parser.text, parser.links


def parse_inline(children: list[Token]) -> tuple[str, tuple[str, ...]]:
    text: list[str] = []
    links: list[str] = []
    for child in children:
        if child.type in {"text", "code_inline"}:
            text.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            text.append(" ")
        elif child.type == "link_open":
            href = child.attrGet("href")
            if href is not None:
                links.append(href)
        elif child.type == "image":
            src = child.attrGet("src")
            if src is not None:
                links.append(src)
            text.append(child.content)
        elif child.type == "html_inline":
            html_text, html_links = parse_html(child.content)
            text.extend(html_text)
            links.extend(html_links)
    return normalize_text(text), tuple(links)


def parse_markdown(text: str) -> ParsedProfile:
    markdown = MarkdownIt("commonmark").enable("table")
    # Expose every destination as a token; the validator below fails closed.
    markdown.validateLink = lambda _url: True
    markdown.normalizeLink = lambda url: url
    tokens = markdown.parse(text)

    visible: list[str] = []
    headings: list[tuple[int, str]] = []
    tables: list[tuple[tuple[Cell, ...], ...]] = []
    links: set[str] = set()
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
            inline_text, inline_links = parse_inline(token.children or [])
            visible.append(inline_text)
            links.update(inline_links)
            if heading_level is not None:
                headings.append((heading_level, inline_text))
            if current_cell is not None:
                current_cell = Cell(inline_text, inline_links)
        elif token.type == "html_block":
            html_text, html_links = parse_html(token.content)
            visible.extend(html_text)
            links.update(html_links)

    return ParsedProfile(
        visible_text=normalize_text(visible),
        headings=tuple(headings),
        tables=tuple(tables),
        links=frozenset(links),
    )


def validate_link(link: str, profile_path: Path) -> tuple[str | None, str | None]:
    if (
        not link
        or unicodedata.normalize("NFKC", link) != link
        or CONTROL_RE.search(link)
    ):
        return f"{profile_path.name}: unsafe or non-normalized link {link!r}", None
    decoded = unquote(link)
    if unicodedata.normalize("NFKC", decoded) != decoded or CONTROL_RE.search(decoded):
        return f"{profile_path.name}: unsafe encoded link {link!r}", None
    if "\\" in link or any(character.isspace() for character in link):
        return f"{profile_path.name}: ambiguous link {link!r}", None

    if link.startswith("#"):
        if not SAFE_FRAGMENT_RE.fullmatch(link):
            return f"{profile_path.name}: invalid local fragment {link!r}", None
        return None, None

    parsed = urlsplit(link)
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
        if parsed.hostname is None or parsed.hostname != parsed.hostname.encode(
            "idna"
        ).decode("ascii"):
            return (
                f"{profile_path.name}: hostname must be normalized ASCII: {link!r}",
                None,
            )
        try:
            port = parsed.port
        except ValueError:
            return f"{profile_path.name}: invalid port in link {link!r}", None
        expected_netloc = parsed.hostname + (f":{port}" if port is not None else "")
        if parsed.netloc != expected_netloc or urlunsplit(parsed) != link:
            return (
                f"{profile_path.name}: ambiguous or non-canonical HTTPS link {link!r}",
                None,
            )
        return None, urldefrag(link)[0]

    if parsed.netloc or link.startswith(("/", "//")):
        return (
            f"{profile_path.name}: repository-local link must be relative: {link!r}",
            None,
        )
    relative, _fragment = urldefrag(link)
    if (
        not relative
        or parsed.query
        or any(part == ".." for part in Path(relative).parts)
    ):
        return f"{profile_path.name}: invalid repository-local link {link!r}", None
    local = (profile_path.parent / relative).resolve()
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
    for required_link in expected["required_links"]:
        if required_link not in parsed.links:
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
