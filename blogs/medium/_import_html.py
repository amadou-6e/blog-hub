"""Render Medium-ready Markdown into a public HTML import artifact."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import importlib.util
import re

from markdown_it import MarkdownIt


@dataclass(frozen=True)
class RenderedMediumImportHtml:
    """Public HTML artifact for Medium URL import."""

    html: str
    title: str | None
    description: str | None


def render_medium_import_html(
    markdown_text: str,
    *,
    clipboard_mode: bool = False,
) -> RenderedMediumImportHtml:
    """Convert Medium-ready Markdown into a styled HTML page for Medium import.

    Parameters
    ----------
    clipboard_mode:
        When True, ``<pre>`` blocks keep literal newlines instead of
        converting them to ``<br>``.  Use this when the HTML will be pasted
        via the clipboard — Medium's paste handler chokes on ``<br>`` inside
        ``<pre>`` and silently truncates the article at that point.
        When False (default), ``<br>`` is used, which is verified working for
        Medium URL import.
    """
    normalized_markdown = markdown_text.replace("\r\n", "\n").strip() + "\n"
    title = _extract_title(normalized_markdown)
    description = _derive_summary_from_markdown(normalized_markdown)
    body_html = _markdown_to_html(normalized_markdown, clipboard_mode=clipboard_mode)
    html = _wrap_html_document(
        body_html=body_html,
        title=title or "Article",
        description=description or "",
    )
    return RenderedMediumImportHtml(
        html=html,
        title=title,
        description=description,
    )


def _extract_title(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _derive_summary_from_markdown(markdown_text: str, *, max_length: int = 160) -> str | None:
    blocks = re.split(r"\n\s*\n", markdown_text.replace("\r\n", "\n"))
    for block in blocks:
        stripped = block.strip()
        if not stripped or stripped.startswith("#") or stripped == "---" or stripped.startswith(
                "!["):
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
        truncated = plain[:max_length - 1].rsplit(" ", 1)[0].strip()
        return (truncated or plain[:max_length - 1]).rstrip(".,;:!?") + "…"
    return None


def _wrap_html_document(*, body_html: str, title: str, description: str) -> str:
    safe_title = escape(title)
    safe_description = escape(description)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <meta name="description" content="{safe_description}">
</head>
<body>
  <article>
{body_html}
  </article>
</body>
</html>
"""


def _markdown_to_html(markdown_text: str, *, clipboard_mode: bool = False) -> str:
    enable_linkify = importlib.util.find_spec("linkify_it") is not None
    renderer = MarkdownIt(
        "default",
        {
            "html": True,
            "linkify": enable_linkify,
            "typographer": True,
        },
    )
    html = renderer.render(markdown_text).strip()
    return _normalize_medium_import_html(html, clipboard_mode=clipboard_mode)


def _normalize_medium_import_html(html: str, *, clipboard_mode: bool = False) -> str:
    # Medium URL import is sensitive to rich source DOM. Keep structure minimal.
    normalized = html
    normalized = re.sub(r"<p>\s*(<img\b[^>]*>)\s*</p>", r"\1", normalized, flags=re.IGNORECASE)

    def replace_pre_code(match: re.Match[str]) -> str:
        code_content = match.group(2)
        return f"<pre>{code_content}</pre>"

    normalized = re.sub(
        r"<pre>\s*<code\b([^>]*)>([\s\S]*?)</code>\s*</pre>",
        replace_pre_code,
        normalized,
        flags=re.IGNORECASE,
    )

    def replace_pre_newlines(match: re.Match[str]) -> str:
        inner = match.group(1).strip("\n")
        if not clipboard_mode:
            # Verified working for Medium URL import: <br> preserves multiline code.
            # Do NOT use for clipboard paste — Medium's paste handler truncates at <br>
            # inside <pre> when the block also contains HTML entities (e.g. &gt;).
            inner = inner.replace("\n", "<br>")
        return f"<pre>{inner}</pre>"

    normalized = re.sub(
        r"<pre>([\s\S]*?)</pre>",
        replace_pre_newlines,
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized
