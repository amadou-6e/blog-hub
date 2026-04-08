"""
test_create_article.py — Create Article screen Playwright tests.

Covers the three-step wizard:
  Step 1 — Write a brief (prompt text, file context)
  Step 2 — Configure generation (format, AI provider, word count)
  Step 3 — Choose destinations (platform toggles, Generate)

Run against a live backend (port 8000):
    pytest tests/tests_ui/screens/test_create_article.py -m browser --browser chromium -v
"""
import re

import pytest

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

CREATE_URL = f"{BASE_URL}/screens/create-article/v1.html"
SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"

SAMPLE_PROMPT = ("A practical guide to zero-downtime Postgres migrations using pg_repack, "
                 "covering common pitfalls and how to verify success.")

# ── Helpers ──────────────────────────────────────────────────────────────────


def goto(page):
    page.goto(CREATE_URL)
    # wait for the `load` event so the inline <script> has fully executed
    page.wait_for_load_state("load")
    # confirm renderStep() ran: back-btn gets visibility:hidden at step 1
    page.wait_for_function(
        "document.getElementById('back-btn') && document.getElementById('back-btn').style.visibility === 'hidden'",
        timeout=5000,
    )


def fill_prompt(page, text=SAMPLE_PROMPT):
    page.locator("#prompt-text").fill(text)


def advance(page):
    page.locator("#next-btn").click()


def go_back(page):
    page.locator("#back-btn").click()


def reach_step2(page):
    goto(page)
    fill_prompt(page)
    advance(page)
    page.wait_for_function(
        "document.getElementById('step-2')?.style.display === 'block'",
        timeout=5000,
    )


def reach_step3(page):
    reach_step2(page)
    advance(page)
    page.wait_for_function(
        "document.getElementById('step-3')?.style.display === 'block'",
        timeout=5000,
    )


# ── 1. Initial render ─────────────────────────────────────────────────────────


def test_step_1_visible_on_load(page):
    goto(page)
    assert page.locator("#step-1").is_visible()


def test_step_2_hidden_on_load(page):
    goto(page)
    assert not page.locator("#step-2").is_visible()


def test_step_3_hidden_on_load(page):
    goto(page)
    assert not page.locator("#step-3").is_visible()


def test_prompt_textarea_visible(page):
    goto(page)
    assert page.locator("#prompt-text").is_visible()


def test_char_count_starts_at_zero(page):
    goto(page)
    assert page.locator("#prompt-count").text_content().strip() == "0"


def test_back_button_hidden_at_step_1(page):
    goto(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "hidden"


def test_next_button_visible_at_step_1(page):
    goto(page)
    assert page.locator("#next-btn").is_visible()


def test_file_drop_zone_visible(page):
    goto(page)
    assert page.locator("#file-drop-zone").is_visible()


def test_step_indicator_has_three_circles(page):
    goto(page)
    for n in (1, 2, 3):
        assert page.locator(f"#si-circle-{n}").is_visible()


# ── 2. Prompt interaction ─────────────────────────────────────────────────────


def test_typing_updates_char_count(page):
    goto(page)
    page.locator("#prompt-text").fill("Hello world")
    count = int(page.locator("#prompt-count").text_content().strip())
    assert count == len("Hello world")


def test_template_tutorial_fills_prompt(page):
    goto(page)
    page.locator("button[onclick=\"loadTemplate('tutorial')\"]").click()
    value = page.locator("#prompt-text").input_value()
    assert len(value.strip()) > 0


def test_template_comparison_fills_prompt(page):
    goto(page)
    page.locator("button[onclick=\"loadTemplate('comparison')\"]").click()
    value = page.locator("#prompt-text").input_value()
    assert len(value.strip()) > 0


def test_save_template_without_prompt_shows_dialog(page):
    goto(page)
    # Prompt is empty — saveAsTemplate() fires a native alert
    dismissed = []
    page.on("dialog", lambda d: (dismissed.append(d.message), d.dismiss()))
    page.locator("button[onclick='saveAsTemplate()']").click()
    assert len(dismissed) == 1 and "brief" in dismissed[0].lower()


def test_save_template_with_prompt_shows_toast(page):
    goto(page)
    fill_prompt(page)
    page.locator("button[onclick='saveAsTemplate()']").click()
    page.locator("#template-toast").wait_for(state="visible", timeout=3000)
    assert page.locator("#template-toast").is_visible()


def test_toast_dismiss_button_hides_toast(page):
    goto(page)
    fill_prompt(page)
    page.locator("button[onclick='saveAsTemplate()']").click()
    page.locator("#template-toast").wait_for(state="visible", timeout=3000)
    # × is the only button inside the toast
    page.locator("#template-toast button").click()
    page.locator("#template-toast").wait_for(state="hidden", timeout=2000)
    assert not page.locator("#template-toast").is_visible()


def test_toast_contains_settings_link(page):
    goto(page)
    fill_prompt(page)
    page.locator("button[onclick='saveAsTemplate()']").click()
    page.locator("#template-toast").wait_for(state="visible", timeout=3000)
    href = page.locator("#template-toast a").get_attribute("href")
    assert "settings" in href


# ── 3. Step 1 → Step 2 ───────────────────────────────────────────────────────


def test_next_advances_to_step_2(page):
    reach_step2(page)
    assert page.locator("#step-2").is_visible()
    assert not page.locator("#step-1").is_visible()


def test_step_2_shows_skill_list(page):
    reach_step2(page)
    page.wait_for_selector("#skill-list", timeout=3000)
    assert page.locator("#skill-list").is_visible()


def test_step_2_skill_list_has_four_options(page):
    reach_step2(page)
    page.wait_for_selector(".skill-row", timeout=3000)
    assert page.locator(".skill-row").count() == 4


def test_step_2_shows_provider_buttons(page):
    reach_step2(page)
    assert page.locator("#provider-claude").is_visible()
    assert page.locator("#provider-codex").is_visible()


def test_step_2_claude_is_default_provider(page):
    reach_step2(page)
    # Claude button has accent background in default state (checked via inline style)
    style = page.locator("#provider-claude").get_attribute("style")
    assert "6366f1" in style  # accent colour means selected


def test_step_2_shows_word_count_label(page):
    reach_step2(page)
    label = page.locator("#word-count-label").text_content()
    assert "words" in label.lower()


def test_step_2_back_button_visible(page):
    reach_step2(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "visible"


def test_step_2_next_enabled(page):
    """Step 2 is purely config — no required selection, so Next is always enabled."""
    reach_step2(page)
    assert not page.locator("#next-btn").is_disabled()


def test_step_indicator_circle_1_shows_checkmark_at_step_2(page):
    reach_step2(page)
    assert page.locator("#si-circle-1").text_content().strip() == "✓"


def test_step_indicator_circle_2_shows_active_border_at_step_2(page):
    reach_step2(page)
    style = page.locator("#si-circle-2").get_attribute("style")
    # Browsers may convert #6366f1 → rgb(99, 102, 241)
    assert "6366f1" in style or "99, 102, 241" in style


# ── 4. Provider toggle ────────────────────────────────────────────────────────


def test_selecting_codex_shows_warning(page):
    reach_step2(page)
    # Inject an unconfigured Codex provider so the warning logic fires
    page.evaluate("_providersData = [{id:'codex',label:'Codex',configured:false}]")
    page.locator("#provider-codex").click()
    # codex-warning uses display:flex when shown; just check visible
    assert page.locator("#codex-warning").is_visible()


def test_codex_warning_has_settings_link(page):
    reach_step2(page)
    page.locator("#provider-codex").click()
    href = page.locator("#codex-warning a").get_attribute("href")
    assert "settings" in href


def test_selecting_claude_hides_codex_warning(page):
    reach_step2(page)
    page.locator("#provider-codex").click()
    page.locator("#provider-claude").click()
    # display is set back to "none"
    display = page.locator("#codex-warning").evaluate("el => el.style.display")
    assert display == "none"


# ── 5. Step 2 → Step 3 ───────────────────────────────────────────────────────


def test_next_on_step_2_advances_to_step_3(page):
    reach_step3(page)
    assert page.locator("#step-3").is_visible()
    assert not page.locator("#step-2").is_visible()


def test_step_3_shows_destination_cards(page):
    reach_step3(page)
    page.wait_for_selector(".dest-card", timeout=3000)
    assert page.locator(".dest-card").count() >= 1


def test_step_3_generate_button_text(page):
    reach_step3(page)
    text = page.locator("#next-btn").text_content()
    assert "Generate" in text


def test_step_3_shows_manage_connections_link(page):
    reach_step3(page)
    assert page.get_by_text("Manage connections").is_visible()


def test_step_3_manage_connections_href_points_to_settings(page):
    reach_step3(page)
    href = page.get_by_text("Manage connections").get_attribute("href")
    assert "settings" in href


def test_step_3_back_button_visible(page):
    reach_step3(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "visible"


def test_step_indicator_circles_1_and_2_show_checkmarks_at_step_3(page):
    reach_step3(page)
    assert page.locator("#si-circle-1").text_content().strip() == "✓"
    assert page.locator("#si-circle-2").text_content().strip() == "✓"


# ── 6. Destination toggles ────────────────────────────────────────────────────


def test_generate_enabled_by_default_at_step_3(page):
    """Medium is on by default in the fallback state."""
    reach_step3(page)
    page.wait_for_selector("#toggle-medium", timeout=3000)
    assert not page.locator("#next-btn").is_disabled()


def test_toggling_off_all_destinations_disables_generate(page):
    reach_step3(page)
    page.wait_for_selector("#toggle-medium", timeout=3000)
    page.locator("#toggle-medium").click()
    assert page.locator("#next-btn").is_disabled()


def test_toggling_destination_back_on_enables_generate(page):
    reach_step3(page)
    page.wait_for_selector("#toggle-medium", timeout=3000)
    page.locator("#toggle-medium").click()  # off
    page.locator("#toggle-medium").click()  # on
    assert not page.locator("#next-btn").is_disabled()


# ── 7. Back navigation ────────────────────────────────────────────────────────


def test_back_on_step_3_returns_to_step_2(page):
    reach_step3(page)
    go_back(page)
    assert page.locator("#step-2").is_visible()
    assert not page.locator("#step-3").is_visible()


def test_back_on_step_2_returns_to_step_1(page):
    reach_step2(page)
    go_back(page)
    assert page.locator("#step-1").is_visible()
    assert not page.locator("#step-2").is_visible()


def test_back_on_step_1_hides_back_button_again(page):
    reach_step2(page)
    go_back(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "hidden"


def test_back_on_step_3_then_step_2_then_step_1(page):
    reach_step3(page)
    go_back(page)
    go_back(page)
    assert page.locator("#step-1").is_visible()


# ── 8. File upload ────────────────────────────────────────────────────────────


def test_uploading_md_file_adds_to_file_list(page):
    goto(page)
    page.locator("#file-input").set_input_files({
        "name": "context.md",
        "mimeType": "text/markdown",
        "buffer": b"# Context\n\nSome extra context for the article.",
    })
    page.wait_for_selector("#file-list .file-chip, #file-list > div", timeout=3000)
    assert "context.md" in page.locator("#file-list").inner_text()


def test_uploading_file_updates_char_count_or_file_count(page):
    """After uploading, the summary reflects the file instead of empty prompt."""
    goto(page)
    page.locator("#file-input").set_input_files({
        "name": "context.md",
        "mimeType": "text/markdown",
        "buffer": b"# Context\n\nSome content.",
    })
    # Advance to step 3 and check summary reflects the file
    advance(page)
    advance(page)
    page.wait_for_selector("#summary-list", timeout=3000)
    summary_text = page.locator("#summary-list").inner_text()
    assert "context.md" in summary_text
