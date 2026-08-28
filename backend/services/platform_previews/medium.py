"""Deterministic Medium-like live preview renderer."""
from __future__ import annotations

import html
import re

from blogs.medium.render import render_markdown
from backend.schemas.previews import (
    PreviewArtifact,
    PreviewCapabilities,
    PreviewPlatform,
    PreviewRenderRequest,
    PreviewSource,
    PreviewState,
    PreviewViewport,
    PreviewWarning,
)
from backend.services.platform_previews.engine import preview_document, render_markdown_fragment


MEDIUM_CSS = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fff;color:#242424;
font-family:sohne,Inter,ui-sans-serif,system-ui,sans-serif}.site-header{height:57px;border-bottom:1px solid #e6e6e6;
display:flex;align-items:center;padding:0 max(24px,calc((100% - 1192px)/2));gap:22px;background:#fff}.wordmark{font-family:
Georgia,'Times New Roman',serif;font-size:30px;font-weight:700;line-height:1}.search{height:38px;width:220px;border-radius:20px;
background:#f2f2f2;color:#6b6b6b;padding:10px 16px;font-size:13px}.header-actions{margin-left:auto;display:flex;align-items:center;
gap:18px;color:#6b6b6b;font-size:13px}.write{color:#242424}.page{width:min(740px,100%);margin:0 auto;padding:54px 30px 90px}
.article-title{font-family:Georgia,'Times New Roman',serif;font-size:46px;line-height:1.12;letter-spacing:0;font-weight:700;
margin:0 0 14px;color:#242424}.subtitle{font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.4;
color:#6b6b6b;margin:0 0 28px}.byline{display:flex;align-items:center;gap:12px;font-size:13px;color:#6b6b6b}.avatar{width:42px;
height:42px;border-radius:50%;background:#1a8917;color:#fff;display:grid;place-items:center;font-weight:600}.author{color:#242424;
margin-bottom:3px}.actions{height:52px;border-top:1px solid #e6e6e6;border-bottom:1px solid #e6e6e6;margin:30px 0 36px;
display:flex;align-items:center;gap:24px;color:#6b6b6b;font-size:13px}.actions .right{margin-left:auto}.content{font-family:
Georgia,'Times New Roman',serif;font-size:20px;line-height:1.65;color:#242424}.content h1,.content h2,.content h3{
font-family:Georgia,'Times New Roman',serif;line-height:1.18;color:#242424;letter-spacing:0}.content h1{font-size:34px}
.content h2{font-size:30px;margin:1.7em 0 .55em}.content h3{font-size:24px;margin:1.5em 0 .5em}.content p,
.content ul,.content ol,.content blockquote,.content pre,.content table{margin:0 0 1.45em}.content a{color:inherit;text-decoration:underline}
.content img{display:block;width:auto;max-width:min(100%,900px);height:auto;margin:2.2em auto}.content blockquote{border-left:3px solid #242424;
margin-left:-20px;padding:.1em 0 .1em 20px;font-size:22px;font-style:italic}.content pre{overflow:auto;background:#f2f2f2;
padding:17px 20px}.content code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82em}.content table{width:100%;
border-collapse:collapse;font-family:sohne,Inter,ui-sans-serif,system-ui,sans-serif;font-size:14px}.content th,.content td{
border-bottom:1px solid #d9d9d9;padding:10px 8px;text-align:left}@media(max-width:640px){.site-header{height:52px;padding:0 16px}
.search,.write{display:none}.wordmark{font-size:26px}.page{padding:34px 20px 60px}.article-title{font-size:36px}.subtitle{font-size:19px}
.content{font-size:18px;line-height:1.68}.content h2{font-size:26px}.content blockquote{margin-left:0}.actions{margin-top:24px}}
"""


def _without_first_title(markdown: str) -> str:
    return re.sub(r"(?m)^#\s+[^\n]+\n?", "", markdown, count=1).lstrip()


class MediumPreviewProvider:
    capabilities = PreviewCapabilities(
        platform=PreviewPlatform.medium,
        renderer_version="medium-1",
        viewports=[PreviewViewport.desktop, PreviewViewport.mobile],
    )

    def render(
        self,
        request: PreviewRenderRequest,
        *,
        source: PreviewSource,
        asset_base_url: str,
    ) -> PreviewArtifact:
        normalized = render_markdown(request.content, image_base_url=asset_base_url)
        body_markdown = _without_first_title(normalized.body_markdown)
        body, warnings = render_markdown_fragment(body_markdown, asset_base_url)
        if body_markdown.strip() != request.content.strip():
            warnings.append(PreviewWarning(
                code="medium_content_normalized",
                message="Title or publishing notes were moved out of the Medium article body.",
                severity="info",
            ))
        if re.search(r"(?m)^\s*\|.+\|\s*$", body_markdown):
            warnings.append(PreviewWarning(
                code="medium_table_approximation",
                message="Medium may transform table layout when the article is published.",
            ))
        description = body_markdown
        description = re.sub(r"[#>*_`\[\]()]", "", description)
        description = re.sub(r"\s+", " ", description).strip()
        subtitle = (description[:157].rstrip() + "...") if len(description) > 160 else description
        subtitle = subtitle or "Live preview of the article as it will appear on Medium."
        words = len(re.findall(r"\w+", body_markdown))
        read_minutes = max(1, round(words / 240))
        shell = f"""
<header class="site-header"><div class="wordmark">Medium</div><div class="search">Search</div>
<div class="header-actions"><span class="write">Write</span><span>Sign up</span></div></header>
<main class="page"><header><h1 class="article-title">{html.escape(request.title)}</h1>
<p class="subtitle">{html.escape(subtitle)}</p><div class="byline"><div class="avatar">B</div>
<div><div class="author">BlogHub author</div><div>{read_minutes} min read</div></div></div></header>
<div class="actions" aria-hidden="true"><span>♡ 0</span><span>◯ 0</span><span class="right">⌑</span><span>↗</span></div>
<article class="content">{body}</article></main>"""
        return PreviewArtifact(
            state=PreviewState.current,
            platform=self.capabilities.platform,
            viewport=request.viewport,
            renderer_version=self.capabilities.renderer_version,
            source=source,
            html=preview_document(
                title=request.title,
                platform=self.capabilities.platform.value,
                css=MEDIUM_CSS,
                body=shell,
            ),
            warnings=warnings,
        )
