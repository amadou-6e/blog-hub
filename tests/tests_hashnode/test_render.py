"""Tests for Hashnode markdown preparation."""

from __future__ import annotations

from blogs.hashnode.client import HashnodeDraftInput
from blogs.hashnode.render import PreparedHashnodeDraft, prepare_draft, render_markdown


def test_render_markdown_strips_title_and_planning_tail():
    source = """# Title

Intro paragraph.

## Section

Body.

**Tags:** Python, Neo4j
"""

    rendered = render_markdown(source)

    assert rendered.title == "Title"
    assert rendered.body_markdown == "Intro paragraph.\n\n## Section\n\nBody.\n"
    assert rendered.subtitle == "Intro paragraph."


def test_prepare_draft_builds_hashnode_payload():
    source = """# Title

Intro paragraph.
"""

    prepared = prepare_draft(
        source,
        publication_id="pub-1",
        canonical_url="https://example.com/source",
        cover_image_url="https://example.com/cover.png",
        tags=("Python", "Neo4j", "Python"),
    )

    assert isinstance(prepared, PreparedHashnodeDraft)
    assert prepared.draft == HashnodeDraftInput(
        title="Title",
        publication_id="pub-1",
        content_markdown="Intro paragraph.\n",
        canonical_url="https://example.com/source",
        subtitle="Intro paragraph.",
        cover_image_url="https://example.com/cover.png",
        tags=("Python", "Neo4j"),
    )
