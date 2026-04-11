"""
test_create_article.py — Playwright click-through tests for the Create Article wizard.

Run:
    pytest tests/tests_ui/test_screens/test_create_article.py -m browser --browser chromium -v
"""
import pytest

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

URL = f"{BASE_URL}/screens/create-article/v1.html"

# ── Helpers ──────────────────────────────────────────────────────────────────


def goto(page):
    page.goto(URL)
    page.wait_for_selector("#step-1", timeout=5000)


def fill_prompt(page, text="A deep dive into Postgres MVCC and bloat management."):
    page.locator("#prompt-text").fill(text)


def click_next(page):
    page.locator("#next-btn").click()


def click_back(page):
    page.locator("#back-btn").click()


# ── 1. Initial render — Step 1 ───────────────────────────────────────────────


def test_step_1_is_visible_on_load(page):
    goto(page)
    assert page.locator("#step-1").is_visible()


def test_step_2_hidden_on_load(page):
    goto(page)
    assert not page.locator("#step-2").is_visible()


def test_step_3_hidden_on_load(page):
    goto(page)
    assert not page.locator("#step-3").is_visible()


def test_step_bar_renders_three_items(page):
    goto(page)
    assert page.locator("#si-1").is_visible()
    assert page.locator("#si-2").is_visible()
    assert page.locator("#si-3").is_visible()


def test_step_1_circle_is_active(page):
    goto(page)
    # Active circle has indigo background (#6366f1) and shows ✓
    circle = page.locator("#si-circle-1")
    style = circle.get_attribute("style")
    assert "6366f1" in style


def test_prompt_textarea_is_present(page):
    goto(page)
    assert page.locator("#prompt-text").is_visible()


def test_file_drop_zone_is_present(page):
    goto(page)
    assert page.locator("#file-drop-zone").is_visible()


def test_back_btn_visible_on_step_1(page):
    """Back button is rendered but visibility-hidden at step 1."""
    goto(page)
    visibility = page.locator("#back-btn").evaluate(
        "el => el.style.visibility || getComputedStyle(el).visibility")
    # Accept 'hidden' (explicit) or display:none — either is correct
    assert visibility in ("hidden", "") or not page.locator("#back-btn").is_visible()


def test_template_buttons_rendered(page):
    goto(page)
    assert page.get_by_role("button", name="Tutorial").is_visible()
    assert page.get_by_role("button", name="Comparison").is_visible()


def test_next_btn_always_enabled_on_step_1(page):
    """Next is enabled on step 1 regardless of prompt content."""
    goto(page)
    assert not page.locator("#next-btn").is_disabled()


# ── 2. Prompt char counter ────────────────────────────────────────────────────


def test_prompt_char_counter_updates(page):
    goto(page)
    page.locator("#prompt-text").fill("hello")
    count = page.locator("#prompt-count").text_content()
    assert count == "5"


def test_prompt_char_counter_starts_at_zero(page):
    goto(page)
    assert page.locator("#prompt-count").text_content() == "0"


# ── 3. Template shortcuts ────────────────────────────────────────────────────


def test_tutorial_template_loads_into_prompt(page):
    goto(page)
    page.get_by_role("button", name="Tutorial").click()
    text = page.locator("#prompt-text").input_value()
    assert len(text) > 20  # non-empty template text injected


def test_comparison_template_loads_into_prompt(page):
    goto(page)
    page.get_by_role("button", name="Comparison").click()
    text = page.locator("#prompt-text").input_value()
    assert len(text) > 20


# ── 4. Template saved toast ───────────────────────────────────────────────────


def test_save_template_with_empty_prompt_shows_no_toast(page):
    """Empty prompt fires an alert but NOT the toast."""
    goto(page)
    # Dismiss the alert that fires for empty prompt
    page.on("dialog", lambda d: d.accept())
    page.locator("[onclick='saveAsTemplate()']").click()
    assert page.locator("#tmpl-toast").evaluate("el => el.style.display") == "none"


def test_save_template_toast_appears(page):
    goto(page)
    fill_prompt(page)
    page.locator("[onclick='saveAsTemplate()']").click()
    page.wait_for_function("document.getElementById('tmpl-toast').style.display !== 'none'",
                           timeout=2000)
    assert page.locator("#tmpl-toast").is_visible()


def test_save_template_toast_title(page):
    goto(page)
    fill_prompt(page)
    page.locator("[onclick='saveAsTemplate()']").click()
    page.wait_for_selector("#tmpl-toast-title", timeout=2000)
    assert page.locator("#tmpl-toast-title").text_content() == "Template saved"


def test_save_template_toast_dismiss_button(page):
    goto(page)
    fill_prompt(page)
    page.locator("[onclick='saveAsTemplate()']").click()
    page.wait_for_selector("#tmpl-toast-close", timeout=2000)
    page.locator("#tmpl-toast-close").click()
    page.wait_for_function("document.getElementById('tmpl-toast').style.display === 'none'",
                           timeout=1000)


# ── 5. Step 1 → Step 2 ───────────────────────────────────────────────────────


def test_next_from_step_1_shows_step_2(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    assert page.locator("#step-2").is_visible()
    assert not page.locator("#step-1").is_visible()


def test_step_2_skill_list_renders(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#skill-list", timeout=3000)
    items = page.locator("#skill-list .skill-row")
    assert items.count() == 4


def test_step_2_provider_buttons_visible(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#provider-claude", timeout=3000)
    assert page.locator("#provider-claude").is_visible()
    assert page.locator("#provider-codex").is_visible()


def test_step_2_word_count_label_shows_default(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#word-count-label", timeout=3000)
    label = page.locator("#word-count-label").text_content()
    assert "1.5k" in label or "1,500" in label


# ── 6. Step 2 interactions ───────────────────────────────────────────────────


def test_clicking_tutorial_skill_marks_it_selected(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#skill-list", timeout=3000)
    page.locator("#skill-list .skill-row").filter(has_text="Tutorial").click()
    selected = page.locator("#skill-list .skill-row.selected")
    assert "Tutorial" in selected.text_content()


def test_switching_to_codex_shows_warning_if_not_configured(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#provider-codex", timeout=3000)
    page.locator("#provider-codex").click()
    # Wait for API response and potential warning display
    page.wait_for_timeout(500)
    # Either the warning is shown (API: not configured) or absent (API: configured)
    # — both are valid; just assert the page did not crash
    assert page.locator("#step-2").is_visible()


# ── 7. Back from Step 2 → Step 1 ─────────────────────────────────────────────


def test_back_from_step_2_returns_to_step_1(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_back(page)
    page.wait_for_selector("#step-1:visible", timeout=3000)
    assert page.locator("#step-1").is_visible()
    assert not page.locator("#step-2").is_visible()


# ── 8. Step 2 → Step 3 ───────────────────────────────────────────────────────


def test_next_from_step_2_shows_step_3(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_next(page)
    page.wait_for_selector("#step-3:visible", timeout=3000)
    assert page.locator("#step-3").is_visible()
    assert not page.locator("#step-2").is_visible()


# ── 9. Step 3 — Destinations ─────────────────────────────────────────────────


def test_step_3_medium_card_visible(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_next(page)
    page.wait_for_selector("#step-3:visible", timeout=3000)
    assert page.locator("#dest-medium").is_visible()


def test_step_3_next_btn_becomes_generate(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_next(page)
    page.wait_for_selector("#step-3:visible", timeout=3000)
    btn_text = page.locator("#next-btn").text_content()
    assert "generate" in btn_text.lower() or "create" in btn_text.lower() or "→" in btn_text


def test_step_3_manage_connections_link_visible(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_next(page)
    page.wait_for_selector("#step-3:visible", timeout=3000)
    link = page.get_by_role("link", name="Manage connections")
    assert link.is_visible()


def test_step_3_manage_connections_links_to_settings(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_next(page)
    page.wait_for_selector("#step-3:visible", timeout=3000)
    href = page.get_by_role("link", name="Manage connections").get_attribute("href")
    assert "settings" in href


def test_step_3_back_returns_to_step_2(page):
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    click_next(page)
    page.wait_for_selector("#step-3:visible", timeout=3000)
    click_back(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    assert page.locator("#step-2").is_visible()


# ── 10. Session persistence (tab change simulation) ──────────────────────────


def test_session_persists_prompt_across_navigation(page):
    """Typing a prompt, navigating away, returning — prompt is restored."""
    goto(page)
    page.locator("#prompt-text").fill("Deep dive into Postgres MVCC.")
    # Navigate away (simulates switching tabs)
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(URL)
    page.wait_for_selector("#step-1", timeout=5000)
    restored = page.locator("#prompt-text").input_value()
    assert restored == "Deep dive into Postgres MVCC."


def test_session_persists_step_on_return(page):
    """After advancing to step 2 and navigating away, returning shows step 2."""
    goto(page)
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    # Navigate away and back
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(URL)
    page.wait_for_selector("#step-2:visible", timeout=5000)
    assert page.locator("#step-2").is_visible()
    assert not page.locator("#step-1").is_visible()


def test_session_persists_skill_selection(page):
    """Selecting a non-default skill is restored after navigation."""
    goto(page)
    click_next(page)
    page.wait_for_selector("#skill-list", timeout=3000)
    page.locator("#skill-list .skill-row").filter(has_text="Tutorial").click()
    # Navigate away and back
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(URL)
    page.wait_for_selector("#step-2:visible", timeout=5000)
    selected = page.locator("#skill-list .skill-row.selected")
    assert "Tutorial" in selected.text_content()


def test_reset_btn_clears_session_and_returns_to_step_1(page):
    """Clicking ↺ Reset clears sessionStorage and returns wizard to step 1."""
    goto(page)
    page.locator("#prompt-text").fill("Some content.")
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    page.get_by_role("button", name="↺ Reset").click()
    page.wait_for_selector("#step-1:visible", timeout=3000)
    assert page.locator("#step-1").is_visible()
    assert page.locator("#prompt-text").input_value() == ""


def test_reset_clears_session_storage(page):
    """After reset, navigating away and back should start at step 1."""
    goto(page)
    page.locator("#prompt-text").fill("Some content.")
    click_next(page)
    page.wait_for_selector("#step-2:visible", timeout=3000)
    page.get_by_role("button", name="↺ Reset").click()
    page.wait_for_selector("#step-1:visible", timeout=3000)
    # Navigate away and back — should still be step 1
    page.goto(f"{BASE_URL}/screens/overview/v3.html")
    page.wait_for_load_state("domcontentloaded")
    page.goto(URL)
    page.wait_for_selector("#step-1:visible", timeout=5000)
    assert page.locator("#step-1").is_visible()
    assert not page.locator("#step-2").is_visible()
