"""
Query helpers over the in-memory article store for Medium-specific views.

These functions are pure: they receive a list of article dicts (as returned
by ``backend.store.memory.list_articles``) and return typed summaries.
No HTTP, no side-effects.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediumArticleSummary:
    id: str
    title: str
    word_count: int
    updated_at: str
    medium_status: str
    medium_url: str | None


def _summarise(article: dict) -> MediumArticleSummary:
    dest = article.get("destinations", {}).get("medium", {})
    return MediumArticleSummary(
        id=article["id"],
        title=article["title"],
        word_count=article.get("word_count", 0),
        updated_at=article.get("updated_at", ""),
        medium_status=dest.get("status", "none"),
        medium_url=dest.get("url"),
    )


def list_drafts(articles: list[dict]) -> list[MediumArticleSummary]:
    """Return articles whose Medium destination status is ``"draft"``."""
    return [
        _summarise(a)
        for a in articles
        if a.get("destinations", {}).get("medium", {}).get("status") == "draft"
    ]


def list_published(articles: list[dict]) -> list[MediumArticleSummary]:
    """Return articles whose Medium destination status is ``"published"``."""
    return [
        _summarise(a)
        for a in articles
        if a.get("destinations", {}).get("medium", {}).get("status") == "published"
    ]
