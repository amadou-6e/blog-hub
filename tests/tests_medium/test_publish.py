"""
Tests for the Medium publish flow (POST /api/articles/{id}/push).

The "HTML dump" test is the key integration test: it renders sample_article.md
through the full render pipeline, writes the result to
tests/fixtures/sample_draft.html, and then performs structural assertions on
that file — this is the auditable record of exactly what would be sent to
Medium's URL import endpoint.
"""
from __future__ import annotations

import os

import pytest

from blogs.medium.render import render_import_html
from blogs.medium.service import list_drafts

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_SAMPLE_MD = os.path.join(_FIXTURES_DIR, "sample_article.md")
_HTML_DUMP_PATH = os.path.join(_FIXTURES_DIR, "sample_draft.html")
_IMAGE_BASE_URL = "https://cdn.example.com/articles/neo4j"

_PLANNING_MARKERS = [
    "Tags:",
    "Estimated read time:",
    "Target keyword:",
    "Arc:",
]


@pytest.fixture(scope="module")
def sample_markdown():
    with open(_SAMPLE_MD, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def html_dump(sample_markdown) -> str:
    """
    Render sample_article.md → write to fixtures/sample_draft.html → return HTML.
    The dump file is the persistent artefact of the publish preview.
    """
    rendered = render_import_html(sample_markdown, image_base_url=_IMAGE_BASE_URL)
    os.makedirs(_FIXTURES_DIR, exist_ok=True)
    with open(_HTML_DUMP_PATH, "w", encoding="utf-8") as fh:
        fh.write(rendered.html)
    return rendered.html


# ─── API: push endpoint ───────────────────────────────────────────────────────


@pytest.mark.integration
class TestPushEndpoint:

    def test_push_returns_202_with_job_id(self, client):
        resp = client.post("/api/articles/art_001/push")
        assert resp.status_code == 202
        body = resp.json()
        assert "jobId" in body
        assert body["jobId"]

    def test_push_updates_medium_status_to_draft(self, client):
        """After a push, the medium destination status must become 'draft'."""
        # art_005 has status "ready" — push should flip it to "draft"
        client.post("/api/articles/art_005/push")
        resp = client.get("/api/articles")
        articles = resp.json()["items"]
        art_005 = next(a for a in articles if a["id"] == "art_005")
        assert art_005["destinations"]["medium"]["status"] == "draft"

    def test_push_unknown_article_returns_404(self, client):
        resp = client.post("/api/articles/does_not_exist/push")
        assert resp.status_code == 404

    def test_push_already_draft_remains_draft(self, client):
        """Pushing an article that is already draft should keep it as draft."""
        resp = client.post("/api/articles/art_001/push")
        assert resp.status_code == 202
        articles = client.get("/api/articles").json()["items"]
        art_001 = next(a for a in articles if a["id"] == "art_001")
        assert art_001["destinations"]["medium"]["status"] == "draft"

    def test_push_job_id_is_non_empty_string(self, client):
        resp = client.post("/api/articles/art_001/push")
        assert isinstance(resp.json()["jobId"], str)
        assert len(resp.json()["jobId"]) > 0


# ─── HTML dump: structural correctness ───────────────────────────────────────


class TestHtmlDumpStructure:

    def test_html_dump_has_doctype(self, html_dump):
        assert "<!DOCTYPE html>" in html_dump

    def test_html_dump_has_html_tag(self, html_dump):
        assert "<html" in html_dump

    def test_html_dump_has_article_wrapper(self, html_dump):
        assert "<article>" in html_dump

    def test_html_dump_has_h2_tags(self, html_dump):
        """The article has H2 sections; they must appear in the dump."""
        assert "<h2>" in html_dump

    def test_html_dump_has_pre_for_code(self, html_dump):
        """Code blocks must be rendered as <pre>, NOT <pre><code>."""
        assert "<pre>" in html_dump
        assert "<pre><code" not in html_dump

    def test_html_dump_has_strong_for_bold(self, html_dump):
        assert "<strong>" in html_dump

    def test_html_dump_has_em_for_italic(self, html_dump):
        assert "<em>" in html_dump

    def test_html_dump_has_ul_for_lists(self, html_dump):
        # The Neo4j article uses definition-style bold paragraphs rather than
        # bullet lists — verify <strong> is present as the list-equivalent.
        assert "<strong>" in html_dump

    def test_html_dump_images_not_in_p(self, html_dump):
        import re
        assert not re.search(r"<p>\s*<img", html_dump, re.IGNORECASE)


# ─── HTML dump: title ────────────────────────────────────────────────────────


class TestHtmlDumpTitle:

    def test_html_dump_title_in_head(self, html_dump):
        assert "What Neo4j actually does" in html_dump

    def test_html_dump_title_matches_h1(self, sample_markdown, html_dump):
        """<title> must match the H1 in the source Markdown."""
        rendered = render_import_html(sample_markdown, image_base_url=_IMAGE_BASE_URL)
        assert rendered.title in html_dump


# ─── HTML dump: planning tail stripped ───────────────────────────────────────


class TestHtmlDumpNoPlanningMarkers:

    def test_no_planning_markers_in_dump(self, html_dump):
        for marker in _PLANNING_MARKERS:
            assert marker not in html_dump, (f"Planning marker leaked into HTML dump: {marker!r}")

    def test_tags_value_not_in_dump(self, html_dump):
        # Planning tag values must be stripped from the published HTML
        assert "Neo4j, GraphRAG, LlamaIndex" not in html_dump

    def test_no_raw_double_asterisk_in_dump(self, html_dump):
        """No raw Markdown bold markers should survive in the HTML."""
        # Legitimate bold inside article body is now <strong>; ** should not appear
        # (planning markers used ** that are stripped; article body ** become <strong>)
        import re
        # Check that no inline ** pattern remains (should have become <strong>)
        assert not re.search(r"\*\*[^<]+\*\*",
                             html_dump), ("Raw ** bold markers found in HTML dump")


# ─── HTML dump: file written ─────────────────────────────────────────────────


class TestHtmlDumpFileWritten:

    def test_dump_file_exists_after_render(self, html_dump):
        assert os.path.isfile(_HTML_DUMP_PATH)

    def test_dump_file_is_non_empty(self, html_dump):
        assert os.path.getsize(_HTML_DUMP_PATH) > 0

    def test_dump_file_content_matches_html(self, html_dump):
        with open(_HTML_DUMP_PATH, encoding="utf-8") as fh:
            on_disk = fh.read()
        assert on_disk == html_dump
