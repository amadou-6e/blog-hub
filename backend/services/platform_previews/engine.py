"""Deterministic live preview rendering and caching."""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import OrderedDict
from threading import Lock
from urllib.parse import quote

from markdown_it import MarkdownIt

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


_RAW_HTML = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")


def working_copy_fingerprint(title: str, content: str) -> str:
    canonical = json.dumps(
        {"title": title, "content": content.replace("\r\n", "\n")},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rewrite_image_url(target: str, asset_base_url: str) -> str:
    if target.startswith(("https://", "http://", "data:", "/")):
        return target
    clean = target.lstrip("./").replace("\\", "/")
    return f"{asset_base_url}/{quote(clean, safe='/')}"


def render_markdown_fragment(markdown: str, asset_base_url: str) -> tuple[str, list[PreviewWarning]]:
    warnings: list[PreviewWarning] = []
    if _RAW_HTML.search(markdown):
        warnings.append(PreviewWarning(
            code="raw_html_escaped",
            message="Raw HTML is shown as text in live previews.",
            severity="info",
        ))
    parser = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable("table")
    tokens = parser.parse(markdown)
    for token in tokens:
        for child in token.children or ():
            if child.type != "image":
                continue
            source = child.attrGet("src")
            if source:
                child.attrSet("src", _rewrite_image_url(source, asset_base_url))
    return parser.renderer.render(tokens, parser.options, {}), warnings


def preview_document(*, title: str, body: str, css: str, platform: str) -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body data-preview-platform="{platform}">{body}</body></html>""".format(
        title=html.escape(title), css=css, platform=platform, body=body,
    )


MARKDOWN_CSS = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fff;color:#20242d;
font:16px/1.7 Inter,ui-sans-serif,system-ui,sans-serif}main{width:min(760px,100%);margin:0 auto;
padding:38px 32px 72px}h1,h2,h3{line-height:1.25;color:#111827;margin:1.6em 0 .55em}
h1{font-size:2.25rem;margin-top:0}h2{font-size:1.55rem}h3{font-size:1.2rem}p,ul,ol,
blockquote,pre,table{margin:0 0 1.2em}a{color:#4f46e5}img{display:block;max-width:100%;height:auto;
margin:1.6em auto}blockquote{border-left:3px solid #a5b4fc;padding:.15em 0 .15em 1em;color:#4b5563}
pre{overflow:auto;background:#111827;color:#e5e7eb;padding:16px;border-radius:6px}code{font-family:
ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}table{width:100%;border-collapse:collapse}
th,td{border:1px solid #d1d5db;padding:8px 10px;text-align:left}@media(max-width:600px){main{padding:24px 18px 52px}
h1{font-size:1.85rem}h2{font-size:1.35rem}}
"""


class MarkdownPreviewProvider:
    capabilities = PreviewCapabilities(
        platform=PreviewPlatform.markdown,
        renderer_version="markdown-1",
        viewports=[PreviewViewport.desktop, PreviewViewport.mobile],
    )

    def render(
        self,
        request: PreviewRenderRequest,
        *,
        source: PreviewSource,
        asset_base_url: str,
    ) -> PreviewArtifact:
        body, warnings = render_markdown_fragment(request.content, asset_base_url)
        document = preview_document(
            title=request.title,
            platform=self.capabilities.platform.value,
            css=MARKDOWN_CSS,
            body=f'<main><article>{body}</article></main>',
        )
        return PreviewArtifact(
            state=PreviewState.current,
            platform=self.capabilities.platform,
            viewport=request.viewport,
            renderer_version=self.capabilities.renderer_version,
            source=source,
            html=document,
            warnings=warnings,
        )


class PreviewEngine:
    def __init__(self, providers=(), *, max_cache_entries: int = 128):
        self._providers = {p.capabilities.platform: p for p in providers}
        self._cache: OrderedDict[str, PreviewArtifact] = OrderedDict()
        self._max_cache_entries = max_cache_entries
        self._lock = Lock()

    def register(self, provider) -> None:
        self._providers[provider.capabilities.platform] = provider

    def capabilities(self) -> list[PreviewCapabilities]:
        return [provider.capabilities for provider in self._providers.values()]

    def render(
        self,
        request: PreviewRenderRequest,
        *,
        source: PreviewSource,
        asset_base_url: str,
    ) -> PreviewArtifact:
        provider = self._providers.get(request.platform)
        if provider is None:
            raise KeyError(request.platform.value)
        cache_key = "|".join((
            source.article_id,
            asset_base_url,
            request.platform.value,
            request.viewport.value,
            source.working_copy_fingerprint or source.revision_id or "",
            provider.capabilities.renderer_version,
        ))
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached.model_copy(deep=True)
        artifact = provider.render(request, source=source, asset_base_url=asset_base_url)
        with self._lock:
            self._cache[cache_key] = artifact.model_copy(deep=True)
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self._max_cache_entries:
                self._cache.popitem(last=False)
        return artifact
