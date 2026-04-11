"""
test_visual_editor.py — Screenshot key states of the Editor screen (v2.html).

Run:
    pytest tests/tests_ui/test_editor/test_visual_editor.py -m visual --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/editor/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.visual

ARTICLE_ID = "art_001"
URL = f"{BASE_URL}/screens/editor/v2.html?id={ARTICLE_ID}"
SCREEN = "editor"


def _goto(page):
    page.goto(URL)
    page.wait_for_selector("#raw-editor", timeout=8000)
    page.wait_for_function(
        "document.getElementById('file-label').textContent !== 'loading\u2026'",
        timeout=10000,
    )


# ── 1. Default loaded state ───────────────────────────────────────────────────


def test_visual_editor_loaded(page):
    """Editor default state — article loaded, comments panel open."""
    _goto(page)
    snap(page, SCREEN, "loaded_default")


# ── 2. Left panel collapsed ───────────────────────────────────────────────────


def test_visual_editor_panel_collapsed(page):
    """Editor with left accordion panel collapsed."""
    _goto(page)
    page.locator("#panel-strip").click()
    page.wait_for_function(
        "document.getElementById('panel-content').style.display === 'none'",
        timeout=3000,
    )
    snap(page, SCREEN, "panel_collapsed")


# ── 3. Accordion sections expanded ───────────────────────────────────────────


def test_visual_editor_destinations_open(page):
    """Editor with Destinations accordion section expanded."""
    _goto(page)
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations:visible", timeout=3000)
    snap(page, SCREEN, "destinations_open")


def test_visual_editor_chat_open(page):
    """Editor with Chat accordion section expanded."""
    _goto(page)
    page.locator(".acc-hdr").filter(has_text="Chat").click()
    page.wait_for_selector("#abody-chat:visible", timeout=3000)
    snap(page, SCREEN, "chat_open")


def test_visual_editor_patches_open(page):
    """Editor with Patches accordion section expanded."""
    _goto(page)
    page.locator(".acc-hdr").filter(has_text="Patches").click()
    page.wait_for_selector("#abody-patches:visible", timeout=3000)
    snap(page, SCREEN, "patches_open")


# ── 4. Unsaved dot (dirty state) ──────────────────────────────────────────────


def test_visual_editor_unsaved_dot(page):
    """Editor showing the amber unsaved-changes indicator."""
    _goto(page)
    page.locator("#raw-editor").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" x")
    page.wait_for_function(
        "document.getElementById('save-indicator').innerHTML.includes('fbbf24')",
        timeout=3000,
    )
    snap(page, SCREEN, "unsaved_dot")


# ── 5. Word count visible ─────────────────────────────────────────────────────


def test_visual_editor_word_count(page):
    """Editor footer bar showing word count."""
    _goto(page)
    page.wait_for_selector("#word-count", timeout=5000)
    snap(page, SCREEN, "word_count_visible")
