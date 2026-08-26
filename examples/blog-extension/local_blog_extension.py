"""Minimal trusted extension example; selectors are intentionally illustrative."""
from pathlib import Path

from blog_extensions import (
    BlogOperationsAdapter,
    BrowserLoginAdapter,
    Capability,
    OperationNotSupported,
    OperationRequest,
)


class LoginAdapter(BrowserLoginAdapter):
    platform = "local-blog"
    login_url = "https://blog.example.com/login"

    def verify_profile(self, profile_dir: Path) -> dict:
        # Real adapters inspect only the platform's non-expired session cookies.
        authenticated = (profile_dir / ".example-session-present").is_file()
        return {
            "authenticated": authenticated,
            "status": "connected" if authenticated else "login_required",
        }


class OperationsAdapter(BlogOperationsAdapter):
    platform = "local-blog"
    capabilities = frozenset({Capability.CREATE_DRAFT, Capability.PUBLISH})

    def execute(self, page, operation: Capability, request: OperationRequest) -> dict:
        if operation not in self.capabilities:
            raise OperationNotSupported(self.platform, operation.value)
        article = request.article
        if article is None:
            raise ValueError("Article data is required")

        page.goto("https://blog.example.com/editor", wait_until="domcontentloaded")
        page.get_by_label("Title").fill(article.title)
        page.get_by_label("Content").fill(article.body)
        page.get_by_role("button", name="Save draft").click()
        if operation == Capability.PUBLISH:
            page.get_by_role("button", name="Publish").click()

        # A real adapter must read the saved article back and compare it before
        # reporting success.
        return {"success": True, "status": "published" if operation == Capability.PUBLISH else "draft"}
