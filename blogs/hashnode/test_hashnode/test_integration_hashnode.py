"""Live Hashnode integration tests that validate actual platform behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from blogs.hashnode.client import HashnodeClient
from blogs.hashnode.render import prepare_draft


_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SAMPLE_MARKDOWN = """# BlogHub Hashnode integration test

This draft verifies that the live Hashnode integration can create a draft and
return stored content through the authenticated drafts query.

## What this checks

- the title survives round-trip
- the body markdown is still present in the retrieved draft content
- the subtitle and cover image survive round-trip

```python
print("hashnode integration")
```

**Tags:** integration, hashnode
"""


def _normalize_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").split()).lower()


def _read_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if key.strip() == name:
            return raw_value.strip()
    return ""


def _read_draft_by_id(client: HashnodeClient, draft_id: str) -> dict:
    query = """
    query MeDraftById($first: Int!) {
      me {
        drafts(first: $first) {
          edges {
                node {
                  id
                  title
                  subtitle
                  canonicalUrl
                  coverImage {
                    url
                  }
                  publication {
                    url
                    title
                  }
              content {
                markdown
                html
                text
              }
            }
          }
        }
      }
    }
    """
    response = client._session.post(
        "https://gql.hashnode.com",
        headers=client.headers,
        json={"query": query, "variables": {"first": 20}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise AssertionError(f"Unexpected Hashnode drafts query errors: {payload['errors']}")
    edges = payload["data"]["me"]["drafts"]["edges"]
    for edge in edges:
        node = edge["node"]
        if node["id"] == draft_id:
            return node
    raise AssertionError(f"Draft {draft_id} not found in authenticated drafts query")


def _build_preview_url(publication_url: str | None, draft_id: str) -> str | None:
    if not publication_url:
        return None
    return publication_url.rstrip("/") + "/preview/" + draft_id


def _read_first_publication_id(client: HashnodeClient) -> str:
    query = """
    query MePublications($first: Int!) {
      me {
        publications(first: $first) {
          edges {
            node {
              id
              title
            }
          }
        }
      }
    }
    """
    response = client._session.post(
        "https://gql.hashnode.com",
        headers=client.headers,
        json={"query": query, "variables": {"first": 10}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    edges = payload["data"]["me"]["publications"]["edges"]
    if not edges:
        raise AssertionError("No Hashnode publications available for this token")
    return edges[0]["node"]["id"]


@pytest.mark.integration
def test_hashnode_live_draft_round_trip():
    personal_access_token = _read_secret("HASHNODE_PAT")
    if not personal_access_token:
        pytest.skip("HASHNODE_PAT is not set")

    client = HashnodeClient(personal_access_token)
    publication_id = _read_secret("HASHNODE_PUBLICATION_ID") or _read_first_publication_id(client)

    unique_suffix = str(int(time.time()))
    cover_image_url = f"https://cdn.example.com/bloghub/hashnode/{unique_suffix}/cover.png"
    source_markdown = _SAMPLE_MARKDOWN.replace(
        "# BlogHub Hashnode integration test",
        f"# BlogHub Hashnode integration test {unique_suffix}",
    )
    prepared = prepare_draft(
        source_markdown,
        publication_id=publication_id,
        canonical_url=f"https://example.com/bloghub/hashnode/{unique_suffix}",
        cover_image_url=cover_image_url,
        tags=("integration", "hashnode"),
    )

    created = client.create_draft(prepared.draft)
    live_draft = _read_draft_by_id(client, created.draft_id)

    artifact = {
        "created": {
            "draft_id": created.draft_id,
            "canonical_url": created.canonical_url,
            "cover_image_url": created.cover_image_url,
            "preview_url": _build_preview_url(
                (live_draft.get("publication") or {}).get("url"),
                created.draft_id,
            ),
        },
        "expected": {
            "title": prepared.draft.title,
            "subtitle": prepared.draft.subtitle,
            "content_markdown": prepared.draft.content_markdown,
            "cover_image_url": prepared.draft.cover_image_url,
        },
        "actual": live_draft,
    }
    artifact_path = _FIXTURES_DIR / f"hashnode_live_roundtrip_{unique_suffix}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    assert live_draft["title"] == prepared.draft.title
    assert live_draft.get("subtitle") == prepared.draft.subtitle
    assert (live_draft.get("coverImage") or {}).get("url") == prepared.draft.cover_image_url

    actual_markdown = live_draft["content"]["markdown"]
    assert _normalize_text(prepared.draft.content_markdown) in _normalize_text(actual_markdown)

    expected_tokens = [
        "the title survives round-trip",
        "the body markdown is still present in the retrieved draft content",
        "print(\"hashnode integration\")",
    ]
    normalized_markdown = _normalize_text(actual_markdown)
    for token in expected_tokens:
        assert _normalize_text(token) in normalized_markdown
