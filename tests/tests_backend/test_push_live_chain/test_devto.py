"""Live push test: DEV.to via the full backend API chain."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.store as store

_REPO_ROOT = Path(__file__).resolve().parents[4]
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
        "```\n")


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
    article_payload = next(
        item for item in client.get("/api/articles").json()["items"] if item["id"] == article_id)
    devto = article_payload["destinations"]["devto"]

    artifact = {"push_response": push_response.json(), "job": job, "article": article_payload}
    (_ARTIFACT_DIR / f"backend_devto_push_{token}.json").write_text(json.dumps(artifact, indent=2),
                                                                    encoding="utf-8")

    assert job["type"] == "push"
    assert job["status"] == "done"
    assert job["result"]["devto"]["status"] == "draft"
    assert isinstance(job["result"]["devto"]["url"], str) and \
        job["result"]["devto"]["url"].startswith("https://dev.to/")
    assert devto["status"] == "draft"
    assert devto["url"] == job["result"]["devto"]["url"]
