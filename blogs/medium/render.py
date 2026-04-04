"""
Medium HTML render pipeline.

Self-contained: all rendering logic lives inside blogs/medium/ and requires
no external article_publishing package.
"""
from __future__ import annotations

from dataclasses import dataclass

from blogs.medium._import_html import render_medium_import_html as _render_import_html
from blogs.medium._render import render_medium_markdown as _render_markdown


@dataclass(frozen=True)
class RenderedClipboard:
    """HTML body fragment ready for clipboard paste into the Medium editor.

    Uses literal newlines (not ``<br>``) inside ``<pre>`` blocks because
    Medium's paste handler silently truncates articles at ``<br>`` tags
    inside ``<pre>`` when HTML entities such as ``&gt;`` are also present.
    """
    html: str
    title: str | None
    description: str | None


@dataclass(frozen=True)
class RenderedPreview:
    """Full HTML page ready for import into Medium via URL import."""
    html: str
    title: str
    description: str


@dataclass(frozen=True)
class RenderedMarkdown:
    """Normalised Markdown body (front-matter and planning tail stripped)."""
    body_markdown: str
    title: str
    first_image_url: str | None


def render_import_html(
    markdown_text: str,
    *,
    image_base_url: str | None = None,
) -> RenderedPreview:
    """
    Convert raw Markdown into a full HTML document suitable for Medium URL
    import.

    Steps
    -----
    1. ``render_medium_markdown()`` strips planning tail + resolves front-matter.
    2. ``render_medium_import_html()`` converts the cleaned markdown → HTML.

    Parameters
    ----------
    markdown_text:
        Raw article Markdown, may contain front-matter and planning tail.
    image_base_url:
        If given, local image paths (``./…``) are rewritten to absolute URLs
        using this as a prefix.
    """
    rendered_md = _render_markdown(
        markdown_text,
        image_base_url=image_base_url or "",
        strip_planning_tail=True,
    )
    rendered_html = _render_import_html(rendered_md.body_markdown)
    return RenderedPreview(
        html=rendered_html.html,
        title=rendered_html.title,
        description=rendered_html.description,
    )


def render_markdown(
    markdown_text: str,
    *,
    image_base_url: str | None = None,
) -> RenderedMarkdown:
    """
    Return cleaned Markdown (front-matter stripped, planning tail removed).
    """
    result = _render_markdown(
        markdown_text,
        image_base_url=image_base_url or "",
        strip_planning_tail=True,
    )
    return RenderedMarkdown(
        body_markdown=result.body_markdown,
        title=result.title,
        first_image_url=result.first_image_url,
    )


def render_clipboard_html(
    markdown_text: str,
    *,
    image_base_url: str | None = None,
) -> RenderedClipboard:
    """
    Convert raw Markdown into an HTML fragment for clipboard paste into Medium.

    Identical to ``render_import_html`` except ``<pre>`` blocks keep literal
    newlines instead of ``<br>``.  Medium's paste handler truncates articles
    at ``<br>`` inside ``<pre>`` when HTML entities are present (e.g. Cypher
    query arrows rendered as ``&gt;``).
    """
    rendered_md = _render_markdown(
        markdown_text,
        image_base_url=image_base_url or "",
        strip_planning_tail=True,
    )
    rendered_html = _render_import_html(rendered_md.body_markdown, clipboard_mode=True)
    return RenderedClipboard(
        html=rendered_html.html,
        title=rendered_html.title,
        description=rendered_html.description,
    )
