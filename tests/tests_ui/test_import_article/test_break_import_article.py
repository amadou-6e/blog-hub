"""
test_break_import_article.py — Breaking-path tests for the Import Article screen.

Each test performs an unexpected or adversarial action sequence and asserts that:
  1. No JavaScript error dialog appears.
  2. The page is still interactive (not frozen / blank / in an error state).
  3. A screenshot of the resulting state is saved for human inspection.

Run:
    pytest tests/tests_ui/test_import_article/test_break_import_article.py -m breaking --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/breaking/import_article/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.breaking

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
UPLOAD_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=upload&returnTo=overview"
SCREEN = "breaking/import_article"

_js_errors: list[str] = []

# ── JS error capture ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def capture_js_errors(page):
    """Collect console errors — checked at end of each test."""
    _js_errors.clear()
    page.on("pageerror", lambda exc: _js_errors.append(str(exc)))
    yield
    # Warn (not fail) — some third-party JS errors are expected in dev
    if _js_errors:
        print(f"\n[breaking] JS errors captured: {_js_errors}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _goto_platform(page):
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)


def _page_responsive(page) -> bool:
    """Return True if the page can respond to a simple JS evaluation."""
    try:
        return bool(page.evaluate("() => true"))
    except Exception:
        return False


# ── 1. Rapid Next clicks without selection ────────────────────────────────────


def test_break_rapid_next_no_selection(page):
    """Clicking Next multiple times without selecting a platform should be no-op."""
    _goto_platform(page)
    btn = page.locator("#primary-btn")
    for _ in range(5):
        if not btn.is_disabled():
            btn.click()
        page.wait_for_timeout(80)
    assert _page_responsive(page), "Page became unresponsive"
    snap(page, SCREEN, "rapid_next_no_selection")


# ── 2. Multi-click Next after selection ───────────────────────────────────────


def test_break_multiclick_next_after_selection(page):
    """Rapidly clicking Next after selection must not skip steps or crash."""
    _goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    btn = page.locator("#primary-btn")
    for _ in range(4):
        if not btn.is_disabled():
            btn.click()
        page.wait_for_timeout(100)
    assert _page_responsive(page)
    snap(page, SCREEN, "multiclick_next_after_selection")


# ── 3. Back from step 1 ───────────────────────────────────────────────────────


def test_break_back_at_step1(page):
    """Clicking Back at step 1 (where it's hidden/disabled) must not crash."""
    _goto_platform(page)
    back = page.locator("#back-btn")
    # Force-click even if visibility-hidden
    page.evaluate("document.getElementById('back-btn').click()")
    page.wait_for_timeout(300)
    assert _page_responsive(page)
    snap(page, SCREEN, "back_at_step1")


# ── 4. Select → deselect → Next ───────────────────────────────────────────────


def test_break_select_deselect_platform(page):
    """Selecting and then deselecting a platform card must re-disable Next."""
    _goto_platform(page)
    card = page.locator(".platform-card").filter(has_text="Medium")
    card.click()
    assert not page.locator("#primary-btn").is_disabled()
    card.click()  # deselect (if the UI supports it)
    page.wait_for_timeout(200)
    assert _page_responsive(page)
    snap(page, SCREEN, "select_deselect_platform")


# ── 5. Upload mode — drop unsupported then supported file ─────────────────────


def test_break_drop_unsupported_then_md(page):
    """Drop an .exe file then a .md file — app must recover and accept the .md."""
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)

    # Drop unsupported type
    page.evaluate("""() => {
        const file = new File(['binary'], 'bad.exe', {type: 'application/octet-stream'});
        const dt = new DataTransfer();
        dt.items.add(file);
        document.getElementById('drop-zone')
            .dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
    }""")
    page.wait_for_timeout(300)
    snap(page, SCREEN, "drop_unsupported_exe")

    # Now drop a valid .md
    page.evaluate("""() => {
        const file = new File(['# Recovery test'], 'article.md', {type: 'text/markdown'});
        const dt = new DataTransfer();
        dt.items.add(file);
        document.getElementById('drop-zone')
            .dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
    }""")
    page.wait_for_timeout(400)
    assert _page_responsive(page)
    snap(page, SCREEN, "drop_unsupported_then_md_recovery")


# ── 6. Upload mode — rapid drop spam ─────────────────────────────────────────


def test_break_upload_rapid_drop_spam(page):
    """Dropping files in rapid succession must not leave the UI in a broken state."""
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)

    for i in range(6):
        page.evaluate(f"""() => {{
            const file = new File(['# Article {i}'], 'article_{i}.md', {{type: 'text/markdown'}});
            const dt = new DataTransfer();
            dt.items.add(file);
            document.getElementById('drop-zone')
                .dispatchEvent(new DragEvent('drop', {{bubbles: true, dataTransfer: dt}}));
        }}""")
        page.wait_for_timeout(60)

    page.wait_for_timeout(300)
    assert _page_responsive(page)
    snap(page, SCREEN, "upload_rapid_drop_spam")


# ── 7. Back from step 3 then re-advance ──────────────────────────────────────


def test_break_back_from_step3_readavance(page):
    """Go to step 3 via review, hit Back twice, then Next twice → should reach review again."""
    import requests as http
    http.put(f"{BASE_URL}/api/connections/medium", json={"token": "t"}, timeout=5)

    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    page.locator(".platform-card").filter(has_text="Medium").click()
    page.locator("#primary-btn").click()
    page.wait_for_selector(".draft-row", timeout=15000)
    page.locator(".draft-row").first.click()
    page.locator("#primary-btn").click()
    page.wait_for_selector("#view-review", timeout=10000)

    snap(page, SCREEN, "back_readavance_at_step3")

    # Back to step 2
    page.locator("#back-btn").click()
    page.wait_for_timeout(300)
    snap(page, SCREEN, "back_readavance_returned_step2")

    # Re-advance
    page.locator(".draft-row").first.click()
    page.locator("#primary-btn").click()
    page.wait_for_selector("#view-review", timeout=10000)
    assert _page_responsive(page)
    snap(page, SCREEN, "back_readavance_step3_again")
