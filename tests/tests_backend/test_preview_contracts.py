import pytest
from pydantic import ValidationError

from backend.schemas.previews import (
    PreviewArtifact,
    PreviewFailure,
    PreviewPlatform,
    PreviewSource,
    PreviewState,
    PreviewViewport,
)


def test_preview_source_accepts_revision_identity():
    source = PreviewSource(article_id="art_001", revision_id="rev_001", revision_number=3)

    assert source.revision_id == "rev_001"
    assert source.working_copy_fingerprint is None


def test_preview_source_accepts_unsaved_working_copy():
    source = PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:abc")

    assert source.working_copy_fingerprint == "sha256:abc"


def test_preview_source_requires_stable_identity():
    with pytest.raises(ValidationError, match="revision_id or working_copy_fingerprint"):
        PreviewSource(article_id="art_001")


def test_current_artifact_requires_rendered_content():
    with pytest.raises(ValidationError, match="requires html or artifact_url"):
        PreviewArtifact(
            state=PreviewState.current,
            platform=PreviewPlatform.hashnode,
            viewport=PreviewViewport.desktop,
            renderer_version="1",
            source=PreviewSource(article_id="art_001", revision_id="rev_001"),
        )


def test_failed_artifact_carries_typed_failure():
    artifact = PreviewArtifact(
        state=PreviewState.failed,
        platform=PreviewPlatform.medium,
        viewport=PreviewViewport.mobile,
        renderer_version="1",
        source=PreviewSource(article_id="art_001", working_copy_fingerprint="sha256:abc"),
        failure=PreviewFailure(code="renderer_failed", message="Could not render"),
    )

    assert artifact.failure.code == "renderer_failed"


def test_failed_artifact_requires_failure_details():
    with pytest.raises(ValidationError, match="requires failure details"):
        PreviewArtifact(
            state=PreviewState.failed,
            platform=PreviewPlatform.medium,
            viewport=PreviewViewport.desktop,
            renderer_version="1",
            source=PreviewSource(article_id="art_001", revision_id="rev_001"),
        )


def test_stale_artifact_requires_the_previous_render():
    with pytest.raises(ValidationError, match="stale preview requires html or artifact_url"):
        PreviewArtifact(
            state=PreviewState.stale,
            platform=PreviewPlatform.hashnode,
            viewport=PreviewViewport.desktop,
            renderer_version="1",
            source=PreviewSource(article_id="art_001", revision_id="rev_001"),
        )


def test_rendered_at_requires_an_iso_timestamp():
    with pytest.raises(ValidationError):
        PreviewArtifact(
            state=PreviewState.current,
            platform=PreviewPlatform.markdown,
            viewport=PreviewViewport.desktop,
            renderer_version="1",
            source=PreviewSource(article_id="art_001", revision_id="rev_001"),
            html="<p>preview</p>",
            rendered_at="not-a-timestamp",
        )
