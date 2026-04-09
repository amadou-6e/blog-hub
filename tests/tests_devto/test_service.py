"""Tests for DEV.to store-facing service helpers."""

from __future__ import annotations

from blogs.devto.service import DevToArticleSummary, list_drafts, list_published


def test_list_drafts_returns_only_devto_drafts(all_articles):
    drafts = list_drafts(all_articles)
    assert {draft.id for draft in drafts} == {"art_001"}
    assert all(isinstance(draft, DevToArticleSummary) for draft in drafts)
    assert all(draft.devto_status == "draft" for draft in drafts)


def test_list_published_returns_only_devto_published(all_articles):
    published = list_published(all_articles)
    assert {article.id for article in published} == {"art_003"}
    assert all(isinstance(article, DevToArticleSummary) for article in published)
    assert all(article.devto_status == "published" for article in published)
