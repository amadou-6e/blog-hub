from __future__ import annotations

import backend.store as store
from backend.store.schema import SEED_USER_ID


def _create_articles(n: int, prefix: str = "Paginated article") -> None:
    for i in range(n):
        store.create_article(SEED_USER_ID, title=f"{prefix} {i:04d}")


def test_list_articles_default_page_size_still_100_cap(client) -> None:
    _create_articles(130)
    response = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=1&pageSize=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["pageSize"] == 100
    assert len(payload["items"]) == 100
    # 6 seed articles + 130 created
    assert payload["total"] == 136


def test_second_page_reaches_articles_beyond_the_first_hundred(client) -> None:
    _create_articles(130)

    first = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=1&pageSize=100").json()
    second = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=2&pageSize=100").json()

    assert first["total"] == second["total"] == 136
    assert len(first["items"]) == 100
    assert len(second["items"]) == 36

    first_ids = [item["id"] for item in first["items"]]
    second_ids = [item["id"] for item in second["items"]]

    # No duplicates and no gaps across pages.
    assert len(set(first_ids)) == 100
    assert len(set(second_ids)) == 36
    assert set(first_ids).isdisjoint(second_ids)
    assert len(set(first_ids) | set(second_ids)) == 136


def test_pagination_preserves_sort_order_across_pages(client) -> None:
    _create_articles(130)

    first = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=1&pageSize=100").json()
    second = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=2&pageSize=100").json()

    paged_updated_at = [item["updatedAt"] for item in first["items"]] + [
        item["updatedAt"] for item in second["items"]
    ]

    # updatedAt must be non-increasing across the full paged sequence (descending sort).
    assert paged_updated_at == sorted(paged_updated_at, reverse=True)
    # The last item of page 1 must not be "newer" than the first item of page 2.
    assert first["items"][-1]["updatedAt"] >= second["items"][0]["updatedAt"]


def test_final_page_is_a_partial_page(client) -> None:
    _create_articles(130)
    third = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=3&pageSize=100").json()
    assert third["items"] == []
    assert third["total"] == 136

    # page=2 pageSize=100 -> items 101..136 (36 items), a genuine partial final page.
    second = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=2&pageSize=100").json()
    assert len(second["items"]) == 36


def test_pagination_max_page_size_is_capped_at_100(client) -> None:
    response = client.get("/api/articles?page=1&pageSize=500")
    assert response.status_code == 422


def test_empty_workspace_page_one_is_empty_not_an_error(client) -> None:
    store.delete_articles(SEED_USER_ID, ids=[a["id"] for a in store.list_articles(SEED_USER_ID, page=1, page_size=100)[0]], force=True)
    response = client.get("/api/articles?page=1&pageSize=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0
