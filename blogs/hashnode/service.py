"""Store-facing Hashnode query helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HashnodeArticleSummary:
    """Small typed summary for Hashnode-specific views."""

    id: str
    title: str
    word_count: int
    updated_at: str
    hashnode_status: str
    hashnode_url: str | None


def _summarise(article: dict) -> HashnodeArticleSummary:
    dest = article.get("destinations", {}).get("hashnode", {})
    return HashnodeArticleSummary(
        id=article["id"],
        title=article["title"],
        word_count=article.get("word_count", 0),
        updated_at=article.get("updated_at", ""),
        hashnode_status=dest.get("status", "none"),
        hashnode_url=dest.get("url"),
    )


def list_drafts(articles: list[dict]) -> list[HashnodeArticleSummary]:
    """Return articles whose Hashnode destination status is draft."""
    return [
        _summarise(article)
        for article in articles
        if article.get("destinations", {}).get("hashnode", {}).get("status") == "draft"
    ]


def list_published(articles: list[dict]) -> list[HashnodeArticleSummary]:
    """Return articles whose Hashnode destination status is published."""
    return [
        _summarise(article)
        for article in articles
        if article.get("destinations", {}).get("hashnode", {}).get("status") == "published"
    ]
