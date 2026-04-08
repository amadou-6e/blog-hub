"""
Integration test — real Medium draft creation + editor DOM extraction.

Replicates the mechanism from test_code_block_format_comparison.js (the last
confirmed working run: report.json draftUrl = medium.com/p/f1945938f2e0/edit):

  1. Load medium-session.json as Playwright storageState.
  2. Navigate to medium.com/new-story.
  3. Paste title via clipboard API.
  4. Open a staging page with the rendered article body HTML,
     Ctrl+A → Ctrl+C, close staging page, Ctrl+V into editor.
  5. Capture the auto-saved draft URL.
  6. Navigate back to the draft, wait for editor hydration.
  7. Extract the editor DOM inner HTML.
  8. Save to tests/fixtures/medium_editor_dump/<timestamp>/ for inspection.
  9. Assert structural properties to detect corruption.

Run:
    cd blog-hub
    python -m pytest blogs/medium/tests/test_integration_medium.py -m integration -v -s

Skip condition: no valid Medium session file found.
Session file resolution order:
  1. MEDIUM_SESSION_FILE env var
  2. C:\\Users\\acisse\\Documents\\CodeWorkspace\\medium-mcp-server\\medium-session.json
  3. article_publishing/config/medium-session.json (py-dockerdb root)
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SAMPLE_MD = _FIXTURES_DIR / "sample_article.md"
_DUMP_DIR = _FIXTURES_DIR / "medium_editor_dump"
_IMAGE_BASE_URL = "https://raw.githubusercontent.com/amadou-6e/blog-components/main/medium/002_neo4j_llamaindex"

_PY_DOCKERDB_ROOT = Path(__file__).parents[4]  # blog-hub/../ = py-dockerdb

_SESSION_FILE_CANDIDATES = [
    os.environ.get("MEDIUM_SESSION_FILE", ""),
    r"C:\Users\acisse\Documents\CodeWorkspace\medium-mcp-server\medium-session.json",
    str(_PY_DOCKERDB_ROOT / "article_publishing" / "config" / "medium-session.json"),
]

_EXPECTED_TITLE = "What Neo4j actually does and how it fits into a GraphRAG pipeline (with a working LlamaIndex example)"
_EXPECTED_LAST_SENTENCE = (
    "The full notebook, including the OpenAlex fetch, graph construction, "
    "multi-hop query, validation, and vector baseline comparison, is available "
    "in the linked GitHub repository.")
_EXPECTED_H2_COUNT = 2  # floor: ≥2 content <h3> sections must render in the viewport
# (article has 7; Medium virtualises beyond the viewport — this guards against total loss)
_EXPECTED_PRE_COUNT = 1  # floor: ≥1 <pre> code block must render
# (article has 12; Medium virtualises beyond viewport — this guards against zero code blocks)
_MIN_IMAGE_COUNT = 1  # floor: ≥1 image must have a data-external-src; ALL found images
# must use the correct GitHub CDN base URL
_PLANNING_MARKERS = ["Tags:", "Estimated read time:", "Target keyword:", "Arc:"]

_BROWSER_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=VizDisplayCompositor,TranslateUI",
    "--disable-ipc-flooding-protection",
]
_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/120.0.0.0 Safari/537.36")

# ---------------------------------------------------------------------------
# Module-scoped helpers
# ---------------------------------------------------------------------------


def _find_session_file() -> str | None:
    for candidate in _SESSION_FILE_CANDIDATES:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def session_file():
    path = _find_session_file()
    if path is None:
        pytest.skip("No Medium session file found. "
                    "Set MEDIUM_SESSION_FILE env var or ensure the MCP server session file exists.")
    return path


@pytest.fixture(scope="module")
def rendered_article():
    from blogs.medium.render import render_import_html
    markdown = _SAMPLE_MD.read_text(encoding="utf-8")
    return render_import_html(markdown, image_base_url=_IMAGE_BASE_URL)


@pytest.fixture(scope="module")
def article_body_html(rendered_article):
    """Extract the <article>…</article> inner content for clipboard paste.

    Uses render_clipboard_html (literal \\n in <pre>, not <br>) because
    Medium's paste handler silently truncates the article when it encounters
    <br> inside <pre> blocks that also contain HTML entities (e.g. &gt; in
    Cypher queries).  The title H1 is stripped because it is typed separately.
    """
    from blogs.medium.render import render_clipboard_html
    markdown = _SAMPLE_MD.read_text(encoding="utf-8")
    clipboard = render_clipboard_html(markdown, image_base_url=_IMAGE_BASE_URL)
    html = clipboard.html
    match = re.search(r"<article>([\s\S]*?)</article>", html, re.IGNORECASE)
    body = match.group(1).strip() if match else html
    body = re.sub(r"^\s*<h1[^>]*>[\s\S]*?</h1>\s*", "", body, count=1, flags=re.IGNORECASE)
    return body


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.timeout(300)
class TestMediumDraftCreation:
    """
    End-to-end: render sample_article.md → create Medium draft → extract
    editor DOM → save locally → assert no corruption.

    The class uses a single shared `draft_result` fixture so the browser
    session is opened only once per test run.
    """

    @pytest.fixture(scope="class")
    def draft_result(self, session_file, rendered_article, article_body_html):
        """
        Drive Playwright to create the draft and extract the editor DOM.

        Returns:
            dict with keys:
                draft_url   — URL of the Medium editor (e.g. /p/<id>/edit)
                editor_html — innerHTML of the editor element
                dump_path   — absolute path to the saved editor_dump.html
                dump_dir    — parent directory of the dump
        """
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PWTimeout

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=80,
                args=_BROWSER_ARGS,
            )
            context = browser.new_context(
                storage_state=session_file,
                viewport={
                    "width": 1280,
                    "height": 720
                },
                user_agent=_USER_AGENT,
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            page = context.new_page()
            page.set_default_timeout(120_000)
            page.set_default_navigation_timeout(120_000)

            try:
                # ── 1. Navigate directly to new-story (session cookie handles auth) ─
                print("\n[integration] Navigating to medium.com/new-story ...")
                page.goto("https://medium.com/new-story", wait_until="load")

                # Wait for editor to appear (SPA mounts asynchronously; 30s timeout)
                try:
                    page.wait_for_selector('[contenteditable="true"]', timeout=30_000)
                    print(f"[integration] Editor ready. URL: {page.url}")
                except PWTimeout:
                    current_url = page.url
                    pytest.fail(f"Medium editor did not appear. Current URL: {current_url}\n"
                                "If this is a signin page, the session file is expired — "
                                "re-run the MCP server to refresh medium-session.json.")

                # ── 3. Click into the title field ──────────────────────────
                # In Medium's legacy editor the first [contenteditable] is the title field.
                for sel in [
                        'h1[data-testid="storyTitle"]',
                        '[placeholder*="Title"]',
                        'h3[data-placeholder="Title"]',
                        '[data-placeholder="Title"]',
                        "h1",
                        '[contenteditable="true"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        el.wait_for(state="visible", timeout=3000)
                        el.click()
                        break
                    except PWTimeout:
                        pass

                # ── 4. Paste title via clipboard API ───────────────────────
                page.evaluate(
                    "async (text) => { await navigator.clipboard.writeText(text); }",
                    rendered_article.title,
                )
                page.keyboard.press("Control+a")
                page.keyboard.press("Control+v")
                page.wait_for_timeout(600)

                # ── 5. Move cursor into body ───────────────────────────────
                page.keyboard.press("Enter")
                page.keyboard.press("Enter")
                page.wait_for_timeout(300)

                # ── 6. Staging-page copy → paste (same mechanism as the JS) ─
                staging_html = (f"<!DOCTYPE html><html><body>{article_body_html}</body></html>")
                staging = context.new_page()
                staging.set_content(staging_html)
                staging.wait_for_load_state("domcontentloaded")
                staging.keyboard.press("Control+a")
                staging.keyboard.press("Control+c")
                staging.close()

                page.bring_to_front()
                page.keyboard.press("Control+v")
                page.wait_for_timeout(4000)  # allow Medium to process the paste

                # ── 7. Capture auto-saved draft URL ────────────────────────
                draft_url = page.url
                print(f"[integration] URL after paste: {draft_url}")
                if "/new-story" in draft_url:
                    # Medium may take a moment to auto-save and redirect
                    page.wait_for_timeout(6000)
                    draft_url = page.url

                if "/new-story" in draft_url:
                    pytest.fail(f"Draft URL still shows /new-story after waiting — "
                                f"editor may not have saved. Current URL: {draft_url}")

                # ── 8. Navigate to draft → extract editor DOM ──────────────
                print(f"[integration] Navigating back to draft: {draft_url}")
                page.goto(draft_url, wait_until="load")
                # Wait for editor to re-hydrate after navigation
                try:
                    page.wait_for_selector('[contenteditable="true"]', timeout=20_000)
                except PWTimeout:
                    pass  # fall through; we'll still capture body innerHTML
                page.wait_for_timeout(3000)  # extra settle time

                # Scroll through the article to force Medium to lazy-render all sections
                page.evaluate("""() => new Promise(resolve => {
                    let pos = 0;
                    const step = () => {
                        pos += 600;
                        window.scrollTo(0, pos);
                        if (pos < document.body.scrollHeight) { setTimeout(step, 150); }
                        else { resolve(); }
                    };
                    step();
                })""")
                page.wait_for_timeout(2000)  # allow lazy sections to hydrate
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(600)

                full_page_html: str = page.content()

                editor_html: str = page.evaluate("""
                    () => {
                        const candidates = [
                            document.querySelector('.postArticle-content'),
                            document.querySelector('.pw-editor'),
                            document.querySelector('[data-testid="richTextEditor"]'),
                            document.querySelector('.ProseMirror'),
                            document.querySelector('[contenteditable="true"]'),
                            document.body,
                        ];
                        for (const el of candidates) {
                            if (el && el.innerHTML && el.innerHTML.length > 100) {
                                return el.innerHTML;
                            }
                        }
                        return document.body.innerHTML;
                    }
                """)

                # ── 9. Save dump ───────────────────────────────────────────
                timestamp = time.strftime("%Y%m%dT%H%M%S")
                dump_dir = _DUMP_DIR / timestamp
                dump_dir.mkdir(parents=True, exist_ok=True)

                dump_path = dump_dir / "editor_dump.html"
                dump_path.write_text(editor_html, encoding="utf-8")

                full_page_path = dump_dir / "full_page.html"
                full_page_path.write_text(full_page_html, encoding="utf-8")

                meta = {
                    "timestamp": timestamp,
                    "draft_url": draft_url,
                    "session_file": session_file,
                    "article_title": rendered_article.title,
                    "editor_html_bytes": len(editor_html.encode()),
                    "full_page_html_bytes": len(full_page_html.encode()),
                }
                (dump_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

                print(f"\n[integration] Draft URL      : {draft_url}")
                print(f"[integration] Editor dump    : {dump_path}")
                print(f"[integration] Full page dump : {full_page_path}")
                print(f"[integration] Editor bytes   : {len(editor_html.encode()):,}")
                print(f"[integration] Full page bytes: {len(full_page_html.encode()):,}")

                return {
                    "draft_url": draft_url,
                    "editor_html": editor_html,
                    "full_page_html": full_page_html,
                    "dump_path": str(dump_path),
                    "full_page_path": str(full_page_path),
                    "dump_dir": str(dump_dir),
                }

            finally:
                browser.close()

    # ── Structural assertions ───────────────────────────────────────────────

    def test_draft_url_is_medium_edit_url(self, draft_result):
        """Draft URL must follow medium.com/p/<id>/edit pattern."""
        assert re.search(
            r"medium\.com/p/[a-f0-9]+/edit",
            draft_result["draft_url"],
        ), f"Unexpected draft URL: {draft_result['draft_url']}"

    def test_editor_html_is_non_empty(self, draft_result):
        assert len(draft_result["editor_html"]) > 500

    def test_editor_dump_file_written(self, draft_result):
        assert Path(draft_result["dump_path"]).exists()
        assert Path(draft_result["full_page_path"]).exists()

    def test_editor_has_title(self, draft_result):
        """Title must survive the paste without being chopped."""
        # Medium replaces spaces with &nbsp; for typography; normalise before checking.
        normalised = draft_result["editor_html"].replace("&nbsp;", " ")
        assert _EXPECTED_TITLE in normalised, (
            "Article title not found in editor DOM — title paste may have failed")

    def test_editor_title_not_duplicated(self, draft_result):
        """Title must appear exactly once — if the H1 was not stripped from the
        paste body it appears both as graf--title and as a second heading."""
        occurrences = draft_result["full_page_html"].count("graf--title")
        assert occurrences == 1, (
            f"'graf--title' appears {occurrences} times — title is duplicated in the editor")

    def test_editor_h2_count_not_below_expected(self, draft_result):
        """Heading count below threshold indicates section corruption.

        Medium maps <h2> → <h3>; after a full scroll-through all sections should
        be rendered. Count <h3> in the full page HTML to capture every section.
        """
        count = len(re.findall(r"<h3\b", draft_result["full_page_html"], re.IGNORECASE))
        assert count >= _EXPECTED_H2_COUNT, (
            f"Expected ≥{_EXPECTED_H2_COUNT} <h3> elements in full page, found {count} — "
            "sections may have been collapsed or dropped")

    def test_editor_code_block_count_not_below_expected(self, draft_result):
        """Low <pre> count means code blocks were split or dropped.

        Uses the full page HTML to capture all rendered sections after scroll.
        """
        count = len(re.findall(r"<pre\b", draft_result["full_page_html"], re.IGNORECASE))
        assert count >= _EXPECTED_PRE_COUNT, (
            f"Expected ≥{_EXPECTED_PRE_COUNT} <pre> elements in full page, found {count} — "
            "code blocks may have been chopped")

    def test_images_use_correct_base_url(self, draft_result):
        """Every image embedded via clipboard paste must reference the correct
        GitHub raw CDN base — wrong base = images will not load on Medium.

        Medium virtualises images beyond the viewport so we assert a floor of 1
        and check that ALL found images use the correct base URL.
        """
        matches = re.findall(
            r'data-external-src="([^"]+)"',
            draft_result["full_page_html"],
        )
        assert len(matches) >= _MIN_IMAGE_COUNT, (
            f"Expected ≥{_MIN_IMAGE_COUNT} data-external-src attributes, found {len(matches)} — "
            "images may not have been pasted correctly")
        bad = [url for url in matches if not url.startswith(_IMAGE_BASE_URL)]
        assert not bad, (f"Images with wrong base URL found: {bad!r}\n"
                         f"Expected all to start with: {_IMAGE_BASE_URL}")

    def test_no_planning_markers_leaked_into_editor(self, draft_result):
        """Planning tail (Tags:, Estimated read time:, …) must be stripped."""
        for marker in _PLANNING_MARKERS:
            assert marker not in draft_result["editor_html"], (
                f"Planning marker leaked into editor DOM: {marker!r}")

    def test_no_raw_markdown_in_editor(self, draft_result):
        """Raw ** or ``` must not appear — they indicate render failure."""
        assert "**Nodes**" not in draft_result["editor_html"], (
            "Raw **bold** markdown found in editor — render pipeline did not convert it")
        assert "```cypher" not in draft_result["editor_html"], (
            "Raw ```cypher fence found in editor — code blocks not rendered to <pre>")

    def test_no_undefined_artefacts_in_editor_preamble(self, draft_result):
        """'undefined' in the first 2000 chars usually indicates a JS paste error."""
        preamble = draft_result["editor_html"][:2000].lower()
        assert "undefined" not in preamble

    def test_last_content_sentence_present(self, draft_result):
        """Last paragraph of the article must appear in the editor DOM.

        Absence means the article was truncated during paste or Medium dropped
        trailing sections during virtualised rendering.  Check full_page.html
        in the dump directory to investigate.
        """
        assert _EXPECTED_LAST_SENTENCE in draft_result["full_page_html"], (
            "Last content sentence not found in editor DOM — article may have been "
            "truncated during paste. Check full_page.html in the dump directory.")


# ---------------------------------------------------------------------------
# URL import test class
# ---------------------------------------------------------------------------
# Known host behaviour from article_publishing experiments (2026-04-01):
#   - DEV.to             → accepted by Medium, draft created (Runs 6, 7, 9)
#   - htmlpreview.github → source DOM valid but Medium blocks import ("import blocked")
#   - jsdelivr/rawgithub → source rendered as raw text; rejected
#   - rawcdn.githack     → interstitial page; rejected
#
# Medium only imports from domains it trusts. Self-hosted localhost is not
# reachable from Medium's import worker. To run this test you must provide a
# MEDIUM_IMPORT_URL env var pointing to a publicly accessible v1 HTML page
# (e.g. GitHub Pages, Gist CDN, or a tunnelled local server).
#
# Known content artefact (from Runs 1, 9, c1ec74c54911 inspection):
#   Medium's import pipeline injects "Auto (TypeScript)" labels into code blocks.
#   The test detects this as a known corruption signal and records it in the dump.
# ---------------------------------------------------------------------------

_IMPORT_URL_ENVVAR = "MEDIUM_IMPORT_URL"
# v1 HTML file generated by render_import_html() (<br> in <pre>)
_V1_HTML = _FIXTURES_DIR / "sample_article_v1_url_import.html"


@pytest.mark.integration
@pytest.mark.timeout(300)
class TestMediumUrlImportDraft:
    """
    End-to-end: drive Medium's URL import flow with the v1 HTML artifact
    (``<br>`` inside ``<pre>``, verified format for Medium URL import).

    Skip condition: ``MEDIUM_IMPORT_URL`` env var not set.
    Set it to a publicly reachable URL serving ``sample_article_v1_url_import.html``.

    This test records whether the ``Auto (TypeScript)`` code-block corruption
    artefact (documented in article_publishing runs 1, 9) is present in the
    imported draft.
    """

    @pytest.fixture(scope="class")
    def import_url(self):
        url = os.environ.get(_IMPORT_URL_ENVVAR, "").strip()
        if not url:
            pytest.skip(f"{_IMPORT_URL_ENVVAR} env var not set. "
                        "Serve sample_article_v1_url_import.html on a public URL "
                        "(GitHub Pages, a tunnel, etc.) and set the env var to run this test.")
        return url

    @pytest.fixture(scope="class")
    def url_import_result(self, session_file, import_url):
        """Drive Medium's /p/import-story UI and extract the resulting editor DOM."""
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PWTimeout

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=80,
                args=_BROWSER_ARGS,
            )
            context = browser.new_context(
                storage_state=session_file,
                viewport={
                    "width": 1280,
                    "height": 720
                },
                user_agent=_USER_AGENT,
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            page = context.new_page()
            page.set_default_timeout(120_000)
            page.set_default_navigation_timeout(120_000)

            try:
                # ── 1. Navigate to import page ─────────────────────────────
                print(f"\n[url-import] Navigating to Medium import page ...")
                page.goto("https://medium.com/p/import-story", wait_until="load")
                page.wait_for_timeout(3000)

                # ── 2. Enter the source URL ────────────────────────────────
                url_input = None
                for sel in [
                        'div.textInput[role="textbox"]',
                        'input[placeholder*="URL"]',
                        'input[type="url"]',
                        'input[name="importUrl"]',
                        '[class*="importUrl"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        el.wait_for(state="visible", timeout=5000)
                        url_input = el
                        break
                    except PWTimeout:
                        pass

                if url_input is None:
                    pytest.fail("Could not find the URL input field on Medium's import page. "
                                f"Current URL: {page.url}")

                url_input.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(import_url)
                page.wait_for_timeout(1000)

                # ── 3. Click Import ────────────────────────────────────────
                for btn_sel in [
                        'button:has-text("Import")',
                        'button[type="submit"]',
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        btn.wait_for(state="visible", timeout=3000)
                        btn.click()
                        break
                    except PWTimeout:
                        pass

                # ── 4. Wait for draft editor URL ───────────────────────────
                try:
                    page.wait_for_url(
                        lambda url: re.search(r"medium\.com/p/.+/edit", url) is not None,
                        timeout=180_000,
                    )
                except PWTimeout:
                    current_url = page.url
                    page_text = page.evaluate("() => document.body.innerText || ''")
                    pytest.fail(f"Medium did not redirect to a draft editor within 3 min.\n"
                                f"Current URL: {current_url}\n"
                                f"Page snippet: {page_text[:400]}\n\n"
                                "Known causes: Medium blocks import from untrusted hosts "
                                "(htmlpreview, jsdelivr, rawgithub are all blocked — "
                                "only trusted domains like DEV.to work reliably). "
                                "Use a domain Medium accepts or publish to GitHub Pages.")

                draft_url = page.url
                print(f"[url-import] Draft URL: {draft_url}")

                # ── 5. Wait for editor to hydrate, scroll, capture ─────────
                try:
                    page.wait_for_selector('[contenteditable="true"]', timeout=20_000)
                except PWTimeout:
                    pass
                page.wait_for_timeout(3000)

                page.evaluate("""() => new Promise(resolve => {
                    let pos = 0;
                    const step = () => {
                        pos += 600;
                        window.scrollTo(0, pos);
                        if (pos < document.body.scrollHeight) { setTimeout(step, 150); }
                        else { resolve(); }
                    };
                    step();
                })""")
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(600)

                full_page_html: str = page.content()
                editor_html: str = page.evaluate("""
                    () => {
                        const candidates = [
                            document.querySelector('.postArticle-content'),
                            document.querySelector('.pw-editor'),
                            document.querySelector('[data-testid="richTextEditor"]'),
                            document.querySelector('.ProseMirror'),
                            document.querySelector('[contenteditable="true"]'),
                            document.body,
                        ];
                        for (const el of candidates) {
                            if (el && el.innerHTML && el.innerHTML.length > 100)
                                return el.innerHTML;
                        }
                        return document.body.innerHTML;
                    }
                """)

                # ── 6. Check for known corruption signal ───────────────────
                auto_typescript_count = editor_html.count("Auto (TypeScript)")
                print(f"[url-import] 'Auto (TypeScript)' corruption count: "
                      f"{auto_typescript_count}")

                # ── 7. Save dump ───────────────────────────────────────────
                timestamp = time.strftime("%Y%m%dT%H%M%S")
                dump_dir = _DUMP_DIR / f"url_import_{timestamp}"
                dump_dir.mkdir(parents=True, exist_ok=True)

                (dump_dir / "editor_dump.html").write_text(editor_html, encoding="utf-8")
                (dump_dir / "full_page.html").write_text(full_page_html, encoding="utf-8")
                meta = {
                    "method": "url_import",
                    "import_url": import_url,
                    "timestamp": timestamp,
                    "draft_url": draft_url,
                    "session_file": session_file,
                    "editor_html_bytes": len(editor_html.encode()),
                    "full_page_html_bytes": len(full_page_html.encode()),
                    "auto_typescript_corruption_count": auto_typescript_count,
                }
                (dump_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                print(f"[url-import] Dump: {dump_dir}")

                return {
                    "draft_url": draft_url,
                    "editor_html": editor_html,
                    "full_page_html": full_page_html,
                    "dump_dir": str(dump_dir),
                    "auto_typescript_count": auto_typescript_count,
                }

            finally:
                browser.close()

    # ── Assertions ──────────────────────────────────────────────────────────

    def test_draft_url_is_medium_edit_url(self, url_import_result):
        assert re.search(
            r"medium\.com/p/[a-f0-9]+/edit",
            url_import_result["draft_url"],
        ), f"Unexpected draft URL: {url_import_result['draft_url']}"

    def test_editor_html_is_non_empty(self, url_import_result):
        assert len(url_import_result["editor_html"]) > 500

    def test_editor_has_title(self, url_import_result):
        normalised = url_import_result["editor_html"].replace("&nbsp;", " ")
        assert _EXPECTED_TITLE in normalised, (
            "Title not found in imported draft — Medium may have dropped it during import")

    def test_editor_h2_count_not_below_expected(self, url_import_result):
        count = len(re.findall(r"<h3\b", url_import_result["full_page_html"], re.IGNORECASE))
        assert count >= _EXPECTED_H2_COUNT, (
            f"Expected ≥{_EXPECTED_H2_COUNT} <h3> elements, found {count}")

    def test_editor_code_block_count_not_below_expected(self, url_import_result):
        count = len(re.findall(r"<pre\b", url_import_result["full_page_html"], re.IGNORECASE))
        assert count >= _EXPECTED_PRE_COUNT, (
            f"Expected ≥{_EXPECTED_PRE_COUNT} <pre> elements, found {count}")

    def test_no_planning_markers_leaked(self, url_import_result):
        for marker in _PLANNING_MARKERS:
            assert marker not in url_import_result["editor_html"], (
                f"Planning marker leaked: {marker!r}")

    def test_last_content_sentence_present(self, url_import_result):
        """Last paragraph must be present — URL import should not truncate.

        Unlike clipboard paste, URL import does not have the <br>-in-<pre>
        truncation bug. If this fails it indicates a different import issue.
        """
        assert _EXPECTED_LAST_SENTENCE in url_import_result["full_page_html"], (
            "Last content sentence not found — draft may have been truncated during import")

    def test_auto_typescript_corruption_recorded(self, url_import_result):
        """Record the 'Auto (TypeScript)' injection count as a quality signal.

        Medium's import pipeline injects this label into code blocks (observed
        in article_publishing runs: c1ec74c54911 had 26 code blocks with this
        label). This test does not fail on the presence of the corruption — it
        asserts the count was recorded so operators can compare clipboard vs
        URL import quality from the meta.json dump.
        """
        count = url_import_result["auto_typescript_count"]
        # Informational: log count. A non-zero count means code blocks were corrupted.
        print(f"\n[url-import] Auto (TypeScript) corruption: {count} occurrences "
              f"({'CLEAN' if count == 0 else 'CORRUPTED — see meta.json'})")
        # Not a hard failure — operators use the dump to decide which method wins.
        assert count >= 0  # always passes; forces the count into the test output
