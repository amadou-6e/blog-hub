"""Extension contract for deterministic and remote preview providers."""
from __future__ import annotations

from typing import Protocol

from backend.schemas.previews import (
    PreviewArtifact,
    PreviewCapabilities,
    PreviewRenderRequest,
    PreviewSource,
)


class PlatformPreviewProvider(Protocol):
    """Render one platform without coupling callers to its implementation."""

    @property
    def capabilities(self) -> PreviewCapabilities:
        ...

    def render(
        self,
        request: PreviewRenderRequest,
        *,
        source: PreviewSource,
        asset_base_url: str,
    ) -> PreviewArtifact:
        ...

