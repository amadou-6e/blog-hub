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

from tests.ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
_REPO_ROOT = Path(__file__).resolve().parents[4]  # py-dockerdb/

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


# ── Module-level skip if no token ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def hashnode_pat():
    pat = _read_secret("HASHNODE_PAT")
    if not pat:
        pytest.skip("HASHNODE_PAT is not set — skipping Hashnode UI tests")
    return pat


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


def test_neo4j_article_preview_renders_images(page):
    """
    Select an article known to contain images (Neo4j article).
    Verify <img> elements appear and have absolute https:// src values.
    Falls back to the first article if the Neo4j article is not in the list.
    """
    _to_draft_list(page)

    # Try to find the Neo4j article via search first
    page.locator("#draft-search").fill("Neo4j")
    page.wait_for_timeout(400)

    rows = page.locator(".draft-row")
    neo4j_rows = rows.filter(has_text="Neo4j")
    if neo4j_rows.count() > 0:
        neo4j_rows.first.click()
    else:
        # Fall back: clear search and pick any first row
        page.locator("#draft-search").fill("")
        page.wait_for_selector(".draft-row", timeout=5_000)
        page.locator(".draft-row").first.click()

    advance(page)
    page.wait_for_selector("#markdown-preview", timeout=10_000)

    # Wait for body fetch to complete and preview to populate
    page.wait_for_function(
        "document.querySelector('#markdown-preview').innerHTML.length > 100",
        timeout=15_000,
    )

    imgs = page.locator("#markdown-preview img")
    if imgs.count() == 0:
        pytest.skip("Selected article has no images — need an image-rich article")

    assert imgs.count() >= 1
    for i in range(imgs.count()):
        src = imgs.nth(i).get_attribute("src") or ""
        assert src.startswith("https://"), f"Image {i} src is not absolute https://: {src!r}"


# ── 5. Import completes ───────────────────────────────────────────────────────


def test_import_navigates_to_editor(page):
    """Clicking Import on the review screen must navigate to the editor."""
    _to_review(page)
    page.wait_for_selector("#title-input", timeout=5_000)
    with page.expect_navigation(timeout=15_000):
        advance(page)
    assert "editor/" in page.url
