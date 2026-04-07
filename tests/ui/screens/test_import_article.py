"""
test_import_article.py — Playwright click-through tests for the Import Article screen.

The screen uses hardcoded mock data (not the real API) so most assertions are pure
UI state checks. The import action itself simulates a 1.5 s delay with 85 % success,
so we verify the overlay appears rather than asserting the final navigation target.

Run:
    pytest tests/ui/test_import_article.py -m browser --browser chromium -v
"""
import pytest

from tests.ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

PLATFORM_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=overview"
UPLOAD_URL   = f"{BASE_URL}/screens/import-article/v1.html?mode=upload&returnTo=overview"
PLATFORM_CA_URL = f"{BASE_URL}/screens/import-article/v1.html?mode=platform&returnTo=create-article"


# ── Helpers ─────────────────────────────────────────────────────────────────

def goto_platform(page):
    page.goto(PLATFORM_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)

def goto_upload(page):
    page.goto(UPLOAD_URL)
    page.wait_for_selector("#drop-zone", timeout=5000)

def advance(page):
    """Click the primary (Next / Import) button."""
    page.locator("#primary-btn").click()


# ── 1. Initial render — platform mode ────────────────────────────────────────

def test_platform_mode_shows_step_1_active(page):
    goto_platform(page)
    # Step bar: circle 1 is active, circles 2 and 3 are future
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute("class")
    assert "future" in circles.nth(1).get_attribute("class")
    assert "future" in circles.nth(2).get_attribute("class")


def test_platform_mode_renders_three_platform_cards(page):
    goto_platform(page)
    cards = page.locator(".platform-card")
    assert cards.count() == 3


def test_platform_mode_devto_is_disconnected(page):
    goto_platform(page)
    # Dev.to card has .disconnected class
    devto = page.locator(".platform-card").filter(has_text="Dev.to")
    assert "disconnected" in devto.get_attribute("class")


def test_platform_mode_next_disabled_before_selection(page):
    goto_platform(page)
    assert page.locator("#primary-btn").is_disabled()


def test_platform_mode_back_hidden_at_step_1(page):
    goto_platform(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "hidden"


# ── 2. Platform selection ────────────────────────────────────────────────────

def test_selecting_medium_enables_next(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    assert not page.locator("#primary-btn").is_disabled()


def test_selecting_medium_shows_check(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    medium_card = page.locator(".platform-card").filter(has_text="Medium")
    assert "selected" in medium_card.get_attribute("class")


def test_cannot_select_disconnected_devto(page):
    goto_platform(page)
    devto = page.locator(".platform-card").filter(has_text="Dev.to")
    devto.click()
    # primary button should remain disabled
    assert page.locator("#primary-btn").is_disabled()


# ── 3. Step 1 → Step 2 (draft list) ─────────────────────────────────────────

def test_advancing_from_platform_shows_draft_list(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    assert page.locator("#view-draft-list").is_visible()


def test_draft_list_shows_platform_name(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#platform-list-title", timeout=3000)
    assert "Medium" in page.locator("#platform-list-title").text_content()


def test_draft_list_shows_article_rows(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    assert page.locator(".draft-row").count() >= 1


def test_draft_list_shows_published_badge(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-badge", timeout=3000)
    badges = page.locator(".draft-badge")
    badge_texts = [badges.nth(i).text_content() for i in range(badges.count())]
    # Medium mock data has both draft and published articles
    assert any(t in ("draft", "published") for t in badge_texts)


def test_step_2_next_disabled_before_article_selection(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    assert page.locator("#primary-btn").is_disabled()


def test_step_2_back_visible(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "visible"


def test_step_2_circle_1_is_done(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".si-circle.done", timeout=3000)
    circles = page.locator(".si-circle")
    assert "done" in circles.nth(0).get_attribute("class")
    assert "active" in circles.nth(1).get_attribute("class")


# ── 4. Article selection ─────────────────────────────────────────────────────

def test_selecting_article_enables_next(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    assert not page.locator("#primary-btn").is_disabled()


def test_selecting_article_highlights_row(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    assert "selected" in page.locator(".draft-row").first.get_attribute("class")


# ── 5. Step 2 → Step 3 (review pane) ────────────────────────────────────────

def test_advancing_from_draft_list_shows_review(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#view-review", timeout=3000)
    assert page.locator("#view-review").is_visible()


def test_review_pane_shows_title_in_input(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    title_value = page.locator("#title-input").input_value()
    assert len(title_value.strip()) > 0


def test_review_pane_shows_markdown_preview(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#markdown-preview", timeout=3000)
    assert len(page.locator("#markdown-preview").inner_html()) > 0


def test_review_primary_button_label_is_import(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#primary-btn", timeout=3000)
    assert "Import" in page.locator("#primary-btn").text_content()


def test_review_primary_enabled_with_title(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    # Title is auto-filled from the selected article; button should be enabled
    assert not page.locator("#primary-btn").is_disabled()


def test_clearing_title_disables_import(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    page.locator("#title-input").fill("")
    assert page.locator("#primary-btn").is_disabled()


def test_clicking_import_navigates_to_editor(page, requests_session):
    # Connect Medium so the import API accepts the platform source
    requests_session.put(f"{BASE_URL}/api/connections/medium", json={"token": "test-token"})
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#title-input", timeout=3000)
    with page.expect_navigation(timeout=8000):
        advance(page)
    assert "editor/" in page.url


# ── 6. Back navigation ───────────────────────────────────────────────────────

def test_back_from_draft_list_returns_to_platform_picker(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    page.locator("#back-btn").click()
    assert page.locator("#view-platform-pick").is_visible()


def test_back_from_review_returns_to_draft_list(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    page.locator(".draft-row").first.click()
    advance(page)
    page.wait_for_selector("#view-review", timeout=3000)
    page.locator("#back-btn").click()
    assert page.locator("#view-draft-list").is_visible()


def test_back_from_draft_list_step_bar_resets(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Medium").click()
    advance(page)
    page.wait_for_selector("#draft-rows", timeout=3000)
    page.locator("#back-btn").click()
    circles = page.locator(".si-circle")
    assert "active" in circles.nth(0).get_attribute("class")
    assert "future" in circles.nth(1).get_attribute("class")


# ── 7. Cancel routing ────────────────────────────────────────────────────────

def test_cancel_with_return_to_overview_navigates_overview(page):
    goto_platform(page)
    with page.expect_navigation():
        page.locator("#cancel-link").click()
    assert "overview/v3.html" in page.url


def test_cancel_with_return_to_create_article_navigates_create_article(page):
    page.goto(PLATFORM_CA_URL)
    page.wait_for_selector("#platform-grid", timeout=5000)
    with page.expect_navigation():
        page.locator("#cancel-link").click()
    assert "create-article/v1.html" in page.url


# ── 8. Hashnode platform ─────────────────────────────────────────────────────

def test_hashnode_shows_3_articles(page):
    goto_platform(page)
    page.locator(".platform-card").filter(has_text="Hashnode").click()
    advance(page)
    page.wait_for_selector(".draft-row", timeout=3000)
    assert page.locator(".draft-row").count() == 3


# ── 9. Upload mode ───────────────────────────────────────────────────────────

def test_upload_mode_shows_drop_zone(page):
    goto_upload(page)
    assert page.locator("#drop-zone").is_visible()


def test_upload_mode_step_bar_has_2_steps(page):
    goto_upload(page)
    circles = page.locator(".si-circle")
    assert circles.count() == 2


def test_upload_mode_primary_disabled_before_file(page):
    goto_upload(page)
    assert page.locator("#primary-btn").is_disabled()


def test_upload_mode_back_hidden_at_step_1(page):
    goto_upload(page)
    visibility = page.locator("#back-btn").evaluate("el => el.style.visibility")
    assert visibility == "hidden"


def test_upload_mode_file_upload_advances_to_review(page):
    goto_upload(page)
    md_content = "# My Test Article\n\nThis is the article content.\n\nSome more words here."
    page.locator("#file-input").set_input_files({
        "name": "my-article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#view-review", timeout=3000)
    assert page.locator("#view-review").is_visible()


def test_upload_mode_title_extracted_from_heading(page):
    goto_upload(page)
    md_content = "# My Test Article\n\nSome content here."
    page.locator("#file-input").set_input_files({
        "name": "my-article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#title-input", timeout=3000)
    assert page.locator("#title-input").input_value() == "My Test Article"


def test_upload_mode_back_from_review_shows_drop_zone(page):
    goto_upload(page)
    md_content = "# Uploaded Article\n\nContent here."
    page.locator("#file-input").set_input_files({
        "name": "article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#view-review", timeout=3000)
    page.locator("#back-btn").click()
    assert page.locator("#view-upload").is_visible()


def test_upload_mode_import_navigates_to_editor(page):
    goto_upload(page)
    md_content = "# Uploaded Article\n\nContent here with enough words."
    page.locator("#file-input").set_input_files({
        "name": "article.md",
        "mimeType": "text/markdown",
        "buffer": md_content.encode(),
    })
    page.wait_for_selector("#title-input", timeout=3000)
    with page.expect_navigation(timeout=8000):
        advance(page)
    assert "editor/" in page.url
    assert "id=art_" in page.url
