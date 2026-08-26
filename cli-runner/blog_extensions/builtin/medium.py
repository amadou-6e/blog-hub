from __future__ import annotations

from pathlib import Path

from medium_browser import (
    check_medium_profile,
    get_medium_article,
    list_medium_articles,
    write_medium_article,
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
    capabilities = frozenset({
        Capability.LIST_ARTICLES,
        Capability.GET_ARTICLE,
        Capability.CREATE_DRAFT,
        Capability.UPDATE_ARTICLE,
        Capability.PUBLISH,
    })

    def execute(self, page, operation: Capability, request: OperationRequest) -> dict:
        if operation == Capability.LIST_ARTICLES:
            return list_medium_articles(page=page, limit=request.limit)
        if operation == Capability.GET_ARTICLE:
            if not request.remote_id:
                raise ValueError("Medium get_article requires a remote_id")
            return get_medium_article(page=page, article_id=request.remote_id)
        if operation in {
            Capability.CREATE_DRAFT,
            Capability.UPDATE_ARTICLE,
            Capability.PUBLISH,
        }:
            if request.article is None:
                raise ValueError(f"Medium {operation.value} requires article content")
            remote_id = request.remote_id or request.article.remote_id
            if operation == Capability.UPDATE_ARTICLE and not remote_id:
                raise ValueError("Medium update_article requires a remote_id")
            return write_medium_article(
                page=page,
                title=request.article.title,
                article_md=request.article.body,
                remote_id=remote_id,
                publish=operation == Capability.PUBLISH,
            )
        raise OperationNotSupported(self.platform, operation.value)
