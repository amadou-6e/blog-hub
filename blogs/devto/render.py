"""DEV.to render helpers copied into blog-hub to keep it standalone."""

from __future__ import annotations

from dataclasses import dataclass
import re

from blogs.devto.client import DevToArticle


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
    """DEV.to-ready article body plus extracted metadata."""

    body_markdown: str
    title: str | None
    main_image: str | None


@dataclass(frozen=True)
class PreparedDevToArticle:
    """Rendered article plus the normalized DEV.to publish payload."""

    rendered: RenderedMarkdown
    article: DevToArticle


def render_markdown(
    markdown_text: str,
    *,
    image_base_url: str | None = None,
    strip_planning_tail: bool = True,
) -> RenderedMarkdown:
    """Convert source Markdown into DEV.to-ready Markdown."""
    title = _extract_title(markdown_text)
    text = markdown_text.replace("\r\n", "\n")
    text = _strip_planning_tail(text) if strip_planning_tail else text
    main_image = _extract_title_image(text, image_base_url=image_base_url)
    text = _remove_title_image(text)
    text = _remove_leading_title_heading(text)
    text = _rewrite_local_images(text, image_base_url=image_base_url)
    text = _normalize_spacing(text)
    return RenderedMarkdown(body_markdown=text, title=title, main_image=main_image)


def prepare_article(
    markdown_text: str,
    *,
    title: str | None = None,
    tags: tuple[str, ...] = (),
    series: str | None = None,
    canonical_url: str | None = None,
    description: str | None = None,
    image_base_url: str | None = None,
    main_image: str | None = None,
    published: bool = False,
) -> PreparedDevToArticle:
    """Render markdown and build a DEV.to article payload."""
    rendered = render_markdown(markdown_text, image_base_url=image_base_url)
    final_title = title or rendered.title
    if not final_title:
        raise ValueError("Could not determine article title.")
    article = DevToArticle(
        title=final_title,
        body_markdown=rendered.body_markdown,
        published=published,
        series=series,
        main_image=main_image or rendered.main_image,
        canonical_url=canonical_url,
        description=description or _derive_description(rendered.body_markdown),
        tags=_normalize_tags(tags),
    )
    return PreparedDevToArticle(rendered=rendered, article=article)


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


def _extract_title_image(markdown_text: str, *, image_base_url: str | None) -> str | None:
    lines = markdown_text.splitlines()
    first_non_empty = next((line.strip() for line in lines if line.strip()), "")
    match = re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", first_non_empty)
    if match is None:
        return None
    return _rewrite_image_url(match.group(1), image_base_url=image_base_url)


def _remove_title_image(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    first_content_index = _first_content_index(lines)
    if first_content_index is None:
        return markdown_text
    first_content = lines[first_content_index].strip()
    if not re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", first_content):
        return markdown_text
    remaining_lines = lines[first_content_index + 1 :]
    while remaining_lines and not remaining_lines[0].strip():
        remaining_lines.pop(0)
    return "\n".join(remaining_lines).rstrip() + "\n"


def _remove_leading_title_heading(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    first_content_index = _first_content_index(lines)
    if first_content_index is None:
        return markdown_text
    if not lines[first_content_index].strip().startswith("# "):
        return markdown_text
    remaining_lines = lines[first_content_index + 1 :]
    while remaining_lines and not remaining_lines[0].strip():
        remaining_lines.pop(0)
    return "\n".join(remaining_lines).rstrip() + "\n"


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
    if not image_base_url:
        return image_url
    normalized_base = image_base_url.rstrip("/")
    normalized_path = image_url.lstrip("./").replace("\\", "/")
    return f"{normalized_base}/{normalized_path}"


def _normalize_spacing(markdown_text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", markdown_text).strip() + "\n"


def _normalize_tags(raw_tags: tuple[str, ...]) -> tuple[str, ...]:
    tags: list[str] = []
    for item in raw_tags:
        normalized = str(item).strip().lower()
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tuple(tags)


def _derive_description(markdown_text: str, *, max_length: int = 160) -> str | None:
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


def _first_content_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return None
