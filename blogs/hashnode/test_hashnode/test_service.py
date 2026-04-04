"""Tests for Hashnode store-facing service helpers."""

from __future__ import annotations

from blogs.hashnode.service import HashnodeArticleSummary, list_drafts, list_published


def test_list_drafts_returns_only_hashnode_drafts(all_articles):
    drafts = list_drafts(all_articles)
    assert {draft.id for draft in drafts} == {"art_002", "art_006"}
    assert all(isinstance(draft, HashnodeArticleSummary) for draft in drafts)
    assert all(draft.hashnode_status == "draft" for draft in drafts)


def test_list_published_returns_only_hashnode_published(all_articles):
    published = list_published(all_articles)
    assert {article.id for article in published} == {"art_003"}
    assert all(isinstance(article, HashnodeArticleSummary) for article in published)
    assert all(article.hashnode_status == "published" for article in published)
