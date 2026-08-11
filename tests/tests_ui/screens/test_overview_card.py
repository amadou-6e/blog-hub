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
    left_box = card.locator(".article-card-left").bounding_box()
    right_box = card.locator(".article-card-right").bounding_box()

    assert round(card_box["width"]) == 1080
    assert round(card_box["height"]) == 241
    assert round(left_box["width"]) == 332
    assert round(right_box["width"]) == 743


def test_preview_selection_survives_card_rerender(page):
    card = open_overview(page)

    card.locator(".plat-tab").filter(has_text="HASHNODE").click()
    page.locator("#sf-all").click()

    active_tab = page.locator(".article-card").first.locator(".plat-tab.active")
    assert active_tab.inner_text().strip() == "HASHNODE"


def test_card_stacks_preview_below_details_on_mobile(page):
    card = open_overview(page, width=390, height=844)

    card_box = card.bounding_box()
    left_box = card.locator(".article-card-left").bounding_box()
    right_box = card.locator(".article-card-right").bounding_box()

    assert round(card_box["width"]) == 326
    assert round(left_box["width"]) == round(right_box["width"])
    assert right_box["y"] >= left_box["y"] + left_box["height"] - 1
    assert right_box["height"] >= 190


def test_edit_opens_the_selected_article(page):
    card = open_overview(page)
    article_id = card.get_attribute("data-id")

    with page.expect_navigation():
        card.get_by_role("button", name="Edit").click()

    assert f"/screens/editor/v2.html?id={article_id}" in page.url
