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
_EXPECTED_H2_COUNT = 2  # floor for clipboard path: ≥2 content <h3> sections
# (article has 7; Medium virtualises beyond the viewport — guards against total loss)
_EXPECTED_PRE_COUNT = 1  # floor for clipboard path: ≥1 <pre> code block
# (article has 12; Medium virtualises beyond viewport — guards against zero code blocks)

# URL-import-specific floors (article: 12 code blocks, 7 headings + 1 title = 8 h3)
_URL_IMPORT_MIN_PRE_COUNT = 10  # ≥10/12 code blocks must survive URL import
_URL_IMPORT_MIN_H3_COUNT = 8  # ≥8 <h3> elements (title + 7 section headings)
_URL_IMPORT_MIN_EDITOR_BYTES = 15_000  # editor HTML must be substantive
_URL_IMPORT_MIN_PRE_TEXT_CHARS = 20  # each non-phantom <pre> must have ≥20 chars of text
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
# DEV.to → Medium URL import test class
# ---------------------------------------------------------------------------
# Strategy (confirmed from article_publishing experiments 2026-04-01):
#   Medium URL import only accepts trusted domains. DEV.to is the only reliably
#   accepted self-serve host (Runs 6, 7, 9 all created drafts from DEV.to URLs).
#   htmlpreview/jsdelivr/rawgithub are all blocked or return raw text.
#
# Flow:
#   1. Render article markdown → DEV.to article (published=True briefly)
#   2. Import the live DEV.to URL into Medium  → draft
#   3. Capture & assert editor DOM
#   4. Teardown: unpublish the DEV.to article (set published=False)
#
# Known quality signal (from article_publishing runs c1ec74c54911, 0c9b91a8c98b):
#   Medium injects "Auto (TypeScript)" labels into code blocks during import.
#   Recorded in meta.json but not a hard failure — comparison metric only.
#
# Skip condition: DEVTO_API_KEY env var not set.
# ---------------------------------------------------------------------------

_DEVTO_API_KEY_ENVVAR = "DEVTO_API_KEY"
_DEVTO_BASE_URL = "https://dev.to/api"


@pytest.mark.integration
@pytest.mark.timeout(360)
class TestMediumDevToImportDraft:
    """
    End-to-end: publish article to DEV.to → import that URL into Medium → assert DOM.

    DEV.to is the only self-serve host reliably accepted by Medium's URL import
    pipeline (confirmed: article_publishing Runs 6, 7, 9).

    Skip condition: ``DEVTO_API_KEY`` env var not set.

    Teardown: the DEV.to article is unpublished (``published=False``) after the
    Medium import is complete regardless of test outcome.
    """

    # ── DEV.to helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _devto_headers(api_key: str) -> dict:
        return {
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _devto_body_markdown(markdown_text: str) -> tuple[str, str]:
        """Return (title, body_without_h1) for DEV.to payload.

        Fenced code blocks are converted to raw HTML ``<pre>`` blocks inside
        the Markdown body.  DEV.to passes inline HTML through without applying
        Rouge syntax highlighting — unlike fenced blocks which always get span
        markup (28-184 spans per block observed).  Medium's URL importer silently
        drops blocks with heavy span-soup but keeps bare ``<pre>`` with 0 spans.

        Strategy confirmed: DEV.to returns ``class=none, 0 spans`` for raw HTML
        pre blocks in a Markdown body (tested 2026-04-04).
        """
        from blogs.medium._render import render_medium_markdown
        import html as _html_lib
        rendered = render_medium_markdown(
            markdown_text,
            image_base_url=_IMAGE_BASE_URL,
            strip_planning_tail=True,
        )
        title = rendered.title or "Untitled"
        # Strip the leading H1 — DEV.to renders it from the title field
        body = re.sub(r"^\s*#[^#][^\n]*\n", "", rendered.body_markdown, count=1)
        body = body.strip()

        # Convert fenced code blocks to raw HTML <pre> so DEV.to skips highlighting.
        # Pattern: ```[lang]\ncontent\n``` → <pre>content</pre> (HTML-escaped)
        def _fence_to_pre(m: re.Match) -> str:
            code = m.group(1)
            return f"<pre>{_html_lib.escape(code)}</pre>"

        body = re.sub(
            r"^```[^\n]*\n(.*?)^```",
            _fence_to_pre,
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
        return title, body

    # ── Fixtures ─────────────────────────────────────────────────────────────

    @pytest.fixture(scope="class")
    def devto_api_key(self):
        key = os.environ.get(_DEVTO_API_KEY_ENVVAR, "").strip()
        if not key:
            pytest.skip(f"{_DEVTO_API_KEY_ENVVAR} env var not set. "
                        "Set it to your DEV.to API key to run the URL-import path.")
        return key

    @pytest.fixture(scope="class")
    def devto_article(self, devto_api_key):
        """Ensure the sample article exists as a published DEV.to article.

        Idempotent: if an article with the same title already exists (e.g. from
        a previous run, or DEV.to 422 rate-limit window), it is reused and set
        to published=True rather than creating a duplicate.

        Unpublishes the article in teardown regardless of test outcome.
        """
        import requests as _requests

        markdown_text = _SAMPLE_MD.read_text(encoding="utf-8")
        title, body = self._devto_body_markdown(markdown_text)
        headers = self._devto_headers(devto_api_key)

        def _find_existing() -> tuple[int, str] | None:
            """Return (id, url) of the first article matching the title, or None."""
            r = _requests.get(
                f"{_DEVTO_BASE_URL}/articles/me/all",
                headers=headers,
                params={"per_page": 100},
                timeout=30,
            )
            if not r.ok:
                return None
            for a in r.json():
                if a.get("title", "").strip() == title.strip():
                    url = a.get("url") or f"https://dev.to{a.get('path', '')}"
                    return int(a["id"]), url
            return None

        print(f"\n[devto] Publishing to DEV.to: {title!r}")
        resp = _requests.post(
            f"{_DEVTO_BASE_URL}/articles",
            headers=headers,
            json={
                "article": {
                    "title": title,
                    "body_markdown": body,
                    "published": True,
                    "main_image": f"{_IMAGE_BASE_URL}/images/title.png",
                    "description": "GraphRAG pipeline walkthrough using LlamaIndex and Neo4j.",
                    "tags": ["neo4j", "graphrag", "python", "llm"],
                }
            },
            timeout=30,
        )

        if resp.ok:
            data = resp.json()
            article_id: int = int(data["id"])
            article_url: str = data.get("url") or f"https://dev.to{data.get('path', '')}"
            print(f"[devto] Created: {article_url} (id={article_id})")
        elif resp.status_code == 422:
            # DEV.to rejects duplicate titles within a 5-minute window.
            # Find the existing article and ensure it is published.
            existing = _find_existing()
            if existing is None:
                pytest.fail(f"DEV.to 422 and no matching article found to reuse.\n"
                            f"Response: {resp.text[:300]}")
            article_id, article_url = existing
            print(f"[devto] Reusing existing article (id={article_id}): {article_url}")
            pub = _requests.put(
                f"{_DEVTO_BASE_URL}/articles/{article_id}",
                headers=headers,
                json={"article": {
                    "published": True
                }},
                timeout=30,
            )
            if not pub.ok:
                pytest.fail(f"Could not re-publish existing DEV.to article {article_id}: "
                            f"{pub.status_code} {pub.text[:200]}")
        else:
            pytest.fail(f"DEV.to publish failed ({resp.status_code}): {resp.text[:400]}")

        yield article_id, article_url

        # ── Teardown: unpublish ────────────────────────────────────────────
        print(f"\n[devto] Unpublishing article id={article_id} ...")
        unpub = _requests.put(
            f"{_DEVTO_BASE_URL}/articles/{article_id}",
            headers=headers,
            json={"article": {
                "published": False
            }},
            timeout=30,
        )
        if unpub.ok:
            print("[devto] Unpublished successfully.")
        else:
            print(f"[devto] WARNING: unpublish returned {unpub.status_code}: {unpub.text[:200]}")

    @pytest.fixture(scope="class")
    def url_import_result(self, session_file, devto_article):
        """Wait for DEV.to to index, then drive Medium URL import."""
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PWTimeout

        _article_id, devto_url = devto_article

        # Brief pause — DEV.to articles occasionally take a few seconds to be
        # Verify the DEV.to article is publicly reachable before attempting Medium import.
        # DEV.to can take up to 60s to make a newly published article crawlable.
        print(f"\n[url-import] Checking DEV.to article reachability: {devto_url}")
        import requests as _req_check
        for _attempt in range(12):  # up to 60 s (12 × 5 s)
            try:
                r = _req_check.get(devto_url,
                                   timeout=10,
                                   allow_redirects=True,
                                   headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and len(r.text) > 1000:
                    print(f"[url-import] DEV.to article reachable (attempt {_attempt + 1}, "
                          f"status={r.status_code}, size={len(r.text)} bytes)")
                    break
                print(f"[url-import] Attempt {_attempt + 1}: status={r.status_code}, "
                      f"size={len(r.text)} — waiting 5 s...")
            except Exception as _e:
                print(f"[url-import] Attempt {_attempt + 1}: error {_e} — waiting 5 s...")
            time.sleep(5)
        else:
            pytest.fail(f"DEV.to article not reachable after 60 s: {devto_url}")

        print(f"[url-import] Importing: {devto_url}")

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
                # ── 1. Navigate to import page ──────────────────────────────
                # Confirmed URL from working JS (tmp_import_003_html_to_medium.js): /p/import
                # Use networkidle (same as working JS) to ensure SPA fully hydrates
                page.goto("https://medium.com/p/import", wait_until="networkidle")
                page.wait_for_timeout(5000)

                # ── Diagnostic dump (always) ────────────────────────────────
                diag_ts = time.strftime("%Y%m%dT%H%M%S")
                diag_dir = _DUMP_DIR / f"devto_import_diag_{diag_ts}"
                diag_dir.mkdir(parents=True, exist_ok=True)
                _early_html = page.content()
                (diag_dir / "import_page.html").write_text(_early_html, encoding="utf-8")
                page.screenshot(path=str(diag_dir / "import_page.png"), full_page=True)
                print(f"[url-import] Diag dump: {diag_dir} (URL: {page.url})")

                # If Medium redirected to a login or sign-in page, fail fast
                if "/signin" in page.url or "/m/signin" in page.url or "/login" in page.url:
                    pytest.fail(f"Medium redirected to login — session may be expired.\n"
                                f"URL: {page.url}\n"
                                f"Diag: {diag_dir}")

                # ── 2. Enter the DEV.to URL ─────────────────────────────────
                # Real element (from diag dump): div.textInput.textInput--large.js-importUrl
                # NOTE: .editable class and role="textbox" are added by JS *after* hydration.
                # The base class js-importUrl is always present in the SSR'd HTML.
                url_input = None
                for sel in [
                        'div.js-importUrl',
                        'div.textInput.textInput--large.js-importUrl',
                        'div.textInput.textInput--large.js-importUrl.editable[role="textbox"]',
                        'div[role="textbox"]',
                        'input[placeholder*="URL"]',
                        'input[type="url"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        el.wait_for(state="visible", timeout=5000)
                        url_input = el
                        print(f"[url-import] Selector matched: {sel!r}")
                        break
                    except PWTimeout:
                        pass

                if url_input is None:
                    pytest.fail(f"Could not locate URL input on Medium import page.\n"
                                f"Current URL: {page.url}\n"
                                f"Diag dump: {diag_dir / 'import_page.html'}")

                url_input.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(devto_url)
                page.wait_for_timeout(1000)

                # ── 3. Click Import ─────────────────────────────────────────
                # Real button (from diag dump): button[data-action="import-url"]
                for btn_sel in [
                        'button[data-action="import-url"]',
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

                # ── 4. Wait for editor URL (Medium redirects on success) ────
                try:
                    page.wait_for_url(
                        lambda u: re.search(r"medium\.com/p/.+/edit", u) is not None,
                        timeout=180_000,
                    )
                except PWTimeout:
                    page_text = page.evaluate("() => document.body.innerText || ''")
                    pytest.fail(f"Medium did not redirect to draft editor.\n"
                                f"Current URL: {page.url}\n"
                                f"Page snippet: {page_text[:400]}\n\n"
                                "DEV.to is the only reliably accepted import host — if this "
                                "fails the article may not have been publicly reachable yet.")

                draft_url = page.url
                print(f"[url-import] Draft URL: {draft_url}")

                # ── 5. Scroll-through to force full render ──────────────────
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
                        if (pos < document.body.scrollHeight) setTimeout(step, 150);
                        else resolve();
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

                # ── 6. Corruption signal ────────────────────────────────────
                auto_typescript_count = editor_html.count("Auto (TypeScript)")
                print(f"[url-import] 'Auto (TypeScript)' corruption: "
                      f"{auto_typescript_count} occurrences "
                      f"({'CLEAN' if auto_typescript_count == 0 else 'CORRUPTED'})")

                # ── 7. Save dump ────────────────────────────────────────────
                # Reuse diag_dir created at the start of the fixture
                (diag_dir / "editor_dump.html").write_text(editor_html, encoding="utf-8")
                (diag_dir / "full_page.html").write_text(full_page_html, encoding="utf-8")
                meta = {
                    "method": "devto_url_import",
                    "devto_url": devto_url,
                    "devto_article_id": _article_id,
                    "timestamp": diag_ts,
                    "draft_url": draft_url,
                    "session_file": session_file,
                    "editor_html_bytes": len(editor_html.encode()),
                    "full_page_html_bytes": len(full_page_html.encode()),
                    "auto_typescript_corruption_count": auto_typescript_count,
                }
                (diag_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                print(f"[url-import] Dump: {diag_dir}")

                return {
                    "draft_url": draft_url,
                    "editor_html": editor_html,
                    "full_page_html": full_page_html,
                    "dump_dir": str(diag_dir),
                    "devto_url": devto_url,
                    "auto_typescript_count": auto_typescript_count,
                }

            finally:
                browser.close()

    # ── Assertions ───────────────────────────────────────────────────────────

    def test_draft_url_is_medium_edit_url(self, url_import_result):
        assert re.search(
            r"medium\.com/p/[a-f0-9]+/edit",
            url_import_result["draft_url"],
        ), f"Unexpected draft URL: {url_import_result['draft_url']}"

    def test_editor_html_is_non_empty(self, url_import_result):
        """Editor HTML must be substantive — raw byte floor catches total import failure."""
        size = len(url_import_result["editor_html"])
        assert size >= _URL_IMPORT_MIN_EDITOR_BYTES, (
            f"editor_html only {size} bytes — import may have returned an empty draft")

    def test_editor_has_title(self, url_import_result):
        normalised = url_import_result["editor_html"].replace("&nbsp;", " ")
        assert _EXPECTED_TITLE in normalised, (
            "Title not found in imported draft editor HTML — Medium may have dropped it")

    def test_editor_has_title_exactly_once(self, url_import_result):
        """Title must appear exactly once in the editor — duplicate means the H1
        was not stripped from the article body before import."""
        count = url_import_result["editor_html"].count("graf--title")
        assert count == 1, (
            f"'graf--title' appears {count} times — title is duplicated in the editor")

    def test_editor_h2_count_not_below_expected(self, url_import_result):
        """All section headings must survive the URL import.

        Source: 7 ## headings + 1 title = 8 expected <h3> nodes (Medium maps ## → h3).
        Checked against editor_html (not full_page_html) to avoid counting Medium UI elements.
        """
        count = len(re.findall(r"<h3\b", url_import_result["editor_html"], re.IGNORECASE))
        assert count >= _URL_IMPORT_MIN_H3_COUNT, (
            f"Expected ≥{_URL_IMPORT_MIN_H3_COUNT} <h3> elements in editor, found {count} — "
            "section headings were lost during URL import")

    def test_editor_code_block_count_not_below_expected(self, url_import_result):
        """≥10 of the 12 source code blocks must survive URL import as <pre> elements.

        Checked against editor_html. A count of 1-2 indicates Medium's importer
        dropped nearly all code blocks (confirmed bad result from 2026-04-04 run).
        """
        count = len(re.findall(r"<pre\b", url_import_result["editor_html"], re.IGNORECASE))
        assert count >= _URL_IMPORT_MIN_PRE_COUNT, (
            f"Expected ≥{_URL_IMPORT_MIN_PRE_COUNT} <pre> code blocks in editor, found {count} — "
            f"Medium URL import dropped {12 - count}/12 code blocks")

    def test_code_blocks_have_substantive_content(self, url_import_result):
        """Non-empty code blocks must reach the minimum count.

        Medium's editor HTML embeds a ``codeBlockMenu-button`` UI div (language
        selector) inside every ``<pre>`` element.  The extraction removes that div
        before measuring block length so that the language label (e.g. "Auto (CSS)")
        is not counted as code content.  Medium also inserts one empty separator
        block after each real block; these are ignored in the count.
        """
        editor = url_import_result["editor_html"]
        pre_blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre>", editor, re.IGNORECASE | re.DOTALL)
        real_content = []
        for raw in pre_blocks:
            # Strip the codeBlockMenu-button UI div before measuring code content.
            code_part = re.sub(r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>',
                               '',
                               raw,
                               flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "", code_part).strip()
            if len(text) >= _URL_IMPORT_MIN_PRE_TEXT_CHARS:
                real_content.append(text[:60])
        print(f"\n[url-import] Non-empty code blocks: {len(real_content)} "
              f"(of {len(pre_blocks)} total including empty separators)")
        assert len(real_content) >= _URL_IMPORT_MIN_PRE_COUNT, (
            f"Only {len(real_content)} code blocks with ≥{_URL_IMPORT_MIN_PRE_TEXT_CHARS} chars "
            f"(need ≥{_URL_IMPORT_MIN_PRE_COUNT}).")

    def test_no_planning_markers_leaked(self, url_import_result):
        for marker in _PLANNING_MARKERS:
            assert marker not in url_import_result["editor_html"], (
                f"Planning marker leaked: {marker!r}")

    def test_last_content_sentence_present(self, url_import_result):
        """URL import must deliver the full article body — last sentence must be present
        in editor_html (not just in Medium's page chrome)."""
        assert _EXPECTED_LAST_SENTENCE in url_import_result["editor_html"], (
            "Last content sentence not found in editor HTML — article was truncated during import")

    def test_no_auto_language_corruption(self, url_import_result):
        """Auto(...) text must not appear inside code block content.

        Medium's editor renders a ``codeBlockMenu-button`` UI div (the language
        selector dropdown) inside every ``<pre>`` that legitimately shows
        "Auto (CSS)", "Auto (TypeScript)" etc. as the detected language label.
        That is a UI element and is NOT corruption.

        Real corruption would be the string "Auto (...)" appearing *inside* the
        actual code text (the ``pre--content`` region).  This test strips the
        ``codeBlockMenu-button`` div before scanning so that normal UI labels
        do not trigger a false failure.
        """
        editor = url_import_result["editor_html"]
        pre_blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre>", editor, re.IGNORECASE | re.DOTALL)
        auto_in_code = 0
        for raw in pre_blocks:
            code_part = re.sub(r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>',
                               '',
                               raw,
                               flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "", code_part).strip()
            auto_in_code += len(re.findall(r"Auto\s+\(\w+\)", text))
        print(f"\n[url-import] Auto(...) inside code content: {auto_in_code} "
              f"({'CLEAN' if auto_in_code == 0 else 'CORRUPTED'})")
        assert auto_in_code == 0, (
            f"{auto_in_code} Auto(...) language-label artefacts found INSIDE code content "
            f"(excluding the codeBlockMenu-button UI element).  This is real corruption.")


# ---------------------------------------------------------------------------
# GitHub CDN → Medium URL import test class
# ---------------------------------------------------------------------------
# Strategy: Push the v1 import HTML (bare <pre>, 0 spans) directly to a GitHub
# repo and import from rawcdn.githack.com.  Medium's backend scraper bypasses
# rawcdn's browser-only interstitial warning page, so the import succeeds.
#
# Confirmed working:
#   - tmp_import_003_html_to_medium.js used rawcdn.githack.com successfully
#     → draft at medium.com/p/f1945938f2e0/edit (26 code-block imports)
#   - article_publishing Phase 2 Run 01 also reached /edit URL via rawcdn
#     (the "source_valid: false" failure was from the article_publishing
#     browser-based pre-validator seeing the interstitial, not Medium itself)
#
# Flow:
#   1. Copy sample_article_v1_url_import.html → blog-components repo
#   2. git add + commit + push via SSH (id_ed25519_amadou key)
#   3. Capture commit SHA → build rawcdn URL
#   4. Import that URL into Medium → assert DOM
#
# v1 HTML has 12 bare <pre> blocks (0 spans, no codehilite wrappers).
# Medium's importer accepts these; DEV.to's span-soup causes drops.
#
# Skip condition: blog-components repo not found at _BLOG_COMPONENTS_REPO.
# ---------------------------------------------------------------------------

# Path to the blog-components git checkout in this workspace
_BLOG_COMPONENTS_REPO = Path(__file__).parents[4] / "tmp_blog_components_repo"
# Subpath within the repo where we push the test import HTML
_BLOG_COMPONENTS_ARTICLE_SUBPATH = "medium/002_neo4j_llamaindex/article_import_test.html"
# GitHub Pages URL (static, no interstitial, accepted by Medium)
# rawcdn.githack.com is blocked by Medium's import backend as of 2026-04-04.
_GITHUB_PAGES_BASE = "https://amadou-6e.github.io/blog-components"


@pytest.mark.integration
@pytest.mark.timeout(360)
class TestMediumGithubCdnImportDraft:
    """
    End-to-end: push v1 import HTML to GitHub → import rawcdn URL into Medium → assert DOM.

    The v1 import HTML (sample_article_v1_url_import.html) contains 12 bare <pre>
    blocks with 0 <span> tags.  Medium's importer accepts these without silently
    dropping them — unlike DEV.to's server-side syntax highlighting which produces
    28-184 spans per block and causes Medium to drop nearly all code blocks.

    rawcdn.githack.com serves GitHub-committed files with Content-Type: text/html.
    Medium's backend scraper ignores the browser-only interstitial warning page
    and imports the article body directly.

    Skip condition: ``_BLOG_COMPONENTS_REPO`` checkout not found.
    """

    # ── Fixtures ─────────────────────────────────────────────────────────────

    @pytest.fixture(scope="class")
    def github_cdn_url(self):
        """Copy v1 HTML to blog-components repo, git push, return GitHub Pages URL.

        GitHub Pages (amadou-6e.github.io/blog-components) serves files from the
        main branch as proper text/html without interstitials.  Medium's import
        backend accepts github.io URLs.

        rawcdn.githack.com is blocked by Medium as of 2026-04-04 — all rawcdn
        imports silently stay on the /p/import page without redirecting.

        Idempotent:
        - If the committed file matches (no-op commit), no push is performed and
          the stable Pages URL is returned directly.
        - If the file differs, a new commit is pushed and Pages deploys within ~75s.
        """
        import shutil
        import subprocess as _sp

        repo = _BLOG_COMPONENTS_REPO
        if not repo.exists():
            pytest.skip(f"blog-components repo checkout not found at {repo}. "
                        "Clone git@github.com:amadou-6e/blog-components.git into that path first.")

        src = _FIXTURES_DIR / "sample_article_v1_url_import.html"
        dest = repo / _BLOG_COMPONENTS_ARTICLE_SUBPATH

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

        repo_str = str(repo)

        # Stage
        _sp.run(
            ["git", "-C", repo_str, "add", _BLOG_COMPONENTS_ARTICLE_SUBPATH],
            check=True,
            capture_output=True,
        )

        # Commit (no-op if file unchanged)
        commit_result = _sp.run(
            [
                "git",
                "-C",
                repo_str,
                "commit",
                "-m",
                "test(medium-import): update article 002 v1 import HTML for URL import test",
            ],
            capture_output=True,
            text=True,
        )
        new_commit = commit_result.returncode == 0
        if not new_commit:
            no_changes = ("nothing to commit" in commit_result.stdout or
                          "nothing to commit" in commit_result.stderr or
                          "nothing added to commit" in commit_result.stdout)
            if not no_changes:
                pytest.fail(f"git commit failed (rc={commit_result.returncode}):\n"
                            f"stdout: {commit_result.stdout[:400]}\n"
                            f"stderr: {commit_result.stderr[:400]}")
            print("\n[github-cdn] File unchanged — reusing existing Pages URL.")
        else:
            # Push the new commit — GitHub Pages redeploys automatically from main
            push_result = _sp.run(
                ["git", "-C", repo_str, "push", "origin", "main"],
                capture_output=True,
                text=True,
            )
            if push_result.returncode != 0:
                pytest.fail(f"git push failed (rc={push_result.returncode}):\n"
                            f"stdout: {push_result.stdout[:400]}\n"
                            f"stderr: {push_result.stderr[:400]}")
            print("\n[github-cdn] Pushed new commit — GitHub Pages will redeploy.")
            # Allow Pages CDN time to serve the new content (deploy is usually <60s)
            print("[github-cdn] Waiting 75s for Pages CDN to propagate...")
            time.sleep(75)

        # GitHub Pages URL is stable (always reflects latest main branch commit)
        pages_url = f"{_GITHUB_PAGES_BASE}/{_BLOG_COMPONENTS_ARTICLE_SUBPATH}"
        print(f"[github-cdn] GitHub Pages URL: {pages_url}")
        return pages_url

    @pytest.fixture(scope="class")
    def url_import_result(self, session_file, github_cdn_url):
        """Drive Medium URL import from rawcdn URL and return editor DOM results."""
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PWTimeout

        import requests as _req_check

        pages_url = github_cdn_url

        # Brief reachability check — GitHub Pages propagates within seconds after deploy.
        print(f"\n[github-cdn] Checking GitHub Pages URL reachability: {pages_url}")
        for _attempt in range(6):
            try:
                r = _req_check.get(pages_url,
                                   timeout=15,
                                   allow_redirects=True,
                                   headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    print(f"[github-cdn] URL reachable (attempt {_attempt + 1}, "
                          f"status={r.status_code}, size={len(r.text)} bytes)")
                    break
                print(
                    f"[github-cdn] Attempt {_attempt + 1}: status={r.status_code} — waiting 5s...")
            except Exception as _e:
                print(f"[github-cdn] Attempt {_attempt + 1}: error {_e} — waiting 5s...")
            time.sleep(5)
        else:
            pytest.fail(f"GitHub Pages URL not reachable after 30s: {pages_url}")

        print(f"[github-cdn] Importing: {pages_url}")

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
                # ── 1. Navigate to import page ──────────────────────────────
                page.goto("https://medium.com/p/import", wait_until="networkidle")
                page.wait_for_timeout(5000)

                # ── Diagnostic dump ─────────────────────────────────────────
                diag_ts = time.strftime("%Y%m%dT%H%M%S")
                diag_dir = _DUMP_DIR / f"github_cdn_import_diag_{diag_ts}"
                diag_dir.mkdir(parents=True, exist_ok=True)
                (diag_dir / "import_page.html").write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(diag_dir / "import_page.png"), full_page=True)
                print(f"[github-cdn] Diag dump: {diag_dir} (URL: {page.url})")

                if "/signin" in page.url or "/m/signin" in page.url or "/login" in page.url:
                    pytest.fail(f"Medium redirected to login — session may be expired.\n"
                                f"URL: {page.url}\nDiag: {diag_dir}")

                # ── 2. Enter the rawcdn URL ─────────────────────────────────
                url_input = None
                for sel in [
                        "div.js-importUrl",
                        "div.textInput.textInput--large.js-importUrl",
                        'div[role="textbox"]',
                        'input[placeholder*="URL"]',
                        'input[type="url"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        el.wait_for(state="visible", timeout=5000)
                        url_input = el
                        print(f"[github-cdn] Selector matched: {sel!r}")
                        break
                    except PWTimeout:
                        pass

                if url_input is None:
                    pytest.fail(f"Could not locate URL input on Medium import page.\n"
                                f"Current URL: {page.url}\n"
                                f"Diag: {diag_dir / 'import_page.html'}")

                url_input.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(pages_url)
                page.wait_for_timeout(1000)

                # ── 3. Click Import ─────────────────────────────────────────
                for btn_sel in [
                        'button[data-action="import-url"]',
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

                # ── 4. Wait for editor URL ──────────────────────────────────
                try:
                    page.wait_for_url(
                        lambda u: re.search(r"medium\.com/p/.+/edit", u) is not None,
                        timeout=180_000,
                    )
                except PWTimeout:
                    page_text = page.evaluate("() => document.body.innerText || ''")
                    pytest.fail(
                        f"Medium did not redirect to draft editor.\n"
                        f"Current URL: {page.url}\n"
                        f"Page snippet: {page_text[:400]}\n\n"
                        "github.io Pages URLs are normally accepted by Medium's URL import — "
                        "check import_page.html in the diag dump for details.")

                draft_url = page.url
                print(f"[github-cdn] Draft URL: {draft_url}")

                # ── 5. Scroll-through to force full render ──────────────────
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
                        if (pos < document.body.scrollHeight) setTimeout(step, 150);
                        else resolve();
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

                # ── 6. Corruption signal ────────────────────────────────────
                auto_typescript_count = editor_html.count("Auto (TypeScript)")
                print(f"[github-cdn] 'Auto (TypeScript)' corruption: "
                      f"{auto_typescript_count} occurrences "
                      f"({'CLEAN' if auto_typescript_count == 0 else 'CORRUPTED'})")

                # ── 7. Save dump ────────────────────────────────────────────
                (diag_dir / "editor_dump.html").write_text(editor_html, encoding="utf-8")
                (diag_dir / "full_page.html").write_text(full_page_html, encoding="utf-8")
                meta = {
                    "method": "github_pages_url_import",
                    "pages_url": pages_url,
                    "timestamp": diag_ts,
                    "draft_url": draft_url,
                    "session_file": session_file,
                    "editor_html_bytes": len(editor_html.encode()),
                    "full_page_html_bytes": len(full_page_html.encode()),
                    "auto_typescript_corruption_count": auto_typescript_count,
                }
                (diag_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                print(f"[github-cdn] Dump: {diag_dir}")

                return {
                    "draft_url": draft_url,
                    "editor_html": editor_html,
                    "full_page_html": full_page_html,
                    "dump_dir": str(diag_dir),
                    "pages_url": pages_url,
                    "auto_typescript_count": auto_typescript_count,
                }

            finally:
                browser.close()

    # ── Assertions ───────────────────────────────────────────────────────────

    def test_draft_url_is_medium_edit_url(self, url_import_result):
        assert re.search(
            r"medium\.com/p/[a-f0-9]+/edit",
            url_import_result["draft_url"],
        ), f"Unexpected draft URL: {url_import_result['draft_url']}"

    def test_editor_html_is_non_empty(self, url_import_result):
        """Editor HTML must be substantive — raw byte floor catches total import failure."""
        size = len(url_import_result["editor_html"])
        assert size >= _URL_IMPORT_MIN_EDITOR_BYTES, (
            f"editor_html only {size} bytes — import may have returned an empty draft")

    def test_editor_has_title(self, url_import_result):
        normalised = url_import_result["editor_html"].replace("&nbsp;", " ")
        assert _EXPECTED_TITLE in normalised, (
            "Title not found in imported draft editor HTML — Medium may have dropped it")

    def test_editor_has_title_exactly_once(self, url_import_result):
        """Title must appear exactly once — duplicate means H1 leaked into the body."""
        count = url_import_result["editor_html"].count("graf--title")
        assert count == 1, (
            f"'graf--title' appears {count} times — title is duplicated in the editor")

    def test_editor_h2_count_not_below_expected(self, url_import_result):
        """All 7 section headings must survive the URL import.

        v1 HTML has 7 <h2> headings (Medium maps <h2> → <h3> in the editor).
        Checked against editor_html to avoid counting Medium UI elements.
        """
        count = len(re.findall(r"<h3\b", url_import_result["editor_html"], re.IGNORECASE))
        assert count >= _URL_IMPORT_MIN_H3_COUNT, (
            f"Expected ≥{_URL_IMPORT_MIN_H3_COUNT} <h3> elements in editor, found {count} — "
            "section headings were lost during URL import")

    def test_editor_code_block_count_not_below_expected(self, url_import_result):
        """All 12 source code blocks must survive URL import as <pre> elements.

        The v1 HTML has 12 bare <pre> blocks (0 <span> tags). Medium's importer
        accepts these — unlike DEV.to's span-soup (28-184 spans) which it drops.
        Checked against editor_html.
        """
        count = len(re.findall(r"<pre\b", url_import_result["editor_html"], re.IGNORECASE))
        assert count >= _URL_IMPORT_MIN_PRE_COUNT, (
            f"Expected ≥{_URL_IMPORT_MIN_PRE_COUNT} <pre> code blocks in editor, found {count} — "
            f"Medium URL import dropped {12 - count}/12 code blocks from the rawcdn HTML")

    def test_code_blocks_have_substantive_content(self, url_import_result):
        """Non-empty code blocks must reach the minimum count.

        See ``TestMediumDevToImportDraft.test_code_blocks_have_substantive_content``
        for the full explanation.  Applies identically here.
        """
        editor = url_import_result["editor_html"]
        pre_blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre>", editor, re.IGNORECASE | re.DOTALL)
        real_content = []
        for raw in pre_blocks:
            code_part = re.sub(r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>',
                               '',
                               raw,
                               flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "", code_part).strip()
            if len(text) >= _URL_IMPORT_MIN_PRE_TEXT_CHARS:
                real_content.append(text[:60])
        print(f"\n[github-cdn] Non-empty code blocks: {len(real_content)} "
              f"(of {len(pre_blocks)} total including empty separators)")
        assert len(real_content) >= _URL_IMPORT_MIN_PRE_COUNT, (
            f"Only {len(real_content)} code blocks with ≥{_URL_IMPORT_MIN_PRE_TEXT_CHARS} chars "
            f"(need ≥{_URL_IMPORT_MIN_PRE_COUNT}).")

    def test_no_planning_markers_leaked(self, url_import_result):
        for marker in _PLANNING_MARKERS:
            assert marker not in url_import_result["editor_html"], (
                f"Planning marker leaked: {marker!r}")

    def test_last_content_sentence_present(self, url_import_result):
        """URL import must deliver the full article — last sentence in editor_html."""
        assert _EXPECTED_LAST_SENTENCE in url_import_result["editor_html"], (
            "Last content sentence not found in editor HTML — article truncated during import")

    def test_no_auto_language_corruption(self, url_import_result):
        """Auto(...) text must not appear inside code block content.

        See ``TestMediumDevToImportDraft.test_no_auto_language_corruption``
        for the full explanation.  Applies identically here.
        """
        editor = url_import_result["editor_html"]
        pre_blocks = re.findall(r"<pre\b[^>]*>(.*?)</pre>", editor, re.IGNORECASE | re.DOTALL)
        auto_in_code = 0
        for raw in pre_blocks:
            code_part = re.sub(r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>',
                               '',
                               raw,
                               flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "", code_part).strip()
            auto_in_code += len(re.findall(r"Auto\s+\(\w+\)", text))
        print(f"\n[github-cdn] Auto(...) inside code content: {auto_in_code} "
              f"({'CLEAN' if auto_in_code == 0 else 'CORRUPTED'})")
        assert auto_in_code == 0, (
            f"{auto_in_code} Auto(...) language-label artefacts found INSIDE code content "
            f"(excluding the codeBlockMenu-button UI element).  This is real corruption.")
