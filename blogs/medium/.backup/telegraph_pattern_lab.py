from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path

import requests


_HERE = Path(__file__).resolve().parent
_BLOG_HUB_ROOT = _HERE.parents[2]
if str(_BLOG_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_BLOG_HUB_ROOT))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from blogs.medium._render import render_medium_markdown


_FIXTURES_DIR = Path(_HERE, "fixtures")
_PATTERN_MARKDOWN = Path(_FIXTURES_DIR, "telegraph_breaking_patterns.md")
_MEDIUM_DUMP_DIR = Path(
    _BLOG_HUB_ROOT,
    "blogs",
    "medium",
    "tests",
    "fixtures",
    "medium_editor_dump",
)
_PY_DOCKERDB_ROOT = _BLOG_HUB_ROOT.parent
_TELEGRAPH_API = "https://api.telegra.ph"
_TELEGRAPH_TOKEN_FILE = Path(
    _BLOG_HUB_ROOT,
    "blogs",
    "medium",
    "tests",
    "fixtures",
    "telegraph_token.txt",
)
_SESSION_FILE_CANDIDATES = [
    os.environ.get("MEDIUM_SESSION_FILE", ""),
    r"C:\Users\acisse\Documents\CodeWorkspace\medium-mcp-server\medium-session.json",
    str(Path(_PY_DOCKERDB_ROOT, "article_publishing", "config", "medium-session.json")),
]
_BROWSER_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=VizDisplayCompositor,TranslateUI",
    "--disable-ipc-flooding-protection",
]
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class PatternExpectation:
    pattern_id: str
    heading: str
    anchor: str
    code_markers: tuple[str, ...]


_PATTERNS = (
    PatternExpectation(
        pattern_id="pattern_01",
        heading="Pattern 01 — Consecutive fenced blocks",
        anchor="PATTERN-01-ANCHOR",
        code_markers=("PATTERN-01-CODE",),
    ),
    PatternExpectation(
        pattern_id="pattern_02",
        heading="Pattern 02 — Empty lines inside code block",
        anchor="PATTERN-02-ANCHOR",
        code_markers=("return first + second",),
    ),
    PatternExpectation(
        pattern_id="pattern_03",
        heading="Pattern 03 — XML and comparison operators",
        anchor="PATTERN-03-ANCHOR",
        code_markers=("PATTERN-03-CODE", '<node id="pattern-03">'),
    ),
    PatternExpectation(
        pattern_id="pattern_04",
        heading="Pattern 04 — List directly before code",
        anchor="PATTERN-04-ANCHOR",
        code_markers=("MATCH (n:Paper)-[:CITES]->(m:Paper)",),
    ),
    PatternExpectation(
        pattern_id="pattern_05",
        heading="Pattern 05 — Paragraph directly after code",
        anchor="PATTERN-05-ANCHOR",
        code_markers=("PATTERN-05-CODE",),
    ),
    PatternExpectation(
        pattern_id="pattern_06",
        heading="Pattern 06 — Blockquote before code",
        anchor="PATTERN-06-ANCHOR",
        code_markers=('SELECT "PATTERN-06-CODE" AS marker',),
    ),
    PatternExpectation(
        pattern_id="pattern_07",
        heading="Pattern 07 — Long code block",
        anchor="PATTERN-07-ANCHOR",
        code_markers=("PATTERN-07-CODE",),
    ),
    PatternExpectation(
        pattern_id="pattern_08",
        heading="Pattern 08 — Heading immediately before code",
        anchor="PATTERN-08-ANCHOR",
        code_markers=("PATTERN-08-CODE",),
    ),
    PatternExpectation(
        pattern_id="pattern_09",
        heading="Pattern 09 — Two code blocks separated by a blank paragraph",
        anchor="PATTERN-09-ANCHOR",
        code_markers=("PATTERN-09-CODE-A", "PATTERN-09-CODE-B"),
    ),
    PatternExpectation(
        pattern_id="pattern_10",
        heading="Pattern 10 — Image-adjacent code marker",
        anchor="PATTERN-10-ANCHOR",
        code_markers=("PATTERN-10-CODE",),
    ),
)


def main() -> None:
    session_file = _find_session_file()
    if session_file is None:
        raise RuntimeError("No Medium session file found.")

    markdown_text = _PATTERN_MARKDOWN.read_text(encoding="utf-8")
    telegraph_url = ensure_telegraph_page(markdown_text)
    result = import_url_to_medium_and_dump(telegraph_url, session_file)
    pattern_report = build_pattern_report(result["editor_html"], result["full_page_html"])
    report_path = Path(result["dump_dir"], "pattern_report.json")
    report_path.write_text(json.dumps(pattern_report, indent=2), encoding="utf-8")

    print(f"[experiment] Telegraph URL: {telegraph_url}")
    print(f"[experiment] Draft URL    : {result['draft_url']}")
    print(f"[experiment] Dump dir     : {result['dump_dir']}")
    print(f"[experiment] Pattern report: {report_path}")


def _find_session_file() -> str | None:
    for candidate in _SESSION_FILE_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _get_telegraph_access_token() -> str:
    if _TELEGRAPH_TOKEN_FILE.exists():
        token = _TELEGRAPH_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token

    response = requests.post(
        f"{_TELEGRAPH_API}/createAccount",
        data={
            "short_name": "bloghub-medium-lab",
            "author_name": "BlogHub Medium Experiment",
        },
        timeout=30,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegraph createAccount failed: {payload}")
    token = payload["result"]["access_token"]
    _TELEGRAPH_TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def ensure_telegraph_page(markdown_text: str) -> str:
    token = _get_telegraph_access_token()
    rendered = render_medium_markdown(markdown_text, strip_planning_tail=False)
    title = rendered.title or "Medium Telegraph Breaking Patterns"
    body = re.sub(r"^\s*#[^#][^\n]*\n", "", rendered.body_markdown, count=1).strip()
    nodes = markdown_to_telegraph_nodes(body)

    existing_path = _find_existing_telegraph_path(token, title)
    if existing_path:
        response = requests.post(
            f"{_TELEGRAPH_API}/editPage/{existing_path}",
            data={
                "access_token": token,
                "title": title,
                "author_name": "BlogHub Medium Experiment",
                "content": json.dumps(nodes, ensure_ascii=False),
                "return_content": "true",
            },
            timeout=30,
        )
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegraph editPage failed: {payload}")
        return "https://telegra.ph/" + payload["result"]["path"]

    response = requests.post(
        f"{_TELEGRAPH_API}/createPage",
        data={
            "access_token": token,
            "title": title,
            "author_name": "BlogHub Medium Experiment",
            "content": json.dumps(nodes, ensure_ascii=False),
            "return_content": "true",
        },
        timeout=30,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegraph createPage failed: {payload}")
    return "https://telegra.ph/" + payload["result"]["path"]


def _find_existing_telegraph_path(token: str, title: str) -> str | None:
    response = requests.post(
        f"{_TELEGRAPH_API}/getPageList",
        data={
            "access_token": token,
            "offset": 0,
            "limit": 50,
        },
        timeout=30,
    )
    payload = response.json()
    if not payload.get("ok"):
        return None
    for page in payload["result"]["pages"]:
        if str(page.get("title") or "").strip() == title.strip():
            return page["path"]
    return None


def markdown_to_telegraph_nodes(markdown_body: str) -> list[dict | str]:
    blocks = re.split(r"\n\s*\n", markdown_body.replace("\r\n", "\n").strip())
    nodes: list[dict | str] = []
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue

        if stripped.startswith("```") and stripped.endswith("```"):
            code_lines = stripped.splitlines()[1:-1]
            children: list[dict | str] = []
            for index, line in enumerate(code_lines):
                if index > 0:
                    children.append({"tag": "br"})
                children.append(line if line.strip() else "\u00a0")
            if nodes and isinstance(nodes[-1], dict) and nodes[-1].get("tag") == "pre":
                nodes.append({"tag": "p", "children": ["\u00a0"]})
            nodes.append({"tag": "pre", "children": children})
            continue

        if stripped.startswith("### "):
            nodes.append({"tag": "h4", "children": [stripped[4:].strip()]})
            continue

        if stripped.startswith("## "):
            nodes.append({"tag": "h3", "children": [stripped[3:].strip()]})
            continue

        if stripped.startswith(">"):
            quote_lines = [line.lstrip("> ").rstrip() for line in stripped.splitlines()]
            nodes.append({"tag": "blockquote", "children": [" ".join(quote_lines)]})
            continue

        if all(line.startswith("- ") for line in stripped.splitlines()):
            nodes.append(
                {
                    "tag": "ul",
                    "children": [
                        {"tag": "li", "children": [line[2:].strip()]}
                        for line in stripped.splitlines()
                    ],
                }
            )
            continue

        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            nodes.append(
                {
                    "tag": "img",
                    "attrs": {"src": image_match.group(2), "alt": image_match.group(1)},
                }
            )
            continue

        paragraph = _inline_markdown_to_text(stripped)
        nodes.append({"tag": "p", "children": [paragraph]})
    return nodes


def _inline_markdown_to_text(text: str) -> str:
    value = text
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    return escape(value, quote=False)


def import_url_to_medium_and_dump(telegraph_url: str, session_file: str) -> dict:
    _wait_for_telegraph_reachability(telegraph_url)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    dump_dir = Path(_MEDIUM_DUMP_DIR, f"telegraph_patterns_{timestamp}")
    dump_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            slow_mo=80,
            args=_BROWSER_ARGS,
        )
        context = browser.new_context(
            storage_state=session_file,
            viewport={"width": 1280, "height": 720},
            user_agent=_USER_AGENT,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = context.new_page()
        page.set_default_timeout(120_000)
        page.set_default_navigation_timeout(120_000)

        try:
            page.goto("https://medium.com/p/import", wait_until="networkidle")
            page.wait_for_timeout(5000)

            Path(dump_dir, "import_page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(Path(dump_dir, "import_page.png")), full_page=True)

            if "/signin" in page.url or "/m/signin" in page.url or "/login" in page.url:
                raise RuntimeError(f"Medium redirected to login: {page.url}")

            try:
                page.wait_for_selector(
                    'div.js-importUrl[contenteditable="true"]',
                    state="visible",
                    timeout=30_000,
                )
            except PlaywrightTimeoutError:
                pass

            input_locator = None
            for selector in (
                'div.js-importUrl[contenteditable="true"]',
                'div.js-importUrl',
                'div[role="textbox"]',
                'input[placeholder*="URL"]',
                'input[type="url"]',
            ):
                try:
                    candidate = page.locator(selector).first
                    candidate.wait_for(state="visible", timeout=5000)
                    input_locator = candidate
                    break
                except PlaywrightTimeoutError:
                    continue

            if input_locator is None:
                raise RuntimeError("Could not locate Medium import URL field.")

            input_locator.click()
            input_locator.fill(telegraph_url)
            page.wait_for_timeout(1000)

            for selector in (
                'button[data-action="import-url"]',
                'button:has-text("Import")',
                'button[type="submit"]',
            ):
                try:
                    button = page.locator(selector).first
                    button.wait_for(state="visible", timeout=3000)
                    button.click()
                    break
                except PlaywrightTimeoutError:
                    continue

            page.wait_for_timeout(3000)
            page.screenshot(path=str(Path(dump_dir, "post_click.png")), full_page=True)

            page.wait_for_url(
                lambda url: re.search(r"medium\.com/p/.+/edit", url) is not None,
                timeout=180_000,
            )
            draft_url = page.url

            try:
                page.wait_for_selector('[contenteditable="true"]', timeout=20_000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(3000)

            page.evaluate(
                """() => new Promise(resolve => {
                    let pos = 0;
                    const step = () => {
                        pos += 600;
                        window.scrollTo(0, pos);
                        if (pos < document.body.scrollHeight) setTimeout(step, 150);
                        else resolve();
                    };
                    step();
                })"""
            )
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(600)

            full_page_html = page.content()
            editor_html = page.evaluate(
                """() => {
                    const candidates = [
                        document.querySelector('.postArticle-content'),
                        document.querySelector('.pw-editor'),
                        document.querySelector('[data-testid="richTextEditor"]'),
                        document.querySelector('.ProseMirror'),
                        document.querySelector('[contenteditable="true"]'),
                        document.body,
                    ];
                    for (const el of candidates) {
                        if (el && el.innerHTML && el.innerHTML.length > 100) return el.innerHTML;
                    }
                    return document.body.innerHTML;
                }"""
            )

            Path(dump_dir, "editor_dump.html").write_text(editor_html, encoding="utf-8")
            Path(dump_dir, "full_page.html").write_text(full_page_html, encoding="utf-8")
            Path(dump_dir, "meta.json").write_text(
                json.dumps(
                    {
                        "method": "telegraph_pattern_import",
                        "telegraph_url": telegraph_url,
                        "draft_url": draft_url,
                        "timestamp": timestamp,
                        "session_file": session_file,
                        "editor_html_bytes": len(editor_html.encode("utf-8")),
                        "full_page_html_bytes": len(full_page_html.encode("utf-8")),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            return {
                "draft_url": draft_url,
                "editor_html": editor_html,
                "full_page_html": full_page_html,
                "dump_dir": str(dump_dir),
            }
        finally:
            browser.close()


def _wait_for_telegraph_reachability(telegraph_url: str) -> None:
    for _ in range(6):
        try:
            response = requests.get(
                telegraph_url,
                timeout=10,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if response.status_code == 200 and len(response.text) > 1000:
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(f"Telegraph page not reachable after retries: {telegraph_url}")


def build_pattern_report(editor_html: str, full_page_html: str) -> dict:
    pre_blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre>", editor_html, re.IGNORECASE | re.DOTALL)
    cleaned_pre_blocks = [_strip_pre_ui(block) for block in pre_blocks]

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_pre_blocks": len(pre_blocks),
        "patterns": [],
    }

    for pattern in _PATTERNS:
        marker_hits = {
            marker: any(marker in block for block in cleaned_pre_blocks)
            for marker in pattern.code_markers
        }
        report["patterns"].append(
            {
                "pattern_id": pattern.pattern_id,
                "heading": pattern.heading,
                "heading_found": pattern.heading in full_page_html or pattern.heading in editor_html,
                "anchor": pattern.anchor,
                "anchor_found": pattern.anchor in full_page_html or pattern.anchor in editor_html,
                "code_markers": marker_hits,
                "all_code_markers_found": all(marker_hits.values()),
            }
        )
    return report


def _strip_pre_ui(raw_pre_html: str) -> str:
    code_part = re.sub(
        r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>',
        "",
        raw_pre_html,
        flags=re.DOTALL,
    )
    return re.sub(r"<[^>]+>", "", code_part).strip()


if __name__ == "__main__":
    main()
