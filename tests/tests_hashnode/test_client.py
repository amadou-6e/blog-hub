"""Tests for the Hashnode client."""

from __future__ import annotations

from blogs.hashnode.client import HashnodeClient, HashnodeDraftInput


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
