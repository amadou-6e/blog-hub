"""
test_overview_import_bridge.py — Bridge tests: Overview → create/import flows.

Covers the split button (variant A):
  - Left button: "New article" navigates directly to create-article/v1.html
  - Right chevron: opens a two-item dropdown (Import from platform / Upload .md file)

Run:
    pytest tests/ui/bridges/test_overview_import_bridge.py -m browser --browser chromium -v
"""
import pytest

from tests.ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

OVERVIEW_URL = f"{BASE_URL}/screens/overview/v3.html"


@pytest.fixture
def overview(page):
    page.goto(OVERVIEW_URL)
    page.wait_for_selector("#split-btn-wrap", timeout=5000)
    return page


@pytest.fixture
def menu_open(overview):
    overview.locator("#create-menu-btn").click()
    overview.wait_for_selector("#import-menu", timeout=3000)
    return overview


# ── Button presence ──────────────────────────────────────────────────────────

def test_new_article_button_visible(overview):
    assert overview.locator("#split-btn-wrap").get_by_text("New article").is_visible()


def test_create_menu_button_visible(overview):
    assert overview.locator("#create-menu-btn").is_visible()


# ── Left button: direct navigation ───────────────────────────────────────────

def test_new_article_navigates_to_create_article(overview):
    with overview.expect_navigation():
        overview.locator("#split-btn-wrap").get_by_text("New article").click()
    assert "create-article/v1.html" in overview.url


# ── Dropdown open / close ─────────────────────────────────────────────────────

def test_button_opens_dropdown(overview):
    overview.locator("#create-menu-btn").click()
    assert overview.locator("#import-menu").is_visible()


def test_dropdown_has_two_items(menu_open):
    assert menu_open.locator("#import-menu button").count() == 2


def test_dropdown_has_import_from_platform(menu_open):
    assert menu_open.locator("#import-menu").get_by_text("Import from platform").is_visible()


def test_dropdown_has_upload_md(menu_open):
    assert menu_open.locator("#import-menu").get_by_text("Upload .md file").is_visible()


def test_dropdown_items_have_subtitles(menu_open):
    subtitles = menu_open.locator("#import-menu button div div:last-child")
    assert subtitles.count() == 2


def test_clicking_outside_closes_dropdown(menu_open):
    menu_open.locator("body").click(position={"x": 100, "y": 400})
    assert not menu_open.locator("#import-menu").is_visible()


def test_button_toggles_dropdown_closed(overview):
    btn = overview.locator("#create-menu-btn")
    btn.click()
    assert overview.locator("#import-menu").is_visible()
    btn.click()
    assert not overview.locator("#import-menu").is_visible()


# ── Navigation: Import from platform ─────────────────────────────────────────

def test_import_platform_navigates_to_import_screen(menu_open):
    with menu_open.expect_navigation():
        menu_open.locator("#import-menu").get_by_text("Import from platform").click()
    assert "import-article/v1.html" in menu_open.url


def test_import_platform_sets_mode_platform(menu_open):
    with menu_open.expect_navigation():
        menu_open.locator("#import-menu").get_by_text("Import from platform").click()
    assert "mode=platform" in menu_open.url


def test_import_platform_sets_return_to_overview(menu_open):
    with menu_open.expect_navigation():
        menu_open.locator("#import-menu").get_by_text("Import from platform").click()
    assert "returnTo=overview" in menu_open.url


# ── Navigation: Upload .md ────────────────────────────────────────────────────

def test_upload_md_navigates_to_import_screen(menu_open):
    with menu_open.expect_navigation():
        menu_open.locator("#import-menu").get_by_text("Upload .md file").click()
    assert "import-article/v1.html" in menu_open.url


def test_upload_md_sets_mode_upload(menu_open):
    with menu_open.expect_navigation():
        menu_open.locator("#import-menu").get_by_text("Upload .md file").click()
    assert "mode=upload" in menu_open.url


def test_upload_md_sets_return_to_overview(menu_open):
    with menu_open.expect_navigation():
        menu_open.locator("#import-menu").get_by_text("Upload .md file").click()
    assert "returnTo=overview" in menu_open.url
