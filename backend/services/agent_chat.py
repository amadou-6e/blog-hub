"""Execute provider chat turns and persist their observable event stream."""
from __future__ import annotations

import backend.services.cli_runner as runner
import backend.store as store


def _connection_api_key(user_id: str, provider: str) -> str | None:
    token = store.get_connection_token(user_id, provider) if provider == "openai" else None
    return runner.api_key_from_connection_token(token)


def run_turn(*, user_id: str, session_id: str) -> None:
    session = store.get_agent_session(user_id, session_id)
    if session is None:
        return
    article = store.get_article(user_id, session["article_id"])
    if article is None:
        store.update_agent_session_status(user_id, session_id, "failed", "Article not found")
        return

    messages = [
        {"role": message["role"], "content": message["content"]}
        for message in session["messages"] if message["role"] in {"user", "assistant"}
    ]
    tools: dict[str, str] = {}
    final_text = ""
    try:
        for event in runner.stream_chat(
            provider=session["provider"], session_id=session_id,
            article_md=article.get("body", ""), messages=messages,
            model=session.get("model"),
            api_key=_connection_api_key(user_id, session["provider"]),
        ):
            kind = event.get("type", "provider_event")
            if kind == "assistant_delta":
                store.add_agent_event(
                    user_id, session_id, kind, {"text": event.get("text", "")}
                )
            elif kind == "assistant_message":
                final_text = event.get("text", "").strip() or final_text
            elif kind == "tool_started":
                provider_id = event.get("toolId") or f"tool-{len(tools) + 1}"
                tool, _ = store.record_agent_tool_call(
                    user_id, session_id,
                    idempotency_key=f"{session_id}:{provider_id}",
                    name=event.get("name", "tool"),
                    arguments=event.get("arguments") or {},
                )
                store.claim_agent_tool_call(user_id, session_id, tool["id"])
                tools[provider_id] = tool["id"]
            elif kind == "tool_completed":
                tool_id = tools.get(event.get("toolId"))
                if tool_id:
                    failed = event.get("status") in {"failed", "error"}
                    store.complete_agent_tool_call(
                        user_id, session_id, tool_id,
                        result={
                            "status": event.get("status"),
                            "output": event.get("result"),
                        },
                        error="Provider tool failed" if failed else None,
                    )
            elif kind == "approval_required":
                store.request_agent_approval(
                    user_id, session_id, event.get("request") or {}
                )
            elif kind == "checkpoint":
                store.add_agent_checkpoint(user_id, session_id, event)
            elif kind == "error":
                raise runner.RunnerUnavailable(
                    event.get("message", "Provider chat failed")
                )

        if final_text:
            store.add_agent_message(user_id, session_id, "assistant", final_text)
        store.add_agent_event(user_id, session_id, "turn_completed")
        current = store.get_agent_session(user_id, session_id)
        if current and current["status"] == "running":
            store.update_agent_session_status(
                user_id, session_id, "waiting_for_input"
            )
    except Exception as exc:
        current = store.get_agent_session(user_id, session_id)
        if current and current["status"] not in {"canceled", "waiting_for_approval"}:
            store.update_agent_session_status(
                user_id, session_id, "failed", str(exc)[:500]
            )
