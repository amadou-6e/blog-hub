"""Synchronous PAT-backed Hashnode-to-workspace synchronization."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import backend.store as default_store
from backend.services.image_ingest import IngestedImage, fetch_and_validate_image
from backend.store.article_revisions import RevisionConflict
from blogs.hashnode.client import HashnodeClient, HashnodeRemoteArticle


class HashnodeSyncStore(Protocol):
    def get_remote_article_identity(
        self, user_id: str, platform: str, remote_id: str,
    ) -> dict | None: ...

    def get_or_create_remote_article(
        self, user_id: str, platform: str, remote_id: str, **kwargs,
    ) -> tuple[dict, bool]: ...

    def get_current_article_revision(self, user_id: str, article_id: str) -> dict | None: ...

    def save_article_revision(self, user_id: str, article_id: str, **kwargs) -> dict: ...

    def sync_remote_article_metadata(
        self, user_id: str, article_id: str, **kwargs,
    ) -> bool: ...

    def store_asset(
        self, user_id: str, article_id: str, filename: str, data: bytes,
        mime_type: str | None = None,
    ) -> str: ...

    def get_article_asset_by_filename(
        self, user_id: str, article_id: str, filename: str,
    ) -> dict | None: ...

    def upsert_remote_article_identity(
        self, user_id: str, article_id: str, platform: str, remote_id: str,
        **kwargs,
    ) -> dict: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _fingerprint(article: HashnodeRemoteArticle) -> str:
    normalized = json.dumps(
        {"title": article.title.strip(), "markdown": article.body_markdown},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(normalized).hexdigest()


def _cover_filename(remote_id: str) -> str:
    digest = hashlib.sha256(remote_id.encode("utf-8")).hexdigest()[:16]
    return f"hashnode-cover-{digest}.png"


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, RevisionConflict):
        return "revision_conflict"
    return "hashnode_request_failed" if exc.__class__.__module__.startswith(
        ("requests", "httpx", "blogs.hashnode")
    ) else "article_sync_failed"


def _fetch_sources(client: HashnodeClient) -> tuple[list[HashnodeRemoteArticle], list[dict]]:
    fetched: dict[str, HashnodeRemoteArticle] = {}
    errors: list[dict] = []
    for source, fetch in (
        ("drafts", client.list_drafts),
        ("published", client.list_published_articles),
    ):
        try:
            articles = fetch()
        except Exception as exc:
            errors.append({"source": source, "error": _safe_error_code(exc)})
            continue
        for article in articles:
            existing = fetched.get(article.article_id)
            if existing is None or article.published:
                fetched[article.article_id] = article
    return list(fetched.values()), errors


def _sync_cover(
    *,
    user_id: str,
    article_id: str,
    remote: HashnodeRemoteArticle,
    identity: dict | None,
    store: HashnodeSyncStore,
    image_fetcher: Callable[[str], IngestedImage],
) -> tuple[int | None, str, str | None]:
    source_url = remote.cover_image_url
    if not source_url:
        return None, "none", None

    previous_result = (identity or {}).get("last_sync_result") or {}
    previous_updated_at = (identity or {}).get("remote_updated_at")
    current_updated_at = _iso(remote.updated_at)
    if (
        identity
        and identity.get("cover_asset_id") is not None
        and previous_result.get("coverSourceUrl") == source_url
        and previous_updated_at == current_updated_at
    ):
        return int(identity["cover_asset_id"]), "unchanged", None

    image = image_fetcher(source_url)
    if not image.ok:
        reason = image.reason.value if image.reason is not None else "image_ingest_failed"
        return (identity or {}).get("cover_asset_id"), "failed", reason

    data = image.thumbnail_bytes or image.image_bytes
    if not data:
        return (identity or {}).get("cover_asset_id"), "failed", "decode_failed"
    filename = _cover_filename(remote.article_id)
    mime_type = "image/png" if image.thumbnail_bytes else image.content_type
    store.store_asset(user_id, article_id, filename, data, mime_type)
    asset = store.get_article_asset_by_filename(user_id, article_id, filename)
    if asset is None:
        raise RuntimeError("stored cover asset was not registered")
    return int(asset["id"]), "downloaded", None


def _sync_article(
    *,
    user_id: str,
    remote: HashnodeRemoteArticle,
    started_at: str,
    store: HashnodeSyncStore,
    image_fetcher: Callable[[str], IngestedImage],
) -> dict:
    fingerprint = _fingerprint(remote)
    remote_updated_at = _iso(remote.updated_at)
    revision_created = False

    article, created = store.get_or_create_remote_article(
        user_id,
        "hashnode",
        remote.article_id,
        title=remote.title,
        body=remote.body_markdown,
        canonical_url=remote.canonical_url,
        remote_updated_at=remote_updated_at,
    )
    article_id = article["id"]

    if created:
        identity = None
        action = "imported"
        revision_created = True
    else:
        identity = store.get_remote_article_identity(user_id, "hashnode", remote.article_id)
        current = store.get_current_article_revision(user_id, article_id)
        content_changed = (
            identity is not None
            and identity.get("remote_content_fingerprint") != fingerprint
        )
        if identity is None or identity.get("remote_content_fingerprint") is None:
            content_changed = current is None or (
                current["title"] != remote.title
                or current["content"] != remote.body_markdown
            )
        if content_changed:
            # Pass the revision we just read as expected_revision_id so a
            # concurrent user edit made between our read and this write is
            # surfaced as a RevisionConflict instead of being silently
            # overwritten (see PR #69 review).
            store.save_article_revision(
                user_id,
                article_id,
                title=remote.title,
                content=remote.body_markdown,
                source="remote-sync",
                description="Synchronized from Hashnode",
                expected_revision_id=current["id"] if current else None,
            )
            revision_created = True
            action = "updated"
        else:
            action = "unchanged"

    metadata_changed = store.sync_remote_article_metadata(
        user_id,
        article_id,
        platform="hashnode",
        status="published" if remote.published else "draft",
        url=remote.url,
        remote_id=remote.article_id,
        canonical_url=remote.canonical_url,
        remote_updated_at=remote_updated_at,
    )
    if action == "unchanged" and metadata_changed:
        action = "metadata_updated"

    cover_asset_id, image_status, image_error = _sync_cover(
        user_id=user_id,
        article_id=article_id,
        remote=remote,
        identity=identity,
        store=store,
        image_fetcher=image_fetcher,
    )
    article_status = "partial" if image_status == "failed" else "succeeded"
    completed_at = _now().isoformat()
    sync_result = {
        "action": action,
        "revisionCreated": revision_created,
        "imageStatus": image_status,
        "coverSourceUrl": remote.cover_image_url,
        "remoteStatus": "published" if remote.published else "draft",
        "remoteUrl": remote.url,
    }
    store.upsert_remote_article_identity(
        user_id,
        article_id,
        "hashnode",
        remote.article_id,
        remote_content_fingerprint=fingerprint,
        subtitle=remote.subtitle,
        cover_asset_id=cover_asset_id,
        last_sync_status=article_status,
        last_sync_result=sync_result,
        last_sync_error=image_error,
        remote_created_at=remote.raw.get("browser_created_at"),
        remote_updated_at=remote_updated_at,
        last_sync_started_at=started_at,
        last_synced_at=completed_at,
    )
    return {
        "remoteId": remote.article_id,
        "articleId": article_id,
        "status": article_status,
        "action": action,
        "revisionCreated": revision_created,
        "imageStatus": image_status,
        "error": image_error,
    }


def _sync_remote_articles(
    user_id: str,
    remote_articles: list[HashnodeRemoteArticle],
    source_errors: list[dict],
    *,
    store: HashnodeSyncStore = default_store,
    image_fetcher: Callable[[str], IngestedImage] = fetch_and_validate_image,
    failed_articles: list[dict] | None = None,
) -> dict[str, Any]:
    """Synchronize normalized Hashnode records from any retrieval adapter."""
    started_at = _now().isoformat()
    article_results: list[dict] = list(failed_articles or [])
    counters = {
        "imported": 0,
        "updated": 0,
        "metadataUpdated": 0,
        "unchanged": 0,
        "failed": 0,
        "imagesDownloaded": 0,
        "imagesFailed": 0,
    }

    counters["failed"] = len(article_results)
    for remote in remote_articles:
        try:
            result = _sync_article(
                user_id=user_id,
                remote=remote,
                started_at=started_at,
                store=store,
                image_fetcher=image_fetcher,
            )
        except Exception as exc:
            result = {
                "remoteId": remote.article_id,
                "articleId": None,
                "status": "failed",
                "action": "failed",
                "revisionCreated": False,
                "imageStatus": "not_attempted",
                "error": _safe_error_code(exc),
            }
        article_results.append(result)
        action_counter = {
            "imported": "imported",
            "updated": "updated",
            "metadata_updated": "metadataUpdated",
            "unchanged": "unchanged",
        }.get(result["action"])
        if action_counter is not None:
            counters[action_counter] += 1
        if result["status"] == "failed":
            counters["failed"] += 1
        if result["imageStatus"] == "downloaded":
            counters["imagesDownloaded"] += 1
        elif result["imageStatus"] == "failed":
            counters["imagesFailed"] += 1

    has_partial = bool(source_errors) or any(
        item["status"] != "succeeded" for item in article_results
    )
    if source_errors and len(source_errors) == 2 and not remote_articles:
        status = "failed"
    elif has_partial:
        status = "partial"
    else:
        status = "succeeded"
    return {
        "status": status,
        "startedAt": started_at,
        "completedAt": _now().isoformat(),
        "fetched": len(remote_articles),
        **counters,
        "sourceErrors": source_errors,
        "articles": article_results,
    }


def sync_hashnode_articles(
    user_id: str,
    token: str,
    *,
    store: HashnodeSyncStore = default_store,
    client: HashnodeClient | None = None,
    image_fetcher: Callable[[str], IngestedImage] = fetch_and_validate_image,
) -> dict[str, Any]:
    """Run one synchronous Hashnode GraphQL synchronization pass."""
    remote_articles, source_errors = _fetch_sources(client or HashnodeClient(token))
    return _sync_remote_articles(
        user_id,
        remote_articles,
        source_errors,
        store=store,
        image_fetcher=image_fetcher,
    )


def sync_hashnode_browser_records(
    user_id: str,
    retrieval: dict,
    *,
    store: HashnodeSyncStore = default_store,
    image_fetcher: Callable[[str], IngestedImage] = fetch_and_validate_image,
) -> dict[str, Any]:
    """Synchronize records returned by the authenticated browser runner."""
    remote_articles: list[HashnodeRemoteArticle] = []
    source_errors: list[dict] = []
    failed_articles: list[dict] = []
    for error in retrieval.get("errors") or []:
        if error.get("remote_id"):
            failed_articles.append({
                "remoteId": str(error["remote_id"]),
                "articleId": None,
                "status": "failed",
                "action": "failed",
                "revisionCreated": False,
                "imageStatus": "not_attempted",
                "error": str(error.get("error") or "article_retrieval_failed"),
            })
        else:
            source_errors.append({
                "source": str(error.get("source") or "browser"),
                "error": str(error.get("error") or "browser_retrieval_failed"),
            })

    for record in retrieval.get("articles") or []:
        try:
            remote_articles.append(HashnodeRemoteArticle(
                article_id=str(record["remote_id"]),
                title=str(record["title"]),
                url=record.get("url"),
                canonical_url=record.get("canonical_url"),
                subtitle=record.get("subtitle"),
                body_markdown=str(record.get("body_markdown") or ""),
                published=bool(record.get("published")),
                updated_at=_datetime(record.get("updated_at")),
                cover_image_url=record.get("cover_image_url"),
                raw={
                    "browser_created_at": record.get("created_at"),
                    "retrieval": "browser",
                },
            ))
        except (KeyError, TypeError, ValueError):
            source_errors.append({
                "source": "browser",
                "error": "invalid_article_record",
            })
    return _sync_remote_articles(
        user_id,
        remote_articles,
        source_errors,
        store=store,
        image_fetcher=image_fetcher,
        failed_articles=failed_articles,
    )
