"""Live backend push tests that exercise the full API -> platform chain."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient


_blog_hub_root = Path(__file__).resolve().parents[2]
if str(_blog_hub_root) not in sys.path:
    sys.path.insert(0, str(_blog_hub_root))

from backend.main import app
import backend.store as store


_REPO_ROOT = Path(__file__).resolve().parents[3]
_ARTIFACT_DIR = Path(__file__).resolve().parent / "fixtures"
_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


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


@pytest.fixture(autouse=True)
def reset_store():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


def _prepare_article_body(title: str, token: str) -> str:
    return (
        f"# {title}\n\n"
        "This article validates the full backend push chain from the REST API to the external platform.\n\n"
        "## Checks\n\n"
        "- request enters the API router\n"
        "- platform renderer transforms the markdown\n"
        "- platform client creates a real draft\n"
        "- article store receives the resulting URL\n\n"
        "```python\n"
        f"print(\"{token}\")\n"
        "```\n"
    )


@pytest.mark.integration
def test_push_devto_via_backend_api_full_chain(client: TestClient):
    api_key = _read_secret("DEVTO_API_KEY")
    if not api_key:
        pytest.skip("DEVTO_API_KEY is not set")

    store.save_connection("devto", api_key)
    created = client.post("/api/articles", json={"title": "Backend DEV.to live chain"}).json()
    article_id = created["id"]
    token = f"devto-backend-{int(time.time())}"
    article = store.get_article(article_id)
    article["body"] = _prepare_article_body(f"Backend DEV.to live chain {token}", token)

    push_response = client.post(f"/api/articles/{article_id}/push", json={"platforms": ["devto"]})
    assert push_response.status_code == 202
    job_id = push_response.json()["jobId"]

    job = client.get(f"/api/jobs/{job_id}").json()
    article_payload = next(item for item in client.get("/api/articles").json()["items"] if item["id"] == article_id)
    devto = article_payload["destinations"]["devto"]

    artifact = {
        "push_response": push_response.json(),
        "job": job,
        "article": article_payload,
    }
    artifact_path = _ARTIFACT_DIR / f"backend_devto_push_{token}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    assert job["type"] == "push"
    assert job["status"] == "done"
    assert job["result"]["devto"]["status"] == "draft"
    assert isinstance(job["result"]["devto"]["url"], str) and job["result"]["devto"]["url"].startswith("https://dev.to/")
    assert devto["status"] == "draft"
    assert devto["url"] == job["result"]["devto"]["url"]


@pytest.mark.integration
def test_push_hashnode_via_backend_api_full_chain(client: TestClient):
    personal_access_token = _read_secret("HASHNODE_PAT")
    if not personal_access_token:
        pytest.skip("HASHNODE_PAT is not set")

    store.save_connection("hashnode", personal_access_token)
    created = client.post("/api/articles", json={"title": "Backend Hashnode live chain"}).json()
    article_id = created["id"]
    token = f"hashnode-backend-{int(time.time())}"
    article = store.get_article(article_id)
    article["body"] = _prepare_article_body(f"Backend Hashnode live chain {token}", token)

    push_response = client.post(f"/api/articles/{article_id}/push", json={"platforms": ["hashnode"]})
    assert push_response.status_code == 202
    job_id = push_response.json()["jobId"]

    job = client.get(f"/api/jobs/{job_id}").json()
    article_payload = next(item for item in client.get("/api/articles").json()["items"] if item["id"] == article_id)
    hashnode = article_payload["destinations"]["hashnode"]

    artifact = {
        "push_response": push_response.json(),
        "job": job,
        "article": article_payload,
    }
    artifact_path = _ARTIFACT_DIR / f"backend_hashnode_push_{token}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    assert job["type"] == "push"
    assert job["status"] == "done"
    assert job["result"]["hashnode"]["status"] == "draft"
    preview_url = job["result"]["hashnode"]["url"]
    assert isinstance(preview_url, str) and "/preview/" in preview_url
    assert hashnode["status"] == "draft"
    assert hashnode["url"] == preview_url
