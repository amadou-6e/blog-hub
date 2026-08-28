from backend.schemas.previews import PreviewPlatform, PreviewRenderRequest, PreviewSource
from backend.services.platform_previews.medium import MediumPreviewProvider


SOURCE = PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:test")


def test_medium_preview_has_editorial_shell_without_duplicate_body_title():
    artifact = MediumPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.medium,
            title="A practical guide",
            content="# A practical guide\n\nA useful introduction.\n\n## First step\n\nDo this.",
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    assert artifact.renderer_version == "medium-2"
    assert 'data-preview-platform="medium"' in artifact.html
    assert '<h1 class="article-title">A practical guide</h1>' in artifact.html
    assert artifact.html.count("A practical guide") == 2  # document title + visible title
    assert "font-family:Georgia" in artifact.html
    assert not any(w.code == "medium_planning_tail_removed" for w in artifact.warnings)


def test_medium_preview_only_strips_a_leading_title():
    artifact = MediumPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.medium,
            title="A practical guide",
            content="Intro before the section.\n\n# A real section\n\nKeep this heading.",
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    assert "A real section" in artifact.html


def test_medium_preview_rewrites_local_images_once():
    artifact = MediumPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.medium,
            title="Images",
            content="![diagram](./img/diagram.png)",
        ),
        source=SOURCE,
        asset_base_url="assets",
    )

    assert 'src="assets/img/diagram.png"' in artifact.html
    assert "assets/assets/" not in artifact.html


def test_medium_preview_derives_subtitle_from_prose_not_a_table():
    artifact = MediumPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.medium,
            title="Table",
            content=(
                "| A | B |\n| - | - |\n| 1 | 2 |\n\n"
                "This is the useful prose summary that follows the table."
            ),
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    assert '<p class="subtitle">This is the useful prose summary that follows the table.</p>' in artifact.html


def test_medium_preview_warns_when_planning_tail_is_removed():
    artifact = MediumPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.medium,
            title="Plan",
            content="Visible.\r\n\r\n**Tags:** preview\r\n\r\n## Hidden section",
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    warning = next(w for w in artifact.warnings if w.code == "medium_planning_tail_removed")
    assert warning.severity == "warning"
    assert "Hidden section" not in artifact.html


def test_medium_preview_warns_about_table_approximation():
    artifact = MediumPreviewProvider().render(
        PreviewRenderRequest(
            platform=PreviewPlatform.medium,
            title="Table",
            content="| A | B |\n| - | - |\n| 1 | 2 |",
            viewport="mobile",
        ),
        source=SOURCE,
        asset_base_url="/assets",
    )

    assert artifact.viewport.value == "mobile"
    assert any(w.code == "medium_table_approximation" for w in artifact.warnings)
    assert "<table>" in artifact.html


def test_medium_renderer_is_available_through_api(client):
    response = client.post(
        "/api/articles/art_001/previews/render",
        json={
            "platform": "medium",
            "viewport": "desktop",
            "title": "Preview title",
            "content": "Intro paragraph.",
        },
    )

    assert response.status_code == 200
    assert response.json()["platform"] == "medium"
    assert "Preview title" in response.json()["html"]
