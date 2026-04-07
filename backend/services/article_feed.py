"""Live overview article feed built from connected external platforms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Callable

from blogs.devto.client import DevToClient, DevToError, DevToRemoteArticle
from blogs.hashnode.client import HashnodeClient, HashnodeError, HashnodeRemoteArticle
from backend.services.preview_images import resolve_preview_image_url


TokenResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class OverviewExternalArticle:
    """Normalized cross-platform article used to populate the overview."""

    platform: str
    remote_id: str
    title: str
    body: str
    url: str | None
    canonical_url: str | None
    updated_at: datetime
    word_count: int
    status: str
    title_image_url: str | None


def fetch_live_overview_articles(get_connection_token: TokenResolver) -> list[dict]:
    """Build overview articles from live DEV.to and Hashnode content."""
    sources = _fetch_external_sources(get_connection_token)
    if not sources:
        return []

    grouped: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for source in sources:
        article_key = _resolve_article_key(source, grouped, aliases)
        article = grouped.get(article_key)
        if article is None:
            article = _new_article_shell(source, article_key)
            grouped[article_key] = article
            for candidate in _article_key_candidates(source):
                aliases[candidate] = article_key

        article["updated_at"] = max(article["updated_at"], source.updated_at)
        article["word_count"] = max(article["word_count"], source.word_count)
        if len(source.body.split()) > len((article.get("body") or "").split()):
            article["body"] = source.body

        article["destinations"][source.platform] = {
            "status": source.status,
            "label": _status_label(source.status),
            "url": source.url,
            "error": None,
            "draft_id": source.remote_id,
        }
        article["recent_timeline"].append(
            {
                "timestamp": source.updated_at,
                "event": _timeline_event(source),
            }
        )
        for candidate in _article_key_candidates(source):
            aliases[candidate] = article_key

    items = list(grouped.values())
    for article in items:
        article["recent_timeline"].sort(key=lambda item: item["timestamp"], reverse=True)
        article["recent_timeline"] = article["recent_timeline"][:5]
        article["preview_image_url"] = resolve_preview_image_url(
            article_id=article["id"],
            title_image_url=article.get("title_image_url"),
            page_url=_preferred_page_url(article),
        )
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return items


def _fetch_external_sources(get_connection_token: TokenResolver) -> list[OverviewExternalArticle]:
    articles: list[OverviewExternalArticle] = []

    devto_token = _resolve_secret("devto", get_connection_token, env_name="DEVTO_API_KEY")
    if devto_token:
        try:
            client = DevToClient(devto_token)
            articles.extend(_map_devto_article(article) for article in client.list_my_articles())
        except DevToError:
            pass

    hashnode_token = _resolve_secret("hashnode", get_connection_token, env_name="HASHNODE_PAT")
    if hashnode_token:
        client = HashnodeClient(hashnode_token)
        try:
            articles.extend(_map_hashnode_article(article) for article in client.list_drafts())
        except HashnodeError:
            pass
        try:
            articles.extend(_map_hashnode_article(article) for article in client.list_published_articles())
        except HashnodeError:
            pass

    return articles


def _new_article_shell(source: OverviewExternalArticle, article_key: str) -> dict:
    destinations = {
        "medium": {"status": "none", "label": "None", "url": None, "error": None},
        "hashnode": {"status": "none", "label": "None", "url": None, "error": None},
        "devto": {"status": "none", "label": "None", "url": None, "error": None},
    }
    return {
        "id": article_key,
        "title": source.title,
        "body": source.body,
        "updated_at": source.updated_at,
        "word_count": source.word_count,
        "gate": "pending",
        "title_image_url": source.title_image_url,
        "preview_image_url": None,
        "destinations": destinations,
        "recent_timeline": [],
    }


def _resolve_article_key(
    source: OverviewExternalArticle,
    grouped: dict[str, dict],
    aliases: dict[str, str],
) -> str:
    for candidate in _article_key_candidates(source):
        article_key = aliases.get(candidate)
        if article_key and article_key in grouped:
            return article_key
    return _article_key_from_value(_primary_group_value(source))


def _article_key_candidates(source: OverviewExternalArticle) -> list[str]:
    candidates = [_article_key_from_value(_primary_group_value(source))]
    normalized_title = _normalize_text(source.title)
    normalized_body = _normalize_text(source.body)
    if normalized_title:
        candidates.append(_article_key_from_value(f"title:{normalized_title}"))
    if normalized_title and normalized_body:
        candidates.append(_article_key_from_value(f"title-body:{normalized_title}:{normalized_body[:160]}"))
    if source.canonical_url:
        candidates.append(_article_key_from_value(f"canonical:{source.canonical_url.strip().lower()}"))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _primary_group_value(source: OverviewExternalArticle) -> str:
    normalized_title = _normalize_text(source.title)
    normalized_body = _normalize_text(source.body)
    if normalized_title and normalized_body:
        return f"title-body:{normalized_title}:{normalized_body[:160]}"
    if normalized_title:
        return f"title:{normalized_title}"
    if source.canonical_url:
        return f"canonical:{source.canonical_url.strip().lower()}"
    return source.remote_id


def _article_key_from_value(raw_value: str) -> str:
    digest = hashlib.sha1(raw_value.encode("utf-8")).hexdigest()[:10]
    return f"live_{digest}"


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _status_label(status: str) -> str:
    if status == "published":
        return "Published"
    if status == "draft":
        return "Draft"
    return status.title()


def _timeline_event(source: OverviewExternalArticle) -> str:
    if source.status == "published":
        return f"Fetched published article from {_platform_label(source.platform)}"
    return f"Fetched draft from {_platform_label(source.platform)}"


def _platform_label(platform: str) -> str:
    if platform == "devto":
        return "Dev.to"
    if platform == "hashnode":
        return "Hashnode"
    return platform.title()


def _map_devto_article(article: DevToRemoteArticle) -> OverviewExternalArticle:
    body = article.body_markdown.strip()
    updated_at = article.updated_at or datetime.now(tz=timezone.utc)
    return OverviewExternalArticle(
        platform="devto",
        remote_id=str(article.article_id),
        title=article.title,
        body=body,
        url=article.url,
        canonical_url=article.canonical_url,
        updated_at=updated_at,
        word_count=_word_count(body),
        status="published" if article.published else "draft",
        title_image_url=article.cover_image,
    )


def _map_hashnode_article(article: HashnodeRemoteArticle) -> OverviewExternalArticle:
    body = article.body_markdown.strip()
    updated_at = article.updated_at or datetime.now(tz=timezone.utc)
    return OverviewExternalArticle(
        platform="hashnode",
        remote_id=article.article_id,
        title=article.title,
        body=body,
        url=article.url,
        canonical_url=article.canonical_url,
        updated_at=updated_at,
        word_count=_word_count(body),
        status="published" if article.published else "draft",
        title_image_url=article.cover_image_url,
    )


def _preferred_page_url(article: dict) -> str | None:
    destinations = article.get("destinations") or {}
    for status in ("published", "draft", "ready", "review", "pending"):
        for platform_name in ("medium", "hashnode", "devto"):
            destination = destinations.get(platform_name) or {}
            if destination.get("status") == status and destination.get("url"):
                return destination["url"]
    return None


def _word_count(markdown_text: str) -> int:
    words = markdown_text.split()
    return len(words)


def _resolve_secret(conn_id: str, get_connection_token: TokenResolver, *, env_name: str) -> str | None:
    token = (get_connection_token(conn_id) or "").strip()
    if token:
        return token
    env_token = os.environ.get(env_name, "").strip()
    if env_token:
        return env_token
    env_path = _repo_env_path()
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == env_name:
            return value.strip()
    return None


def _repo_env_path() -> Path:
    services_dir = Path(__file__).resolve().parents[2]
    return Path(services_dir.parent, ".env")
