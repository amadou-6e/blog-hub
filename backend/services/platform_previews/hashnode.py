"""Deterministic Hashnode-like live preview renderer."""
from __future__ import annotations

import html
import re

from blogs.hashnode.render import render_markdown
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


HASHNODE_CSS = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fff;color:#111827;
font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}.site-header{height:64px;border-bottom:1px solid #e5e7eb;
display:flex;align-items:center;padding:0 24px;gap:12px;position:sticky;top:0;background:#fffffffa}.brand-mark{width:34px;
height:34px;border-radius:7px;background:#2563eb;color:#fff;display:grid;place-items:center;font-weight:800}.brand{font-weight:700}
.search{margin-left:auto;width:180px;height:34px;border:1px solid #d1d5db;border-radius:7px;color:#9ca3af;padding:7px 11px;
font-size:13px}.page{width:min(1040px,100%);margin:0 auto;padding:48px 24px 80px}.article-head{width:min(800px,100%);
margin:0 auto 30px}.eyebrow{font-size:13px;color:#2563eb;font-weight:600;margin-bottom:15px}.article-title{font-size:48px;
line-height:1.12;letter-spacing:0;margin:0 0 15px;font-weight:800;color:#111827}.subtitle{font-size:20px;line-height:1.5;
color:#4b5563;margin:0 0 24px}.byline{display:flex;align-items:center;gap:11px;color:#4b5563;font-size:13px}.avatar{width:38px;
height:38px;border-radius:50%;background:#dbeafe;color:#1d4ed8;display:grid;place-items:center;font-weight:700}.author{color:#111827;
font-weight:600}.layout{width:min(920px,100%);margin:0 auto;display:grid;grid-template-columns:52px minmax(0,800px);gap:24px}
.rail{padding-top:8px;display:flex;flex-direction:column;align-items:center;gap:15px;color:#6b7280;font-size:12px}.rail-button{width:38px;
height:38px;border:1px solid #e5e7eb;border-radius:50%;display:grid;place-items:center;background:#fff}.content{font-family:Georgia,
'Times New Roman',serif;font-size:19px;line-height:1.82;color:#1f2937;min-width:0}.content h1,.content h2,.content h3{
font-family:Inter,ui-sans-serif,system-ui,sans-serif;line-height:1.25;color:#111827;letter-spacing:0}.content h1{font-size:34px}
.content h2{font-size:28px;margin:1.7em 0 .55em}.content h3{font-size:22px;margin:1.5em 0 .5em}.content p,.content ul,
.content ol,.content blockquote,.content pre,.content table{margin:0 0 1.35em}.content a{color:#2563eb}.content img{display:block;
max-width:100%;height:auto;border-radius:5px;margin:2em auto}.content blockquote{border-left:4px solid #2563eb;margin-left:0;padding:
.2em 0 .2em 1.2em;color:#4b5563;font-style:italic}.content pre{overflow:auto;background:#111827;color:#e5e7eb;padding:18px;
border-radius:7px}.content code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em}.content table{width:100%;
border-collapse:collapse;font-family:Inter,ui-sans-serif,system-ui,sans-serif;font-size:14px}.content th,.content td{border:1px solid #d1d5db;
padding:9px 11px;text-align:left}.content th{background:#f9fafb}@media(max-width:640px){.site-header{height:56px;padding:0 14px}
.search{display:none}.page{padding:28px 18px 56px}.article-title{font-size:34px}.subtitle{font-size:17px}.layout{display:block}
.rail{display:none}.content{font-size:17px;line-height:1.75}.content h2{font-size:24px}}
"""


class HashnodePreviewProvider:
    capabilities = PreviewCapabilities(
        platform=PreviewPlatform.hashnode,
        renderer_version="hashnode-1",
        viewports=[PreviewViewport.desktop, PreviewViewport.mobile],
    )

    def render(
        self,
        request: PreviewRenderRequest,
        *,
        source: PreviewSource,
        asset_base_url: str,
    ) -> PreviewArtifact:
        normalized = render_markdown(request.content)
        body, warnings = render_markdown_fragment(normalized.body_markdown, asset_base_url)
        if normalized.body_markdown.strip() != request.content.strip():
            warnings.append(PreviewWarning(
                code="hashnode_content_normalized",
                message="Title or publishing notes were moved out of the Hashnode article body.",
                severity="info",
            ))
        words = len(re.findall(r"\w+", normalized.body_markdown))
        read_minutes = max(1, round(words / 220))
        subtitle = normalized.subtitle or "Live preview of the article as it will appear on Hashnode."
        shell = f"""
<header class="site-header"><div class="brand-mark">H</div><div class="brand">Publication</div>
<div class="search">Search articles</div></header>
<main class="page"><header class="article-head"><div class="eyebrow">Publication</div>
<h1 class="article-title">{html.escape(request.title)}</h1>
<p class="subtitle">{html.escape(subtitle)}</p><div class="byline"><div class="avatar">B</div>
<div><div class="author">BlogHub author</div><div>{read_minutes} min read</div></div></div></header>
<div class="layout"><aside class="rail" aria-hidden="true"><div class="rail-button">♡</div><span>0</span>
<div class="rail-button">↗</div></aside><article class="content">{body}</article></div></main>"""
        return PreviewArtifact(
            state=PreviewState.current,
            platform=self.capabilities.platform,
            viewport=request.viewport,
            renderer_version=self.capabilities.renderer_version,
            source=source,
            html=preview_document(
                title=request.title,
                platform=self.capabilities.platform.value,
                css=HASHNODE_CSS,
                body=shell,
            ),
            warnings=warnings,
        )

