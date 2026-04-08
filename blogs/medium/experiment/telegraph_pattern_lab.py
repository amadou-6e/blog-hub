from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from html import escape
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests


_HERE = Path(__file__).resolve().parent
_BLOG_HUB_ROOT = _HERE.parents[2]
if str(_BLOG_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_BLOG_HUB_ROOT))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from blogs.medium.import_flow import import_url_via_medium
from blogs.medium._render import render_medium_markdown


_FIXTURES_DIR = Path(_HERE, "fixtures")
_PATTERN_MARKDOWN = Path(_FIXTURES_DIR, "telegraph_breaking_patterns.md")
_PATTERN_MANUAL_HTML = Path(_FIXTURES_DIR, "telegraph_breaking_patterns_manual.html")
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
    heading_alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class TelegraphVariant:
    name: str
    title_suffix: str
    line_break_mode: str
    empty_line_mode: str
    language_mode: str = "none"
    tag_mode: str = "pre"
    code_class_mode: str = "none"
    indentation_mode: str = "raw"


_VARIANTS = (
    TelegraphVariant(
        name="pre_br_nbsp",
        title_suffix="pre-br-nbsp",
        line_break_mode="br",
        empty_line_mode="nbsp",
    ),
    TelegraphVariant(
        name="pre_br_empty",
        title_suffix="pre-br-empty",
        line_break_mode="br",
        empty_line_mode="empty",
    ),
    TelegraphVariant(
        name="pre_newline_nbsp",
        title_suffix="pre-newline-nbsp",
        line_break_mode="newline",
        empty_line_mode="nbsp",
    ),
    TelegraphVariant(
        name="pre_newline_empty",
        title_suffix="pre-newline-empty",
        line_break_mode="newline",
        empty_line_mode="empty",
    ),
)

_LANGUAGE_VARIANTS = (
    TelegraphVariant(
        name="lang_none",
        title_suffix="lang-none",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        language_mode="none",
    ),
    TelegraphVariant(
        name="lang_label_plain",
        title_suffix="lang-label-plain",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        language_mode="plain_label",
    ),
    TelegraphVariant(
        name="lang_label_code",
        title_suffix="lang-label-code",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        language_mode="code_label",
    ),
)

_TAG_VARIANTS = (
    TelegraphVariant(
        name="tag_pre",
        title_suffix="tag-pre",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre",
    ),
    TelegraphVariant(
        name="tag_pre_code",
        title_suffix="tag-pre-code",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre_code",
    ),
    TelegraphVariant(
        name="tag_code",
        title_suffix="tag-code",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="code",
    ),
    TelegraphVariant(
        name="tag_plain",
        title_suffix="tag-plain",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="plain",
    ),
)

_CLASS_VARIANTS = (
    TelegraphVariant(
        name="tag_pre_code_class_language",
        title_suffix="tag-pre-code-class-language",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre_code",
        code_class_mode="language_prefixed",
    ),
    TelegraphVariant(
        name="tag_pre_code_class_raw",
        title_suffix="tag-pre-code-class-raw",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre_code",
        code_class_mode="raw_language",
    ),
    TelegraphVariant(
        name="tag_code_class_language",
        title_suffix="tag-code-class-language",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="code",
        code_class_mode="language_prefixed",
    ),
    TelegraphVariant(
        name="tag_code_class_raw",
        title_suffix="tag-code-class-raw",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="code",
        code_class_mode="raw_language",
    ),
)

_INDENTATION_VARIANTS = (
    TelegraphVariant(
        name="indent_raw_spaces",
        title_suffix="indent-raw-spaces",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre",
        indentation_mode="raw",
    ),
    TelegraphVariant(
        name="indent_leading_nbsp",
        title_suffix="indent-leading-nbsp",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre",
        indentation_mode="leading_nbsp",
    ),
    TelegraphVariant(
        name="indent_leading_four_nbsp",
        title_suffix="indent-leading-four-nbsp",
        line_break_mode="newline",
        empty_line_mode="nbsp",
        tag_mode="pre",
        indentation_mode="leading_four_nbsp",
    ),
)

_LONG_BLOCK_VARIANTS = (
    TelegraphVariant(
        name="long_block_pre_code_raw_indent",
        title_suffix="long-block-pre-code-raw-indent",
        line_break_mode="br",
        empty_line_mode="empty",
        tag_mode="pre_code",
        code_class_mode="raw_language",
        indentation_mode="raw",
    ),
    TelegraphVariant(
        name="long_block_pre_code_nbsp_indent",
        title_suffix="long-block-pre-code-nbsp-indent",
        line_break_mode="br",
        empty_line_mode="empty",
        tag_mode="pre_code",
        code_class_mode="raw_language",
        indentation_mode="leading_nbsp",
    ),
    TelegraphVariant(
        name="long_block_pre_code_tab_indent",
        title_suffix="long-block-pre-code-tab-indent",
        line_break_mode="br",
        empty_line_mode="empty",
        tag_mode="pre_code",
        code_class_mode="raw_language",
        indentation_mode="leading_tabs",
    ),
)


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
    run_line_break_matrix()
    run_language_matrix()
    run_tag_matrix()


def run_indentation_matrix() -> None:
    session_file = _find_session_file()
    if session_file is None:
        raise RuntimeError("No Medium session file found.")

    markdown_text = _PATTERN_MARKDOWN.read_text(encoding="utf-8")
    summary: list[dict] = []
    for variant in _INDENTATION_VARIANTS:
        telegraph_url = ensure_telegraph_page(markdown_text, variant)
        result = import_url_to_medium_and_dump(telegraph_url, session_file, variant.name)
        pattern_report = build_pattern_report(result["editor_html"], result["full_page_html"])
        report_path = Path(result["dump_dir"], "pattern_report.json")
        report_path.write_text(json.dumps(pattern_report, indent=2), encoding="utf-8")
        summary.append(
            {
                "variant": variant.name,
                "telegraph_url": telegraph_url,
                "draft_url": result["draft_url"],
                "dump_dir": result["dump_dir"],
                "pattern_report": str(report_path),
                "total_pre_blocks": pattern_report["total_pre_blocks"],
                "patterns_with_all_code_markers": sum(
                    1 for item in pattern_report["patterns"] if item["all_code_markers_found"]
                ),
            }
        )
        print(f"[experiment:{variant.name}] Telegraph URL: {telegraph_url}")
        print(f"[experiment:{variant.name}] Draft URL    : {result['draft_url']}")
        print(f"[experiment:{variant.name}] Dump dir     : {result['dump_dir']}")
        print(f"[experiment:{variant.name}] Pattern report: {report_path}")

    summary_path = Path(_MEDIUM_DUMP_DIR, f"telegraph_indentation_summary_{time.strftime('%Y%m%dT%H%M%S')}.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[experiment] Indentation summary report: {summary_path}")


def run_line_break_matrix() -> None:
    session_file = _find_session_file()
    if session_file is None:
        raise RuntimeError("No Medium session file found.")

    markdown_text = _PATTERN_MARKDOWN.read_text(encoding="utf-8")
    summary: list[dict] = []
    for variant in _VARIANTS:
        telegraph_url = ensure_telegraph_page(markdown_text, variant)
        result = import_url_to_medium_and_dump(telegraph_url, session_file, variant.name)
        pattern_report = build_pattern_report(result["editor_html"], result["full_page_html"])
        report_path = Path(result["dump_dir"], "pattern_report.json")
        report_path.write_text(json.dumps(pattern_report, indent=2), encoding="utf-8")
        summary.append(
            {
                "variant": variant.name,
                "telegraph_url": telegraph_url,
                "draft_url": result["draft_url"],
                "dump_dir": result["dump_dir"],
                "pattern_report": str(report_path),
                "total_pre_blocks": pattern_report["total_pre_blocks"],
                "patterns_with_all_code_markers": sum(
                    1 for item in pattern_report["patterns"] if item["all_code_markers_found"]
                ),
            }
        )
        print(f"[experiment:{variant.name}] Telegraph URL: {telegraph_url}")
        print(f"[experiment:{variant.name}] Draft URL    : {result['draft_url']}")
        print(f"[experiment:{variant.name}] Dump dir     : {result['dump_dir']}")
        print(f"[experiment:{variant.name}] Pattern report: {report_path}")

    summary_path = Path(_MEDIUM_DUMP_DIR, f"telegraph_variant_summary_{time.strftime('%Y%m%dT%H%M%S')}.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[experiment] Line-break summary report: {summary_path}")


def run_language_matrix() -> None:
    session_file = _find_session_file()
    if session_file is None:
        raise RuntimeError("No Medium session file found.")

    markdown_text = _PATTERN_MARKDOWN.read_text(encoding="utf-8")
    summary: list[dict] = []
    for variant in _LANGUAGE_VARIANTS:
        telegraph_url = ensure_telegraph_page(markdown_text, variant)
        result = import_url_to_medium_and_dump(telegraph_url, session_file, variant.name)
        pattern_report = build_pattern_report(result["editor_html"], result["full_page_html"])
        report_path = Path(result["dump_dir"], "pattern_report.json")
        report_path.write_text(json.dumps(pattern_report, indent=2), encoding="utf-8")
        summary.append(
            {
                "variant": variant.name,
                "telegraph_url": telegraph_url,
                "draft_url": result["draft_url"],
                "dump_dir": result["dump_dir"],
                "pattern_report": str(report_path),
                "total_pre_blocks": pattern_report["total_pre_blocks"],
                "patterns_with_all_code_markers": sum(
                    1 for item in pattern_report["patterns"] if item["all_code_markers_found"]
                ),
            }
        )
        print(f"[experiment:{variant.name}] Telegraph URL: {telegraph_url}")
        print(f"[experiment:{variant.name}] Draft URL    : {result['draft_url']}")
        print(f"[experiment:{variant.name}] Dump dir     : {result['dump_dir']}")
        print(f"[experiment:{variant.name}] Pattern report: {report_path}")

    summary_path = Path(_MEDIUM_DUMP_DIR, f"telegraph_language_summary_{time.strftime('%Y%m%dT%H%M%S')}.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[experiment] Language summary report: {summary_path}")


def run_tag_matrix() -> None:
    session_file = _find_session_file()
    if session_file is None:
        raise RuntimeError("No Medium session file found.")

    markdown_text = _PATTERN_MARKDOWN.read_text(encoding="utf-8")
    summary: list[dict] = []
    for variant in _TAG_VARIANTS:
        telegraph_url = ensure_telegraph_page(markdown_text, variant)
        result = import_url_to_medium_and_dump(telegraph_url, session_file, variant.name)
        pattern_report = build_pattern_report(result["editor_html"], result["full_page_html"])
        report_path = Path(result["dump_dir"], "pattern_report.json")
        report_path.write_text(json.dumps(pattern_report, indent=2), encoding="utf-8")
        summary.append(
            {
                "variant": variant.name,
                "telegraph_url": telegraph_url,
                "draft_url": result["draft_url"],
                "dump_dir": result["dump_dir"],
                "pattern_report": str(report_path),
                "total_pre_blocks": pattern_report["total_pre_blocks"],
                "patterns_with_all_code_markers": sum(
                    1 for item in pattern_report["patterns"] if item["all_code_markers_found"]
                ),
            }
        )
        print(f"[experiment:{variant.name}] Telegraph URL: {telegraph_url}")
        print(f"[experiment:{variant.name}] Draft URL    : {result['draft_url']}")
        print(f"[experiment:{variant.name}] Dump dir     : {result['dump_dir']}")
        print(f"[experiment:{variant.name}] Pattern report: {report_path}")

    summary_path = Path(_MEDIUM_DUMP_DIR, f"telegraph_tag_summary_{time.strftime('%Y%m%dT%H%M%S')}.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[experiment] Tag summary report: {summary_path}")


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


def ensure_telegraph_page(markdown_text: str, variant: TelegraphVariant) -> str:
    token = _get_telegraph_access_token()
    rendered = render_medium_markdown(markdown_text, strip_planning_tail=False)
    base_title = rendered.title or "Medium Telegraph Breaking Patterns"
    title = f"{base_title} [{variant.title_suffix}]"
    body = re.sub(r"^\s*#[^#][^\n]*\n", "", rendered.body_markdown, count=1).strip()
    nodes = markdown_to_telegraph_nodes(body, variant)

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


def ensure_telegraph_page_from_html(html_text: str, variant: TelegraphVariant) -> str:
    token = _get_telegraph_access_token()
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.IGNORECASE | re.DOTALL)
    base_title = unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else "Medium Telegraph Breaking Patterns"
    title = f"{base_title} [{variant.title_suffix}]"
    nodes = html_to_telegraph_nodes(html_text, variant)

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


class _FixtureHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[dict | str] = []
        self._stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node: dict = {"tag": tag, "children": []}
        attrs_dict = {key: value for key, value in attrs if value is not None}
        if attrs_dict:
            node["attrs"] = attrs_dict
        self._append(node)
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1]["tag"] == tag:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        self._append(data)

    def _append(self, item: dict | str) -> None:
        if self._stack:
            self._stack[-1]["children"].append(item)
        else:
            self.root.append(item)


def html_to_telegraph_nodes(html_text: str, variant: TelegraphVariant) -> list[dict | str]:
    parser = _FixtureHtmlParser()
    parser.feed(html_text)
    return _transform_html_fixture_nodes(parser.root, variant)


def _transform_html_fixture_nodes(
    items: list[dict | str],
    variant: TelegraphVariant,
    *,
    inside_pre: bool = False,
) -> list[dict | str]:
    transformed: list[dict | str] = []
    for item in items:
        if isinstance(item, str):
            if inside_pre:
                transformed.append(item)
            elif item.strip():
                transformed.append(item.strip())
            continue

        tag = item["tag"]
        attrs = dict(item.get("attrs") or {})
        children = item.get("children") or []

        if tag == "pre":
            code_text, code_language = _extract_code_payload(children)
            code_lines = code_text.replace("\r\n", "\n").split("\n")
            transformed.append(_build_pre_node(code_lines, code_language, variant))
            continue

        if tag == "code" and not inside_pre:
            code_text, code_language = _extract_code_payload([item])
            code_lines = code_text.replace("\r\n", "\n").split("\n")
            transformed.append(_build_pre_node(code_lines, code_language, variant))
            continue

        mapped_tag = {"h1": "h3", "h2": "h3", "h3": "h4"}.get(tag, tag)
        new_node: dict = {"tag": mapped_tag}
        if mapped_tag == "img":
            new_node["attrs"] = {key: value for key, value in attrs.items() if key in {"src", "alt"}}
            transformed.append(new_node)
            continue

        child_nodes = _transform_html_fixture_nodes(children, variant, inside_pre=(mapped_tag in {"pre", "code"}))
        if child_nodes:
            new_node["children"] = child_nodes
            transformed.append(new_node)
    return transformed


def _extract_code_payload(children: list[dict | str]) -> tuple[str, str]:
    language = ""
    text_parts: list[str] = []

    for child in children:
        if isinstance(child, str):
            text_parts.append(child)
            continue

        child_tag = child["tag"]
        child_attrs = dict(child.get("attrs") or {})
        if child_tag == "code":
            class_value = child_attrs.get("class", "")
            language = _extract_language_from_class(class_value)
            nested_text, nested_language = _extract_code_payload(child.get("children") or [])
            text_parts.append(nested_text)
            if nested_language:
                language = nested_language
            continue

        nested_text, nested_language = _extract_code_payload(child.get("children") or [])
        text_parts.append(nested_text)
        if nested_language and not language:
            language = nested_language

    return "".join(text_parts), language


def _extract_language_from_class(class_value: str) -> str:
    tokens = [token.strip() for token in class_value.split() if token.strip()]
    for token in tokens:
        if token.startswith("language-"):
            return token[len("language-") :]
    return tokens[0] if tokens else ""


def markdown_to_telegraph_nodes(markdown_body: str, variant: TelegraphVariant) -> list[dict | str]:
    lines = markdown_body.replace("\r\n", "\n").strip().split("\n")
    nodes: list[dict | str] = []
    paragraph_lines: list[str] = []
    quote_lines: list[str] = []
    list_lines: list[str] = []
    in_code = False
    code_lines: list[str] = []
    code_language = ""

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            paragraph = _inline_markdown_to_text(" ".join(line.strip() for line in paragraph_lines))
            nodes.append({"tag": "p", "children": [paragraph]})
            paragraph_lines = []

    def flush_quote() -> None:
        nonlocal quote_lines
        if quote_lines:
            nodes.append({"tag": "blockquote", "children": [" ".join(quote_lines)]})
            quote_lines = []

    def flush_list() -> None:
        nonlocal list_lines
        if list_lines:
            nodes.append(
                {
                    "tag": "ul",
                    "children": [
                        {"tag": "li", "children": [_inline_markdown_to_text(line[2:].strip())]}
                        for line in list_lines
                    ],
                }
            )
            list_lines = []

    def flush_code() -> None:
        nonlocal code_lines
        nonlocal code_language
        if not code_lines:
            return
        if nodes and isinstance(nodes[-1], dict) and nodes[-1].get("tag") == "pre":
            nodes.append({"tag": "p", "children": ["\u00a0"]})
        label_node = _build_language_label_node(code_language, variant)
        if label_node is not None:
            nodes.append(label_node)
        nodes.append(_build_pre_node(code_lines, code_language, variant))
        code_lines = []
        code_language = ""

    for raw_line in lines:
        stripped = raw_line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            flush_quote()
            flush_list()
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
                code_language = stripped[3:].strip()
            continue

        if in_code:
            code_lines.append(raw_line)
            continue

        if not stripped:
            flush_paragraph()
            flush_quote()
            flush_list()
            continue

        if stripped.startswith("### "):
            flush_paragraph()
            flush_quote()
            flush_list()
            nodes.append({"tag": "h4", "children": [stripped[4:].strip()]})
            continue

        if stripped.startswith("## "):
            flush_paragraph()
            flush_quote()
            flush_list()
            nodes.append({"tag": "h3", "children": [stripped[3:].strip()]})
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            quote_lines.append(stripped.lstrip("> ").rstrip())
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            flush_quote()
            list_lines.append(stripped)
            continue

        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph()
            flush_quote()
            flush_list()
            nodes.append(
                {
                    "tag": "img",
                    "attrs": {"src": image_match.group(2), "alt": image_match.group(1)},
                }
            )
            continue

        flush_quote()
        flush_list()
        paragraph_lines.append(raw_line)

    flush_paragraph()
    flush_quote()
    flush_list()
    flush_code()
    return nodes


def _build_pre_node(code_lines: list[str], code_language: str, variant: TelegraphVariant) -> dict:
    normalized_lines = [
        _normalize_indentation(line, variant) if line.strip() else ("\u00a0" if variant.empty_line_mode == "nbsp" else "")
        for line in code_lines
    ]
    if variant.line_break_mode == "newline":
        text_child = "\n".join(normalized_lines)
        linebreak_children = [text_child]
    else:
        linebreak_children = []
        for index, line in enumerate(normalized_lines):
            if index > 0:
                linebreak_children.append({"tag": "br"})
            linebreak_children.append(line)

    code_attrs = _build_code_attrs(code_language, variant)
    code_node = {"tag": "code", "children": linebreak_children}
    if code_attrs is not None:
        code_node["attrs"] = code_attrs

    if variant.tag_mode == "pre":
        return {"tag": "pre", "children": linebreak_children}
    if variant.tag_mode == "pre_code":
        return {"tag": "pre", "children": [code_node]}
    if variant.tag_mode == "code":
        return code_node
    if variant.tag_mode == "plain":
        return {"tag": "p", "children": linebreak_children}
    return {"tag": "pre", "children": linebreak_children}


def _build_code_attrs(code_language: str, variant: TelegraphVariant) -> dict | None:
    normalized = code_language.strip().lower()
    if not normalized or variant.code_class_mode == "none":
        return None
    if variant.code_class_mode == "language_prefixed":
        return {"class": f"language-{normalized}"}
    if variant.code_class_mode == "raw_language":
        return {"class": normalized}
    return None


def _normalize_indentation(line: str, variant: TelegraphVariant) -> str:
    if variant.indentation_mode == "raw":
        return line

    match = re.match(r"^( +)", line)
    if match is None:
        return line

    leading = match.group(1)
    rest = line[len(leading):]

    if variant.indentation_mode == "leading_nbsp":
        return ("\u00a0" * len(leading)) + rest

    if variant.indentation_mode == "leading_four_nbsp":
        groups = len(leading) // 4
        remainder = len(leading) % 4
        return ("\u00a0" * (groups * 4 + remainder)) + rest

    if variant.indentation_mode == "leading_tabs":
        groups = len(leading) // 4
        remainder = len(leading) % 4
        return ("\t" * groups) + (" " * remainder) + rest

    return line


def _build_language_label_node(language: str, variant: TelegraphVariant) -> dict | None:
    normalized = language.strip()
    if not normalized or variant.language_mode == "none":
        return None
    if variant.language_mode == "plain_label":
        return {"tag": "p", "children": [f"Language: {normalized}"]}
    if variant.language_mode == "code_label":
        return {"tag": "p", "children": ["Code language: ", {"tag": "code", "children": [normalized]}]}
    return None


def _inline_markdown_to_text(text: str) -> str:
    value = text
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    return escape(value, quote=False)


def import_url_to_medium_and_dump(telegraph_url: str, session_file: str, variant_name: str) -> dict:
    _wait_for_telegraph_reachability(telegraph_url)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    dump_dir = Path(_MEDIUM_DUMP_DIR, f"telegraph_patterns_{variant_name}_{timestamp}")
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
            if "/signin" in page.url or "/m/signin" in page.url or "/login" in page.url:
                raise RuntimeError(f"Medium redirected to login: {page.url}")

            draft_url = import_url_via_medium(page, telegraph_url, dump_dir=dump_dir)

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
                        "variant": variant_name,
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
    cleaned_pre_blocks = [_extract_pre_text(block) for block in pre_blocks]
    normalized_pre_blocks = [_normalize_medium_text(block) for block in cleaned_pre_blocks]
    normalized_editor_html = _normalize_medium_text(editor_html)
    normalized_full_page_html = _normalize_medium_text(full_page_html)
    expected_blocks = _load_expected_code_blocks()

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_pre_blocks": len(pre_blocks),
        "patterns": [],
    }

    for pattern in _PATTERNS:
        heading_candidates = [pattern.heading]
        if pattern.pattern_id == "pattern_08":
            heading_candidates.append("Subheading for Pattern 08")
        marker_hits = {
            marker: any(_normalize_medium_text(marker) in block for block in normalized_pre_blocks)
            for marker in pattern.code_markers
        }
        layout_by_marker = {
            marker: _build_marker_layout_report(marker, cleaned_pre_blocks, expected_blocks)
            for marker in pattern.code_markers
        }
        layout_preserved = all(item["layout_preserved"] for item in layout_by_marker.values())
        report["patterns"].append(
            {
                "pattern_id": pattern.pattern_id,
                "heading": pattern.heading,
                "heading_found": any(
                    _normalize_medium_text(candidate) in normalized_full_page_html
                    or _normalize_medium_text(candidate) in normalized_editor_html
                    for candidate in heading_candidates
                ),
                "anchor": pattern.anchor,
                "anchor_found": _normalize_medium_text(pattern.anchor) in normalized_full_page_html
                or _normalize_medium_text(pattern.anchor) in normalized_editor_html,
                "code_markers": marker_hits,
                "all_code_markers_found": all(marker_hits.values()),
                "code_layout": layout_by_marker,
                "layout_preserved": layout_preserved,
                "flattened_suspected": not layout_preserved,
                "all_code_markers_preserved": all(marker_hits.values()) and layout_preserved,
            }
        )
    return report


def _extract_pre_text(raw_pre_html: str) -> str:
    code_part = re.sub(
        r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>',
        "",
        raw_pre_html,
        flags=re.DOTALL,
    )
    code_part = re.sub(r"<br\s*/?>", "\n", code_part, flags=re.IGNORECASE)
    code_part = re.sub(r"</(p|div|li|blockquote|h[1-6])>", "\n", code_part, flags=re.IGNORECASE)
    text = unescape(re.sub(r"<[^>]+>", "", code_part))
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _load_expected_code_blocks() -> dict[str, dict]:
    markdown_text = _PATTERN_MARKDOWN.read_text(encoding="utf-8")
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    code_blocks: list[list[str]] = []
    in_code = False
    current_lines: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            if in_code:
                code_blocks.append(current_lines[:])
                current_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            current_lines.append(raw_line)

    expected: dict[str, dict] = {}
    for pattern in _PATTERNS:
        for marker in pattern.code_markers:
            normalized_marker = _normalize_medium_text(marker)
            for block_lines in code_blocks:
                block_text = "\n".join(block_lines)
                if normalized_marker in _normalize_medium_text(block_text):
                    expected[marker] = {
                        "expected_line_count": len(block_lines),
                        "expected_nonempty_line_count": sum(1 for line in block_lines if line.strip()),
                    }
                    break
    return expected


def _build_marker_layout_report(
    marker: str,
    cleaned_pre_blocks: list[str],
    expected_blocks: dict[str, dict],
) -> dict:
    normalized_marker = _normalize_medium_text(marker)
    matched_block = next(
        (block for block in cleaned_pre_blocks if normalized_marker in _normalize_medium_text(block)),
        "",
    )
    matched_lines = [line for line in matched_block.splitlines() if line.strip()]
    expected = expected_blocks.get(
        marker,
        {
            "expected_line_count": 1,
            "expected_nonempty_line_count": 1,
        },
    )
    layout_preserved = len(matched_lines) >= expected["expected_nonempty_line_count"]
    return {
        "matched": bool(matched_block),
        "expected_line_count": expected["expected_line_count"],
        "expected_nonempty_line_count": expected["expected_nonempty_line_count"],
        "matched_nonempty_line_count": len(matched_lines),
        "layout_preserved": layout_preserved,
    }


def _normalize_medium_text(value: str) -> str:
    text = unescape(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("—", "-")
    text = text.replace("–", "-")
    text = text.replace("→", "->")
    text = text.replace("&", " & ")
    text = re.sub(r"([<>()[\]{}:=,+\"'])", r" \1 ", text)
    text = re.sub(r"\s*-\s*>\s*", " -> ", text)
    text = re.sub(r"(?<=\w)\s*-\s*(?=\w)", "-", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


if __name__ == "__main__":
    main()
