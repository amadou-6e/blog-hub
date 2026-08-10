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


def _revision_id(client: TestClient) -> str:
    return client.get("/api/articles/art_001").json()["revision_id"]


def _turn(client: TestClient, session_id: str, content: str):
    return client.post(
        f"/api/agent-sessions/{session_id}/turns",
        json={"content": content, "articleRevisionId": _revision_id(client)},
    )


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

    response = _turn(client, session_id, "Review the introduction")
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
        f"/api/agent-sessions/{session_id}/turns",
        json={"content": "Hello", "articleRevisionId": _revision_id(client)},
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
    _turn(client, session_id, "Rewrite the title")
    pending = client.get(f"/api/agent-sessions/{session_id}").json()
    assert pending["status"] == "waiting_for_approval"
    approval = pending["approvals"][0]

    resolved = client.post(
        f"/api/agent-sessions/{session_id}/approvals/{approval['id']}/resolve",
        json={"approved": True, "response": {"surface": "editor"}},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"


def test_agent_edit_is_queued_until_next_turn(client, monkeypatch):
    session_id = _session(client)
    original = client.get("/api/articles/art_001").json()["content"]
    revised = original + "\n\nA queued conclusion."
    calls = []

    def stream_chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            text = (
                "BLOGHUB_ARTICLE_START\n" + revised
                + "\nBLOGHUB_ARTICLE_END\nI revised the conclusion."
            )
        else:
            text = "The queued conclusion is now in the article."
        return iter([{"type": "assistant_message", "text": text}])

    monkeypatch.setattr(agent_chat.runner, "stream_chat", stream_chat)
    first = _turn(client, session_id, "Revise the conclusion")
    assert first.status_code == 202
    assert client.get("/api/articles/art_001").json()["content"] == original
    patches = client.get("/api/articles/art_001/patches").json()["patches"]
    assert patches[0]["state"] == "pending"
    assert patches[0]["agentSessionId"] == session_id

    second = _turn(client, session_id, "Review that revision")
    assert second.status_code == 202
    assert second.json()["articleChanged"] is True
    assert client.get("/api/articles/art_001").json()["content"] == revised
    assert calls[1]["article_md"] == revised


def test_closing_session_applies_queued_agent_edit(client, monkeypatch):
    session_id = _session(client)
    original = client.get("/api/articles/art_001").json()["content"]
    revised = original + "\n\nFinal line."
    monkeypatch.setattr(agent_chat.runner, "stream_chat", lambda **_kwargs: iter([{
        "type": "assistant_message",
        "text": f"BLOGHUB_ARTICLE_START\n{revised}\nBLOGHUB_ARTICLE_END\nDone.",
    }]))
    _turn(client, session_id, "Add a final line")

    closed = client.post(
        f"/api/agent-sessions/{session_id}/close",
        json={"articleRevisionId": _revision_id(client)},
    )
    assert closed.status_code == 200
    assert closed.json()["articleChanged"] is True
    assert closed.json()["session"]["status"] == "completed"
    assert client.get("/api/articles/art_001").json()["content"] == revised


def test_queued_agent_edit_conflicts_with_newer_editor_revision(client, monkeypatch):
    session_id = _session(client)
    article = client.get("/api/articles/art_001").json()
    revised = article["content"] + "\n\nAgent line."
    monkeypatch.setattr(agent_chat.runner, "stream_chat", lambda **_kwargs: iter([{
        "type": "assistant_message",
        "text": f"BLOGHUB_ARTICLE_START\n{revised}\nBLOGHUB_ARTICLE_END",
    }]))
    _turn(client, session_id, "Add an agent line")
    saved = client.patch("/api/articles/art_001", json={
        "content": article["content"] + "\n\nEditor line.",
        "base_revision_id": article["revision_id"],
    })
    assert saved.status_code == 200

    conflict = client.post(
        f"/api/agent-sessions/{session_id}/close",
        json={"articleRevisionId": saved.json()["revision_id"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "revision_conflict"


def test_worker_uses_exact_revision_snapshot(client, monkeypatch):
    session_id = _session(client)
    article = client.get("/api/articles/art_001").json()
    seen = {}
    monkeypatch.setattr(
        agent_chat.runner,
        "stream_chat",
        lambda **kwargs: seen.update(kwargs) or iter([{"type": "assistant_message", "text": "Read."}]),
    )
    _turn(client, session_id, "Read it")
    assert seen["article_md"] == article["content"]


def test_duplicate_turn_does_not_apply_queued_patch(client):
    session_id = _session(client)
    article = client.get("/api/articles/art_001").json()
    patch = store.add_patch(
        _USER_ID,
        article_id="art_001",
        label="Queued agent edit",
        removed=article["content"],
        added=article["content"] + "\n\nQueued line.",
        base_revision_id=article["revision_id"],
    )
    store.add_agent_output(
        _USER_ID, session_id, kind="article_patch", reference=patch["id"]
    )
    store.add_agent_event(_USER_ID, session_id, "turn_started", {"message_id": "active"})
    store.add_agent_event(_USER_ID, session_id, "assistant_delta", {"text": "Working"})

    duplicate = _turn(client, session_id, "Start another turn")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "A response is already running"
    assert client.get("/api/articles/art_001").json()["content"] == article["content"]
    assert store.get_patch(_USER_ID, "art_001", patch["id"])["state"] == "pending"


def test_regeneration_cleanup_preserves_queued_agent_patch(client):
    session_id = _session(client)
    article = client.get("/api/articles/art_001").json()
    patch = store.add_patch(
        _USER_ID,
        article_id="art_001",
        label="Queued agent edit",
        removed=article["content"],
        added=article["content"] + "\n\nQueued line.",
        base_revision_id=article["revision_id"],
    )
    store.add_agent_output(
        _USER_ID, session_id, kind="article_patch", reference=patch["id"]
    )

    store.delete_patches(_USER_ID, "art_001")

    assert store.get_patch(_USER_ID, "art_001", patch["id"])["state"] == "pending"
