"""
Tests for blogs.medium.render.render_import_html (preview pipeline).

Loads sample_article.md, runs it through the render pipeline, and validates
the resulting HTML document against Medium import requirements.
"""
from __future__ import annotations

import os
import re

import pytest

from blogs.medium.render import render_import_html, RenderedPreview

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_SAMPLE_MD = os.path.join(_FIXTURES_DIR, "sample_article.md")
_IMAGE_BASE_URL = "https://cdn.example.com/articles/pgvector"

_PLANNING_MARKERS = [
    "**Tags:**",
    "**Estimated read time:**",
    "**Target keyword:**",
    "**Arc:**",
    "**Repo mention:**",
    "**Title image:**",
]


@pytest.fixture(scope="module")
def sample_markdown():
    with open(_SAMPLE_MD, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def rendered(sample_markdown):
    return render_import_html(sample_markdown, image_base_url=_IMAGE_BASE_URL)


# ─── Return type ─────────────────────────────────────────────────────────────


class TestReturnType:

    def test_returns_rendered_preview(self, rendered):
        assert isinstance(rendered, RenderedPreview)

    def test_html_is_string(self, rendered):
        assert isinstance(rendered.html, str)

    def test_title_is_string(self, rendered):
        assert isinstance(rendered.title, str)

    def test_description_is_string_or_none(self, rendered):
        assert rendered.description is None or isinstance(rendered.description, str)


# ─── HTML document structure ─────────────────────────────────────────────────


class TestHtmlDocumentStructure:

    def test_has_doctype(self, rendered):
        assert "<!DOCTYPE html>" in rendered.html

    def test_has_html_tag(self, rendered):
        assert "<html" in rendered.html

    def test_has_head_tag(self, rendered):
        assert "<head>" in rendered.html or "<head " in rendered.html

    def test_has_body_tag(self, rendered):
        assert "<body>" in rendered.html

    def test_has_article_wrapper(self, rendered):
        assert "<article>" in rendered.html

    def test_title_in_head(self, rendered):
        assert "<title>" in rendered.html

    def test_description_meta_present(self, rendered):
        assert 'name="description"' in rendered.html


# ─── Title extraction ─────────────────────────────────────────────────────────


class TestTitleExtraction:

    def test_title_extracted_from_h1(self, rendered):
        assert "Building a Vector DB from Scratch with pgvector" in rendered.title

    def test_title_in_head_title_tag(self, rendered):
        assert "Building a Vector DB from Scratch with pgvector" in rendered.html

    def test_description_non_empty(self, rendered):
        assert rendered.description  # non-None, non-empty


# ─── Code block normalisation ────────────────────────────────────────────────


class TestCodeBlockNormalisation:

    def test_code_blocks_are_bare_pre_not_pre_code(self, rendered):
        """Medium import requires <pre>…</pre>, not <pre><code>…</code></pre>."""
        assert "<pre><code" not in rendered.html

    def test_pre_tags_present(self, rendered):
        assert "<pre>" in rendered.html

    def test_pre_blocks_have_no_literal_newlines(self, rendered):
        """Literal newlines inside <pre> must be replaced by <br> (variant B, verified working)."""
        blocks = re.findall(r"<pre>([\s\S]*?)</pre>", rendered.html, re.IGNORECASE)
        assert blocks, "Expected at least one <pre> block"
        for inner in blocks:
            assert "\n" not in inner, f"Literal newline found inside <pre> block: {inner[:80]!r}"

    def test_pre_blocks_use_br_for_multiline(self, rendered):
        """Multi-line code blocks must use <br> inside <pre> for Medium import."""
        blocks = re.findall(r"<pre>([\s\S]*?)</pre>", rendered.html, re.IGNORECASE)
        assert any("<br>" in b for b in blocks), "Expected <br> in at least one <pre> block"


# ─── Image normalisation ─────────────────────────────────────────────────────


class TestImageNormalisation:

    def test_images_not_wrapped_in_p(self, rendered):
        """<p><img…> sequences must have been unwrapped."""
        assert not re.search(r"<p>\s*<img", rendered.html, re.IGNORECASE)

    def test_remote_images_pass_through_unchanged(self, rendered):
        assert "https://cdn.example.com/pgvector-bench.png" in rendered.html

    def test_local_images_rewritten_with_base_url(self, rendered):
        """./assets/architecture.png must be rewritten to an absolute URL."""
        # The local path should NOT appear verbatim
        assert "./assets/architecture.png" not in rendered.html
        # An absolute URL derived from image_base_url should appear instead
        assert "https://cdn.example.com/articles/pgvector" in rendered.html


# ─── Planning tail ───────────────────────────────────────────────────────────


class TestPlanningTailStripped:

    def test_tags_marker_not_in_html(self, rendered):
        assert "**Tags:**" not in rendered.html

    def test_estimated_read_time_not_in_html(self, rendered):
        assert "**Estimated read time:**" not in rendered.html

    def test_target_keyword_not_in_html(self, rendered):
        assert "**Target keyword:**" not in rendered.html

    def test_arc_not_in_html(self, rendered):
        assert "**Arc:**" not in rendered.html

    def test_no_planning_marker_in_html(self, rendered):
        for marker in _PLANNING_MARKERS:
            plain = marker.replace("**", "")
            assert plain not in rendered.html, f"Planning marker leaked: {marker!r}"


# ─── Markdown not leaking into HTML ──────────────────────────────────────────


class TestNoRawMarkdown:

    def test_no_raw_double_asterisk_bold(self, rendered):
        """Bold should be rendered as <strong>, not leaked as **text**."""
        # The content bold markers should be gone (planning markers checked above)
        # Only the article body's ** should be converted
        assert "**pgvector**" not in rendered.html
        assert "**actively maintained**" not in rendered.html

    def test_strong_tag_present_for_bold(self, rendered):
        assert "<strong>" in rendered.html

    def test_em_tag_present_for_italic(self, rendered):
        assert "<em>" in rendered.html
