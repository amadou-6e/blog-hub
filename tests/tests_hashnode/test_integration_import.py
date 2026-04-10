"""
Integration test: full Hashnode import flow with images.

Steps validated:
1. Create a draft on Hashnode with markdown images (GitHub raw URLs).
2. Confirm the draft is discoverable via the drafts list API (paginated all-fetch).
3. Confirm the draft detail API returns status 200 with the full body + images.
4. Confirm images are absolute URLs (so browsers can render them without a proxy).
5. Import the article via POST /api/articles/import and verify a workspace article
   is created with the correct title and body containing the image markdown.

Requires:
    HASHNODE_PAT env var (or in root .env file)
    A running BlogHub dev server is NOT required — tests use FastAPI TestClient.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
import backend.store as store
from blogs.hashnode.client import HashnodeClient
from blogs.hashnode.render import prepare_draft

_REPO_ROOT = Path(__file__).resolve().parents[3]  # py-dockerdb/
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

# Images from the real blog-components repo (raw GitHub, CORS-enabled)
_IMAGE_BASE = (
    "https://raw.githubusercontent.com/amadou-6e/blog-components/main/"
    "medium/002_neo4j_llamaindex/images"
)
_SAMPLE_MARKDOWN_WITH_IMAGES = """\
# BlogHub import integration test — images {suffix}

This draft is created by the BlogHub import integration test suite.

## Introduction

An article with real images to validate end-to-end import preview.

![Title image]({base}/title.png)

## How it works

The import wizard fetches this draft's body via `draft(id: $id)` and renders
the markdown including images in the browser preview.

![Architecture diagram]({base}/knowledge_graph.png)

## Code example

```python
from llama_index.core import KnowledgeGraphIndex
index = KnowledgeGraphIndex.from_documents(docs)
```

## Summary

End-to-end import confirmed.

**Tags:** integration, images
"""


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


def _read_first_publication_id(client: HashnodeClient) -> str:
    query = """
    query MePublications($first: Int!) {
      me {
        publications(first: $first) {
          edges { node { id title } }
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
    edges = response.json()["data"]["me"]["publications"]["edges"]
    if not edges:
        raise AssertionError("No Hashnode publications available for this token")
    return edges[0]["node"]["id"]


# ---------------------------------------------------------------------------
# Helpers shared across test functions
# ---------------------------------------------------------------------------

def _build_sample_markdown(suffix: str) -> str:
    return _SAMPLE_MARKDOWN_WITH_IMAGES.format(base=_IMAGE_BASE, suffix=suffix)


@pytest.fixture(scope="module")
def _integration_setup():
    """
    Module-scoped fixture that:
      1. Reads credentials and skips if absent.
      2. Creates a single Hashnode draft with images.
      3. Registers the Hashnode token in the BlogHub store.
      4. Yields a dict with client, draft_id, title, suffix.
    """
    pat = _read_secret("HASHNODE_PAT")
    if not pat:
        pytest.skip("HASHNODE_PAT is not set — skipping Hashnode import integration tests")

    hashnode_client = HashnodeClient(pat)
    pub_id = _read_secret("HASHNODE_PUBLICATION_ID") or _read_first_publication_id(hashnode_client)

    suffix = str(int(time.time()))
    title = f"BlogHub import integration test — images {suffix}"
    markdown = _build_sample_markdown(suffix)

    prepared = prepare_draft(
        markdown,
        publication_id=pub_id,
        canonical_url=f"https://example.com/bloghub/import-test/{suffix}",
        cover_image_url=f"{_IMAGE_BASE}/title.png",
        tags=("integration", "bloghub"),
    )
    result = hashnode_client.create_draft(prepared.draft)
    draft_id = result.draft_id

    artifact = {"draft_id": draft_id, "title": title, "suffix": suffix}
    artifact_path = _FIXTURES_DIR / f"import_integration_{suffix}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    yield {
        "pat": pat,
        "hashnode_client": hashnode_client,
        "draft_id": draft_id,
        "title": title,
        "suffix": suffix,
        "markdown": markdown,
    }

    store.reset()


@pytest.fixture(autouse=True)
def _reset_store_between_tests(_integration_setup):
    """
    Override conftest's reset_store for this module.
    We still reset but immediately restore the Hashnode connection so that
    each test gets a clean article/job state while keeping the platform token.
    """
    pat = _integration_setup["pat"]
    store.reset()
    store.save_connection("hashnode", token=pat, status="connected", username="test")
    yield
    store.reset()


@pytest.mark.integration
class TestHashnodeImportFlow:
    """
    End-to-end import test: publish draft with images → fetch list → fetch detail
    → import article → verify body and images.
    """

    # ── 1. Draft appears in list (paginated) ──────────────────────────────

    def test_draft_appears_in_draft_list(self, _integration_setup):
        """The newly created draft must be discoverable via GET /api/connections/hashnode/drafts."""
        draft_id = _integration_setup["draft_id"]
        title = _integration_setup["title"]

        api_client = TestClient(app)
        r = api_client.get("/api/connections/hashnode/drafts", params={"per_page": 200, "page": 1})
        assert r.status_code == 200, f"Drafts list failed: {r.text}"

        data = r.json()
        ids = [d["id"] for d in data["drafts"]]
        titles = [d["title"] for d in data["drafts"]]

        assert draft_id in ids, (
            f"Draft {draft_id!r} ({title!r}) not found in list of {len(ids)} drafts. "
            f"First 5 titles: {titles[:5]}"
        )

    # ── 2. Draft detail returns body + images ────────────────────────────

    def test_draft_detail_returns_body(self, _integration_setup):
        """GET /api/connections/hashnode/drafts/{id} must return HTTP 200 with body string."""
        draft_id = _integration_setup["draft_id"]

        api_client = TestClient(app)
        r = api_client.get(f"/api/connections/hashnode/drafts/{draft_id}")
        assert r.status_code == 200, f"Draft detail failed: {r.text}"

        data = r.json()
        assert isinstance(data["body"], str), "body field must be a string"
        assert len(data["body"]) > 100, "body was unexpectedly short"

    def test_draft_detail_body_is_string_not_object(self, _integration_setup):
        """The body field must be a plain string (guard against [object Object] regression)."""
        draft_id = _integration_setup["draft_id"]

        api_client = TestClient(app)
        data = api_client.get(f"/api/connections/hashnode/drafts/{draft_id}").json()

        assert isinstance(data["body"], str), (
            f"body must be str, got {type(data['body']).__name__}: {str(data['body'])[:80]}"
        )

    def test_draft_detail_images_present(self, _integration_setup):
        """Body must contain at least one markdown image line with an absolute URL."""
        draft_id = _integration_setup["draft_id"]

        api_client = TestClient(app)
        data = api_client.get(f"/api/connections/hashnode/drafts/{draft_id}").json()
        body: str = data["body"]

        image_lines = [line for line in body.splitlines() if line.strip().startswith("![")]
        assert len(image_lines) >= 1, f"Expected at least 1 image in body, found 0.\nBody[:400]:\n{body[:400]}"

        # All image URLs must be absolute so a browser can load them
        import re
        for line in image_lines:
            m = re.search(r"!\[.*?\]\((.+?)\)", line)
            if m:
                url = m.group(1)
                assert url.startswith("http"), (
                    f"Image URL is not absolute: {url!r} — browser cannot render it"
                )

    def test_draft_detail_cover_image_present(self, _integration_setup):
        """cover_image field must be a non-empty absolute URL."""
        draft_id = _integration_setup["draft_id"]
        api_client = TestClient(app)
        data = api_client.get(f"/api/connections/hashnode/drafts/{draft_id}").json()

        cover = data.get("cover_image")
        assert cover, "cover_image must be set for this draft"
        assert cover.startswith("http"), f"cover_image is not an absolute URL: {cover!r}"

    # ── 3. Import creates workspace article ──────────────────────────────

    def test_import_creates_article(self, _integration_setup):
        """POST /api/articles/import must create an article and return 201."""
        draft_id = _integration_setup["draft_id"]
        title = _integration_setup["title"]

        api_client = TestClient(app)
        r = api_client.post("/api/articles/import", json={
            "source": "platform",
            "platform": "hashnode",
            "draft_id": draft_id,
            "title": title,
            # no content — backend must fetch it via _fetch_draft → get_draft_by_id
        })
        assert r.status_code == 201, f"Import failed: {r.text}"
        assert "id" in r.json()

    def test_import_article_body_contains_images(self, _integration_setup):
        """Imported article body must contain the image markdown."""
        draft_id = _integration_setup["draft_id"]
        title = _integration_setup["title"]
        suffix = _integration_setup["suffix"]

        api_client = TestClient(app)
        result = api_client.post("/api/articles/import", json={
            "source": "platform",
            "platform": "hashnode",
            "draft_id": draft_id,
            "title": f"{title} (body-check {suffix})",
        }).json()
        article_id = result["id"]

        # Fetch the article detail to check body (field is "content" in the detail endpoint)
        detail = api_client.get(f"/api/articles/{article_id}").json()
        body = detail.get("content", "") or detail.get("body", "")
        assert body, f"Article body is empty after import. article_id={article_id}"

        image_lines = [l for l in body.splitlines() if l.strip().startswith("![")]
        assert len(image_lines) >= 1, (
            f"No image markdown found in imported article body.\n"
            f"Body[:400]:\n{body[:400]}"
        )

    def test_import_idempotent_deduplication(self, _integration_setup):
        """Importing the same draft twice must not create a duplicate article."""
        draft_id = _integration_setup["draft_id"]
        title = _integration_setup["title"]
        dedup_title = f"{title} (dedup)"

        api_client = TestClient(app)
        id1 = api_client.post("/api/articles/import", json={
            "source": "platform",
            "platform": "hashnode",
            "draft_id": draft_id,
            "title": dedup_title,
        }).json()["id"]
        id2 = api_client.post("/api/articles/import", json={
            "source": "platform",
            "platform": "hashnode",
            "draft_id": draft_id,
            "title": dedup_title,
        }).json()["id"]
        assert id1 == id2, "Duplicate import must return the same article id"
