from backend.schemas.previews import PreviewPlatform, PreviewRenderRequest, PreviewSource
from backend.services.platform_previews.hashnode import HashnodePreviewProvider


SOURCE = PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:test")


def test_hashnode_preview_has_platform_shell_and_normalized_content():
    artifact = HashnodePreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.hashnode,
            title="A practical guide",
            content="# A practical guide\n\nA useful introduction.\n\n## First step\n\nDo this.",
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    assert artifact.renderer_version == "hashnode-1"
    assert 'data-preview-platform="hashnode"' in artifact.html
    assert '<h1 class="article-title">A practical guide</h1>' in artifact.html
    assert artifact.html.count("A practical guide") == 2  # document title + visible title
    assert "A useful introduction." in artifact.html
    assert not artifact.warnings


def test_hashnode_preview_warns_when_the_planning_tail_is_removed():
    artifact = HashnodePreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.hashnode,
            title="Notes",
            content="# Notes\r\n\r\nBody.\r\n\r\n**Tags:** Python\r\n\r\n## Hidden section",
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    warning = next(w for w in artifact.warnings if w.code == "hashnode_planning_tail_removed")
    assert warning.severity == "warning"
    assert "all content after it" in warning.message
    assert "Hidden section" not in artifact.html


def test_hashnode_preview_uses_authenticated_asset_urls():
    artifact = HashnodePreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.hashnode,
            title="Images",
            content="![diagram](./diagram.png)",
            viewport="mobile",
        ),
        source=SOURCE,
        asset_base_url="/api/articles/art_001/assets/by-filename",
    )

    assert artifact.viewport.value == "mobile"
    assert "/api/articles/art_001/assets/by-filename/diagram.png" in artifact.html
    assert "@media(max-width:640px)" in artifact.html


def test_hashnode_renderer_is_available_through_api(client):
    response = client.post(
        "/api/articles/art_001/previews/render",
        json={
            "platform": "hashnode",
            "viewport": "desktop",
            "title": "Preview title",
            "content": "Intro paragraph.",
        },
    )

    assert response.status_code == 200
    assert response.json()["platform"] == "hashnode"
    assert "Preview title" in response.json()["html"]
