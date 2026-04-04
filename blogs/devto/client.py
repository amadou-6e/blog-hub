"""Thin DEV.to HTTP client used by blog-hub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


class DevToError(RuntimeError):
    """Raised when the DEV.to API returns an error payload."""


@dataclass(frozen=True)
class DevToArticle:
    """Normalized DEV.to publish payload."""

    title: str
    body_markdown: str
    published: bool = False
    series: str | None = None
    main_image: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DevToPublishResult:
    """Small subset of the DEV.to response."""

    article_id: int
    url: str
    api_url: str
    raw: dict[str, Any]


class DevToClient:
    """Thin wrapper around the DEV.to article endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://dev.to/api",
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        """Headers required by DEV.to."""
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def publish_article(self, article: DevToArticle) -> DevToPublishResult:
        """Create a new DEV.to article."""
        response = self._session.post(
            f"{self._base_url}/articles",
            headers=self.headers,
            json={"article": self._article_payload(article)},
            timeout=30,
        )
        return self._handle_response(response)

    def update_article(self, article_id: int, article: DevToArticle) -> DevToPublishResult:
        """Update an existing DEV.to article."""
        response = self._session.put(
            f"{self._base_url}/articles/{article_id}",
            headers=self.headers,
            json={"article": self._article_payload(article)},
            timeout=30,
        )
        return self._handle_response(response)

    def build_request_body(self, article: DevToArticle) -> dict[str, Any]:
        """Return the JSON body without sending it."""
        return {"article": self._article_payload(article)}

    @staticmethod
    def _article_payload(article: DevToArticle) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": article.title,
            "body_markdown": article.body_markdown,
            "published": article.published,
        }
        if article.series:
            payload["series"] = article.series
        if article.main_image:
            payload["main_image"] = article.main_image
        if article.canonical_url:
            payload["canonical_url"] = article.canonical_url
        if article.description:
            payload["description"] = article.description
        if article.tags:
            payload["tags"] = list(article.tags)
        return payload

    @staticmethod
    def _handle_response(response: requests.Response) -> DevToPublishResult:
        try:
            data = response.json()
        except ValueError as exc:
            raise DevToError(f"DEV.to API returned non-JSON ({response.status_code})") from exc

        if response.ok:
            return DevToPublishResult(
                article_id=int(data["id"]),
                url=str(data.get("url") or data.get("path") or ""),
                api_url=str(data.get("url") or ""),
                raw=data,
            )

        error_message: object = data
        if isinstance(data, dict):
            error_message = data.get("error") or data.get("message") or data
        raise DevToError(f"DEV.to API error {response.status_code}: {error_message}")
