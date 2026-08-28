from backend.schemas.previews import PreviewPlatform, PreviewRenderRequest, PreviewSource
from backend.services.platform_previews.engine import (
    MarkdownPreviewProvider,
    PreviewEngine,
    working_copy_fingerprint,
)


def test_fingerprint_is_deterministic_and_normalizes_line_endings():
    assert working_copy_fingerprint("Title", "one\r\ntwo") == working_copy_fingerprint(
        "Title", "one\ntwo"
    )


def test_markdown_renderer_escapes_raw_html_and_unsafe_links():
    provider = MarkdownPreviewProvider()
    artifact = provider.render(
        PreviewRenderRequest(
            platform=PreviewPlatform.markdown,
            title="Safe",
            content="<script>alert(1)</script>\n\n[x](javascript:alert(2))",
        ),
        source=PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:x"),
        asset_base_url="/assets",
    )

    assert "<script>" not in artifact.html
    assert "&lt;script&gt;" in artifact.html
    assert 'href="javascript:' not in artifact.html
    assert artifact.warnings[0].code == "raw_html_escaped"


def test_markdown_renderer_rewrites_local_images_only():
    provider = MarkdownPreviewProvider()
    artifact = provider.render(
        PreviewRenderRequest(
            platform=PreviewPlatform.markdown,
            title="Images",
            content="![local](./images/photo.png)\n\n![remote](https://example.com/a.png)",
        ),
        source=PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:x"),
        asset_base_url="/api/articles/art_001/assets/by-filename",
    )

    assert "/api/articles/art_001/assets/by-filename/images/photo.png" in artifact.html
    assert "https://example.com/a.png" in artifact.html


def test_markdown_renderer_does_not_rewrite_images_inside_fenced_code():
    artifact = MarkdownPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.markdown,
            title="Image syntax",
            content="```markdown\n![literal](./logo.png)\n```\n\n![real](./logo.png)",
        ),
        source=PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:x"),
        asset_base_url="/api/articles/art_001/assets/by-filename",
    )

    assert "![literal](./logo.png)" in artifact.html
    assert artifact.html.count("/api/articles/art_001/assets/by-filename/logo.png") == 1


def test_engine_cache_is_keyed_by_fingerprint_and_returns_copies():
    class CountingProvider(MarkdownPreviewProvider):
        calls = 0

        def render(self, *args, **kwargs):
            self.calls += 1
            return super().render(*args, **kwargs)

    provider = CountingProvider()
    engine = PreviewEngine([provider])
    request = PreviewRenderRequest(platform=PreviewPlatform.markdown, title="A", content="B")
    source = PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:same")

    first = engine.render(request, source=source, asset_base_url="/assets")
    second = engine.render(request, source=source, asset_base_url="/assets")
    second.html = "changed"

    assert provider.calls == 1
    assert first.html != second.html


def test_engine_cache_is_isolated_by_article_and_asset_base_url():
    class CountingProvider(MarkdownPreviewProvider):
        calls = 0

        def render(self, *args, **kwargs):
            self.calls += 1
            return super().render(*args, **kwargs)

    provider = CountingProvider()
    engine = PreviewEngine([provider])
    request = PreviewRenderRequest(
        platform=PreviewPlatform.markdown,
        title="Same",
        content="![cover](./cover.png)",
    )
    first = engine.render(
        request,
        source=PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:same"),
        asset_base_url="/api/articles/art_001/assets/by-filename",
    )
    second = engine.render(
        request,
        source=PreviewSource(article_id="art_002", working_copy_fingerprint="sha256:same"),
        asset_base_url="/api/articles/art_002/assets/by-filename",
    )

    assert provider.calls == 2
    assert first.source.article_id == "art_001"
    assert second.source.article_id == "art_002"
    assert "/art_001/assets/" in first.html
    assert "/art_002/assets/" in second.html


def test_render_api_uses_revision_for_saved_content(client):
    article = client.get("/api/articles/art_001").json()
    response = client.post(
        "/api/articles/art_001/previews/render",
        json={
            "platform": "markdown",
            "viewport": "desktop",
            "title": article["title"],
            "content": article["content"],
            "base_revision_id": article["revision_id"],
        },
    )

    assert response.status_code == 200
    artifact = response.json()
    assert artifact["state"] == "current"
    assert artifact["source"]["revision_id"] == article["revision_id"]
    assert artifact["source"]["working_copy_fingerprint"] is None


def test_render_api_uses_fingerprint_for_unsaved_content(client):
    article = client.get("/api/articles/art_001").json()
    response = client.post(
        "/api/articles/art_001/previews/render",
        json={
            "platform": "markdown",
            "title": article["title"],
            "content": article["content"] + "\nUnsaved",
            "base_revision_id": article["revision_id"],
        },
    )

    assert response.status_code == 200
    source = response.json()["source"]
    assert source["revision_id"] is None
    assert source["working_copy_fingerprint"].startswith("sha256:")


def test_unregistered_renderer_returns_typed_not_supported(client):
    response = client.post(
        "/api/articles/art_001/previews/render",
        json={"platform": "medium", "title": "T", "content": "Body"},
    )

    assert response.status_code == 501
    assert response.json()["detail"] == {
        "code": "preview_not_supported",
        "platform": "medium",
    }
