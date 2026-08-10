from fastapi.testclient import TestClient

import backend.services.agent_chat as agent_chat
import backend.store as store

_USER_ID = "user_seed"


def _session(client: TestClient, provider: str = "anthropic") -> str:
    store.save_connection(
        _USER_ID, provider, token=f"web_session:{provider}", status="connected"
    )
    response = client.post("/api/agent-sessions", json={
        "provider": provider, "articleId": "art_001", "title": "Editor chat",
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_chat_turn_persists_message_native_tool_and_reply(client, monkeypatch):
    session_id = _session(client)
    monkeypatch.setattr(agent_chat.runner, "stream_chat", lambda **_kwargs: iter([
        {"type": "assistant_delta", "text": "Reading"},
        {"type": "tool_started", "toolId": "read-1", "name": "Read",
         "arguments": {"path": "article.md"}},
        {"type": "tool_completed", "toolId": "read-1", "status": "completed",
         "result": "article content"},
        {"type": "assistant_message", "text": "The introduction needs a concrete example."},
        {"type": "done", "exitCode": 0},
    ]))

    response = client.post(
        f"/api/agent-sessions/{session_id}/turns",
        json={"content": "Review the introduction"},
    )
    assert response.status_code == 202
    persisted = client.get(f"/api/agent-sessions/{session_id}").json()
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert persisted["tool_calls"][0]["name"] == "Read"
    assert persisted["tool_calls"][0]["status"] == "completed"
    assert persisted["status"] == "waiting_for_input"


def test_chat_turn_requires_connected_selected_provider(client):
    response = client.post("/api/agent-sessions", json={
        "provider": "openai", "articleId": "art_001", "title": "Editor chat",
    })
    session_id = response.json()["id"]
    turn = client.post(
        f"/api/agent-sessions/{session_id}/turns", json={"content": "Hello"}
    )
    assert turn.status_code == 409
    assert "not connected" in turn.json()["detail"]


def test_provider_permission_request_becomes_resolvable_approval(client, monkeypatch):
    session_id = _session(client)
    monkeypatch.setattr(agent_chat.runner, "stream_chat", lambda **_kwargs: iter([
        {"type": "approval_required", "request": {
            "tool_name": "Edit", "path": "article.md",
        }},
        {"type": "done", "exitCode": 0},
    ]))
    client.post(
        f"/api/agent-sessions/{session_id}/turns", json={"content": "Rewrite the title"}
    )
    pending = client.get(f"/api/agent-sessions/{session_id}").json()
    assert pending["status"] == "waiting_for_approval"
    approval = pending["approvals"][0]

    resolved = client.post(
        f"/api/agent-sessions/{session_id}/approvals/{approval['id']}/resolve",
        json={"approved": True, "response": {"surface": "editor"}},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"
