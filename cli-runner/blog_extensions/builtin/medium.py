from __future__ import annotations

from pathlib import Path

from medium_browser import check_medium_profile

from ..contracts import (
    BlogOperationsAdapter,
    BrowserLoginAdapter,
    Capability,
    OperationNotSupported,
    OperationRequest,
)


class MediumLoginAdapter(BrowserLoginAdapter):
    platform = "medium"
    login_url = "https://medium.com/m/signin"

    def verify_profile(self, profile_dir: Path) -> dict:
        return check_medium_profile(profile_dir=str(profile_dir))


class MediumOperationsAdapter(BlogOperationsAdapter):
    """Capability placeholder for the Medium implementation tracked by #43/#67."""

    platform = "medium"
    capabilities = frozenset()

    def execute(self, page, operation: Capability, request: OperationRequest) -> dict:
        raise OperationNotSupported(self.platform, operation.value)
