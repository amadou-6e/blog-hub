"""
test_break_create_article.py — Breaking-path tests for the Create Article wizard.

Run:
    pytest tests/tests_ui/test_create_article/test_break_create_article.py -m breaking --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/breaking/create_article/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import snap

pytestmark = pytest.mark.breaking

URL = f"{BASE_URL}/screens/create-article/v1.html"
SCREEN = "breaking/create_article"


@pytest.fixture(autouse=True)
def capture_js_errors(page):
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield
    if errors:
        print(f"\n[breaking] JS errors: {errors}")


def _goto(page):
    page.goto(URL)
    page.wait_for_selector("#step-1", timeout=5000)


def _responsive(page) -> bool:
    try:
        return bool(page.evaluate("() => true"))
    except Exception:
        return False


# ── 1. Next with empty prompt ─────────────────────────────────────────────────


def test_break_next_empty_prompt(page):
    """Clicking Next from step 1 with no prompt text must not crash."""
    _goto(page)
    page.locator("#next-btn").click()
    page.wait_for_timeout(400)
    assert _responsive(page)
    snap(page, SCREEN, "next_empty_prompt")


# ── 2. Rapid Next/Back cycles ─────────────────────────────────────────────────


def test_break_rapid_next_back_cycles(page):
    """Rapidly alternating Next and Back between steps must leave the wizard intact."""
    _goto(page)
    for _ in range(4):
        page.locator("#next-btn").click()
        page.wait_for_timeout(80)
        page.locator("#back-btn").click()
        page.wait_for_timeout(80)
    assert _responsive(page)
    snap(page, SCREEN, "rapid_next_back_cycles")


# ── 3. Save template with whitespace-only prompt ──────────────────────────────


def test_break_save_template_whitespace_only(page):
    """Saving a template with only whitespace should show an alert or be a no-op."""
    _goto(page)
    page.locator("#prompt-text").fill("   \t\n  ")
    page.on("dialog", lambda d: d.accept())
    page.locator("[onclick='saveAsTemplate()']").click()
    page.wait_for_timeout(300)
    assert _responsive(page)
    snap(page, SCREEN, "save_template_whitespace")


# ── 4. Advance to step 3 and click Back multiple times ───────────────────────


def test_break_step3_multi_back(page):
    """Reach step 3 then click Back more times than there are steps."""
    _goto(page)
    page.locator("#next-btn").click()
    page.wait_for_selector("#step-2:visible", timeout=3000)
    page.locator("#next-btn").click()
    page.wait_for_selector("#step-3", timeout=5000)

    for _ in range(5):
        page.locator("#back-btn").click()
        page.wait_for_timeout(100)

    assert _responsive(page)
    snap(page, SCREEN, "step3_multi_back")


# ── 5. Simultaneous template spam ────────────────────────────────────────────


def test_break_template_btn_spam(page):
    """Clicking template buttons in rapid succession must not corrupt prompt state."""
    _goto(page)
    for _ in range(6):
        page.get_by_role("button", name="Tutorial").click()
        page.wait_for_timeout(40)
        page.get_by_role("button", name="Comparison").click()
        page.wait_for_timeout(40)
    text = page.locator("#prompt-text").input_value()
    assert len(text) > 0, "Prompt empty after template spam"
    assert _responsive(page)
    snap(page, SCREEN, "template_btn_spam")
