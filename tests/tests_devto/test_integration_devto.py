"""Live DEV.to integration tests that validate actual platform behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote
import time

import pytest

from blogs.devto.client import DevToClient
from blogs.devto.render import prepare_article


_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SAMPLE_MARKDOWN = """![Hero](images/title.png)

# BlogHub DEV.to integration test

This draft verifies that the live DEV.to integration can create a draft and
return the stored markdown through the authenticated article listing API.

## What this checks

- the title survives round-trip
- the body markdown survives round-trip
- local images are rewritten for the publish payload

```python
print("devto integration")
```

**Tags:** integration, devto
"""
_IMAGE_BASE_URL = "https://cdn.example.com/bloghub/devto"


def _normalize_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").split())


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


@pytest.mark.integration
def test_devto_live_draft_round_trip():
    api_key = _read_secret("DEVTO_API_KEY")
    if not api_key:
        pytest.skip("DEVTO_API_KEY is not set")

    unique_suffix = str(int(time.time()))
    source_markdown = _SAMPLE_MARKDOWN.replace(
        "# BlogHub DEV.to integration test",
        f"# BlogHub DEV.to integration test {unique_suffix}",
    )
    prepared = prepare_article(
        source_markdown,
        image_base_url=_IMAGE_BASE_URL,
        tags=("integration", "devto"),
        canonical_url=f"https://example.com/bloghub/devto/{unique_suffix}",
        published=False,
    )

    client = DevToClient(api_key)
    created = client.publish_article(prepared.article)

    listing_response = client._session.get(
        "https://dev.to/api/articles/me/all",
        headers=client.headers,
        timeout=30,
    )
    listing_response.raise_for_status()
    articles = listing_response.json()
    live_article = next((item for item in articles if int(item["id"]) == created.article_id), None)
    assert live_article is not None, f"Created draft {created.article_id} not found in /me/all"

    artifact = {
        "created": {
            "article_id": created.article_id,
            "url": created.url,
        },
        "expected": {
            "title": prepared.article.title,
            "body_markdown": prepared.article.body_markdown,
            "description": prepared.article.description,
            "canonical_url": prepared.article.canonical_url,
        },
        "actual": {
            "id": live_article["id"],
            "title": live_article["title"],
            "body_markdown": live_article["body_markdown"],
            "description": live_article.get("description"),
            "canonical_url": live_article.get("canonical_url"),
            "cover_image": live_article.get("cover_image"),
            "published": live_article.get("published"),
            "url": live_article.get("url"),
        },
    }
    artifact_path = _FIXTURES_DIR / f"devto_live_roundtrip_{unique_suffix}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    assert live_article["published"] is False
    assert live_article["title"] == prepared.article.title
    assert live_article.get("canonical_url") == prepared.article.canonical_url
    assert live_article.get("description") == prepared.article.description
    cover_image = live_article.get("cover_image")
    assert isinstance(cover_image, str) and quote(prepared.article.main_image, safe="") in cover_image
    assert live_article["body_markdown"] == prepared.article.body_markdown

    expected_tokens = [
        "the title survives round-trip",
        "the body markdown survives round-trip",
        "print(\"devto integration\")",
    ]
    actual_text = _normalize_text(live_article["body_markdown"])
    for token in expected_tokens:
        assert _normalize_text(token) in actual_text
