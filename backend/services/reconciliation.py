"""Classify and resolve local-versus-remote article divergence."""
from __future__ import annotations

from typing import Any

from backend.services.hashnode_sync import RemoteSyncArticle, _fingerprint
from backend.store.article_revisions import RevisionConflict


def local_fingerprint(revision: dict, remote_id: str) -> str:
    return _fingerprint(RemoteSyncArticle(
        article_id=remote_id,
        title=revision["title"],
        body_markdown=revision["content"],
        published=False,
    ))


def current_view(store: Any, user_id: str, article_id: str, observation: dict) -> dict:
    revision = store.get_current_article_revision(user_id, article_id)
    if revision is None:
        raise KeyError(article_id)
    fingerprint = local_fingerprint(revision, observation["remote_id"])
    state = observation["sync_state"]
    if observation["availability"] == "available":
        if fingerprint == observation["remote_fingerprint"]:
            state = "in_sync"
        elif state == "in_sync":
            state = "local_ahead"
        elif state == "remote_ahead" and fingerprint != observation["local_fingerprint"]:
            state = "conflict"
    return {
        **observation,
        "local_fingerprint": fingerprint,
        "current_revision_id": revision["id"],
        "sync_state": state,
    }


def record_unavailable(
    store: Any,
    user_id: str,
    article_id: str,
    identity: dict,
    *,
    availability: str,
    error: str,
) -> dict:
    revision = store.get_current_article_revision(user_id, article_id)
    if revision is None:
        raise KeyError(article_id)
    return store.record_reconciliation_observation(
        user_id,
        article_id,
        identity["platform"],
        identity["remote_id"],
        local_revision_id=revision["id"],
        baseline_fingerprint=identity.get("remote_content_fingerprint"),
        local_fingerprint=local_fingerprint(revision, identity["remote_id"]),
        availability=availability,
        sync_state="remote_deleted" if availability == "deleted" else "inaccessible",
        error=error,
    )


def resolve(
    store: Any,
    user_id: str,
    article_id: str,
    platform: str,
    action: str,
    base_revision_id: str,
) -> dict:
    observation = store.get_latest_reconciliation_observation(
        user_id, article_id, platform,
    )
    if observation is None or observation["availability"] != "available":
        raise ValueError("No available remote observation can be resolved")
    current = store.get_current_article_revision(user_id, article_id)
    if current is None:
        raise KeyError(article_id)
    if current["id"] != base_revision_id:
        raise RevisionConflict(current)

    if action == "use_remote":
        if observation["remote_title"] is None or observation["remote_content"] is None:
            raise ValueError("Remote content is unavailable")
        current = store.save_article_revision(
            user_id,
            article_id,
            title=observation["remote_title"],
            content=observation["remote_content"],
            expected_revision_id=base_revision_id,
            source="remote-sync",
            description=f"Accepted remote {platform.title()} version",
        )
        identity = store.get_remote_article_identity(
            user_id, platform, observation["remote_id"],
        )
        store.upsert_remote_article_identity(
            user_id,
            article_id,
            platform,
            observation["remote_id"],
            remote_content_fingerprint=observation["remote_fingerprint"],
            subtitle=(identity or {}).get("subtitle"),
            cover_asset_id=(identity or {}).get("cover_asset_id"),
            last_sync_status="succeeded",
            last_sync_result={"action": "use_remote", "resolvedObservationId": observation["id"]},
            last_sync_error=None,
            remote_created_at=(identity or {}).get("remote_created_at"),
            remote_updated_at=observation["remote_updated_at"],
            last_sync_started_at=(identity or {}).get("last_sync_started_at"),
            last_synced_at=observation["observed_at"],
        )

    fingerprint = local_fingerprint(current, observation["remote_id"])
    state = "in_sync" if action == "use_remote" else "local_ahead"
    return store.record_reconciliation_observation(
        user_id,
        article_id,
        platform,
        observation["remote_id"],
        local_revision_id=current["id"],
        baseline_fingerprint=observation["remote_fingerprint"],
        local_fingerprint=fingerprint,
        remote_fingerprint=observation["remote_fingerprint"],
        availability="available",
        sync_state=state,
        remote_title=observation["remote_title"],
        remote_content=observation["remote_content"],
        canonical_url=observation["canonical_url"],
        remote_url=observation["remote_url"],
        remote_status=observation["remote_status"],
        remote_updated_at=observation["remote_updated_at"],
        metadata=observation["metadata"],
    )
