"""Tests for the DEV.to client."""

from __future__ import annotations

import pytest

from blogs.devto.client import DevToArticle, DevToClient, DevToError


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: object, ok: bool):
        self.status_code = status_code
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.response

    def put(self, url, **kwargs):
        self.calls.append({"method": "PUT", "url": url, **kwargs})
        return self.response


def test_publish_article_posts_expected_payload():
    session = _FakeSession(
        _FakeResponse(
            status_code=201,
            ok=True,
            payload={"id": 42, "url": "https://dev.to/example/post"},
        )
    )
    client = DevToClient("token", session=session)

    result = client.publish_article(
        DevToArticle(
            title="Title",
            body_markdown="Hello",
            published=False,
            tags=("python", "api"),
        )
    )

    assert result.article_id == 42
    assert result.url == "https://dev.to/example/post"
    assert session.calls[0]["json"] == {
        "article": {
            "title": "Title",
            "body_markdown": "Hello",
            "published": False,
            "tags": ["python", "api"],
        }
    }


def test_update_article_raises_error_for_api_failure():
    session = _FakeSession(
        _FakeResponse(
            status_code=422,
            ok=False,
            payload={"error": "Validation failed"},
        )
    )
    client = DevToClient("token", session=session)

    with pytest.raises(DevToError, match="Validation failed"):
        client.update_article(99, DevToArticle(title="Title", body_markdown="Body"))
