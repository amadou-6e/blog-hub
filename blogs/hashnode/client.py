"""Thin Hashnode GraphQL client used by blog-hub."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

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


class HashnodeClient:
    """Thin wrapper around the Hashnode draft API."""

    def __init__(self, personal_access_token: str, session: requests.Session | None = None) -> None:
        self._token = personal_access_token
        self._session = session or requests.Session()

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
