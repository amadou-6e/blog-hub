"""
test_remote_components.py — Remote fidelity tests.

For every visual component sourced from an external dependency, fetch the raw
upstream asset and store it beside the local screenshot so a human can compare
"what the CDN serves" vs "what the app renders".

Run:
    pytest tests/tests_ui/test_remote/test_remote_components.py -m visual --browser chromium -v -s

Outputs:
    outputs/remote_dumps/images/   ← raw upstream images
    outputs/remote_dumps/html/     ← raw upstream HTML pages
    outputs/screenshots/remote/    ← local renders of components that consume remote assets

Tests are gracefully skipped (not failed) when a remote URL is unreachable.
"""
from __future__ import annotations

import pytest
import requests as http

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.remote import fetch_remote_image, fetch_remote_html
from tests.tests_ui.utils.screenshots import snap, snap_element

pytestmark = pytest.mark.visual

# ── Hashnode fixture image constants (same source as test_import_hashnode.py) ─
_IMAGE_BASE = (
    "https://raw.githubusercontent.com/amadou-6e/blog-components/main/"
    "medium/002_neo4j_llamaindex/images"
)

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
SCREEN = "remote"


# ── 1. Hashnode blog-components cover image ───────────────────────────────────


def test_remote_hashnode_cover_title_image():
    """Fetch the 'title.png' image used as the Hashnode fixture cover and save it."""
    url = f"{_IMAGE_BASE}/title.png"
    path = fetch_remote_image(url, "hashnode_fixture_cover_title")
    if path is None:
        pytest.skip(f"Remote image unreachable: {url}")
    assert path.exists() and path.stat().st_size > 0, "Saved image is empty"


def test_remote_hashnode_knowledge_graph_image():
    """Fetch the 'knowledge_graph.png' inline body image and save it."""
    url = f"{_IMAGE_BASE}/knowledge_graph.png"
    path = fetch_remote_image(url, "hashnode_fixture_body_knowledge_graph")
    if path is None:
        pytest.skip(f"Remote image unreachable: {url}")
    assert path.exists() and path.stat().st_size > 0, "Saved image is empty"


# ── 2. Hashnode review pane — local render alongside remote dump ───────────────


def test_remote_hashnode_review_pane_vs_remote(page):
    """
    Navigate to the Hashnode review pane for the image fixture draft and screenshot
    the rendered article body.  The remote images fetched above live in
    outputs/remote_dumps/ for side-by-side human comparison.
    """
    # Save both remote images (best-effort; skip whole test if CDN down)
    title_path = fetch_remote_image(f"{_IMAGE_BASE}/title.png", "hashnode_fixture_cover_title")
    kg_path = fetch_remote_image(f"{_IMAGE_BASE}/knowledge_graph.png",
                                 "hashnode_fixture_body_knowledge_graph")
    if title_path is None or kg_path is None:
        pytest.skip("Remote images unreachable — cannot perform fidelity comparison")

    # Navigate to import flow, select Hashnode
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    # Hashnode requires PAT — this test intentionally stops at the platform picker
    # and screenshots it rather than trying the live API (the live API path is
    # covered by test_import_hashnode.py which requires HASHNODE_PAT).
    snap(page, SCREEN, "import_platform_hashnode_selected")


# ── 3. Overview screen — article card cover image rendering ───────────────────


def test_remote_overview_article_card_cover(page):
    """
    Screenshot each article card in the overview grid.  Seed articles don't carry
    CDN cover images (source=native), so this captures the placeholder render.
    If a future seed article has a cover_image URL, this test saves the remote
    image and the rendered card side-by-side.
    """
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_selector(".article-card", timeout=8000)

    cards = page.locator(".article-card")
    for i in range(min(cards.count(), 6)):
        card = cards.nth(i)

        # Try to read any cover image src from within the card
        cover_src: str = card.evaluate(
            "el => { const img = el.querySelector('img'); return img ? img.src : ''; }"
        )

        if cover_src and cover_src.startswith("http"):
            stem = f"card_{i}_cover"
            fetch_remote_image(cover_src, stem)  # best-effort, no skip

        snap_element(card, SCREEN, f"overview_card_{i}")

    # Full page overview for context
    snap(page, SCREEN, "overview_full_page")


# ── 4. Settings page — raw HTML dump ─────────────────────────────────────────


def test_remote_settings_page_html_dump():
    """Fetch the settings page HTML and save it to remote_dumps/html/.

    Useful for inspecting the rendered DOM structure without a browser.
    """
    url = f"{BASE_URL}/screens/settings/v2.html"
    path = fetch_remote_html(url, "settings_v2")
    if path is None:
        pytest.skip(f"Settings page unreachable at {url}")
    assert path.exists() and path.stat().st_size > 0
