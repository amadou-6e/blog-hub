"""
Tests for blogs.medium.service.list_drafts
"""
import pytest

from blogs.medium.service import list_drafts, MediumArticleSummary

# Seed data has 2 articles with medium status == "draft":
#   art_001  "Building a Vector DB from Scratch with pgvector"
#   art_004  "Graph Neural Networks: A Practical Intro"
_EXPECTED_DRAFT_IDS = {"art_001", "art_004"}
_EXPECTED_DRAFT_COUNT = 2


class TestListDraftReturnsOnlyDraftArticles:

    def test_returns_only_medium_draft_articles(self, all_articles):
        drafts = list_drafts(all_articles)
        assert all(d.medium_status == "draft" for d in drafts)

    def test_draft_count_matches_seed(self, all_articles):
        drafts = list_drafts(all_articles)
        assert len(drafts) == _EXPECTED_DRAFT_COUNT

    def test_draft_ids_match_seed(self, all_articles):
        drafts = list_drafts(all_articles)
        assert {d.id for d in drafts} == _EXPECTED_DRAFT_IDS


class TestListDraftsShape:

    def test_returns_medium_article_summary_instances(self, all_articles):
        drafts = list_drafts(all_articles)
        assert all(isinstance(d, MediumArticleSummary) for d in drafts)

    def test_each_draft_has_id(self, all_articles):
        drafts = list_drafts(all_articles)
        assert all(d.id for d in drafts)

    def test_each_draft_has_title(self, all_articles):
        drafts = list_drafts(all_articles)
        assert all(d.title for d in drafts)

    def test_each_draft_has_word_count(self, all_articles):
        drafts = list_drafts(all_articles)
        assert all(isinstance(d.word_count, int) for d in drafts)

    def test_each_draft_has_updated_at(self, all_articles):
        drafts = list_drafts(all_articles)
        assert all(d.updated_at for d in drafts)

    def test_draft_url_is_none_or_string(self, all_articles):
        drafts = list_drafts(all_articles)
        for d in drafts:
            assert d.medium_url is None or isinstance(d.medium_url, str)


class TestListDraftsEmpty:

    def test_returns_empty_when_no_drafts(self):
        """No articles in the list → no drafts."""
        assert list_drafts([]) == []

    def test_returns_empty_when_all_are_published(self):
        non_drafts = [{
            "id": "x",
            "title": "T",
            "word_count": 100,
            "updated_at": "2026-01-01T00:00:00+00:00",
            "destinations": {
                "medium": {
                    "status": "published",
                    "url": "http://example.com"
                }
            },
        }]
        assert list_drafts(non_drafts) == []

    def test_excludes_review_status(self, all_articles):
        # art_002 has medium status "review" — must NOT appear in drafts
        drafts = list_drafts(all_articles)
        ids = {d.id for d in drafts}
        assert "art_002" not in ids

    def test_excludes_ready_status(self, all_articles):
        # art_005 has medium status "ready" — must NOT appear in drafts
        drafts = list_drafts(all_articles)
        ids = {d.id for d in drafts}
        assert "art_005" not in ids

    def test_excludes_error_status(self, all_articles):
        # art_006 has medium status "error" — must NOT appear in drafts
        drafts = list_drafts(all_articles)
        ids = {d.id for d in drafts}
        assert "art_006" not in ids
