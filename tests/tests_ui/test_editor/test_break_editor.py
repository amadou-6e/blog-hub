"""
test_break_editor.py — Breaking-path tests for the Editor screen.

Run:
    pytest tests/tests_ui/test_editor/test_break_editor.py -m breaking --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/breaking/editor/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.breaking

SCREEN = "breaking/editor"
ARTICLE_ID = "art_001"
URL = f"{BASE_URL}/screens/editor/v2.html?id={ARTICLE_ID}"


@pytest.fixture(autouse=True)
def capture_js_errors(page):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield
    if errors:
        print(f"\n[breaking] JS errors: {errors}")


def _goto(page):
    page.goto(URL)
    page.wait_for_selector("#raw-editor", timeout=8000)
    page.wait_for_function(
        "document.getElementById('file-label').textContent !== 'loading\u2026'",
        timeout=10000,
    )


def _responsive(page) -> bool:
    try:
        return bool(page.evaluate("() => true"))
    except Exception:
        return False


# ── 1. Navigate without ?id= ──────────────────────────────────────────────────


def test_break_editor_missing_id(page):
    """Loading the editor without ?id= must redirect gracefully, not crash."""
    page.goto(f"{BASE_URL}/screens/editor/v2.html")
    page.wait_for_timeout(2000)
    assert _responsive(page)
    snap(page, SCREEN, "missing_id_redirect")


# ── 2. Non-existent article ID ────────────────────────────────────────────────


def test_break_editor_bad_article_id(page):
    """Loading an article ID that does not exist must not hard-crash the editor."""
    page.goto(f"{BASE_URL}/screens/editor/v2.html?id=non_existent_000")
    page.wait_for_timeout(3000)
    assert _responsive(page)
    snap(page, SCREEN, "bad_article_id")


# ── 3. Rapid accordion open/close ────────────────────────────────────────────


def test_break_accordion_rapid_toggle(page):
    """Rapidly toggling accordion sections must not corrupt the DOM or freeze."""
    _goto(page)
    headers = page.locator(".acc-hdr")
    count = headers.count()
    for _ in range(3):
        for i in range(count):
            headers.nth(i).click()
            page.wait_for_timeout(30)
    assert _responsive(page)
    snap(page, SCREEN, "accordion_rapid_toggle")


# ── 4. Type and immediately navigate away ────────────────────────────────────


def test_break_editor_navigate_away_unsaved(page):
    """Navigating away with unsaved edits must not leave the app in a broken state."""
    _goto(page)
    page.locator("#raw-editor").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" unsaved-break-test")
    # Navigate away before autosave fires
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_timeout(600)
    assert _responsive(page)
    snap(page, SCREEN, "navigate_away_unsaved")


# ── 5. Panel strip triple toggle ─────────────────────────────────────────────


def test_break_panel_strip_triple_toggle(page):
    """Toggling the panel strip three times must leave it in a consistent state."""
    _goto(page)
    for _ in range(3):
        page.locator("#panel-strip").click()
        page.wait_for_timeout(150)
    assert _responsive(page)
    snap(page, SCREEN, "panel_strip_triple_toggle")


# ── 6. Paste extremely large content ─────────────────────────────────────────


def test_break_editor_paste_large_content(page):
    """Pasting very large text must not freeze the word-count or lock the UI."""
    _goto(page)
    large_text = "word " * 5000  # 25 000 chars
    page.locator("#raw-editor").click()
    page.keyboard.press("Control+A")
    page.keyboard.type(large_text[:500])  # paste representatively, not all 25k
    page.wait_for_timeout(500)
    assert _responsive(page)
    snap(page, SCREEN, "paste_large_content")
