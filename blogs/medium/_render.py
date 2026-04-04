"""Render local article Markdown into Medium-ready Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Inline copy of PLANNING_MARKERS (originally in article_publishing.publishing.devto_render).
# Update here if the planning section format changes.
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
class RenderedMediumArticle:
    """Medium-ready article body plus extracted metadata."""

    body_markdown: str
    title: str | None
    first_image_url: str | None


def render_medium_markdown(
    markdown_text: str,
    *,
    image_base_url: str | None = None,
    strip_planning_tail: bool = True,
) -> RenderedMediumArticle:
    """Convert a source article into Medium-ready Markdown with hosted images."""
    title = _extract_title(markdown_text)
    text = markdown_text.replace("\r\n", "\n")
    text = _strip_planning_tail(text) if strip_planning_tail else text
    text = _rewrite_local_images(text, image_base_url=image_base_url)
    text = _move_leading_image_below_title(text)
    text = _normalize_spacing(text)
    return RenderedMediumArticle(
        body_markdown=text,
        title=title,
        first_image_url=_extract_first_image_url(text),
    )


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


def _rewrite_local_images(markdown_text: str, *, image_base_url: str | None) -> str:
    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

    def replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        image_url = _rewrite_image_url(match.group(2), image_base_url=image_base_url)
        return f"![{alt_text}]({image_url})"

    return pattern.sub(replace, markdown_text)


def _rewrite_image_url(image_url: str, *, image_base_url: str | None) -> str:
    if image_url.startswith(("http://", "https://")):
        return image_url
    if image_base_url is None:
        return image_url
    normalized_base = image_base_url.rstrip("/")
    normalized_path = image_url.lstrip("./").replace("\\", "/")
    return f"{normalized_base}/{normalized_path}"


def _extract_first_image_url(markdown_text: str) -> str | None:
    match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text)
    if match is None:
        return None
    return match.group(1)


def _move_leading_image_below_title(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    first_content_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip():
            first_content_index = index
            break
    if first_content_index is None:
        return markdown_text

    first_content = lines[first_content_index].strip()
    image_match = re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", first_content)
    if image_match is None:
        return markdown_text

    next_content_index: int | None = None
    for index in range(first_content_index + 1, len(lines)):
        if lines[index].strip():
            next_content_index = index
            break
    if next_content_index is None:
        return markdown_text
    if not lines[next_content_index].strip().startswith("# "):
        return markdown_text

    image_line = lines[first_content_index]
    remaining_lines = lines[:first_content_index] + lines[first_content_index + 1:]

    insertion_index = next_content_index
    for index in range(next_content_index + 1, len(remaining_lines)):
        stripped = remaining_lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("*") and stripped.endswith("*"):
            insertion_index = index
        break

    updated_lines = remaining_lines[:insertion_index + 1]
    updated_lines.extend(["", image_line, ""])
    updated_lines.extend(remaining_lines[insertion_index + 1:])
    return "\n".join(updated_lines)


def _normalize_spacing(markdown_text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", markdown_text)
    return text.strip() + "\n"
