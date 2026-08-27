#!/usr/bin/env python3
"""Validate the organization profile's identity, discovery, and link contract."""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urldefrag, urlparse


ROOT = Path(__file__).resolve().parents[1]
PROFILES = (ROOT / "profile" / "README.md", ROOT / "profile" / "README_zh.md")
QUERY_TERMS = (
    "Maya MCP",
    "3ds Max MCP",
    "Blender MCP",
    "Unreal MCP",
    "Unity MCP",
    "Tuanjie MCP",
    "Godot MCP",
    "Maya CLI",
    "Blender CLI",
)
APPLICATIONS = {
    "maya": "dcc-mcp-maya",
    "3ds-max": "dcc-mcp-3dsmax",
    "blender": "dcc-mcp-blender",
    "unreal-engine": "dcc-mcp-unreal",
    "unity": "dcc-mcp-unity",
    "godot": "dcc-mcp-godot",
}
URL_RE = re.compile(r"(?:\[[^]]*\]\(([^ )]+)|(?:href|src)=\"([^\"]+)\")")


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def extract_links(text: str) -> set[str]:
    return {next(value for value in match.groups() if value) for match in URL_RE.finditer(text)}


def check_contract() -> tuple[list[str], set[str]]:
    failures: list[str] = []
    texts = {path: path.read_text(encoding="utf-8") for path in PROFILES}
    english = texts[PROFILES[0]]
    chinese = texts[PROFILES[1]]

    for path, text in texts.items():
        require("# DCC MCP" in text, f"{path.name}: missing DCC MCP identity", failures)
        require("https://dcc-mcp.github.io/" in text, f"{path.name}: missing official website", failures)
        require("https://github.com/dcc-mcp/dcc-mcp-core" in text, f"{path.name}: missing Core owner link", failures)
        require(not re.search(r"(?:clawhub@\d|pip install|openclaw skills install)", text, re.I),
                f"{path.name}: duplicates volatile setup guidance", failures)

        links = extract_links(text)
        for slug, adapter in APPLICATIONS.items():
            guide = f"https://dcc-mcp.github.io/{'zh/' if path == PROFILES[1] else ''}control/{slug}"
            owner = f"https://github.com/dcc-mcp/{adapter}"
            require(guide in links, f"{path.name}: missing canonical guide {guide}", failures)
            require(owner in links, f"{path.name}: missing owning adapter {owner}", failures)

        for link in links:
            parsed = urlparse(link)
            if parsed.scheme or link.startswith("#"):
                continue
            local = (path.parent / urldefrag(link)[0]).resolve()
            require(local.exists(), f"{path.name}: missing local target {link}", failures)

    for term in QUERY_TERMS:
        require(term in english, f"README.md: missing discovery term {term}", failures)
        require(term in chinese, f"README_zh.md: missing discovery term {term}", failures)
    require("3ds Max CLI" in english and "3ds Max CLI" in chinese,
            "profiles: missing 3ds Max CLI discovery term", failures)
    require("团结引擎" in english and "团结引擎" in chinese,
            "profiles: missing Tuanjie Chinese identity", failures)

    urls = set().union(*(extract_links(text) for text in texts.values()))
    return failures, {urldefrag(url)[0] for url in urls if url.startswith(("http://", "https://"))}


def check_url(url: str) -> str | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "dcc-mcp-profile-link-check/1.0", "Accept": "text/html,*/*"},
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
            last_error = str(exc.reason if isinstance(exc, urllib.error.URLError) else exc)
        time.sleep(attempt + 1)
    return f"{url}: {last_error}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", action="store_true", help="check every public profile URL")
    args = parser.parse_args()

    failures, urls = check_contract()
    if args.links:
        with ThreadPoolExecutor(max_workers=8) as executor:
            failures.extend(error for error in executor.map(check_url, sorted(urls)) if error)
        print(f"Checked {len(urls)} unique public URLs.")

    if failures:
        print("Profile contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Profile identity and discovery contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
