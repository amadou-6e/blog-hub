from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
import backend.store as store

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = Path(_REPO_ROOT, ".env")
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if key.strip() == name:
            return raw_value.strip()
    return ""


def test_live_overview_articles_feed_includes_real_platform_entries(
        monkeypatch: pytest.MonkeyPatch) -> None:
    if not (_read_secret("DEVTO_API_KEY") or _read_secret("HASHNODE_PAT")):
        pytest.skip("No live DEV.to or Hashnode credentials configured")

    monkeypatch.setenv("BLOGHUB_ENABLE_LIVE_SYNC", "1")
    store.reset()

    client = TestClient(app)
    client.post("/api/auth/login",
                json={"email": "seed@example.com", "password": "seed1234", "remember_me": False})
    response = client.get("/api/articles?sortBy=updatedAt&sortDir=desc&page=1&pageSize=20")
    response.raise_for_status()
    payload = response.json()

    assert payload["items"], "Expected live overview feed to return at least one article"
    assert any(item["destinations"]["devto"]["status"] != "none" or
               item["destinations"]["hashnode"]["status"] != "none" for item in payload["items"])
    assert any((item["destinations"]["devto"]["url"] or "").startswith("https://dev.to/") or
               "hashnode.dev" in (item["destinations"]["hashnode"]["url"] or "")
               for item in payload["items"])
