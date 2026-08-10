from __future__ import annotations

from fastapi.testclient import TestClient

import backend.services.connection_auth as connection_auth


def test_browser_callback_flow_uses_shared_api_contract(
    client: TestClient, monkeypatch,
):
    monkeypatch.setattr(
        connection_auth.runner,
        "login",
        lambda provider: {
            "available": True,
            "url": "https://claude.example/authorize?state=temporary",
        },
    )
    callbacks = []
    monkeypatch.setattr(
        connection_auth.runner,
        "submit_login_callback",
        lambda provider, callback: callbacks.append((provider, callback)),
    )
    monkeypatch.setattr(
        connection_auth.runner,
        "login_status",
        lambda provider: {"status": "connected", "username": "writer@example.com"},
    )

    started = client.post("/api/connections/anthropic/auth-flows")
    assert started.status_code == 201
    flow = started.json()
    assert flow["provider"] == "anthropic"
    assert flow["flowType"] == "browser_callback"
    assert flow["status"] == "waiting_for_authorization"

    callback = "http://localhost:54322/callback?code=secret-code&state=secret-state"
    submitted = client.post(
        f"/api/connections/auth-flows/{flow['flowId']}/callback",
        json={"callbackUrl": callback},
    )
    assert submitted.status_code == 200
    assert callbacks == [("anthropic", callback)]

    completed = client.get(f"/api/connections/auth-flows/{flow['flowId']}")
    assert completed.status_code == 200
    assert completed.json()["status"] == "connected"
    assert completed.json()["username"] == "writer@example.com"


def test_device_code_flow_uses_same_status_endpoint(
    client: TestClient, monkeypatch,
):
    monkeypatch.setattr(
        connection_auth.runner,
        "login",
        lambda provider: {
            "available": True,
            "url": "https://openai.example/device",
            "device_code": "ABCD-EFGH",
        },
    )
    monkeypatch.setattr(
        connection_auth.runner,
        "login_status",
        lambda provider: {"status": "pending"},
    )

    started = client.post("/api/connections/openai/auth-flows")
    assert started.status_code == 201
    flow = started.json()
    assert flow["flowType"] == "device_code"
    assert flow["deviceCode"] == "ABCD-EFGH"

    active = client.get("/api/connections/auth-flows/active")
    assert active.status_code == 200
    assert [item["flowId"] for item in active.json()["flows"]] == [flow["flowId"]]

    pending = client.get(f"/api/connections/auth-flows/{flow['flowId']}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "waiting_for_authorization"


def test_callback_flow_requires_authentication(anon_client: TestClient):
    response = anon_client.post("/api/connections/anthropic/auth-flows")
    assert response.status_code == 401
