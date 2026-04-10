"""
test_import_hashnode.py — Playwright UI tests for the Hashnode import flow.

Covers the full browser path:
  platform pick → draft list (real Hashnode API) → review pane (images) → import

Run:
    pytest tests/ui/screens/test_import_hashnode.py -m browser -v -s

Requires:
    HASHNODE_PAT env var or root .env file
    Backend running on port 8000 (playwright.config.js spins up uvicorn automatically)
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests as http

from blogs.hashnode.client import HashnodeClient
from blogs.hashnode.render import prepare_draft
from tests.ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
_REPO_ROOT = Path(__file__).resolve().parents[4]  # py-dockerdb/
_OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"
_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Image fixture constants ───────────────────────────────────────────────────
# Fixed title — never changes between runs so subsequent runs reuse the draft.
_FIXTURE_TITLE = "BlogHub UI fixture — image preview test"
_IMAGE_BASE = (
    "https://raw.githubusercontent.com/amadou-6e/blog-components/main/"
    "medium/002_neo4j_llamaindex/images"
)
_FIXTURE_MARKDOWN = f"""\
# {_FIXTURE_TITLE}

This draft is the stable BlogHub UI test fixture for image-preview validation.
Do not delete — it is recreated automatically if absent.

## Introduction

An article with real images to validate end-to-end import preview.

![Title image]({_IMAGE_BASE}/title.png)

## How it works

The import wizard fetches this draft's body via `draft(id: $id)` and renders
the markdown including images in the browser preview.

![Architecture diagram]({_IMAGE_BASE}/knowledge_graph.png)

## Summary

End-to-end UI import confirmed.
"""

# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() == name:
            return raw.strip()
    return ""


def goto_platform(page):
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)


def advance(page):
    page.locator("#primary-btn").click()


def _to_draft_list(page):
    """Navigate to the Hashnode draft list step."""
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    # Hashnode API round-trip — allow up to 30 s
    page.wait_for_selector(".draft-row", timeout=30_000)


def _to_review(page, *, search: str | None = None):
    """Navigate through platform → draft list → select → review."""
    _to_draft_list(page)
    if search:
        page.locator("#draft-search").fill(search)
        page.wait_for_timeout(400)
        page.wait_for_selector(".draft-row", timeout=5_000)
    rows = page.locator(".draft-row")
    rows.first.click()
    advance(page)
    page.wait_for_selector("#view-review", timeout=10_000)
    # renderReview() is async — it awaits a body fetch before filling #title-input.
    # Wait until the title is populated so subsequent assertions are stable.
    page.wait_for_function(
        "document.querySelector('#title-input').value.trim().length > 0",
        timeout=30_000,
    )


# ── Module-level skip if no token ────────────────────────────────────────────


def _read_first_publication_id(client: HashnodeClient) -> str:
    query = """
    query MePublications($first: Int!) {
      me {
        publications(first: $first) {
          edges { node { id title } }
        }
      }
    }
    """
    resp = client._session.post(
        "https://gql.hashnode.com",
        headers=client.headers,
        json={"query": query, "variables": {"first": 10}},
        timeout=30,
    )
    resp.raise_for_status()
    edges = resp.json()["data"]["me"]["publications"]["edges"]
    if not edges:
        raise RuntimeError("No Hashnode publications for this token")
    return edges[0]["node"]["id"]


@pytest.fixture(scope="module")
def hashnode_pat():
    pat = _read_secret("HASHNODE_PAT")
    if not pat:
        pytest.skip("HASHNODE_PAT is not set — skipping Hashnode UI tests")
    return pat


@pytest.fixture(scope="module")
def image_fixture_draft_id(hashnode_pat):
    """
    Module-scoped fixture that guarantees a Hashnode draft with a fixed stable
    title and two embedded images exists in the account.

    If the draft is already present (e.g. from a previous run) it is reused;
    otherwise it is created.  The draft ID is returned.
    """
    client = HashnodeClient(hashnode_pat)

    # Search existing drafts for the stable fixture title
    drafts = client.list_all_drafts(page_size=20)
    for d in drafts:
        if d.title == _FIXTURE_TITLE:
            return d.article_id

    # Not found — create it
    pub_id = _read_secret("HASHNODE_PUBLICATION_ID") or _read_first_publication_id(client)
    prepared = prepare_draft(
        _FIXTURE_MARKDOWN,
        publication_id=pub_id,
        cover_image_url=f"{_IMAGE_BASE}/title.png",
        tags=("bloghub", "fixture"),
    )
    result = client.create_draft(prepared.draft)
    return result.draft_id


@pytest.fixture(autouse=True)
def hashnode_connection(reset_store, hashnode_pat):
    """Save the Hashnode token via the live API after the store is reset."""
    http.put(
        f"{BASE_URL}/api/connections/hashnode",
        json={"token": hashnode_pat},
        timeout=10,
    )
    yield


# ── 1. Platform pick ──────────────────────────────────────────────────────────


def test_hashnode_card_visible(page):
    goto_platform(page)
    assert page.locator(".platform-card").filter(has_text="Hashnode").is_visible()


# ── 2. Draft list ─────────────────────────────────────────────────────────────


def test_draft_list_loads(page):
    _to_draft_list(page)
    assert page.locator(".draft-row").count() >= 1


def test_draft_rows_have_titles(page):
    """Every visible row must show a non-empty title string."""
    _to_draft_list(page)
    rows = page.locator(".draft-row")
    for i in range(min(rows.count(), 10)):
        title = rows.nth(i).locator(".draft-row-title").text_content() or ""
        assert title.strip(), f"Row {i} has an empty title"


def test_draft_titles_are_not_object_object(page):
    """Titles must not contain the JavaScript stringification artefact."""
    _to_draft_list(page)
    rows = page.locator(".draft-row")
    for i in range(min(rows.count(), 10)):
        title = rows.nth(i).locator(".draft-row-title").text_content() or ""
        assert "[object Object]" not in title, f"Row {i} title is [object Object]"


def test_search_filters_rows(page):
    """Typing in the search box narrows the visible rows."""
    _to_draft_list(page)
    before = page.locator(".draft-row").count()
    page.locator("#draft-search").fill("xxxxxxxxxxxxxxxxxxxxxxx_no_match_xxxxxxxxxxx")
    page.wait_for_timeout(400)
    after = page.locator(".draft-row").count()
    assert after < before, "Search did not filter any rows"


def test_selecting_row_enables_next(page):
    _to_draft_list(page)
    page.locator(".draft-row").first.click()
    assert not page.locator("#primary-btn").is_disabled()


def test_selected_row_has_selected_class(page):
    _to_draft_list(page)
    page.locator(".draft-row").first.click()
    classes = page.locator(".draft-row").first.get_attribute("class") or ""
    assert "selected" in classes


# ── 3. Review pane ────────────────────────────────────────────────────────────


def test_review_shows_title_input(page):
    _to_review(page)  # waits until title-input is populated
    title = page.locator("#title-input").input_value()
    assert len(title.strip()) > 0


def test_review_preview_has_content(page):
    """Markdown preview must render non-trivial HTML."""
    _to_review(page)
    page.wait_for_function(
        "document.querySelector('#markdown-preview').innerHTML.length > 50",
        timeout=10_000,
    )
    html = page.locator("#markdown-preview").inner_html()
    assert len(html) > 50


def test_review_preview_is_not_object_object(page):
    """The rendered preview must never contain the [object Object] artefact."""
    _to_review(page)
    page.wait_for_function(
        "document.querySelector('#markdown-preview').innerHTML.length > 50",
        timeout=10_000,
    )
    html = page.locator("#markdown-preview").inner_html()
    assert "[object Object]" not in html


def test_review_import_button_is_enabled(page):
    _to_review(page)
    assert not page.locator("#primary-btn").is_disabled()


def test_clearing_title_disables_import(page):
    _to_review(page)  # renderReview() is fully done; title is filled
    page.locator("#title-input").fill("")
    assert page.locator("#primary-btn").is_disabled()


# ── 4. Article with images ────────────────────────────────────────────────────


def test_image_fixture_preview_renders_images(page, image_fixture_draft_id):
    """
    Navigate to the stable image-fixture draft (created if absent), open its
    review pane, assert images render with absolute src values, and save a
    full-page screenshot of the preview to tests/ui/outputs/.
    """
    _to_draft_list(page)

    # Search for the fixture by its fixed title
    page.locator("#draft-search").fill(_FIXTURE_TITLE[:30])  # partial match is fine
    page.wait_for_timeout(400)
    page.wait_for_selector(".draft-row", timeout=10_000)

    fixture_rows = page.locator(".draft-row").filter(has_text="image preview test")
    assert fixture_rows.count() > 0, (
        f"Fixture draft '{_FIXTURE_TITLE}' not found in draft list after creation"
    )
    fixture_rows.first.click()

    advance(page)
    page.wait_for_selector("#view-review", timeout=10_000)
    # Wait for async renderReview() to finish (body fetch + title fill)
    page.wait_for_function(
        "document.querySelector('#title-input').value.trim().length > 0",
        timeout=30_000,
    )
    # Also wait for markdown preview to have rendered image HTML
    page.wait_for_function(
        "document.querySelector('#markdown-preview').innerHTML.includes('<img')",
        timeout=15_000,
    )
    # Wait for network activity to settle (images downloading) — then screenshot.
    # Using a best-effort wait; failure to load images from GitHub CDN won't fail
    # the test because we assert on src attributes, not visual rendering.
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass  # proceed even if some resources are still in-flight

    # ── Screenshot ─────────────────────────────────────────────────────────
    screenshot_path = _OUTPUTS_DIR / "preview_hashnode_image_fixture.png"
    page.locator("#view-review").screenshot(path=str(screenshot_path))

    # ── Assertions ─────────────────────────────────────────────────────────
    imgs = page.locator("#markdown-preview img")
    assert imgs.count() >= 1, "No <img> elements found in the markdown preview"
    for i in range(imgs.count()):
        src = imgs.nth(i).get_attribute("src") or ""
        assert src.startswith("https://"), (
            f"Image {i} src is not absolute https://: {src!r}"
        )


# ── 5. Import completes ───────────────────────────────────────────────────────


def test_import_navigates_to_editor(page):
    """Clicking Import on the review screen must navigate to the editor."""
    _to_review(page)
    page.wait_for_selector("#title-input", timeout=5_000)
    with page.expect_navigation(timeout=15_000):
        advance(page)
    assert "editor/" in page.url
