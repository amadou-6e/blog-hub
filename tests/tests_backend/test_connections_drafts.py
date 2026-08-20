"""
Tests for GET /api/connections/{conn_id}/drafts
     and GET /api/connections/{conn_id}/drafts/{draft_id}

Unit tests:        mocked httpx.Client — no network required
Integration tests: real credentials read from .env / env-vars (marked `integration`)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import sys

import pytest
from fastapi.testclient import TestClient

_blog_hub_root = Path(__file__).resolve().parents[2]
if str(_blog_hub_root) not in sys.path:
    sys.path.insert(0, str(_blog_hub_root))

from backend.main import app
import backend.store as store

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ── helpers ──────────────────────────────────────────────────────────────────


def _read_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if key.strip() == name:
            return raw_value.strip()
    return ""


def _mock_response(json_data: Any, status_code: int = 200) -> MagicMock:
    """Return a mock that behaves like an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _hashnode_gql_response(drafts: list[dict], posts: list[dict]) -> dict:
    """Build a fake Hashnode GraphQL response shaped like _fetch_hashnode_drafts expects."""
    return {
        "data": {
            "me": {
                "drafts": {
                    "edges": [{
                        "node": {
                            "id": d["id"],
                            "title": d.get("title", "Draft"),
                            "subtitle": d.get("subtitle", ""),
                            "updatedAt": d.get("updatedAt", "2026-04-01T10:00:00Z"),
                            "content": {
                                "markdown": d.get("markdown", "# Hello\n\nBody text.")
                            },
                        }
                    } for d in drafts]
                },
                # posts uses offset-based pagination: nodes (not edges)
                "posts": {
                    "nodes": [{
                        "id": p["id"],
                        "title": p.get("title", "Post"),
                        "brief": p.get("brief", ""),
                        "updatedAt": p.get("updatedAt", "2026-03-15T08:00:00Z"),
                        "content": {
                            "markdown": p.get("markdown", "# Published\n\nContent.")
                        },
                    } for p in posts]
                },
            }
        }
    }


def _devto_list_item(article_id: int, title: str, status: str) -> dict:
    return {
        "id": article_id,
        "title": title,
        "description": f"Snippet for {title}",
        "reading_time_minutes": 4,
        "edited_at": "2026-04-02T09:00:00Z",
        "published_at": "2026-04-01T09:00:00Z",
    }


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    c = TestClient(app)
    c.post("/api/auth/login",
           json={"email": "seed@example.com", "password": "seed1234", "remember_me": False})
    return c


# reset_store is autouse from conftest.py

# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — no network
# ─────────────────────────────────────────────────────────────────────────────


class TestListDraftsUnit:

    def test_list_hashnode_unauthenticated(self, client: TestClient):
        r = client.get("/api/connections/hashnode/drafts")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "platform_not_connected"

    def test_list_devto_unauthenticated(self, client: TestClient):
        r = client.get("/api/connections/devto/drafts")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "platform_not_connected"

    def test_list_hashnode_shape(self, client: TestClient):
        store.save_connection("user_seed", "hashnode", token="fake-hn-token")
        gql_payload = _hashnode_gql_response(
            drafts=[
                {
                    "id": "d1",
                    "title": "Draft One",
                    "subtitle": "Sub one",
                    "markdown": "# D1\n\nword word word"
                },
                {
                    "id": "d2",
                    "title": "Draft Two",
                    "markdown": "# D2\n\nword"
                },
            ],
            posts=[
                {
                    "id": "p1",
                    "title": "Post One",
                    "brief": "Brief one",
                    "markdown": "# P1\n\npublished content"
                },
            ],
        )
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.post.return_value = _mock_response(gql_payload)

        with patch("backend.routers.connections.httpx.Client", return_value=mock_ctx):
            r = client.get("/api/connections/hashnode/drafts")

        assert r.status_code == 200
        body = r.json()
        assert body["platform"] == "hashnode"
        assert body["total"] == 3
        assert body["page"] == 1
        assert "per_page" in body
        assert "has_more" in body

        drafts = body["drafts"]
        assert len(drafts) == 3

        d1 = next(d for d in drafts if d["id"] == "d1")
        assert d1["title"] == "Draft One"
        assert d1["status"] == "draft"
        assert d1["snippet"] == "Sub one"
        assert d1["word_count"] > 0
        assert d1["updated_at"] != ""

        p1 = next(d for d in drafts if d["id"] == "p1")
        assert p1["status"] == "published"
        assert p1["snippet"] == "Brief one"

    def test_list_devto_shape(self, client: TestClient):
        store.save_connection("user_seed", "devto", token="fake-devto-token")

        unpublished_payload = [
            _devto_list_item(101, "Unpublished One", "draft"),
            _devto_list_item(102, "Unpublished Two", "draft"),
        ]
        published_payload = [
            _devto_list_item(201, "Published One", "published"),
        ]

        # Share iterator across Client instances (_get_list creates one Client per call)
        _responses = iter([
            _mock_response(unpublished_payload),
            _mock_response(published_payload),
        ])

        def make_mock_ctx(*args, **kwargs):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.get.side_effect = lambda *a, **kw: next(_responses)
            return mock_ctx

        with patch("backend.routers.connections.httpx.Client", side_effect=make_mock_ctx):
            r = client.get("/api/connections/devto/drafts")

        assert r.status_code == 200
        body = r.json()
        assert body["platform"] == "devto"
        assert body["total"] == 3

        ids = {d["id"] for d in body["drafts"]}
        assert "101" in ids
        assert "201" in ids

        unpub = next(d for d in body["drafts"] if d["id"] == "101")
        assert unpub["status"] == "draft"

        pub = next(d for d in body["drafts"] if d["id"] == "201")
        assert pub["status"] == "published"

    def test_list_pagination(self, client: TestClient):
        store.save_connection("user_seed", "hashnode", token="fake-hn-token")

        # 5 drafts, 0 posts
        gql_payload = _hashnode_gql_response(
            drafts=[{
                "id": f"d{i}",
                "title": f"Draft {i}",
                "markdown": "word"
            } for i in range(5)],
            posts=[],
        )
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.post.return_value = _mock_response(gql_payload)

        with patch("backend.routers.connections.httpx.Client", return_value=mock_ctx):
            r = client.get("/api/connections/hashnode/drafts?page=2&per_page=2")

        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 2
        assert body["per_page"] == 2
        assert len(body["drafts"]) == 2
        assert body["has_more"] is True  # 4 items served so far out of 5

    def test_list_hashnode_api_error_returns_502(self, client: TestClient):
        import httpx as _httpx
        store.save_connection("user_seed", "hashnode", token="fake-hn-token")

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        error_resp = MagicMock()
        error_resp.status_code = 401
        mock_ctx.post.side_effect = _httpx.HTTPStatusError("401 Unauthorized",
                                                           request=MagicMock(),
                                                           response=error_resp)

        with patch("backend.routers.connections.httpx.Client", return_value=mock_ctx):
            r = client.get("/api/connections/hashnode/drafts")

        assert r.status_code == 502

    def test_list_devto_api_error_returns_502(self, client: TestClient):
        import httpx as _httpx
        store.save_connection("user_seed", "devto", token="fake-devto-token")

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        error_resp = MagicMock()
        error_resp.status_code = 403
        mock_ctx.get.side_effect = _httpx.HTTPStatusError("403 Forbidden",
                                                          request=MagicMock(),
                                                          response=error_resp)

        with patch("backend.routers.connections.httpx.Client", return_value=mock_ctx):
            r = client.get("/api/connections/devto/drafts")

        assert r.status_code == 502

    def test_list_medium_falls_back_to_mock(self, client: TestClient):
        from backend.routers.connections import _MOCK_DRAFTS
        store.save_connection("user_seed", "medium", token="fake-medium-token")

        r = client.get("/api/connections/medium/drafts")

        assert r.status_code == 200
        body = r.json()
        assert body["platform"] == "medium"
        assert body["total"] == len(_MOCK_DRAFTS["medium"])
        assert len(body["drafts"]) > 0

    def test_list_medium_uses_connected_browser_profile(self, client: TestClient):
        store.start_browser_connection(
            "user_seed", "medium", session_id="pbs_medium",
            organization_id="o_medium", app_url="http://localhost/login",
        )
        store.update_browser_connection(
            "user_seed", "medium", "connected", profile_id="bp_medium"
        )
        payload = [{
            "id": "medium-1", "title": "A live Medium draft",
            "snippet": "Retrieved in the browser", "word_count": 42,
            "updated_at": "2026-08-20T00:00:00Z", "status": "draft",
        }]

        with patch(
            "backend.routers.connections.runner.list_medium_browser_articles",
            return_value=payload,
        ) as fetch:
            response = client.get("/api/connections/medium/drafts")

        assert response.status_code == 200
        assert response.json()["drafts"][0]["title"] == "A live Medium draft"
        fetch.assert_called_once_with(
            organization_id="o_medium", profile_id="bp_medium"
        )


class TestGetDraftUnit:

    def test_get_draft_hashnode_returns_body(self, client: TestClient):
        store.save_connection("user_seed", "hashnode", token="fake-hn-token")

        gql_payload = _hashnode_gql_response(
            drafts=[{
                "id": "d1",
                "title": "My Draft",
                "markdown": "# My Draft\n\nFull body here."
            }],
            posts=[],
        )
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.post.return_value = _mock_response(gql_payload)

        with patch("backend.routers.connections.httpx.Client", return_value=mock_ctx):
            r = client.get("/api/connections/hashnode/drafts/d1")

        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "d1"
        assert body["title"] == "My Draft"
        assert "Full body here" in body["body"]
        assert body["status"] == "draft"

    def test_get_draft_devto_returns_body(self, client: TestClient):
        store.save_connection("user_seed", "devto", token="fake-devto-token")

        list_item = {
            **_devto_list_item(42, "My Dev Article", "draft"), "body_markdown":
                "# My Dev Article\n\nFull markdown body."
        }

        # get_draft now calls _fetch_devto_drafts (2 GET calls: unpublished + published)
        # body_markdown is already in the listing response; no third call needed
        _responses = iter([
            _mock_response([list_item]),  # unpublished
            _mock_response([]),  # published
        ])

        def make_mock_ctx(*args, **kwargs):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.get.side_effect = lambda *a, **kw: next(_responses)
            return mock_ctx

        with patch("backend.routers.connections.httpx.Client", side_effect=make_mock_ctx):
            r = client.get("/api/connections/devto/drafts/42")

        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "42"
        assert body["title"] == "My Dev Article"
        assert "Full markdown body" in body["body"]

    def test_get_draft_hashnode_not_found(self, client: TestClient):
        store.save_connection("user_seed", "hashnode", token="fake-hn-token")

        gql_payload = _hashnode_gql_response(
            drafts=[{
                "id": "d1",
                "title": "Exists",
                "markdown": "body"
            }],
            posts=[],
        )
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.post.return_value = _mock_response(gql_payload)

        with patch("backend.routers.connections.httpx.Client", return_value=mock_ctx):
            r = client.get("/api/connections/hashnode/drafts/does-not-exist")

        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "draft_not_found"

    def test_get_draft_devto_not_found(self, client: TestClient):
        store.save_connection("user_seed", "devto", token="fake-devto-token")

        _responses = iter([_mock_response([]), _mock_response([])])

        def make_mock_ctx(*args, **kwargs):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.get.side_effect = lambda *a, **kw: next(_responses)
            return mock_ctx

        with patch("backend.routers.connections.httpx.Client", side_effect=make_mock_ctx):
            r = client.get("/api/connections/devto/drafts/9999")

        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "draft_not_found"

    def test_get_draft_medium_mock_body(self, client: TestClient):
        from backend.routers.connections import _MOCK_DRAFTS
        store.save_connection("user_seed", "medium", token="fake-medium-token")

        first_id = _MOCK_DRAFTS["medium"][0]["id"]
        r = client.get(f"/api/connections/medium/drafts/{first_id}")

        assert r.status_code == 200
        body = r.json()
        assert body["id"] == first_id
        assert len(body["body"]) > 0

    def test_get_medium_article_uses_connected_browser_profile(self, client: TestClient):
        store.start_browser_connection(
            "user_seed", "medium", session_id="pbs_medium",
            organization_id="o_medium", app_url="http://localhost/login",
        )
        store.update_browser_connection(
            "user_seed", "medium", "connected", profile_id="bp_medium"
        )
        payload = {
            "id": "medium-1", "title": "A live Medium draft",
            "body": "# Retrieved\n\nReal browser content.", "word_count": 3,
            "updated_at": "2026-08-20T00:00:00Z", "status": "draft",
            "canonical_url": None, "cover_image": None,
        }

        with patch(
            "backend.routers.connections.runner.get_medium_browser_article",
            return_value=payload,
        ) as fetch:
            response = client.get("/api/connections/medium/drafts/medium-1")

        assert response.status_code == 200
        assert response.json()["body"].startswith("# Retrieved")
        fetch.assert_called_once_with(
            "medium-1", organization_id="o_medium", profile_id="bp_medium"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Live-fetch tests — no push/publish; skip only when credentials are absent
# ─────────────────────────────────────────────────────────────────────────────


class TestDraftsIntegration:

    @pytest.fixture(autouse=True)
    def reset(self):
        store.reset()
        yield
        store.reset()

    def test_integration_hashnode_list(self, client: TestClient):
        token = _read_secret("HASHNODE_PAT")
        if not token:
            pytest.skip("HASHNODE_PAT not set")

        store.save_connection("user_seed", "hashnode", token=token)
        r = client.get("/api/connections/hashnode/drafts?per_page=50")
        assert r.status_code == 200

        body = r.json()
        assert body["platform"] == "hashnode"
        assert isinstance(body["total"], int)
        assert body["total"] >= 0

        for d in body["drafts"]:
            assert "id" in d
            assert "title" in d
            assert "status" in d
            assert d["status"] in ("draft", "published")
            assert isinstance(d["word_count"], int)

    def test_integration_devto_list(self, client: TestClient):
        token = _read_secret("DEVTO_API_KEY")
        if not token:
            pytest.skip("DEVTO_API_KEY not set")

        store.save_connection("user_seed", "devto", token=token)
        r = client.get("/api/connections/devto/drafts?per_page=50")
        assert r.status_code == 200

        body = r.json()
        assert body["platform"] == "devto"
        assert isinstance(body["total"], int)

        for d in body["drafts"]:
            assert "id" in d
            assert "title" in d
            assert d["status"] in ("draft", "published")

    def test_integration_hashnode_get_draft(self, client: TestClient):
        token = _read_secret("HASHNODE_PAT")
        if not token:
            pytest.skip("HASHNODE_PAT not set")

        store.save_connection("user_seed", "hashnode", token=token)
        list_r = client.get("/api/connections/hashnode/drafts?per_page=50")
        assert list_r.status_code == 200
        drafts = list_r.json()["drafts"]
        if not drafts:
            pytest.skip("No Hashnode articles found for this account")

        first_id = drafts[0]["id"]
        r = client.get(f"/api/connections/hashnode/drafts/{first_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == first_id
        assert isinstance(body["body"], str)
        assert len(body["body"]) > 0

    def test_integration_devto_get_draft(self, client: TestClient):
        token = _read_secret("DEVTO_API_KEY")
        if not token:
            pytest.skip("DEVTO_API_KEY not set")

        store.save_connection("user_seed", "devto", token=token)
        list_r = client.get("/api/connections/devto/drafts?per_page=50")
        assert list_r.status_code == 200
        drafts = list_r.json()["drafts"]
        if not drafts:
            pytest.skip("No Dev.to articles found for this account")

        first_id = drafts[0]["id"]
        r = client.get(f"/api/connections/devto/drafts/{first_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == first_id
        assert isinstance(body["body"], str)
        assert len(body["body"]) > 0
