"""Remote comparison and explicit conflict resolution endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import backend.services.cli_runner as runner
import backend.services.connection_health as connection_health
import backend.store as store
from backend.schemas.reconciliation import (
    ReconciliationListResponse,
    ReconciliationObservation,
    ResolveReconciliationRequest,
)
from backend.services import reconciliation
from backend.services.hashnode_sync import (
    sync_browser_records,
    sync_hashnode_articles,
    sync_hashnode_browser_records,
)
from backend.services.medium_sync import sync_medium_browser_records
from backend.store.article_revisions import RevisionConflict
from blogs.devto.client import DevToClient, DevToError
import requests


router = APIRouter(prefix="/api/articles", tags=["reconciliation"])


def _identity(user_id: str, article_id: str, platform: str) -> dict:
    matches = [
        item for item in store.list_article_remote_identities(user_id, article_id)
        if item["platform"] == platform
    ]
    if not matches:
        raise HTTPException(
            status_code=409,
            detail={"error": "remote_identity_required", "platform": platform},
        )
    return matches[0]


def _refresh(user_id: str, article_id: str, platform: str) -> dict:
    identity = _identity(user_id, article_id, platform)
    browser = store.get_browser_connection(user_id, platform)
    try:
        if platform == "medium":
            if not browser or browser["status"] != "connected":
                raise HTTPException(409, "Connected Medium browser profile required")
            retrieval = runner.medium_browser_articles(
                organization_id=browser["skyvern_organization_id"],
                profile_id=browser["skyvern_profile_id"],
            )
            connection_health.record_operation_result(
                store, user_id, platform, retrieval,
            )
            result = sync_medium_browser_records(user_id, retrieval)
        elif platform == "hashnode" and browser and browser["status"] == "connected":
            retrieval = runner.hashnode_browser_articles(
                organization_id=browser["skyvern_organization_id"],
                profile_id=browser["skyvern_profile_id"],
            )
            connection_health.record_operation_result(
                store, user_id, platform, retrieval,
            )
            result = sync_hashnode_browser_records(user_id, retrieval)
        elif platform == "hashnode":
            token = store.get_connection_token(user_id, "hashnode")
            if not token or token == "cli_session":
                raise HTTPException(409, "Connected Hashnode profile or token required")
            result = sync_hashnode_articles(user_id, token)
        elif platform == "devto":
            token = store.get_connection_token(user_id, "devto")
            if not token:
                raise HTTPException(409, "Connected Dev.to API key required")
            client = DevToClient(token)
            records = []
            for page_number in range(1, 101):
                page = client.list_my_articles(per_page=100, page=page_number)
                records.extend(page)
                if len(page) < 100:
                    break
            retrieval = {"success": True, "articles": [{
                "platform": "devto",
                "remote_id": str(item.article_id),
                "title": item.title,
                "body": item.body_markdown,
                "status": "published" if item.published else "draft",
                "subtitle": item.description,
                "canonical_url": item.canonical_url,
                "cover_url": item.cover_image,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "metadata": {"url": item.url},
            } for item in records], "diagnostics": {"errors": []}}
            result = sync_browser_records(user_id, retrieval, platform="devto")
        else:
            raise HTTPException(422, f"Reconciliation is not supported for {platform}")
    except runner.RunnerUnavailable:
        connection_health.record_unavailable(store, user_id, platform)
        reconciliation.record_unavailable(
            store,
            user_id,
            article_id,
            identity,
            availability="inaccessible",
            error=f"{platform.title()} could not be reached.",
        )
        observation = store.get_latest_reconciliation_observation(
            user_id, article_id, platform,
        )
        return reconciliation.current_view(
            store, user_id, article_id, observation,
        )
    except (DevToError, requests.RequestException):
        reconciliation.record_unavailable(
            store,
            user_id,
            article_id,
            identity,
            availability="inaccessible",
            error="Dev.to could not be reached.",
        )
        observation = store.get_latest_reconciliation_observation(
            user_id, article_id, platform,
        )
        return reconciliation.current_view(
            store, user_id, article_id, observation,
        )

    matching = next(
        (item for item in result["articles"] if item["remoteId"] == identity["remote_id"]),
        None,
    )
    if matching is None or matching.get("status") == "failed":
        unavailable = result["status"] != "succeeded" or matching is not None
        reconciliation.record_unavailable(
            store,
            user_id,
            article_id,
            identity,
            availability="inaccessible" if unavailable else "deleted",
            error=(
                "The remote provider could not confirm this article."
                if unavailable
                else "The linked remote article no longer exists or is no longer visible."
            ),
        )
    observation = store.get_latest_reconciliation_observation(
        user_id, article_id, platform,
    )
    if observation is None:
        raise HTTPException(502, "Remote refresh produced no comparison")
    return reconciliation.current_view(store, user_id, article_id, observation)


@router.get("/{article_id}/reconciliation", response_model=ReconciliationListResponse)
def list_reconciliation(request: Request, article_id: str):
    user_id = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(404, "Article not found")
    observations = store.list_latest_reconciliation_observations(user_id, article_id)
    observed_platforms = {item["platform"] for item in observations}
    revision = store.get_current_article_revision(user_id, article_id)
    for identity in store.list_article_remote_identities(user_id, article_id):
        if identity["platform"] in observed_platforms or revision is None:
            continue
        observations.append({
            "id": f"identity:{identity['platform']}:{identity['remote_id']}",
            "article_id": article_id,
            "platform": identity["platform"],
            "remote_id": identity["remote_id"],
            "local_revision_id": revision["id"],
            "baseline_fingerprint": identity.get("remote_content_fingerprint"),
            "local_fingerprint": reconciliation.local_fingerprint(
                revision, identity["remote_id"],
            ),
            "availability": "unknown",
            "sync_state": "unknown",
            "metadata": {},
            "observed_at": identity.get("last_synced_at") or identity["updated_at"],
        })
    return ReconciliationListResponse(comparisons=[
        ReconciliationObservation(**reconciliation.current_view(
            store, user_id, article_id, item,
        ))
        for item in observations
    ])


@router.post(
    "/{article_id}/reconciliation/{platform}/refresh",
    response_model=ReconciliationObservation,
)
def refresh_reconciliation(request: Request, article_id: str, platform: str):
    user_id = request.state.user_id
    if store.get_article(user_id, article_id) is None:
        raise HTTPException(404, "Article not found")
    return ReconciliationObservation(**_refresh(user_id, article_id, platform))


@router.post(
    "/{article_id}/reconciliation/{platform}/resolve",
    response_model=ReconciliationObservation,
)
def resolve_reconciliation(
    request: Request,
    article_id: str,
    platform: str,
    body: ResolveReconciliationRequest,
):
    user_id = request.state.user_id
    try:
        observation = reconciliation.resolve(
            store,
            user_id,
            article_id,
            platform,
            body.action,
            body.base_revision_id,
        )
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "revision_conflict",
            "message": str(exc),
            "current": exc.current,
        }) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReconciliationObservation(**reconciliation.current_view(
        store, user_id, article_id, observation,
    ))
