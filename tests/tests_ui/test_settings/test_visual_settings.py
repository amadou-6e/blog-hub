"""
test_visual_settings.py — Screenshot key states of the Settings screen (v2.html).

Run:
    pytest tests/tests_ui/test_settings/test_visual_settings.py -m visual --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/settings/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL, SETTINGS_URL
from tests.tests_ui.utils.screenshots import snap, snap_element

pytestmark = pytest.mark.visual

SCREEN = "settings"
PLATFORM_IDS = ("medium", "hashnode", "devto")


def _goto(page):
    page.goto(SETTINGS_URL)
    page.wait_for_selector("#section-platforms", timeout=5000)
    page.wait_for_function(
        "document.querySelector('#platform-list .text-muted') === null "
        "|| document.querySelector('#platform-list').children.length > 1",
        timeout=5000,
    )


# ── 1. Platforms tab (default) ────────────────────────────────────────────────


def test_visual_settings_platforms_tab(page):
    """Settings — Publishing Platforms tab, all disconnected."""
    _goto(page)
    snap(page, SCREEN, "platforms_tab_disconnected")


def test_visual_settings_platform_card_each(page):
    """Settings — close-up of each platform card."""
    _goto(page)
    for pid in PLATFORM_IDS:
        card = page.locator(f"#plat-card-{pid}")
        snap_element(card, SCREEN, f"platform_card_{pid}")


# ── 2. AI Providers tab ───────────────────────────────────────────────────────


def test_visual_settings_ai_providers_tab(page):
    """Settings — AI Providers tab, both cards not configured."""
    _goto(page)
    page.locator("[data-section='ai']").click()
    page.wait_for_selector("#section-ai:visible", timeout=3000)
    snap(page, SCREEN, "ai_providers_tab")


def test_visual_settings_ai_anthropic_card(page):
    """Settings — close-up of the Anthropic (Claude) AI card."""
    _goto(page)
    page.locator("[data-section='ai']").click()
    page.wait_for_selector("#ai-wrap-anthropic", timeout=3000)
    snap_element(page.locator("#ai-wrap-anthropic"), SCREEN, "ai_card_anthropic")


# ── 3. Key-input expanded ─────────────────────────────────────────────────────


def test_visual_settings_medium_key_expanded(page):
    """Settings — Medium platform card with API key input row expanded."""
    _goto(page)
    card = page.locator("#plat-card-medium")
    card.get_by_role("button").filter(
        has_text=lambda t: any(w in t.lower() for w in ("key", "token", "connect"))).first.click()
    page.wait_for_selector("#expand-medium:visible", timeout=2000)
    snap(page, SCREEN, "medium_key_input_expanded")


def test_visual_settings_hashnode_key_expanded(page):
    """Settings — Hashnode platform card with API key input row expanded."""
    _goto(page)
    card = page.locator("#plat-card-hashnode")
    card.get_by_role("button").filter(
        has_text=lambda t: any(w in t.lower() for w in ("key", "token", "connect"))).first.click()
    page.wait_for_selector("#expand-hashnode:visible", timeout=2000)
    snap(page, SCREEN, "hashnode_key_input_expanded")


# ── 4. Token saved → connected state ─────────────────────────────────────────


def test_visual_settings_medium_connected(page):
    """Settings — Medium platform card after token saved (connected state)."""
    _goto(page)
    card = page.locator("#plat-card-medium")
    card.get_by_role("button").filter(
        has_text=lambda t: any(w in t.lower() for w in ("key", "token", "connect"))).first.click()
    page.wait_for_selector("#key-input-medium", timeout=2000)
    page.locator("#key-input-medium").fill("test-token-visual")
    card.get_by_role("button", name="Save").click()
    page.wait_for_timeout(600)
    snap(page, SCREEN, "medium_connected")
