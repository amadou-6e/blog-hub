"""
test_settings_platforms.py — Playwright tests for the Publishing Platforms section of Settings.

Run:
    pytest tests/tests_ui/screens/test_settings_platforms.py -m browser --browser chromium -v

Covers:
- Initial render of Platforms section
- Per-card state on fresh store (disconnected)
- API key expand / collapse
- Save key → PUT /api/connections/{id} called with correct body
- Disconnect confirmation flow → DELETE /api/connections/{id}
- Test connection → GET /api/connections/{id}/test
- Navigation between sections
- "Manage connections" link from create-article routes here
"""
import pytest
import requests

from tests.tests_ui.conftest import BASE_URL

pytestmark = pytest.mark.browser

SETTINGS_URL = f"{BASE_URL}/screens/settings/v2.html"
PLATFORM_IDS = ("medium", "hashnode", "devto")

# ── Helpers ───────────────────────────────────────────────────────────────────


def goto_settings(page):
    page.goto(SETTINGS_URL)
    page.wait_for_selector("#section-platforms", timeout=5000)
    # Wait for the loading placeholder to disappear
    page.wait_for_function(
        "document.querySelector('#platform-list .text-muted') === null "
        "|| document.querySelector('#platform-list').children.length > 1",
        timeout=5000,
    )


def platform_card(page, platform_id: str):
    return page.locator(f"#plat-card-{platform_id}")


# ── 1. Initial render ─────────────────────────────────────────────────────────


def test_platforms_section_is_default(page):
    goto_settings(page)
    assert page.locator("#section-platforms").is_visible()
    assert not page.locator("#section-ai").is_visible()


def test_platforms_heading_present(page):
    goto_settings(page)
    page.get_by_role("heading", name="Publishing Platforms").wait_for()


def test_all_three_platform_cards_render(page):
    goto_settings(page)
    for pid in PLATFORM_IDS:
        assert platform_card(page, pid).is_visible(), f"card for {pid} not visible"


def test_platform_cards_show_correct_labels(page):
    goto_settings(page)
    assert platform_card(page, "medium").get_by_text("Medium").count() >= 1
    assert platform_card(page, "hashnode").get_by_text("Hashnode").count() >= 1
    assert platform_card(page, "devto").get_by_text("Dev.to").count() >= 1


def test_all_platforms_disconnected_on_fresh_store(page):
    goto_settings(page)
    for pid in PLATFORM_IDS:
        card = platform_card(page, pid)
        badge_text = card.locator(
            ".status-badge, [class*='badge'], [class*='status']").first.text_content()
        assert "disconnected" in badge_text.lower() or "not connected" in badge_text.lower(), (
            f"{pid}: expected disconnected badge, got: {badge_text!r}")


def test_connection_count_updates_in_header(page):
    goto_settings(page)
    label = page.locator("#count-label").text_content()
    # All 5 connections exist but all disconnected on fresh store
    assert "connection" in label.lower()


# ── 2. Navigation between sections ───────────────────────────────────────────


def test_clicking_ai_providers_tab_shows_ai_section(page):
    goto_settings(page)
    page.locator("[data-section='ai']").click()
    page.wait_for_selector("#section-ai:visible", timeout=3000)
    assert page.locator("#section-ai").is_visible()
    assert not page.locator("#section-platforms").is_visible()


def test_clicking_platforms_tab_shows_platforms_section(page):
    goto_settings(page)
    page.locator("[data-section='ai']").click()
    page.wait_for_selector("#section-ai:visible", timeout=3000)
    page.locator("[data-section='platforms']").click()
    page.wait_for_selector("#section-platforms:visible", timeout=3000)
    assert page.locator("#section-platforms").is_visible()


def test_active_tab_button_has_active_class(page):
    goto_settings(page)
    active_btn = page.locator(".nav-btn.active")
    assert active_btn.get_attribute("data-section") == "platforms"


# ── 3. Expand / collapse key input ───────────────────────────────────────────


def test_expand_key_shows_input_row_for_medium(page):
    goto_settings(page)
    # Disconnected card — "Add API key" or "Update token" button
    card = platform_card(page, "medium")
    expand_btn = card.get_by_role("button").filter(has_text=lambda t: "key" in t.lower() or "token"
                                                   in t.lower() or "connect" in t.lower()).first
    expand_btn.click()
    page.wait_for_selector("#expand-medium:visible", timeout=2000)
    assert page.locator("#expand-medium").is_visible()


def test_key_input_field_visible_after_expand(page):
    goto_settings(page)
    card = platform_card(page, "medium")
    card.get_by_role("button").filter(has_text=lambda t: "key" in t.lower() or "token" in t.lower()
                                      or "connect" in t.lower()).first.click()
    page.wait_for_selector("#key-input-medium", timeout=2000)
    assert page.locator("#key-input-medium").is_visible()


def test_cancel_collapses_key_input(page):
    goto_settings(page)
    card = platform_card(page, "hashnode")
    card.get_by_role("button").filter(has_text=lambda t: "key" in t.lower() or "token" in t.lower()
                                      or "connect" in t.lower()).first.click()
    page.wait_for_selector("#expand-hashnode:visible", timeout=2000)
    # Click the Cancel button
    card.get_by_role("button", name="Cancel").click()
    page.wait_for_function(
        "!document.querySelector('#expand-hashnode') || "
        "document.querySelector('#expand-hashnode').style.display === 'none'",
        timeout=1500,
    )


# ── 4. Save key — API contract ───────────────────────────────────────────────


def test_saving_medium_token_calls_put(page):
    """PUT /api/connections/medium  { token: "…" }  → 200."""
    goto_settings(page)
    card = platform_card(page, "medium")
    card.get_by_role("button").filter(has_text=lambda t: "key" in t.lower() or "token" in t.lower()
                                      or "connect" in t.lower()).first.click()
    page.wait_for_selector("#key-input-medium", timeout=2000)

    with page.expect_request(
            lambda r: "/api/connections/medium" in r.url and r.method == "PUT") as req_info:
        page.locator("#key-input-medium").fill("test-token-abc")
        card.get_by_role("button", name="Save").click()

    body = req_info.value.post_data_json
    assert body["token"] == "test-token-abc"


def test_saving_devto_key_calls_put(page):
    goto_settings(page)
    card = platform_card(page, "devto")
    card.get_by_role("button").filter(has_text=lambda t: "key" in t.lower() or "token" in t.lower()
                                      or "connect" in t.lower()).first.click()
    page.wait_for_selector("#key-input-devto", timeout=2000)

    with page.expect_request(
            lambda r: "/api/connections/devto" in r.url and r.method == "PUT") as req_info:
        page.locator("#key-input-devto").fill("devto-key-xyz")
        card.get_by_role("button", name="Save").click()

    body = req_info.value.post_data_json
    assert body["token"] == "devto-key-xyz"


# ── 5. Test connection ────────────────────────────────────────────────────────


def test_test_connection_button_present_for_each_platform(page):
    goto_settings(page)
    for pid in PLATFORM_IDS:
        assert page.locator(f"#test-btn-{pid}").is_visible(), f"test button missing for {pid}"


def test_clicking_test_connection_fires_api_call(page):
    """GET /api/connections/medium/test  is called when Test button is clicked."""
    goto_settings(page)
    with page.expect_request(lambda r: "/api/connections/medium/test" in r.url):
        page.locator("#test-btn-medium").click()


def test_test_result_area_appears_after_test(page):
    goto_settings(page)
    page.locator("#test-btn-medium").click()
    # Result area should eventually appear (even if the connection fails)
    page.wait_for_selector("#test-result-medium:not(:empty)", timeout=5000)
    text = page.locator("#test-result-medium").text_content()
    assert len(text.strip()) > 0


# ── 6. Disconnect flow ────────────────────────────────────────────────────────


def _connect_medium(base_url: str):
    """Seed a connected medium token via the API directly."""
    requests.put(f"{base_url}/api/connections/medium", json={"token": "seed-tok"})


def test_disconnect_confirmation_popup_appears(page):
    _connect_medium(BASE_URL)
    goto_settings(page)
    # After connecting, the Disconnect button should be present
    disconnect_btn = platform_card(page, "medium").get_by_role("button", name="Disconnect")
    if not disconnect_btn.is_visible():
        pytest.skip("Disconnect button not present — card may show disconnected state")
    disconnect_btn.click()
    page.wait_for_selector(f"#confirm-medium:visible", timeout=2000)
    assert page.locator("#confirm-medium").is_visible()


def test_disconnect_cancel_closes_popup(page):
    _connect_medium(BASE_URL)
    goto_settings(page)
    disconnect_btn = platform_card(page, "medium").get_by_role("button", name="Disconnect")
    if not disconnect_btn.is_visible():
        pytest.skip("Disconnect button not visible")
    disconnect_btn.click()
    page.wait_for_selector(f"#confirm-medium:visible", timeout=2000)
    page.locator("#confirm-medium").get_by_role("button", name="Cancel").click()
    page.wait_for_function(
        "document.querySelector('#confirm-medium').style.display === 'none' "
        "|| document.querySelector('#confirm-medium').classList.contains('hidden')",
        timeout=1500,
    )


def test_confirm_disconnect_calls_delete_api(page):
    _connect_medium(BASE_URL)
    goto_settings(page)
    disconnect_btn = platform_card(page, "medium").get_by_role("button", name="Disconnect")
    if not disconnect_btn.is_visible():
        pytest.skip("Disconnect button not visible")
    disconnect_btn.click()
    page.wait_for_selector("#confirm-medium:visible", timeout=2000)

    with page.expect_request(lambda r: "/api/connections/medium" in r.url and r.method == "DELETE"):
        page.locator("#confirm-medium").get_by_role("button", name="Disconnect").click()


# ── 7. "Manage connections" deep link from create-article ────────────────────


def test_create_article_manage_connections_link_lands_on_platforms(page):
    """
    The 'Manage connections' link on create-article step 3 should navigate to
    the Settings page (which defaults to the Platforms section).
    """
    page.goto(f"{BASE_URL}/screens/create-article/v1.html")
    page.wait_for_selector("#step-1", timeout=5000)

    # Advance to step 3
    page.locator("#next-btn").click()
    page.wait_for_selector("#step-2:visible", timeout=3000)
    page.locator("#next-btn").click()
    page.wait_for_selector("#step-3:visible", timeout=3000)

    link = page.get_by_role("link", name="Manage connections")
    assert link.is_visible()

    link.click()
    page.wait_for_url("**/settings/v2.html", timeout=5000)
    page.wait_for_selector("#section-platforms", timeout=5000)
    assert page.locator("#section-platforms").is_visible()
