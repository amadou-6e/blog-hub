"""
test_settings_bridge.py — Bridge tests: create-article / import-article ↔ settings.

Covers all navigation links that cross the boundary between content-creation
screens and the Settings screen that were added or fixed recently:

  create-article/v1.html:
    • Codex warning  "Add in Settings →"  → settings
    • Step 3         "Manage connections" → settings

  import-article/v1.html (platform mode, disconnected state):
    • "Connect" / configure workflow leads user toward settings

  settings/v2.html:
    • "Articles" back-link               → overview

Run against a live backend (port 8000):
    pytest tests/tests_ui/bridges/test_settings_bridge.py -m browser --browser chromium -v
"""
import pytest

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

CREATE_URL = f"{BASE_URL}/screens/create-article/v1.html"
IMPORT_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"

SAMPLE_PROMPT = "A practical guide to zero-downtime Postgres migrations using pg_repack."

# ── Helpers ───────────────────────────────────────────────────────────────────


def goto_create(page):
    page.goto(CREATE_URL)
    page.wait_for_selector("#step-1", timeout=5000)


def goto_import(page):
    page.goto(IMPORT_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)


def reach_step2(page):
    goto_create(page)
    page.locator("#prompt-text").fill(SAMPLE_PROMPT)
    page.locator("#next-btn").click()
    page.wait_for_selector("#step-2", timeout=3000)


def reach_step3(page):
    reach_step2(page)
    page.locator("#next-btn").click()
    page.wait_for_selector("#step-3", timeout=3000)


# ── 1. create-article → settings (Codex warning link) ────────────────────────


def test_codex_warning_visible_after_selecting_codex(page):
    reach_step2(page)
    page.evaluate("_providersData = [{id:'codex',label:'Codex',configured:false}]")
    page.locator("#provider-codex").click()
    assert page.locator("#codex-warning").is_visible()


def test_codex_warning_add_in_settings_link_exists(page):
    reach_step2(page)
    page.evaluate("_providersData = [{id:'codex',label:'Codex',configured:false}]")
    page.locator("#provider-codex").click()
    link = page.locator("#codex-warning a")
    assert link.is_visible()
    assert "settings" in link.get_attribute("href")


def test_codex_warning_add_in_settings_navigates_to_settings(page):
    reach_step2(page)
    page.evaluate("_providersData = [{id:'codex',label:'Codex',configured:false}]")
    page.locator("#provider-codex").click()
    with page.expect_navigation(timeout=5000):
        page.locator("#codex-warning a").click()
    assert "settings" in page.url


# ── 2. create-article → settings (Manage connections button) ─────────────────


def test_manage_connections_link_visible_at_step_3(page):
    reach_step3(page)
    assert page.get_by_text("Manage connections").is_visible()


def test_manage_connections_link_href_contains_settings(page):
    reach_step3(page)
    href = page.get_by_text("Manage connections").get_attribute("href")
    assert "settings" in href


def test_manage_connections_navigates_to_settings(page):
    reach_step3(page)
    with page.expect_navigation(timeout=5000):
        page.get_by_text("Manage connections").click()
    assert "settings" in page.url


# ── 3. settings → overview (back-link) ───────────────────────────────────────


def test_settings_articles_link_navigates_to_overview(page):
    page.goto(SETTINGS_URL)
    page.wait_for_selector("a[href*='overview']", timeout=5000)
    with page.expect_navigation(timeout=5000):
        page.locator("a[href*='overview']").first.click()
    assert "overview" in page.url


def test_settings_articles_link_goes_to_v3(page):
    page.goto(SETTINGS_URL)
    page.wait_for_selector("a[href*='overview']", timeout=5000)
    href = page.locator("a[href*='overview']").first.get_attribute("href")
    assert "v3" in href


# ── 4. import-article → settings (disconnected platform path) ────────────────


def test_import_platform_devto_is_disconnected(page):
    goto_import(page)
    devto = page.locator(".platform-card").filter(has_text="Dev.to")
    assert "disconnected" in devto.get_attribute("class")


def test_import_disconnected_platform_cannot_advance(page):
    """Selecting a disconnected platform keeps Next disabled, nudging user to settings."""
    goto_import(page)
    page.locator(".platform-card").filter(has_text="Dev.to").click()
    assert page.locator("#primary-btn").is_disabled()


def test_import_cancel_returns_to_overview(page):
    goto_import(page)
    with page.expect_navigation(timeout=5000):
        page.locator("#cancel-link").click()
    assert "overview" in page.url
