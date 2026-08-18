"""Compare local article revisions with linked remote publishing records."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Callable

from blogs.devto.client import DevToClient
from blogs.hashnode.client import HashnodeClient


SUPPORTED_PLATFORMS = ("hashnode", "devto")


class ReconciliationError(RuntimeError):
    """A remote article could not be fetched reliably."""


@dataclass(frozen=True)
class RemoteArticle:
    platform: str
    remote_id: str
    title: str
    content: str
    canonical_url: str | None
    remote_url: str | None
    status: str
    updated_at: str | None
    metadata: dict[str, Any]


RemoteFetcher = Callable[..., RemoteArticle | None]


def content_fingerprint(title: str, content: str, canonical_url: str | None = None) -> str:
    """Hash provider-neutral article content after harmless normalization."""
    normalized_title = " ".join(title.strip().split())
    normalized_body = content.replace("\r\n", "\n").strip()
    lines = normalized_body.splitlines()
    if lines and re.sub(r"\s+", " ", lines[0].removeprefix("# ").strip()) == normalized_title:
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    normalized_body = "\n".join(line.rstrip() for line in lines).strip()
    payload = {
        "title": normalized_title,
        "content": normalized_body,
        "canonical_url": (canonical_url or "").strip(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def fetch_remote_article(
    platform: str,
    token: str,
    remote_id: str,
    expected_title: str | None = None,
    expected_canonical_url: str | None = None,
) -> RemoteArticle | None:
    """Fetch one linked record, returning None only when a complete listing omits it."""
    try:
        if platform == "devto":
            records = DevToClient(token).list_my_articles(per_page=100, page=1)
            match = next((item for item in records if str(item.article_id) == remote_id), None)
            if match is None:
                return None
            return RemoteArticle(
                platform=platform,
                remote_id=str(match.article_id),
                title=match.title,
                content=match.body_markdown,
                canonical_url=match.canonical_url,
                remote_url=match.url,
                status="published" if match.published else "draft",
                updated_at=_iso(match.updated_at),
                metadata={
                    "description": match.description,
                    "cover_image": match.cover_image,
                },
            )
        if platform == "hashnode":
            client = HashnodeClient(token)
            records = [*client.list_drafts(first=100), *client.list_published_articles(post_first=100)]
            match = next((item for item in records if str(item.article_id) == remote_id), None)
            if match is None and expected_canonical_url:
                canonical_matches = [
                    item for item in records
                    if item.canonical_url == expected_canonical_url
                ]
                match = canonical_matches[0] if len(canonical_matches) == 1 else None
            if match is None and expected_title:
                normalized_title = " ".join(expected_title.casefold().split())
                title_matches = [
                    item for item in records
                    if " ".join(item.title.casefold().split()) == normalized_title
                ]
                match = title_matches[0] if len(title_matches) == 1 else None
            if match is None:
                return None
            return RemoteArticle(
                platform=platform,
                remote_id=str(match.article_id),
                title=match.title,
                content=match.body_markdown,
                canonical_url=match.canonical_url,
                remote_url=match.url,
                status="published" if match.published else "draft",
                updated_at=_iso(match.updated_at),
                metadata={
                    "subtitle": match.subtitle,
                    "cover_image": match.cover_image_url,
                },
            )
    except Exception as exc:
        raise ReconciliationError(str(exc)) from exc
    raise ReconciliationError(f"Reconciliation is not supported for {platform}")


def refresh(store: Any, user_id: str, article_id: str, platform: str,
            *, fetcher: RemoteFetcher | None = None) -> dict:
    article = store.get_article(user_id, article_id)
    if article is None:
        raise KeyError(article_id)
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(platform)

    current_revision = store.get_current_article_revision(user_id, article_id)
    assert current_revision is not None
    local_fingerprint = content_fingerprint(
        current_revision["title"], current_revision["content"], article.get("canonical_url")
    )
    destination = article["destinations"].get(platform) or {}
    remote_id = destination.get("draft_id")
    previous = store.get_latest_remote_snapshot(user_id, article_id, platform)

    common = {
        "platform": platform,
        "remote_id": remote_id,
        "local_revision_id": current_revision["id"],
        "local_fingerprint": local_fingerprint,
    }
    if not remote_id:
        return store.record_remote_snapshot(user_id, article_id, {
            **common,
            "availability": "unlinked",
            "sync_state": "unlinked",
            "error": "No remote article ID is linked to this destination.",
        })

    token = store.get_connection_token(user_id, platform)
    if not token:
        return store.record_remote_snapshot(user_id, article_id, {
            **common,
            "availability": "inaccessible",
            "sync_state": "inaccessible",
            "error": f"{platform} is not connected.",
        })

    try:
        remote = (fetcher or fetch_remote_article)(
            platform,
            token,
            remote_id,
            article["title"],
            article.get("canonical_url"),
        )
    except ReconciliationError as exc:
        return store.record_remote_snapshot(user_id, article_id, {
            **common,
            "availability": "inaccessible",
            "sync_state": "inaccessible",
            "error": str(exc),
        })
    if remote is None:
        return store.record_remote_snapshot(user_id, article_id, {
            **common,
            "availability": "deleted",
            "sync_state": "remote_deleted",
            "error": "The linked remote article no longer exists or is no longer visible.",
        })

    remote_fingerprint = content_fingerprint(
        remote.title, remote.content, remote.canonical_url
    )
    sync_state = _classify(local_fingerprint, remote_fingerprint, previous)
    return store.record_remote_snapshot(user_id, article_id, {
        **common,
        "remote_id": remote.remote_id,
        "availability": "available",
        "sync_state": sync_state,
        "remote_fingerprint": remote_fingerprint,
        "title": remote.title,
        "content": remote.content,
        "canonical_url": remote.canonical_url,
        "remote_url": remote.remote_url,
        "remote_status": remote.status,
        "remote_updated_at": remote.updated_at,
        "metadata": remote.metadata,
    })


def current_view(store: Any, user_id: str, article_id: str, snapshot: dict) -> dict:
    article = store.get_article(user_id, article_id)
    revision = store.get_current_article_revision(user_id, article_id)
    if article is None or revision is None:
        raise KeyError(article_id)
    current_fingerprint = content_fingerprint(
        revision["title"], revision["content"], article.get("canonical_url")
    )
    state = snapshot["sync_state"]
    if snapshot["availability"] == "available":
        if current_fingerprint == snapshot["remote_fingerprint"]:
            state = "in_sync"
        elif current_fingerprint != snapshot["local_fingerprint"]:
            state = "conflict" if snapshot["sync_state"] in {"remote_ahead", "conflict"} else "local_ahead"
    return {**snapshot, "sync_state": state, "current_revision_id": revision["id"]}


def acknowledge_local(store: Any, user_id: str, article_id: str, platform: str) -> dict:
    latest = store.get_latest_remote_snapshot(user_id, article_id, platform)
    if latest is None or latest["availability"] != "available":
        raise ValueError("No available remote snapshot can be resolved")
    article = store.get_article(user_id, article_id)
    revision = store.get_current_article_revision(user_id, article_id)
    assert article is not None and revision is not None
    return store.record_remote_snapshot(user_id, article_id, {
        **latest,
        "id": None,
        "local_revision_id": revision["id"],
        "local_fingerprint": content_fingerprint(
            revision["title"], revision["content"], article.get("canonical_url")
        ),
        "sync_state": "local_ahead",
    })


def import_remote(store: Any, user_id: str, article_id: str, platform: str,
                  expected_revision_id: str) -> dict:
    latest = store.get_latest_remote_snapshot(user_id, article_id, platform)
    if latest is None or latest["availability"] != "available":
        raise ValueError("No available remote snapshot can be imported")
    return store.save_article_revision(
        user_id,
        article_id,
        title=latest["title"],
        content=latest["content"],
        expected_revision_id=expected_revision_id,
        source="import",
        description=f"Accepted remote {platform.title()} version",
    )


def _classify(local_fingerprint: str, remote_fingerprint: str,
              previous: dict | None) -> str:
    if local_fingerprint == remote_fingerprint:
        return "in_sync"
    if previous is None or previous["availability"] != "available":
        return "conflict"
    local_changed = local_fingerprint != previous["local_fingerprint"]
    remote_changed = remote_fingerprint != previous["remote_fingerprint"]
    if local_changed and remote_changed:
        return "conflict"
    if remote_changed:
        return "conflict" if previous["sync_state"] == "local_ahead" else "remote_ahead"
    if local_changed:
        return "conflict" if previous["sync_state"] == "remote_ahead" else "local_ahead"
    return previous["sync_state"] if previous["sync_state"] != "in_sync" else "conflict"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
