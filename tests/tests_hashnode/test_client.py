"""Tests for the Hashnode client."""

from __future__ import annotations

import pytest

from blogs.hashnode.client import HashnodeClient, HashnodeDraftInput, HashnodeError


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.calls: list[dict[str, object]] = []
        self.payload = payload

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self.payload)


class _QueuedSession:
    def __init__(self, payloads):
        self.calls: list[dict[str, object]] = []
        self.payloads = iter(payloads)

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(next(self.payloads))


def _page(nodes, *, has_next=False, end_cursor=None):
    return {
        "edges": [{"node": node} for node in nodes],
        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
    }


def _article(article_id, *, published=False):
    return {
        "id": article_id,
        "title": f"Article {article_id}",
        "subtitle": None,
        "canonicalUrl": None,
        "url": f"https://example.hashnode.dev/{article_id}" if published else None,
        "publishedAt": "2026-01-01T00:00:00Z" if published else None,
        "dateUpdated": "2026-01-01T00:00:00Z" if not published else None,
        "coverImage": None,
        "publication": {"url": "https://example.hashnode.dev"},
        "content": {"markdown": f"Body {article_id}"},
    }


def test_create_draft_sends_cover_image_and_slugged_tags():
    session = _FakeSession(
        {
            "data": {
                "createDraft": {
                    "draft": {
                        "id": "draft-1",
                        "title": "Title",
                        "canonicalUrl": "https://example.com/source",
                        "coverImage": {"url": "https://example.com/cover.png"},
                    }
                }
            }
        }
    )
    client = HashnodeClient("token", session=session)

    result = client.create_draft(
        HashnodeDraftInput(
            title="Title",
            publication_id="pub-1",
            content_markdown="Body",
            canonical_url="https://example.com/source",
            subtitle="Subtitle",
            cover_image_url="https://example.com/cover.png",
            tags=("Python", "Neo4j"),
        )
    )

    assert result.draft_id == "draft-1"
    assert result.cover_image_url == "https://example.com/cover.png"
    assert session.calls[0]["json"]["variables"]["input"] == {
        "title": "Title",
        "publicationId": "pub-1",
        "contentMarkdown": "Body",
        "tags": [
            {"name": "Python", "slug": "python"},
            {"name": "Neo4j", "slug": "neo4j"},
        ],
        "subtitle": "Subtitle",
        "originalArticleURL": "https://example.com/source",
        "coverImageOptions": {"coverImageURL": "https://example.com/cover.png"},
    }


def test_list_drafts_fetches_every_cursor_page():
    session = _QueuedSession([
        {"data": {"me": {"drafts": _page([_article("d1")], has_next=True, end_cursor="draft-1")}}},
        {"data": {"me": {"drafts": _page([_article("d2")])}}},
    ])

    articles = HashnodeClient("token", session=session).list_drafts(first=1)

    assert [article.article_id for article in articles] == ["d1", "d2"]
    assert [call["json"]["variables"] for call in session.calls] == [
        {"first": 1, "after": None},
        {"first": 1, "after": "draft-1"},
    ]


def test_list_publications_fetches_every_cursor_page():
    session = _QueuedSession([
        {"data": {"me": {"publications": _page(
            [{"id": "p1", "title": "One", "url": "https://one.example"}],
            has_next=True,
            end_cursor="publication-1",
        )}}},
        {"data": {"me": {"publications": _page(
            [{"id": "p2", "title": "Two", "url": "https://two.example"}],
        )}}},
    ])

    publications = HashnodeClient("token", session=session).list_publications(first=1)

    assert [publication["id"] for publication in publications] == ["p1", "p2"]
    assert [call["json"]["variables"] for call in session.calls] == [
        {"first": 1, "after": None},
        {"first": 1, "after": "publication-1"},
    ]


def test_list_published_articles_paginates_each_publication_independently():
    session = _QueuedSession([
        {"data": {"me": {"publications": _page([
            {"id": "p1", "title": "One", "url": "https://one.example"},
            {"id": "p2", "title": "Two", "url": "https://two.example"},
        ])}}},
        {"data": {"publication": {"posts": _page(
            [_article("one-1", published=True)],
            has_next=True,
            end_cursor="one-page-1",
        )}}},
        {"data": {"publication": {"posts": _page([
            _article("one-2", published=True),
        ])}}},
        {"data": {"publication": {"posts": _page([
            _article("two-1", published=True),
        ])}}},
    ])

    articles = HashnodeClient("token", session=session).list_published_articles(
        publication_first=2,
        post_first=1,
    )

    assert [article.article_id for article in articles] == ["one-1", "one-2", "two-1"]
    assert [call["json"]["variables"] for call in session.calls] == [
        {"first": 2, "after": None},
        {"host": "one.example", "first": 1, "after": None},
        {"host": "one.example", "first": 1, "after": "one-page-1"},
        {"host": "two.example", "first": 1, "after": None},
    ]


def test_list_published_articles_treats_missing_publication_as_empty():
    session = _QueuedSession([
        {"data": {"me": {"publications": _page([
            {"id": "p1", "title": "One", "url": "https://missing.example"},
        ])}}},
        {"data": {"publication": None}},
    ])

    articles = HashnodeClient("token", session=session).list_published_articles()

    assert articles == []


def test_pagination_propagates_graphql_error_from_later_page():
    session = _QueuedSession([
        {"data": {"me": {"drafts": _page(
            [_article("d1")], has_next=True, end_cursor="draft-1",
        )}}},
        {"errors": [{"message": "Token expired"}]},
    ])

    with pytest.raises(HashnodeError, match="Token expired"):
        HashnodeClient("token", session=session).list_drafts()


@pytest.mark.parametrize("end_cursor", [None, "same-cursor"])
def test_pagination_rejects_missing_or_repeated_cursor(end_cursor):
    first_cursor = "same-cursor" if end_cursor == "same-cursor" else None
    payloads = []
    if first_cursor is not None:
        payloads.append({"data": {"me": {"drafts": _page(
            [], has_next=True, end_cursor=first_cursor,
        )}}})
    payloads.append({"data": {"me": {"drafts": _page(
        [], has_next=True, end_cursor=end_cursor,
    )}}})
    session = _QueuedSession(payloads)

    with pytest.raises(HashnodeError, match="cursor"):
        HashnodeClient("token", session=session).list_drafts()
