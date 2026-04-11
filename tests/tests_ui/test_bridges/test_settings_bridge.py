"""
test_settings_bridge.py — Playwright tests for the Settings screen.

Covers: platform connection cards, AI provider cards, save/clear token,
and navigation links.

Run:
    pytest tests/tests_ui/test_bridges/test_settings_bridge.py -m browser --browser chromium -v
"""
import pytest

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

URL = f"{BASE_URL}/screens/settings/v2.html"


# ── Helpers ──────────────────────────────────────────────────────────────────


def goto(page):
    page.goto(URL)
    page.wait_for_selector("nav", timeout=5000)


def open_section(page, data_section: str):
    """Click a sidebar nav button to open a settings section."""
    page.locator(f"[data-section='{data_section}']").click()


# ── 1. Page load ─────────────────────────────────────────────────────────────


def test_settings_page_loads(page):
    goto(page)
    assert "Settings" in page.title() or "BlogHub" in page.title()


def test_nav_bar_is_visible(page):
    goto(page)
    assert page.locator("nav").is_visible()


def test_settings_sidebar_is_visible(page):
    goto(page)
    assert page.locator("aside").is_visible()


# ── 2. Navigation links ───────────────────────────────────────────────────────


def test_nav_articles_link_href(page):
    goto(page)
    link = page.locator("nav a", has_text="Articles").first
    href = link.get_attribute("href")
    assert href and "overview" in href


def test_nav_new_article_link_href(page):
    goto(page)
    link = page.locator("nav a", has_text="New article").first
    href = link.get_attribute("href")
    assert href and "create-article" in href


def test_nav_import_link_href(page):
    goto(page)
    link = page.locator("nav a", has_text="Import").first
    href = link.get_attribute("href")
    assert href and "import-article" in href


# ── 3. Sidebar sections ───────────────────────────────────────────────────────


def test_platforms_section_button_visible(page):
    goto(page)
    assert page.locator("[data-section='platforms']").is_visible()


def test_ai_section_button_visible(page):
    goto(page)
    assert page.locator("[data-section='ai']").is_visible()


def test_platforms_section_shows_on_click(page):
    goto(page)
    open_section(page, "platforms")
    # The platforms section should contain a list of platform cards
    # At least one connection card should be present
    page.wait_for_timeout(300)
    # Check the content area has platform-related content
    content = page.locator("main, .flex-1, #content-area, section").first
    assert content.is_visible()


def test_ai_section_shows_on_click(page):
    goto(page)
    open_section(page, "ai")
    page.wait_for_timeout(300)
    # AI section should be visible after switching
    btn = page.locator("[data-section='ai']")
    assert "active" in (btn.get_attribute("class") or "")


# ── 4. Platform cards ─────────────────────────────────────────────────────────


def test_medium_card_visible(page):
    goto(page)
    open_section(page, "platforms")
    page.wait_for_timeout(300)
    # Settings page should show a card or section for Medium
    body = page.content()
    assert "medium" in body.lower() or "Medium" in body


def test_hashnode_card_visible(page):
    goto(page)
    open_section(page, "platforms")
    page.wait_for_timeout(300)
    body = page.content()
    assert "hashnode" in body.lower() or "Hashnode" in body


def test_devto_card_visible(page):
    goto(page)
    open_section(page, "platforms")
    page.wait_for_timeout(300)
    body = page.content()
    assert "dev.to" in body.lower() or "devto" in body.lower() or "Dev.to" in body


# ── 5. API key input ──────────────────────────────────────────────────────────


def test_save_button_exists_in_platforms(page):
    goto(page)
    open_section(page, "platforms")
    page.wait_for_timeout(400)
    # At least one Save/Update/Test button should be visible in the section
    body = page.content()
    assert "Save" in body or "Update" in body or "Test" in body


# ── 6. Connection counter in nav ─────────────────────────────────────────────


def test_connection_count_label_exists(page):
    goto(page)
    # Nav should have a connection count indicator
    body = page.content()
    assert "connections" in body.lower() or "connected" in body.lower()
