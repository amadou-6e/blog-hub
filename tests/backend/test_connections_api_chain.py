"""Backend API tests for DEV.to and Hashnode connection flows."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient


_blog_hub_root = Path(__file__).resolve().parents[2]
if str(_blog_hub_root) not in sys.path:
    sys.path.insert(0, str(_blog_hub_root))

from backend.main import app
import backend.store as store


_REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _connection_by_id(payload: dict, conn_id: str) -> dict:
    return next(item for item in payload["connections"] if item["id"] == conn_id)


@pytest.mark.parametrize(
    ("conn_id", "secret_name"),
    [
        ("devto", "DEVTO_API_KEY"),
        ("hashnode", "HASHNODE_PAT"),
    ],
)
def test_connection_save_list_delete_chain(client: TestClient, conn_id: str, secret_name: str):
    token = _read_secret(secret_name)
    if not token:
        pytest.skip(f"{secret_name} is not set")

    initial = client.get("/api/connections")
    assert initial.status_code == 200
    initial_conn = _connection_by_id(initial.json(), conn_id)
    assert initial_conn["status"] == "disconnected"

    save_response = client.put(f"/api/connections/{conn_id}", json={"token": token})
    assert save_response.status_code == 200
    assert save_response.json()["id"] == conn_id
    assert save_response.json()["status"] == "connected"

    after_save = client.get("/api/connections")
    assert after_save.status_code == 200
    saved_conn = _connection_by_id(after_save.json(), conn_id)
    assert saved_conn["status"] == "connected"
    assert saved_conn["connected_at"] is not None

    delete_response = client.delete(f"/api/connections/{conn_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "disconnected"

    after_delete = client.get("/api/connections")
    assert after_delete.status_code == 200
    deleted_conn = _connection_by_id(after_delete.json(), conn_id)
    assert deleted_conn["status"] == "disconnected"
    assert deleted_conn["connected_at"] is None
