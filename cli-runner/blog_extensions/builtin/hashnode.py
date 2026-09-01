from __future__ import annotations

from pathlib import Path
import time

from hashnode_browser import (
    check_hashnode_profile,
    retrieve_hashnode_articles,
    upload_hashnode_page,
)

from ..contracts import (
    BlogOperationsAdapter,
    BrowserLoginAdapter,
    Capability,
    OperationNotSupported,
    OperationRequest,
)


class HashnodeLoginAdapter(BrowserLoginAdapter):
    platform = "hashnode"
    login_url = "https://hashnode.com/login"

    def verify_profile(self, profile_dir: Path) -> dict:
        return check_hashnode_profile(profile_dir=str(profile_dir))

    def verify_live_session(self, probe: dict) -> dict:
        authenticated = any(
            cookie.get("present")
            and str(cookie.get("domain") or "").lstrip(".") == "hashnode.com"
            and _cookie_is_live(cookie.get("expires"))
            and (
                cookie.get("name") in {"authjs.session-token", "hashnode-session"}
                or str(cookie.get("name") or "").startswith(
                    "__Secure-authjs.session-token"
                )
            )
            for cookie in probe.get("cookies", [])
        )
        return {
            "authenticated": authenticated,
            "status": "connected" if authenticated else "login_required",
        }


def _cookie_is_live(expires: object) -> bool:
    try:
        value = float(expires)
    except (TypeError, ValueError):
        return False
    return value < 0 or value > time.time()


class HashnodeOperationsAdapter(BlogOperationsAdapter):
    platform = "hashnode"
    capabilities = frozenset({
        Capability.LIST_ARTICLES,
        Capability.CREATE_DRAFT,
        Capability.PUBLISH,
    })

    def execute(self, page, operation: Capability, request: OperationRequest) -> dict:
        if operation not in self.capabilities:
            raise OperationNotSupported(self.platform, operation.value)
        if operation == Capability.LIST_ARTICLES:
            return retrieve_hashnode_articles(page=page)
        article = request.article
        if article is None:
            raise ValueError("Hashnode create and publish operations require article data")
        result = upload_hashnode_page(
            page,
            title=article.title,
            article_md=article.body,
            publish=operation == Capability.PUBLISH,
        )
        if result.get("draft_id") and not result.get("remote_id"):
            result["remote_id"] = result["draft_id"]
        return result
