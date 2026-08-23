from __future__ import annotations

from pathlib import Path

from medium_browser import (
    check_medium_profile,
    get_medium_article,
    list_medium_articles,
)

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
    platform = "medium"
    capabilities = frozenset({Capability.LIST_ARTICLES, Capability.GET_ARTICLE})

    def execute(self, page, operation: Capability, request: OperationRequest) -> dict:
        if operation == Capability.LIST_ARTICLES:
            return list_medium_articles(page=page, limit=request.limit)
        if operation == Capability.GET_ARTICLE:
            if not request.remote_id:
                raise ValueError("Medium get_article requires a remote_id")
            return get_medium_article(page=page, article_id=request.remote_id)
        raise OperationNotSupported(self.platform, operation.value)
