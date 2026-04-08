"""Store-facing DEV.to query helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DevToArticleSummary:
    """Small typed summary for DEV.to-specific views."""

    id: str
    title: str
    word_count: int
    updated_at: str
    devto_status: str
    devto_url: str | None


def _summarise(article: dict) -> DevToArticleSummary:
    dest = article.get("destinations", {}).get("devto", {})
    return DevToArticleSummary(
        id=article["id"],
        title=article["title"],
        word_count=article.get("word_count", 0),
        updated_at=article.get("updated_at", ""),
        devto_status=dest.get("status", "none"),
        devto_url=dest.get("url"),
    )


def list_drafts(articles: list[dict]) -> list[DevToArticleSummary]:
    """Return articles whose DEV.to destination status is draft."""
    return [
        _summarise(article)
        for article in articles
        if article.get("destinations", {}).get("devto", {}).get("status") == "draft"
    ]


def list_published(articles: list[dict]) -> list[DevToArticleSummary]:
    """Return articles whose DEV.to destination status is published."""
    return [
        _summarise(article)
        for article in articles
        if article.get("destinations", {}).get("devto", {}).get("status") == "published"
    ]
