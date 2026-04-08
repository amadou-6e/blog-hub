"""Tests for DEV.to markdown preparation."""

from __future__ import annotations

from blogs.devto.client import DevToArticle
from blogs.devto.render import PreparedDevToArticle, prepare_article, render_markdown


def test_render_markdown_strips_planning_tail_and_rewrites_images():
    source = """![Hero](images/title.png)

# Title

Intro paragraph.

![Diagram](images/plot.png)

**Tags:** one, two
**CTA:** stuff
"""

    rendered = render_markdown(
        source,
        image_base_url="https://cdn.example.com/articles/devto",
    )

    assert rendered.title == "Title"
    assert rendered.main_image == "https://cdn.example.com/articles/devto/images/title.png"
    assert rendered.body_markdown == (
        "Intro paragraph.\n\n"
        "![Diagram](https://cdn.example.com/articles/devto/images/plot.png)\n"
    )


def test_prepare_article_builds_normalized_payload():
    source = """# Sample title

Body text that explains the article.
"""

    prepared = prepare_article(
        source,
        tags=("Python", "dev.to", "python"),
        series="Publishing",
        canonical_url="https://example.com/source",
        published=True,
    )

    assert isinstance(prepared, PreparedDevToArticle)
    assert prepared.article == DevToArticle(
        title="Sample title",
        body_markdown="Body text that explains the article.\n",
        published=True,
        series="Publishing",
        main_image=None,
        canonical_url="https://example.com/source",
        description="Body text that explains the article.",
        tags=("python", "dev.to"),
    )
