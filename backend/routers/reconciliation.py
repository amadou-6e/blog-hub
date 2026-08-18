"""Remote article comparison and explicit conflict resolution endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import backend.store as store
from backend.schemas.reconciliation import (
    ReconciliationListResponse,
    RemoteSnapshot,
    ResolveRemoteConflictRequest,
)
from backend.services import reconciliation
from backend.store.article_revisions import RevisionConflict


router = APIRouter(prefix="/api/articles", tags=["reconciliation"])


def _require_article(user_id: str, article_id: str) -> None:
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(status_code=404, detail="Article not found")


@router.get("/{article_id}/reconciliation", response_model=ReconciliationListResponse)
def list_comparisons(request: Request, article_id: str):
    user_id = request.state.user_id
    _require_article(user_id, article_id)
    snapshots = store.list_latest_remote_snapshots(user_id, article_id)
    return ReconciliationListResponse(
        comparisons=[
            RemoteSnapshot(**reconciliation.current_view(store, user_id, article_id, item))
            for item in snapshots
        ]
    )


@router.post(
    "/{article_id}/reconciliation/{platform}/refresh",
    response_model=RemoteSnapshot,
)
def refresh_comparison(request: Request, article_id: str, platform: str):
    user_id = request.state.user_id
    _require_article(user_id, article_id)
    try:
        snapshot = reconciliation.refresh(store, user_id, article_id, platform)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unsupported platform: {platform}") from exc
    if snapshot["availability"] == "available":
        store.apply_remote_destination_state(
            user_id,
            article_id,
            platform,
            status=snapshot["remote_status"],
            url=snapshot["remote_url"],
            remote_id=snapshot["remote_id"],
        )
    return RemoteSnapshot(**reconciliation.current_view(store, user_id, article_id, snapshot))


@router.post(
    "/{article_id}/reconciliation/{platform}/resolve",
    response_model=RemoteSnapshot,
)
def resolve_comparison(
    request: Request,
    article_id: str,
    platform: str,
    body: ResolveRemoteConflictRequest,
):
    user_id = request.state.user_id
    _require_article(user_id, article_id)
    try:
        if body.action == "use_remote":
            reconciliation.import_remote(
                store, user_id, article_id, platform, body.base_revision_id
            )
            latest = store.get_latest_remote_snapshot(user_id, article_id, platform)
            assert latest is not None
            snapshot = latest
        else:
            snapshot = reconciliation.acknowledge_local(
                store, user_id, article_id, platform
            )
    except RevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "revision_conflict",
                "message": str(exc),
                "current": exc.current,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RemoteSnapshot(**reconciliation.current_view(store, user_id, article_id, snapshot))
