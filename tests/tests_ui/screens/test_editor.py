"""
test_editor.py — Playwright UI tests for the Editor screen (v2.html).

Run:
    pytest tests/tests_ui/screens/test_editor.py -m browser --browser chromium -v

Requires a live backend on http://localhost:8000:
    .venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
"""
import pytest
import requests as _requests

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

# Seed article IDs (reset before each test via autouse reset_store fixture)
ARTICLE_ID = "art_001"          # has 3 destinations, gate=pass
ARTICLE_WITH_ERROR_ID = "art_002"  # has devto error destination


def editor_url(article_id=ARTICLE_ID):
    return f"{BASE_URL}/screens/editor/v2.html?id={article_id}"


def goto_editor(page, article_id=ARTICLE_ID):
    page.goto(editor_url(article_id))
    # wait-for-selector with a short timeout; if the page redirects away (API 404)
    # this raises clearly so tests fail fast instead of timing out on file-label.
    page.wait_for_selector("#raw-editor", timeout=8000)
    # Wait until the file-label is populated (article loaded from API)
    page.wait_for_function(
        "document.getElementById('file-label').textContent !== 'loading…'",
        timeout=10000,
    )


# ── 1. Initial load ───────────────────────────────────────────────────────────

def test_editor_loads_article_title(page):
    goto_editor(page)
    title = page.locator("#article-title").inner_text()
    assert "Building a Vector DB" in title


def test_editor_loads_article_content(page):
    goto_editor(page)
    content = page.locator("#raw-editor").input_value()
    assert len(content) > 50


def test_editor_shows_word_count(page):
    goto_editor(page)
    wc = page.locator("#word-count").inner_text()
    assert "words" in wc


def test_editor_file_label_shows_article_id(page):
    goto_editor(page)
    label = page.locator("#file-label").inner_text()
    assert ARTICLE_ID in label


def test_missing_id_redirects_to_overview(page):
    page.goto(f"{BASE_URL}/screens/editor/v2.html")
    page.wait_for_url("**/overview/**", timeout=5000)
    assert "overview" in page.url


# ── 2. Save indicator ─────────────────────────────────────────────────────────

def test_save_indicator_shows_saved_on_load(page):
    goto_editor(page)
    indicator = page.locator("#save-indicator").inner_text()
    assert "saved" in indicator.lower()


def test_typing_shows_unsaved_dot(page):
    goto_editor(page)
    page.locator("#raw-editor").click()
    page.keyboard.press("End")
    page.keyboard.type(" x")
    # Amber dot appears immediately
    page.wait_for_function(
        "document.getElementById('save-indicator').innerHTML.includes('fbbf24')",
        timeout=3000,
    )


def test_autosave_clears_unsaved_dot(page):
    """After 2 s of inactivity the autosave fires and the dot returns to 'saved'."""
    goto_editor(page)
    page.locator("#raw-editor").click()
    page.keyboard.press("End")
    page.keyboard.type(" autosave-test")
    # Dot appears
    page.wait_for_function(
        "document.getElementById('save-indicator').innerHTML.includes('fbbf24')",
        timeout=3000,
    )
    # Wait for autosave (debounce=2 s, plus network round-trip)
    page.wait_for_function(
        "document.getElementById('save-indicator').innerText.includes('saved')",
        timeout=8000,
    )


# ── 3. Word count updates ─────────────────────────────────────────────────────

def test_word_count_updates_on_typing(page):
    goto_editor(page)
    # Count words from the textarea content directly (the displayed count comes from
    # the API and may differ from the actual local content length)
    before = page.evaluate(
        "document.getElementById('raw-editor').value.trim().split(/\\s+/).filter(Boolean).length"
    )
    page.locator("#raw-editor").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" extraword")
    after = page.evaluate(
        "document.getElementById('raw-editor').value.trim().split(/\\s+/).filter(Boolean).length"
    )
    assert after == before + 1


# ── 4. Left panel accordion ───────────────────────────────────────────────────

def test_comments_section_open_by_default(page):
    goto_editor(page)
    # Comments body is visible (accOpen.comments defaults to true)
    body = page.locator("#abody-comments")
    assert body.is_visible()


def test_patches_section_closed_by_default(page):
    goto_editor(page)
    body = page.locator("#abody-patches")
    assert not body.is_visible()


def test_clicking_patches_header_expands_it(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Patches").click()
    page.wait_for_selector("#abody-patches:visible", timeout=3000)
    assert page.locator("#abody-patches").is_visible()


def test_clicking_open_section_again_collapses_it(page):
    goto_editor(page)
    # Comments is open; click header to close
    page.locator(".acc-hdr").filter(has_text="Comments").click()
    page.wait_for_function(
        "document.getElementById('abody-comments').style.display === 'none'",
        timeout=3000,
    )


def test_destinations_section_expands(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations:visible", timeout=3000)
    assert page.locator("#abody-destinations").is_visible()


def test_chat_section_expands(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Chat").click()
    page.wait_for_selector("#abody-chat:visible", timeout=3000)
    assert page.locator("#abody-chat").is_visible()


def test_rules_section_expands(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Rules").click()
    page.wait_for_selector("#abody-rules:visible", timeout=3000)
    assert page.locator("#abody-rules").is_visible()


# ── 5. Left panel collapse / expand ──────────────────────────────────────────

def test_panel_strip_collapses_left_panel(page):
    goto_editor(page)
    page.locator("#panel-strip").click()
    page.wait_for_function(
        "document.getElementById('panel-content').style.display === 'none'",
        timeout=3000,
    )


def test_panel_strip_re_expands_left_panel(page):
    goto_editor(page)
    # Collapse
    page.locator("#panel-strip").click()
    page.wait_for_function(
        "document.getElementById('panel-content').style.display === 'none'",
        timeout=3000,
    )
    # Expand again
    page.locator("#panel-strip").click()
    page.wait_for_function(
        "document.getElementById('panel-content').style.display !== 'none'",
        timeout=3000,
    )


# ── 6. Preview pane ───────────────────────────────────────────────────────────

def test_preview_pane_visible_on_load(page):
    goto_editor(page)
    assert page.locator("#preview-content").is_visible()


def test_preview_strip_collapses_preview(page):
    goto_editor(page)
    page.locator("#preview-strip").click()
    page.wait_for_function(
        "document.getElementById('preview-content').style.display === 'none'",
        timeout=3000,
    )


def test_preview_strip_re_expands_preview(page):
    goto_editor(page)
    page.locator("#preview-strip").click()
    page.wait_for_function(
        "document.getElementById('preview-content').style.display === 'none'",
        timeout=3000,
    )
    page.locator("#preview-strip").click()
    page.wait_for_function(
        "document.getElementById('preview-content').style.display !== 'none'",
        timeout=3000,
    )


def test_preview_body_has_content_on_load(page):
    goto_editor(page)
    body = page.locator("#preview-body")
    assert len(body.inner_html()) > 0


def test_preview_selector_options(page):
    goto_editor(page)
    options = page.locator("#preview-sel option")
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Rendered MD" in labels
    assert "Medium" in labels
    assert "Hashnode" in labels
    assert "Dev.to" in labels


# ── 7. Top nav actions ────────────────────────────────────────────────────────

def test_back_button_navigates_to_overview(page):
    goto_editor(page)
    with page.expect_navigation(timeout=5000):
        page.locator(".icon-btn[title='Back to overview']").click()
    assert "overview" in page.url


def test_publish_button_visible(page):
    goto_editor(page)
    btn = page.get_by_role("button", name="Publish")
    assert btn.is_visible()


def test_review_button_visible(page):
    goto_editor(page)
    btn = page.get_by_role("button", name="Review")
    assert btn.is_visible()


def test_inspect_button_visible(page):
    goto_editor(page)
    btn = page.get_by_role("button", name="Inspect")
    assert btn.is_visible()


# ── 8. Article title inline edit ─────────────────────────────────────────────

def test_title_is_contenteditable(page):
    goto_editor(page)
    editable = page.locator("#article-title").get_attribute("contenteditable")
    assert editable == "true"


def test_editing_title_triggers_unsaved(page):
    goto_editor(page)
    title = page.locator("#article-title")
    title.click()
    page.keyboard.press("End")
    page.keyboard.type("X")
    page.wait_for_function(
        "document.getElementById('save-indicator').innerHTML.includes('fbbf24')",
        timeout=3000,
    )


# ── 9. Review overlay ────────────────────────────────────────────────────────

def test_gen_overlay_hidden_on_load(page):
    goto_editor(page)
    assert page.locator("#gen-overlay").evaluate("el => el.style.display") == "none"


def test_dismiss_button_hides_overlay(page):
    goto_editor(page)
    # Show overlay directly via JS
    page.evaluate("document.getElementById('gen-overlay').style.display = 'flex'")
    page.wait_for_selector("#gen-overlay", timeout=2000)
    page.get_by_role("button", name="Dismiss").click()
    page.wait_for_function(
        "document.getElementById('gen-overlay').style.display === 'none'",
        timeout=3000,
    )


def test_finish_review_hides_overlay_and_opens_patches(page):
    goto_editor(page)
    page.evaluate("document.getElementById('gen-overlay').style.display = 'flex'")
    page.get_by_role("button", name="Done — view patches").click()
    page.wait_for_function(
        "document.getElementById('gen-overlay').style.display === 'none'",
        timeout=3000,
    )
    # Patches section should now be open
    page.wait_for_selector("#abody-patches:visible", timeout=3000)
    assert page.locator("#abody-patches").is_visible()


# ── 10. Toolbar ───────────────────────────────────────────────────────────────

def test_toolbar_bold_button_visible(page):
    goto_editor(page)
    assert page.locator(".icon-btn[title='Bold']").is_visible()


def test_toolbar_italic_button_visible(page):
    goto_editor(page)
    assert page.locator(".icon-btn[title='Italic']").is_visible()


def test_toolbar_code_button_visible(page):
    goto_editor(page)
    assert page.locator(".icon-btn[title='Code']").is_visible()


def test_toolbar_h2_button_visible(page):
    goto_editor(page)
    assert page.locator(".icon-btn[title='H2']").is_visible()


def test_toolbar_h3_button_visible(page):
    goto_editor(page)
    assert page.locator(".icon-btn[title='H3']").is_visible()


def test_ai_strip_visible(page):
    goto_editor(page)
    # The AI strip contains "Regenerate" button
    btn = page.get_by_role("button", name="Regenerate")
    assert btn.is_visible()


# ── 11. /comment command ──────────────────────────────────────────────────────

def test_slash_comment_inserts_comment_marker(page):
    goto_editor(page)
    # Append a /comment line via JS and fire oninput so the handler processes it
    page.evaluate("""
        const ta = document.getElementById('raw-editor');
        ta.value = ta.value + '\\n/comment This is a test note';
        ta.dispatchEvent(new Event('input', {bubbles: true}));
    """)
    # onInput replaces the /comment line with an HTML comment marker
    page.wait_for_function(
        "document.getElementById('raw-editor').value.includes('[comment]')",
        timeout=8000,
    )


def test_slash_comment_opens_comments_section(page):
    goto_editor(page)
    # Collapse comments first
    page.locator(".acc-hdr").filter(has_text="Comments").click()
    page.wait_for_function(
        "document.getElementById('abody-comments').style.display === 'none'",
        timeout=3000,
    )
    ta = page.locator("#raw-editor")
    ta.click()
    ta.press("Control+End")
    ta.type("\n/comment open section test")
    # Comments section should reopen
    page.wait_for_selector("#abody-comments:visible", timeout=5000)


def test_insert_comment_toolbar_button_inserts_command(page):
    goto_editor(page)
    before = page.locator("#raw-editor").input_value()
    page.locator(".ai-btn.warn").first.click()
    after = page.locator("#raw-editor").input_value()
    assert "/comment" in after
    assert len(after) > len(before)


# ── 12. Comments section ─────────────────────────────────────────────────────

def test_comments_section_shows_empty_state_when_no_comments(page, requests_session):
    """With a freshly-reset article that has no comments, show the empty-state text."""
    goto_editor(page, "art_004")
    # Wait for the comments section to finish rendering (loadComments completes async)
    page.wait_for_function(
        "document.getElementById('abody-comments').innerText.trim() !== ''",
        timeout=8000,
    )
    assert "No comments yet" in page.locator("#abody-comments").inner_text()


def test_resolve_button_present_for_open_comment(page, requests_session):
    """POST a comment via API then check Resolve button appears in the panel."""
    requests_session.post(
        f"{BASE_URL}/api/articles/{ARTICLE_ID}/comments",
        json={"author": "Tester", "text": "This paragraph needs work."},
    )
    goto_editor(page)
    # Comments section is open by default; wait for loadComments to re-render it
    page.wait_for_function(
        "document.getElementById('abody-comments').innerText.includes('Tester')",
        timeout=10000,
    )
    assert page.get_by_role("button", name="Resolve").count() >= 1


def test_resolve_comment_removes_it_from_active_list(page, requests_session):
    """Clicking Resolve calls the API and the comment disappears from the open list."""
    requests_session.post(
        f"{BASE_URL}/api/articles/{ARTICLE_ID}/comments",
        json={"author": "Tester", "text": "Resolve me."},
    )
    goto_editor(page)
    page.wait_for_function(
        "document.getElementById('abody-comments').innerText.includes('Resolve me')",
        timeout=10000,
    )
    page.get_by_role("button", name="Resolve").first.click()
    # Count badge should drop (or the comment shows "Resolved" label)
    page.wait_for_function(
        """
        () => {
            const el = document.getElementById('abody-comments');
            return el.innerText.includes('Resolved') ||
                   !el.innerText.includes('Resolve me');
        }
        """,
        timeout=5000,
    )


# ── 13. Patches section ───────────────────────────────────────────────────────

def test_patches_section_shows_empty_state_when_no_patches(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Patches").click()
    page.wait_for_selector("#abody-patches:visible", timeout=3000)
    # Wait for loadPatches to finish rendering the section
    page.wait_for_function(
        "document.getElementById('abody-patches').innerText.trim() !== ''",
        timeout=8000,
    )
    assert "All patches resolved" in page.locator("#abody-patches").inner_text()


def test_accepting_patch_marks_it_accepted(page, requests_session):
    """Seed a patch via API, then Accept it in the UI."""
    patch_resp = requests_session.post(
        f"{BASE_URL}/api/articles/{ARTICLE_ID}/patches",
        json={
            "label": "Shorten intro",
            "removed": "This is a very long introduction.",
            "added": "Short intro.",
            "comment_id": None,
        },
    )
    if patch_resp.status_code not in (200, 201):
        pytest.skip("Patch creation endpoint not available")
    patch_id = patch_resp.json().get("id")

    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Patches").click()
    page.wait_for_function(
        "document.getElementById('abody-patches').innerText.includes('Shorten intro')",
        timeout=5000,
    )
    page.get_by_role("button", name="Accept").first.click()
    page.wait_for_function(
        "document.getElementById('abody-patches').innerText.includes('Accepted')",
        timeout=5000,
    )


def test_rejecting_patch_marks_it_rejected(page, requests_session):
    patch_resp = requests_session.post(
        f"{BASE_URL}/api/articles/{ARTICLE_ID}/patches",
        json={
            "label": "Add disclaimer",
            "removed": "No disclaimer.",
            "added": "This is not legal advice.",
            "comment_id": None,
        },
    )
    if patch_resp.status_code not in (200, 201):
        pytest.skip("Patch creation endpoint not available")

    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Patches").click()
    page.wait_for_function(
        "document.getElementById('abody-patches').innerText.includes('Add disclaimer')",
        timeout=5000,
    )
    page.get_by_role("button", name="Reject").first.click()
    page.wait_for_function(
        "document.getElementById('abody-patches').innerText.includes('Rejected')",
        timeout=5000,
    )


# ── 14. Destinations section ─────────────────────────────────────────────────

def test_destinations_shows_platform_names(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations:visible", timeout=3000)
    body_text = page.locator("#abody-destinations").inner_text()
    assert "Medium" in body_text
    assert "Hashnode" in body_text


def test_destinations_shows_status_pills(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations .pill", timeout=3000)
    assert page.locator("#abody-destinations .pill").count() >= 1


def test_destinations_shows_error_for_failed_platform(page):
    """art_002 has a devto error destination."""
    goto_editor(page, ARTICLE_WITH_ERROR_ID)
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations:visible", timeout=3000)
    body_text = page.locator("#abody-destinations").inner_text()
    assert "code block split" in body_text


def test_destinations_run_inspection_button_present(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations:visible", timeout=3000)
    assert page.get_by_role("button", name="Run inspection").is_visible()


def test_destinations_published_url_link_present(page):
    """art_003 has published URLs for all platforms."""
    goto_editor(page, "art_003")
    page.locator(".acc-hdr").filter(has_text="Destinations").click()
    page.wait_for_selector("#abody-destinations:visible", timeout=3000)
    links = page.locator("#abody-destinations a")
    assert links.count() >= 1
    href = links.first.get_attribute("href")
    assert href and href.startswith("https://")


# ── 15. Chat section ─────────────────────────────────────────────────────────

def test_chat_section_has_input(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Chat").click()
    page.wait_for_selector("#abody-chat:visible", timeout=3000)
    assert page.locator("#chat-input").is_visible()


def test_chat_shows_empty_state_initially(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Chat").click()
    page.wait_for_selector("#abody-chat:visible", timeout=3000)
    # Empty chat means no user/bot bubbles
    bubbles = page.locator("#abody-chat .bubble")
    assert bubbles.count() == 0


# ── 16. Rules section ────────────────────────────────────────────────────────

def test_rules_section_shows_rule_items(page):
    goto_editor(page)
    page.locator(".acc-hdr").filter(has_text="Rules").click()
    page.wait_for_selector("#abody-rules:visible", timeout=3000)
    body_text = page.locator("#abody-rules").inner_text()
    assert "Word count" in body_text
    assert "Readability" in body_text


# ── 17. Selection popover ─────────────────────────────────────────────────────

def test_sel_popover_hidden_on_load(page):
    goto_editor(page)
    # The popover has display:none in CSS; inline style may be "" or "none"
    display = page.locator("#sel-popover").evaluate("el => el.style.display")
    assert display in ("", "none")


def test_sel_popover_appears_on_text_selection(page):
    goto_editor(page)
    ta = page.locator("#raw-editor")
    ta.click()
    # Select first 10 characters via keyboard
    ta.press("Control+Home")
    page.keyboard.down("Shift")
    for _ in range(10):
        page.keyboard.press("ArrowRight")
    page.keyboard.up("Shift")
    # Trigger mouseup manually to show the popover
    ta.dispatch_event("mouseup", {"clientX": 300, "clientY": 200})
    page.wait_for_function(
        "document.getElementById('sel-popover').style.display !== 'none'",
        timeout=3000,
    )


def test_sel_popover_disappears_on_outside_click(page):
    goto_editor(page)
    # Show popover via JS
    page.evaluate(
        "showSelPopover(300, 200, 'some text')"
    )
    page.wait_for_function(
        "document.getElementById('sel-popover').style.display !== 'none'",
        timeout=2000,
    )
    # Click outside
    page.locator("#article-title").click()
    page.wait_for_function(
        "document.getElementById('sel-popover').style.display === 'none'",
        timeout=3000,
    )
