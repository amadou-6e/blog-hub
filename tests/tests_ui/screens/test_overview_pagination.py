import re

import pytest

from tests.tests_ui.conftest import BASE_URL


pytestmark = pytest.mark.browser

OVERVIEW_URL = f"{BASE_URL}/screens/overview/v3.html"

# 6 seed articles ship out of the box (see backend/store/backends/sqlite.py).
SEED_ARTICLE_COUNT = 6


def _login(page):
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        data={
            "email": "seed@example.com",
            "password": "seed1234",
            "remember_me": False,
        },
    )
    assert response.ok
    return response


def _seed_extra_articles(page, count, prefix="Bulk seeded article"):
    for i in range(count):
        response = page.request.post(
            f"{BASE_URL}/api/articles",
            data={"title": f"{prefix} {i:04d}"},
        )
        assert response.ok, response.text()


def _delete_all_articles(page):
    listing = page.request.get(f"{BASE_URL}/api/articles?page=1&pageSize=100").json()
    ids = [item["id"] for item in listing["items"]]
    if ids:
        response = page.request.delete(
            f"{BASE_URL}/api/articles",
            data={"ids": ids, "force": True},
        )
        assert response.ok, response.text()


def open_overview(page, width=1440, height=1000, extra_articles=0):
    """Log in, optionally seed extra articles, then land on the overview screen."""
    page.set_viewport_size({"width": width, "height": height})
    _login(page)
    if extra_articles:
        _seed_extra_articles(page, extra_articles)
    page.goto(OVERVIEW_URL)
    page.wait_for_selector(".article-card")


def card_ids(page):
    return page.locator(".article-card").evaluate_all(
        "elements => elements.map(el => el.dataset.id)"
    )


# ── multiple pages / final partial page ────────────────────────────────────


def test_load_more_reveals_articles_beyond_the_first_hundred(page):
    open_overview(page, extra_articles=110)  # total = 116

    assert page.locator(".article-card").count() == 100
    status = page.locator("#load-more-status")
    assert status.inner_text().strip() == "Showing 100 of 116 articles"

    page.locator("#load-more-button").click()
    page.wait_for_function("document.querySelectorAll('.article-card').length === 116")

    assert page.locator(".article-card").count() == 116
    assert page.locator(".article-card").last.get_attribute("data-id") is not None


def test_final_page_is_partial_and_load_more_disappears_when_exhausted(page):
    open_overview(page, extra_articles=110)  # total = 116, second page = 16 items

    page.locator("#load-more-button").click()
    page.wait_for_function("document.querySelectorAll('.article-card').length === 116")

    assert page.locator("#load-more-button").count() == 0
    status = page.locator(".load-more-status")
    assert status.inner_text().strip() == "Showing all 116 articles"


def test_load_more_does_not_duplicate_or_reorder_already_rendered_cards(page):
    open_overview(page, extra_articles=110)

    ids_before = card_ids(page)
    assert len(ids_before) == 100
    assert len(set(ids_before)) == 100

    page.locator("#load-more-button").click()
    page.wait_for_function("document.querySelectorAll('.article-card').length === 116")

    ids_after = card_ids(page)
    assert len(ids_after) == 116
    assert len(set(ids_after)) == 116  # no duplicates
    assert ids_after[:100] == ids_before  # already-rendered order untouched


# ── empty results ───────────────────────────────────────────────────────────


def test_empty_workspace_shows_no_results_without_load_more_control(page):
    # Note: a genuinely article-free workspace renders through the same
    # "no matches" state as an over-filtered one (#no-results) — this is
    # pre-existing overview behavior, unchanged by pagination. What matters
    # for this issue is that no load-more control appears when there is
    # nothing to page through.
    page.set_viewport_size({"width": 1440, "height": 1000})
    _login(page)
    _delete_all_articles(page)
    page.goto(OVERVIEW_URL)
    page.wait_for_selector("#no-results")

    assert page.locator(".article-card").count() == 0
    assert page.locator("#load-more-button").count() == 0
    assert page.locator("#no-results").is_visible()


# ── request failure / retry ─────────────────────────────────────────────────


def test_load_more_failure_shows_retry_and_recovers(page):
    open_overview(page, extra_articles=110)

    attempts = {"count": 0}

    def _maybe_fail(route, request):
        if "page=2" in request.url:
            attempts["count"] += 1
            if attempts["count"] == 1:
                route.fulfill(status=500, body="boom")
                return
        route.continue_()

    page.route(re.compile(r"/api/articles\?.*"), _maybe_fail)

    page.locator("#load-more-button").click()
    page.wait_for_selector("text=Couldn't load more articles")
    assert page.locator(".article-card").count() == 100  # unchanged after failure

    retry = page.get_by_role("button", name="Retry")
    retry.click()
    page.wait_for_function("document.querySelectorAll('.article-card').length === 116")
    assert page.locator(".article-card").count() == 116

    page.unroute(re.compile(r"/api/articles\?.*"))


# ── filter changes during in-flight loading ─────────────────────────────────


def test_changing_filter_while_page_load_in_flight_does_not_corrupt_state(page):
    open_overview(page, extra_articles=110)

    def _delay_page_two(route, request):
        if "page=2" in request.url:
            page.wait_for_timeout(300)
        route.continue_()

    page.route(re.compile(r"/api/articles\?.*"), _delay_page_two)

    page.locator("#load-more-button").click()
    # Change filters while the page-2 request is still in flight.
    page.locator("#sf-drafting").click()

    page.wait_for_timeout(600)  # let the delayed response land (and be ignored/applied)

    ids = card_ids(page)
    assert len(ids) == len(set(ids))  # never duplicated regardless of race outcome

    page.unroute(re.compile(r"/api/articles\?.*"))


def test_filter_change_during_initial_load_does_not_discard_page_one(page):
    page.set_viewport_size({"width": 1440, "height": 1000})
    _login(page)

    def _delay_page_one(route, request):
        if "page=1" in request.url:
            page.wait_for_timeout(300)
        route.continue_()

    page.route(re.compile(r"/api/articles\?.*"), _delay_page_one)
    page.goto(OVERVIEW_URL)
    page.locator("#search-input").fill("article")

    page.wait_for_selector(".article-card")
    assert page.locator(".article-card").count() > 0

    page.unroute(re.compile(r"/api/articles\?.*"))


def test_search_automatically_includes_matches_beyond_page_one(page):
    page.set_viewport_size({"width": 1440, "height": 1000})
    _login(page)
    target = page.request.post(
        f"{BASE_URL}/api/articles",
        data={"title": "Unique deep pagination target"},
    )
    assert target.ok
    _seed_extra_articles(page, 110, prefix="Newer filler article")

    page.goto(OVERVIEW_URL)
    page.wait_for_selector(".article-card")
    page.locator("#search-input").fill("Unique deep pagination target")

    match = page.locator(".article-card").filter(has_text="Unique deep pagination target")
    match.wait_for()
    assert match.count() == 1


# ── preview-tab selection survives incremental rendering ───────────────────


def test_active_preview_tab_survives_load_more(page):
    open_overview(page, extra_articles=110)

    first_card = page.locator(".article-card").first
    first_card.locator(".plat-tab").filter(has_text="HASHNODE").click()

    page.locator("#load-more-button").click()
    page.wait_for_function("document.querySelectorAll('.article-card').length === 116")

    active_tab = page.locator(".article-card").first.locator(".plat-tab.active")
    assert active_tab.inner_text().strip() == "HASHNODE"


# ── accessibility ────────────────────────────────────────────────────────────


def test_load_more_control_is_accessible(page):
    open_overview(page, extra_articles=110)

    button = page.locator("#load-more-button")
    assert button.get_attribute("aria-describedby") == "load-more-status"

    status = page.locator("#load-more-status")
    assert status.get_attribute("role") == "status"
    assert status.get_attribute("aria-live") == "polite"

    # Keyboard: focus and activate via Enter.
    button.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.article-card').length === 116")
    assert page.locator(".article-card").count() == 116


# ── mobile layout: no overlap/resize from the load-more control ────────────


def test_load_more_control_does_not_overlap_cards_on_mobile(page):
    open_overview(page, width=390, height=844, extra_articles=110)

    last_card_box = page.locator(".article-card").last.bounding_box()
    button_box = page.locator("#load-more-button").bounding_box()

    assert button_box["y"] >= last_card_box["y"] + last_card_box["height"] - 1
    assert button_box["width"] <= 390
