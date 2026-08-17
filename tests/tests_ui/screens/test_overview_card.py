import pytest

from tests.tests_ui.conftest import BASE_URL


pytestmark = pytest.mark.browser

OVERVIEW_URL = f"{BASE_URL}/screens/overview/v3.html"


def open_overview(page, width=1440, height=1000):
    page.set_viewport_size({"width": width, "height": height})
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        data={
            "email": "seed@example.com",
            "password": "seed1234",
            "remember_me": False,
        },
    )
    assert response.ok
    page.goto(OVERVIEW_URL)
    page.wait_for_selector(".article-card")
    return page.locator(".article-card").first


def test_card_matches_approved_desktop_geometry(page):
    card = open_overview(page)

    card_box = card.bounding_box()
    media_box = card.locator(".article-card-media").bounding_box()
    copy_box = card.locator(".article-card-copy").bounding_box()

    assert round(card_box["width"]) == 750
    assert round(card_box["height"]) == 241
    assert round(media_box["width"]) == 273
    assert round(media_box["height"]) == 187
    assert round(copy_box["width"]) == 468

    title_box = card.locator(".article-card-title").bounding_box()
    subtitle_box = card.locator(".article-card-subtitle").bounding_box()
    assert round(subtitle_box["y"] - title_box["y"] - title_box["height"]) == 4


def test_preview_selection_survives_card_rerender(page):
    card = open_overview(page)

    card.locator(".plat-tab").filter(has_text="HASHNODE").click()
    page.locator("#sf-all").click()

    active_tab = page.locator(".article-card").first.locator(".plat-tab.active")
    assert active_tab.inner_text().strip() == "HASHNODE"


def test_preview_selection_updates_the_accent_color(page):
    card = open_overview(page)
    accent = card.locator(".accent-bar")

    assert accent.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(110, 168, 254)"
    card.locator(".plat-tab").filter(has_text="HASHNODE").click()

    updated_accent = page.locator(".article-card").first.locator(".accent-bar")
    assert updated_accent.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(251, 191, 36)"


def test_card_stacks_preview_below_details_on_mobile(page):
    card = open_overview(page, width=390, height=844)

    card_box = card.bounding_box()
    tabs_box = card.locator(".article-card-tabs").bounding_box()
    media_box = card.locator(".article-card-media").bounding_box()
    copy_box = card.locator(".article-card-copy").bounding_box()

    assert round(card_box["width"]) == 326
    assert round(media_box["width"]) == round(copy_box["width"])
    assert media_box["y"] >= tabs_box["y"] + tabs_box["height"] - 1
    assert copy_box["y"] >= media_box["y"] + media_box["height"] - 1
    assert round(media_box["height"]) == 180


def test_edit_opens_the_selected_article(page):
    card = open_overview(page)
    article_id = card.get_attribute("data-id")

    with page.expect_navigation():
        card.get_by_role("button", name="Edit").click()

    assert f"/screens/editor/v2.html?id={article_id}" in page.url
