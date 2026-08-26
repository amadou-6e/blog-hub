from __future__ import annotations

from pathlib import Path

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
