"""
test_visual_create_article.py — Screenshot every wizard step of Create Article.

Run:
    pytest tests/tests_ui/test_create_article/test_visual_create_article.py -m visual --browser chromium -v -s

Outputs → tests/tests_ui/outputs/screenshots/create_article/
"""
import pytest

from tests.tests_ui.conftest import BASE_URL
from tests.tests_ui.utils.screenshots import assert_then_snap, snap
from tests.tests_ui.utils.states import create_step_1, create_step_2, create_step_3

pytestmark = pytest.mark.visual

URL = f"{BASE_URL}/screens/create-article/v1.html"
SCREEN = "create_article"


def _goto(page):
    page.goto(URL)
    page.wait_for_selector("#step-1", timeout=5000)


# ── Step 1 ────────────────────────────────────────────────────────────────────


def test_visual_create_step1_empty(page):
    """Step 1 — prompt textarea, empty."""
    _goto(page)
    assert_then_snap(page, create_step_1, SCREEN, "step1_empty")


def test_visual_create_step1_filled(page):
    """Step 1 — prompt textarea with text, template selected."""
    _goto(page)
    page.get_by_role("button", name="Tutorial").click()
    assert_then_snap(page, create_step_1, SCREEN, "step1_template_filled")


def test_visual_create_step1_char_count(page):
    """Step 1 — character counter updated after typing."""
    _goto(page)
    page.locator("#prompt-text").fill("Short test prompt.")
    assert_then_snap(page, create_step_1, SCREEN, "step1_char_count")


# ── Step 2 ────────────────────────────────────────────────────────────────────


def test_visual_create_step2(page):
    """Step 2 — skill selection + provider buttons."""
    _goto(page)
    page.locator("#next-btn").click()
    assert_then_snap(page, create_step_2, SCREEN, "step2_default")


def test_visual_create_step2_skill_selected(page):
    """Step 2 — one skill row highlighted."""
    _goto(page)
    page.locator("#next-btn").click()
    create_step_2.assert_on(page)
    page.locator("#skill-list .skill-row").first.click()
    assert_then_snap(page, create_step_2, SCREEN, "step2_skill_selected")


# ── Step 3 ────────────────────────────────────────────────────────────────────


def test_visual_create_step3(page):
    """Step 3 — generation / review step."""
    _goto(page)
    page.locator("#next-btn").click()
    create_step_2.assert_on(page)
    page.locator("#next-btn").click()
    assert_then_snap(page, create_step_3, SCREEN, "step3_default")
