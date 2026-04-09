"""
Tests for blogs.medium.service.list_published
"""
import pytest

from blogs.medium.service import list_published, MediumArticleSummary

# Seed data has 1 article with medium status == "published":
#   art_003  "Dockerised Postgres: Production Checklist"
_EXPECTED_PUBLISHED_IDS = {"art_003"}
_EXPECTED_PUBLISHED_COUNT = 1


class TestListPublishedReturnsOnlyPublishedArticles:

    def test_returns_only_medium_published_articles(self, all_articles):
        published = list_published(all_articles)
        assert all(p.medium_status == "published" for p in published)

    def test_published_count_matches_seed(self, all_articles):
        published = list_published(all_articles)
        assert len(published) == _EXPECTED_PUBLISHED_COUNT

    def test_published_ids_match_seed(self, all_articles):
        published = list_published(all_articles)
        assert {p.id for p in published} == _EXPECTED_PUBLISHED_IDS


class TestListPublishedShape:

    def test_returns_medium_article_summary_instances(self, all_articles):
        published = list_published(all_articles)
        assert all(isinstance(p, MediumArticleSummary) for p in published)

    def test_published_has_url(self, all_articles):
        """All published articles must carry a Medium URL."""
        published = list_published(all_articles)
        for p in published:
            assert isinstance(p.medium_url, str) and p.medium_url.startswith("https://")

    def test_each_published_has_id(self, all_articles):
        assert all(p.id for p in list_published(all_articles))

    def test_each_published_has_title(self, all_articles):
        assert all(p.title for p in list_published(all_articles))

    def test_each_published_has_word_count(self, all_articles):
        assert all(isinstance(p.word_count, int) for p in list_published(all_articles))

    def test_each_published_has_updated_at(self, all_articles):
        assert all(p.updated_at for p in list_published(all_articles))


class TestListPublishedEmpty:

    def test_returns_empty_when_no_articles(self):
        assert list_published([]) == []

    def test_returns_empty_when_all_are_drafts(self):
        draft_only = [{
            "id": "x",
            "title": "T",
            "word_count": 200,
            "updated_at": "2026-01-01T00:00:00+00:00",
            "destinations": {
                "medium": {
                    "status": "draft",
                    "url": None
                }
            },
        }]
        assert list_published(draft_only) == []

    def test_excludes_draft_status(self, all_articles):
        # art_001 and art_004 are "draft" — must NOT appear in published
        published = list_published(all_articles)
        ids = {p.id for p in published}
        assert "art_001" not in ids
        assert "art_004" not in ids

    def test_excludes_review_status(self, all_articles):
        published = list_published(all_articles)
        ids = {p.id for p in published}
        assert "art_002" not in ids

    def test_excludes_error_status(self, all_articles):
        published = list_published(all_articles)
        ids = {p.id for p in published}
        assert "art_006" not in ids
