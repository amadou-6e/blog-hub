"""Hashnode render helpers copied into blog-hub to keep it standalone."""

from __future__ import annotations

from dataclasses import dataclass
import re

from blogs.hashnode.client import HashnodeClient, HashnodeDraftInput


PLANNING_MARKERS = (
    "**Tags:**",
    "**Estimated read time:**",
    "**Target keyword:**",
    "**Arc:**",
    "**Repo mention:**",
    "**Title image:**",
    "**Supporting images:**",
    "**CTA:**",
    "**Teaser for next post:**",
    "**Recommended publication:**",
)


@dataclass(frozen=True)
class RenderedMarkdown:
    """Hashnode-ready markdown plus extracted metadata."""

    title: str | None
    body_markdown: str
    subtitle: str | None


@dataclass(frozen=True)
class PreparedHashnodeDraft:
    """Rendered article plus the normalized Hashnode draft payload."""

    rendered: RenderedMarkdown
    draft: HashnodeDraftInput


def render_markdown(
    markdown_text: str,
    *,
    strip_planning_tail: bool = True,
) -> RenderedMarkdown:
    """Convert source Markdown into Hashnode-ready Markdown."""
    normalized = markdown_text.replace("\r\n", "\n")
    title = _extract_title(normalized)
    stripped = _strip_planning_tail(normalized) if strip_planning_tail else normalized
    body_markdown = HashnodeClient.strip_leading_h1(stripped)
    subtitle = _derive_summary_from_markdown(body_markdown)
    return RenderedMarkdown(title=title, body_markdown=body_markdown, subtitle=subtitle)


def prepare_draft(
    markdown_text: str,
    *,
    publication_id: str,
    canonical_url: str | None = None,
    subtitle: str | None = None,
    cover_image_url: str | None = None,
    tags: tuple[str, ...] = (),
) -> PreparedHashnodeDraft:
    """Render markdown and build a Hashnode draft payload."""
    rendered = render_markdown(markdown_text)
    if not rendered.title:
        raise ValueError("Could not determine article title.")
    draft = HashnodeDraftInput(
        title=rendered.title,
        publication_id=publication_id,
        content_markdown=rendered.body_markdown,
        canonical_url=canonical_url,
        subtitle=subtitle or rendered.subtitle,
        cover_image_url=cover_image_url,
        tags=_normalize_tags(tags),
    )
    return PreparedHashnodeDraft(rendered=rendered, draft=draft)


def _extract_title(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _strip_planning_tail(markdown_text: str) -> str:
    cut_index: int | None = None
    lines = markdown_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(PLANNING_MARKERS):
            cut_index = index
            break
    if cut_index is None:
        return markdown_text
    return "\n".join(lines[:cut_index]).rstrip() + "\n"


def _normalize_tags(raw_tags: tuple[str, ...]) -> tuple[str, ...]:
    tags: list[str] = []
    for item in raw_tags:
        normalized = str(item).strip()
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tuple(tags)


def _derive_summary_from_markdown(markdown_text: str, *, max_length: int = 160) -> str | None:
    blocks = re.split(r"\n\s*\n", markdown_text.replace("\r\n", "\n"))
    for block in blocks:
        stripped = block.strip()
        if not stripped or stripped.startswith("#") or stripped == "---" or stripped.startswith("!["):
            continue
        if stripped.startswith("*") and stripped.endswith("*") and "\n" not in stripped:
            continue
        plain = stripped
        plain = re.sub(r"!\[[^\]]*\]\(([^)]+)\)", "", plain)
        plain = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", plain)
        plain = re.sub(r"`([^`]+)`", r"\1", plain)
        plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", plain)
        plain = re.sub(r"\*([^*]+)\*", r"\1", plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        if not plain:
            continue
        if len(plain) <= max_length:
            return plain
        truncated = plain[: max_length - 1].rsplit(" ", 1)[0].strip()
        return (truncated or plain[: max_length - 1]).rstrip(".,;:!?") + "..."
    return None
