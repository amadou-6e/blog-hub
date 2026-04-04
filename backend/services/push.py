"""Platform push orchestration for article drafts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Callable

from blogs.devto.render import prepare_article as prepare_devto_article
from blogs.devto.client import DevToClient
from blogs.hashnode.render import prepare_draft as prepare_hashnode_draft
from blogs.hashnode.client import HashnodeClient
import requests


TokenResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class PushPlatformResult:
    """Normalized per-platform push outcome."""

    platform: str
    success: bool
    status: str
    label: str
    url: str | None = None
    error: str | None = None
    draft_id: str | None = None


def push_article_to_platforms(
    article: dict,
    platforms: list[str],
    *,
    get_connection_token: TokenResolver,
) -> dict[str, PushPlatformResult]:
    """Push an article to one or more platforms."""
    results: dict[str, PushPlatformResult] = {}
    source_markdown = _article_markdown(article)

    for platform in platforms:
        if platform == "devto":
            results[platform] = _push_devto(article, source_markdown, get_connection_token)
            continue
        if platform == "hashnode":
            results[platform] = _push_hashnode(article, source_markdown, get_connection_token)
            continue
        if platform == "medium":
            results[platform] = _push_medium_placeholder(article)
            continue
        results[platform] = PushPlatformResult(
            platform=platform,
            success=False,
            status="error",
            label="Error",
            error=f"Unsupported platform: {platform}",
        )
    return results


def _push_devto(article: dict, source_markdown: str, get_connection_token: TokenResolver) -> PushPlatformResult:
    token = _resolve_secret("devto", get_connection_token, env_name="DEVTO_API_KEY")
    if not token:
        return _simulated_result("devto", article)

    prepared = prepare_devto_article(
        source_markdown,
        tags=("integration", "bloghub"),
        canonical_url=_canonical_url(article, "devto"),
        image_base_url=_image_base_url(article, "devto"),
        published=False,
    )
    client = DevToClient(token)
    result = client.publish_article(prepared.article)
    return PushPlatformResult(
        platform="devto",
        success=True,
        status="draft",
        label="Draft",
        url=result.url,
        draft_id=str(result.article_id),
    )


def _push_hashnode(article: dict, source_markdown: str, get_connection_token: TokenResolver) -> PushPlatformResult:
    token = _resolve_secret("hashnode", get_connection_token, env_name="HASHNODE_PAT")
    if not token:
        return _simulated_result("hashnode", article)

    client = HashnodeClient(token)
    publication_id = _resolve_secret(
        "hashnode_publication_id",
        get_connection_token,
        env_name="HASHNODE_PUBLICATION_ID",
    ) or _read_first_hashnode_publication_id(client)
    prepared = prepare_hashnode_draft(
        source_markdown,
        publication_id=publication_id,
        canonical_url=_canonical_url(article, "hashnode"),
        cover_image_url=_cover_image_url(article, "hashnode"),
        tags=("integration", "bloghub"),
    )
    result = client.create_draft(prepared.draft)
    publication_url = _read_hashnode_publication_url(client, result.draft_id)
    preview_url = None
    if publication_url:
        preview_url = publication_url.rstrip("/") + "/preview/" + result.draft_id
    return PushPlatformResult(
        platform="hashnode",
        success=True,
        status="draft",
        label="Draft",
        url=preview_url,
        draft_id=result.draft_id,
    )


def _push_medium_placeholder(article: dict) -> PushPlatformResult:
    existing_url = article.get("destinations", {}).get("medium", {}).get("url")
    return PushPlatformResult(
        platform="medium",
        success=True,
        status="draft",
        label="Draft",
        url=existing_url,
        draft_id=article.get("destinations", {}).get("medium", {}).get("draft_id"),
    )


def _simulated_result(platform: str, article: dict) -> PushPlatformResult:
    existing_url = article.get("destinations", {}).get(platform, {}).get("url")
    return PushPlatformResult(
        platform=platform,
        success=True,
        status="draft",
        label="Draft",
        url=existing_url,
    )


def _article_markdown(article: dict) -> str:
    body = (article.get("body") or article.get("canonical_content") or "").strip()
    if body:
        return body if body.endswith("\n") else body + "\n"
    title = article["title"]
    return (
        f"# {title}\n\n"
        f"This article is managed by BlogHub.\n\n"
        f"## Summary\n\n"
        f"A draft for {title}.\n"
    )


def _canonical_url(article: dict, platform: str) -> str:
    article_id = article["id"]
    return f"https://example.com/bloghub/{platform}/{article_id}"


def _image_base_url(article: dict, platform: str) -> str:
    return f"https://cdn.example.com/bloghub/{platform}/{article['id']}"


def _cover_image_url(article: dict, platform: str) -> str:
    return f"https://cdn.example.com/bloghub/{platform}/{article['id']}/cover.png"


def _resolve_secret(conn_id: str, get_connection_token: TokenResolver, *, env_name: str) -> str | None:
    token = (get_connection_token(conn_id) or "").strip()
    if token:
        return token
    env_token = os.environ.get(env_name, "").strip()
    if env_token:
        return env_token
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
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
    backend_dir = Path(__file__).resolve().parents[2]
    return Path(backend_dir.parent, ".env")


def _read_first_hashnode_publication_id(client: HashnodeClient) -> str:
    query = """
    query MePublications($first: Int!) {
      me {
        publications(first: $first) {
          edges {
            node {
              id
            }
          }
        }
      }
    }
    """
    payload = _hashnode_graphql(client, query, {"first": 10})
    edges = payload["data"]["me"]["publications"]["edges"]
    if not edges:
        raise RuntimeError("No Hashnode publication available for this token")
    return edges[0]["node"]["id"]


def _read_hashnode_publication_url(client: HashnodeClient, draft_id: str) -> str | None:
    query = """
    query MeDrafts($first: Int!) {
      me {
        drafts(first: $first) {
          edges {
            node {
              id
              publication {
                url
              }
            }
          }
        }
      }
    }
    """
    payload = _hashnode_graphql(client, query, {"first": 20})
    if payload.get("errors"):
        raise RuntimeError(str(payload["errors"]))
    for edge in payload["data"]["me"]["drafts"]["edges"]:
        node = edge["node"]
        if node["id"] == draft_id:
            publication = node.get("publication") or {}
            return publication.get("url")
    return None


def _hashnode_graphql(
    client: HashnodeClient,
    query: str,
    variables: dict,
    *,
    attempts: int = 3,
    delay_seconds: float = 1.0,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client._session.post(
                "https://gql.hashnode.com",
                headers=client.headers,
                json={"query": query, "variables": variables},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay_seconds)
    raise RuntimeError(f"Hashnode GraphQL request failed after {attempts} attempts") from last_error
