"""Thin Hashnode GraphQL client used by blog-hub."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any
from urllib.parse import urlparse

import requests


class HashnodeError(RuntimeError):
    """Raised when the Hashnode API returns an error payload."""


@dataclass(frozen=True)
class HashnodeDraftInput:
    """Normalized Hashnode draft payload."""

    title: str
    publication_id: str
    content_markdown: str
    canonical_url: str | None = None
    subtitle: str | None = None
    cover_image_url: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class HashnodeDraftResult:
    """Small subset of the created draft result."""

    draft_id: str
    title: str | None
    canonical_url: str | None
    cover_image_url: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class HashnodeRemoteArticle:
    """Normalized Hashnode article payload returned by draft/post queries."""

    article_id: str
    title: str
    url: str | None
    canonical_url: str | None
    subtitle: str | None
    body_markdown: str
    published: bool
    updated_at: datetime | None
    cover_image_url: str | None
    raw: dict[str, Any]


class HashnodeClient:
    """Thin wrapper around the Hashnode draft API."""

    def __init__(self, personal_access_token: str, session: requests.Session | None = None) -> None:
        self._token = personal_access_token
        self._session = session or requests.Session()
        if session is None:
            self._session.trust_env = False

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": self._token,
        }

    def create_draft(self, draft: HashnodeDraftInput) -> HashnodeDraftResult:
        mutation = """
        mutation CreateDraft($input: CreateDraftInput!) {
          createDraft(input: $input) {
            draft {
              id
              title
              canonicalUrl
              coverImage {
                url
              }
            }
          }
        }
        """
        response = self._session.post(
            "https://gql.hashnode.com",
            headers=self.headers,
            json={"query": mutation, "variables": {"input": self._draft_payload(draft)}},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        errors = data.get("errors")
        if errors:
            raise HashnodeError(str(errors))

        draft_data = data["data"]["createDraft"]["draft"]
        cover_image = draft_data.get("coverImage") or {}
        return HashnodeDraftResult(
            draft_id=str(draft_data["id"]),
            title=draft_data.get("title"),
            canonical_url=draft_data.get("canonicalUrl"),
            cover_image_url=cover_image.get("url"),
            raw=data,
        )

    def get_draft_by_id(self, draft_id: str) -> HashnodeRemoteArticle | None:
        """Fetch a single draft by its ID directly from the Hashnode API."""
        query = """
        query GetDraft($id: ObjectId!) {
          draft(id: $id) {
            id
            title
            subtitle
            canonicalUrl
            dateUpdated
            coverImage {
              url
            }
            publication {
              url
            }
            content {
              markdown
            }
          }
        }
        """
        payload = self._graphql(query, {"id": draft_id})
        node = (payload.get("data") or {}).get("draft")
        if not node:
            return None
        return self._remote_article_payload(node, published=False)

    def list_drafts(self, *, first: int = 20) -> list[HashnodeRemoteArticle]:
        return self.list_all_drafts(page_size=first, max_pages=1)

    def list_all_drafts(self, *, page_size: int = 20, max_pages: int = 100) -> list[HashnodeRemoteArticle]:
        """Fetch all drafts using cursor-based pagination. Max page_size is 20 (Hashnode limit)."""
        page_size = min(page_size, 20)  # Hashnode enforces max 20 per page
        query = """
        query MeDraftsPage($first: Int!, $after: String) {
          me {
            drafts(first: $first, after: $after) {
              pageInfo { hasNextPage endCursor }
              edges {
                node {
                  id
                  title
                  subtitle
                  canonicalUrl
                  dateUpdated
                  coverImage {
                    url
                  }
                  publication {
                    url
                  }
                  content {
                    markdown
                  }
                }
              }
            }
          }
        }
        """
        results: list[HashnodeRemoteArticle] = []
        after: str | None = None
        for _ in range(max_pages):
            payload = self._graphql(query, {"first": page_size, "after": after})
            drafts_data = payload["data"]["me"]["drafts"]
            results.extend(
                self._remote_article_payload(edge["node"], published=False)
                for edge in drafts_data["edges"]
            )
            page_info = drafts_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
            if not after:
                break
        return results

    def list_published_articles(
        self,
        *,
        publication_first: int = 10,
        post_first: int = 20,
    ) -> list[HashnodeRemoteArticle]:
        articles: list[HashnodeRemoteArticle] = []
        for publication in self.list_publications(first=publication_first):
            host = _publication_host(publication["url"])
            if not host:
                continue
            query = """
            query PublicationPosts($host: String!, $first: Int!) {
              publication(host: $host) {
                posts(first: $first) {
                  edges {
                    node {
                      id
                      title
                      subtitle
                      canonicalUrl
                      url
                      publishedAt
                      coverImage {
                        url
                      }
                      content {
                        markdown
                      }
                    }
                  }
                }
              }
            }
            """
            payload = self._graphql(query, {"host": host, "first": post_first})
            edges = (((payload.get("data") or {}).get("publication") or {}).get("posts") or {}).get(
                "edges",
                [],
            )
            articles.extend(
                self._remote_article_payload(edge["node"], published=True)
                for edge in edges
            )
        return articles

    def list_publications(self, *, first: int = 10) -> list[dict[str, str]]:
        query = """
        query MePublications($first: Int!) {
          me {
            publications(first: $first) {
              edges {
                node {
                  id
                  title
                  url
                }
              }
            }
          }
        }
        """
        payload = self._graphql(query, {"first": first})
        return [edge["node"] for edge in payload["data"]["me"]["publications"]["edges"]]

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(
            "https://gql.hashnode.com",
            headers=self.headers,
            json={"query": query, "variables": variables},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        errors = data.get("errors")
        if errors:
            raise HashnodeError(str(errors))
        return data

    @staticmethod
    def strip_leading_h1(markdown_text: str) -> str:
        """Remove the leading H1 to avoid a duplicate title in Hashnode."""
        text = markdown_text.replace("\r\n", "\n")
        lines = text.splitlines()
        first_content_index = next((index for index, line in enumerate(lines) if line.strip()), None)
        if first_content_index is None:
            return text
        if not lines[first_content_index].strip().startswith("# "):
            return text
        remaining_lines = lines[first_content_index + 1 :]
        while remaining_lines and not remaining_lines[0].strip():
            remaining_lines.pop(0)
        return "\n".join(remaining_lines).strip() + "\n"

    @staticmethod
    def slugify_tag(tag_name: str) -> str:
        """Convert source tags into a Hashnode-compatible slug."""
        normalized = re.sub(r"[^a-z0-9]+", "-", tag_name.lower()).strip("-")
        return normalized or "tag"

    def _draft_payload(self, draft: HashnodeDraftInput) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": draft.title,
            "publicationId": draft.publication_id,
            "contentMarkdown": draft.content_markdown,
            "tags": [
                {"name": tag_name, "slug": self.slugify_tag(tag_name)}
                for tag_name in draft.tags
            ],
        }
        if draft.subtitle:
            payload["subtitle"] = draft.subtitle
        if draft.canonical_url:
            payload["originalArticleURL"] = draft.canonical_url
        if draft.cover_image_url:
            payload["coverImageOptions"] = {"coverImageURL": draft.cover_image_url}
        return payload

    @staticmethod
    def _remote_article_payload(payload: dict[str, Any], *, published: bool) -> HashnodeRemoteArticle:
        cover_image = payload.get("coverImage") or {}
        publication = payload.get("publication") or {}
        article_url = _optional_string(payload.get("url"))
        if not article_url and not published:
            publication_url = _optional_string(publication.get("url"))
            draft_id = _optional_string(payload.get("id"))
            if publication_url and draft_id:
                article_url = publication_url.rstrip("/") + "/preview/" + draft_id
        content = payload.get("content") or {}
        updated_at = (
            _parse_datetime(payload.get("dateUpdated"))
            or _parse_datetime(payload.get("publishedAt"))
            or _parse_datetime(payload.get("updatedAt"))
        )
        return HashnodeRemoteArticle(
            article_id=str(payload["id"]),
            title=str(payload.get("title") or ""),
            url=article_url,
            canonical_url=_optional_string(payload.get("canonicalUrl")),
            subtitle=_optional_string(payload.get("subtitle")),
            body_markdown=str(content.get("markdown") or ""),
            published=published,
            updated_at=updated_at,
            cover_image_url=_optional_string(cover_image.get("url")),
            raw=payload,
        )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(raw_value: object) -> datetime | None:
    value = _optional_string(raw_value)
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _publication_host(publication_url: str | None) -> str | None:
    if not publication_url:
        return None
    parsed = urlparse(publication_url)
    host = (parsed.netloc or "").strip()
    return host or None
