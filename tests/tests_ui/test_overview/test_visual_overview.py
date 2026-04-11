"""
test_visual_overview.py — Screenshot every key state of the Overview screen.

Run:
    pytest tests/tests_ui/test_overview/test_visual_overview.py -m visual --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/overview/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import assert_then_snap, snap, snap_element, snap_states
from tests.tests_ui.utils.states import overview_articles_loaded, overview_idle, overview_menu_open

pytestmark = pytest.mark.visual

URL = f"{BASE_URL}/screens/overview/v3.html"


def _goto(page):
    page.goto(URL)
    page.wait_for_timeout(800)


# ── 1. Empty store ────────────────────────────────────────────────────────────


def test_visual_overview_empty_store(page):
    """Overview with the seed store reset but no articles shown (empty state)."""
    _goto(page)
    assert_then_snap(page, overview_idle, "overview", "empty_store")


# ── 2. Articles loaded ────────────────────────────────────────────────────────


def test_visual_overview_articles_loaded(page):
    """Overview after articles are visible in the grid."""
    _goto(page)
    assert_then_snap(page, overview_articles_loaded, "overview", "articles_loaded")


def test_visual_overview_article_card(page):
    """Close-up of a single article card (first in the grid)."""
    _goto(page)
    overview_articles_loaded.assert_on(page)
    card = page.locator(".article-card").first
    snap_element(card, "overview", "article_card_close")


# ── 3. Split-button menu open ─────────────────────────────────────────────────


def test_visual_overview_create_menu_open(page):
    """Overview with the split-button dropdown open."""
    _goto(page)
    page.locator("#create-menu-btn").click()
    assert_then_snap(page, overview_menu_open, "overview", "create_menu_open")


# ── 4. Step-through states via snap_states ────────────────────────────────────


def test_visual_overview_all_states(page):
    """Capture multiple UI states from a single test function."""
    _goto(page)
    page.wait_for_selector(".article-card", timeout=8000)

    snap_states(page, "overview", [
        ("loaded_default", lambda: None),
        ("create_dropdown",
         lambda: (page.locator("#create-menu-btn").click(),
                  page.wait_for_selector("#import-menu", timeout=3000))),
    ])
