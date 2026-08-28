"""API contracts shared by local and remote article previews."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PreviewPlatform(str, Enum):
    markdown = "markdown"
    hashnode = "hashnode"
    medium = "medium"


class PreviewKind(str, Enum):
    live = "live"
    remote = "remote"


class PreviewState(str, Enum):
    missing = "missing"
    rendering = "rendering"
    current = "current"
    stale = "stale"
    failed = "failed"


class PreviewViewport(str, Enum):
    desktop = "desktop"
    mobile = "mobile"


class PreviewWarning(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning"] = "warning"


class PreviewFailure(BaseModel):
    code: str
    message: str
    retryable: bool = False


class PreviewSource(BaseModel):
    article_id: str
    revision_id: str | None = None
    revision_number: int | None = Field(default=None, ge=1)
    working_copy_fingerprint: str | None = None

    @model_validator(mode="after")
    def require_revision_or_working_copy(self) -> "PreviewSource":
        if not self.revision_id and not self.working_copy_fingerprint:
            raise ValueError("revision_id or working_copy_fingerprint is required")
        return self


class PreviewCapabilities(BaseModel):
    platform: PreviewPlatform
    renderer_version: str
    viewports: list[PreviewViewport]
    live: bool = True
    remote_capture: bool = False


class PreviewRenderRequest(BaseModel):
    platform: PreviewPlatform
    viewport: PreviewViewport = PreviewViewport.desktop
    title: str = Field(max_length=500)
    content: str = Field(max_length=2_000_000)
    base_revision_id: str | None = None


class PreviewArtifact(BaseModel):
    kind: PreviewKind = PreviewKind.live
    state: PreviewState
    platform: PreviewPlatform
    viewport: PreviewViewport
    renderer_version: str
    source: PreviewSource
    html: str | None = None
    warnings: list[PreviewWarning] = Field(default_factory=list)
    failure: PreviewFailure | None = None
    artifact_url: str | None = None
    rendered_at: str | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "PreviewArtifact":
        if self.state == PreviewState.current and self.html is None and self.artifact_url is None:
            raise ValueError("a current preview requires html or artifact_url")
        if self.state == PreviewState.failed and self.failure is None:
            raise ValueError("a failed preview requires failure details")
        return self

