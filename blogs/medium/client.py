"""
Medium API v1 — thin HTTP client.

Only the endpoints used by blog-hub are wrapped here.
All HTTP calls are made through an injected requests.Session so tests can
substitute a mock session without monkey-patching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

BASE_URL = "https://api.medium.com/v1"


class MediumApiError(RuntimeError):
    """Raised when the Medium API returns an error payload or non-2xx status."""


@dataclass(frozen=True)
class MediumUser:
    id: str
    username: str
    name: str
    url: str
    image_url: str | None


@dataclass(frozen=True)
class MediumPost:
    id: str
    title: str
    url: str
    canonical_url: str | None
    publish_status: str  # "draft" | "public" | "unlisted"


class MediumApiClient:
    """
    Thin wrapper around Medium API v1.

    Inject a custom ``session`` (e.g. ``unittest.mock.MagicMock``) in tests
    to avoid real HTTP calls.
    """

    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        self._token = token
        self._session = session or requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------

    def get_user(self) -> MediumUser:
        """GET /v1/me — return the authenticated user."""
        resp = self._session.get(f"{BASE_URL}/me", headers=self._headers, timeout=10)
        resp.raise_for_status()
        data = self._unwrap(resp)
        return MediumUser(
            id=data["id"],
            username=data["username"],
            name=data["name"],
            url=data["url"],
            image_url=data.get("imageUrl"),
        )

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def create_post(self, user_id: str, payload: dict[str, Any]) -> MediumPost:
        """
        POST /v1/users/{userId}/posts — create a new post.

        ``payload`` follows the Medium API spec:
          title, contentFormat, content, tags, publishStatus, canonicalUrl, ...
        """
        resp = self._session.post(
            f"{BASE_URL}/users/{user_id}/posts",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = self._unwrap(resp)
        return MediumPost(
            id=data["id"],
            title=data.get("title", ""),
            url=data.get("url", ""),
            canonical_url=data.get("canonicalUrl"),
            publish_status=data.get("publishStatus", "draft"),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap(resp: requests.Response) -> dict[str, Any]:
        """Extract ``data`` from a Medium API response, raising on errors."""
        try:
            body = resp.json()
        except ValueError as exc:
            raise MediumApiError(f"Medium API returned non-JSON ({resp.status_code})") from exc
        errors = body.get("errors")
        if errors:
            raise MediumApiError(str(errors))
        return body["data"]
