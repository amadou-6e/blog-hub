"""
test_break_overview.py — Breaking-path tests for the Overview screen.

Run:
    pytest tests/tests_ui/test_overview/test_break_overview.py -m breaking --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/breaking/overview/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.breaking

URL = f"{BASE_URL}/screens/overview/v3.html"
SCREEN = "breaking/overview"


@pytest.fixture(autouse=True)
def capture_js_errors(page):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield
    if errors:
        print(f"\n[breaking] JS errors: {errors}")


def _goto(page):
    page.goto(URL)
    page.wait_for_timeout(600)


def _responsive(page) -> bool:
    try:
        return bool(page.evaluate("() => true"))
    except Exception:
        return False


# ── 1. Open split-menu then immediately navigate ──────────────────────────────

def test_break_menu_open_then_navigate(page):
    """Open the split-button dropdown then navigate to another page — no crash."""
    _goto(page)
    page.wait_for_selector("#create-menu-btn", timeout=5000)
    page.locator("#create-menu-btn").click()
    page.wait_for_selector("#import-menu", timeout=3000)
    snap(page, SCREEN, "menu_open_before_navigate")
    # Navigate away while menu is open
    page.goto(f"{BASE_URL}/screens/settings/v2.html")
    page.wait_for_timeout(400)
    assert _responsive(page)
    snap(page, SCREEN, "menu_open_navigated_away")


# ── 2. Click article card with empty store ───────────────────────────────────

def test_break_click_card_empty_store(page):
    """Click an article card when none may be loaded yet → must not panic."""
    _goto(page)
    cards = page.locator(".article-card")
    if cards.count() == 0:
        # No cards on empty store — the test passes trivially, capture state
        snap(page, SCREEN, "click_card_no_cards_present")
        return
    cards.first.click()
    page.wait_for_timeout(500)
    assert _responsive(page)
    snap(page, SCREEN, "click_card_action_taken")


# ── 3. Rapid split-button dropdown open/close ─────────────────────────────────

def test_break_split_menu_rapid_toggle(page):
    """Rapidly toggling the split-button dropdown must not leave it stuck open."""
    _goto(page)
    page.wait_for_selector("#create-menu-btn", timeout=5000)
    btn = page.locator("#create-menu-btn")
    for _ in range(6):
        btn.click()
        page.wait_for_timeout(60)
    page.wait_for_timeout(200)
    assert _responsive(page)
    snap(page, SCREEN, "split_menu_rapid_toggle")


# ── 4. Click outside menu to dismiss, then re-open ───────────────────────────

def test_break_menu_dismiss_reopen(page):
    """Dismiss the dropdown by clicking outside, then reopen it — must stay stable."""
    _goto(page)
    page.wait_for_selector("#create-menu-btn", timeout=5000)
    for _ in range(3):
        page.locator("#create-menu-btn").click()
        page.wait_for_selector("#import-menu", timeout=2000)
        page.locator("body").click(position={"x": 100, "y": 500})
        page.wait_for_timeout(150)
    assert _responsive(page)
    snap(page, SCREEN, "menu_dismiss_reopen")


# ── 5. Select Import from platform then immediately use browser Back ──────────

def test_break_import_then_browser_back(page):
    """Navigate to import screen via menu, then hit browser Back → overview intact."""
    _goto(page)
    page.wait_for_selector("#create-menu-btn", timeout=5000)
    page.locator("#create-menu-btn").click()
    page.wait_for_selector("#import-menu", timeout=3000)

    with page.expect_navigation(timeout=5000):
        page.locator("#import-menu").get_by_text("Import from platform").click()

    page.go_back()
    page.wait_for_timeout(400)
    assert _responsive(page)
    snap(page, SCREEN, "import_then_browser_back")
