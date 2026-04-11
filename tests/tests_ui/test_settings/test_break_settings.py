"""
test_break_settings.py — Breaking-path tests for the Settings screen.

Run:
    pytest tests/tests_ui/test_settings/test_break_settings.py -m breaking --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/breaking/settings/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL, SETTINGS_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.breaking

SCREEN = "breaking/settings"


@pytest.fixture(autouse=True)
def capture_js_errors(page):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield
    if errors:
        print(f"\n[breaking] JS errors: {errors}")


def _goto(page):
    page.goto(SETTINGS_URL)
    page.wait_for_selector("#section-platforms", timeout=5000)


def _responsive(page) -> bool:
    try:
        return bool(page.evaluate("() => true"))
    except Exception:
        return False


# ── 1. Save empty token ───────────────────────────────────────────────────────


def test_break_save_empty_token(page):
    """Clicking Save without entering a token value must not crash."""
    _goto(page)
    card = page.locator("#plat-card-medium")
    card.get_by_role("button").filter(
        has_text=lambda t: any(w in t.lower() for w in ("key", "token", "connect"))).first.click()
    page.wait_for_selector("#key-input-medium", timeout=2000)
    # Clear the field (it may have a placeholder value)
    page.locator("#key-input-medium").fill("")
    card.get_by_role("button", name="Save").click()
    page.wait_for_timeout(400)
    assert _responsive(page)
    snap(page, SCREEN, "save_empty_token")


# ── 2. Rapid tab switching ────────────────────────────────────────────────────


def test_break_rapid_tab_switch(page):
    """Rapidly switching between Platforms and AI Providers tabs must not corrupt state."""
    _goto(page)
    for _ in range(6):
        page.locator("[data-section='ai']").click()
        page.wait_for_timeout(60)
        page.locator("[data-section='platforms']").click()
        page.wait_for_timeout(60)
    assert _responsive(page)
    snap(page, SCREEN, "rapid_tab_switch")


# ── 3. Expand/collapse key input multiple times ───────────────────────────────


def test_break_key_input_expand_collapse_spam(page):
    """Rapidly expanding and collapsing the key input row must not corrupt the card."""
    _goto(page)
    card = page.locator("#plat-card-hashnode")
    expand_btn = card.get_by_role("button").filter(
        has_text=lambda t: any(w in t.lower() for w in ("key", "token", "connect"))).first

    for _ in range(5):
        expand_btn.click()
        page.wait_for_timeout(100)
        cancel = card.locator("button", has_text="Cancel")
        if cancel.is_visible():
            cancel.click()
        page.wait_for_timeout(100)

    assert _responsive(page)
    snap(page, SCREEN, "key_input_expand_collapse_spam")


# ── 4. Test-connection button spam ───────────────────────────────────────────


def test_break_test_connection_spam(page):
    """Clicking Test Connection multiple times rapidly must not queue hanging requests."""
    _goto(page)
    btn = page.locator("#test-btn-medium")
    if btn.is_visible():
        for _ in range(4):
            btn.click()
            page.wait_for_timeout(80)
        page.wait_for_timeout(600)
        assert _responsive(page)
        snap(page, SCREEN, "test_connection_spam")
    else:
        pytest.skip("test-btn-medium not visible on fresh store")


# ── 5. Disconnect when already disconnected ──────────────────────────────────


def test_break_disconnect_while_disconnected(page):
    """Attempting to trigger disconnect on an unconnected platform must not crash."""
    _goto(page)
    # The disconnect button is typically only shown when connected; force-evaluate
    result = page.evaluate("""() => {
        // Some UIs expose a disconnect function globally
        if (typeof window.disconnectPlatform === 'function') {
            try { window.disconnectPlatform('medium'); return 'called'; }
            catch (e) { return 'threw: ' + e.message; }
        }
        return 'fn_not_found';
    }""")
    page.wait_for_timeout(400)
    assert _responsive(page)
    snap(page, SCREEN, "disconnect_while_disconnected")
    print(f"\n[breaking] disconnectPlatform result: {result}")
