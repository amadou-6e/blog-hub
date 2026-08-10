"""Execute provider chat turns and persist their observable event stream."""
from __future__ import annotations

import re

import backend.services.cli_runner as runner
import backend.store as store


_ARTICLE_BLOCK = re.compile(
    r"BLOGHUB_ARTICLE_START[ \t]*\r?\n(.*?)\r?\nBLOGHUB_ARTICLE_END", re.DOTALL
)


def _extract_article_update(text: str) -> tuple[str, str | None]:
    match = _ARTICLE_BLOCK.search(text)
    if match is None:
        return text.strip(), None
    article = match.group(1)
    reply = _ARTICLE_BLOCK.sub("", text).strip()
    return reply or "I prepared an article edit for the next agent boundary.", article


def _connection_api_key(user_id: str, provider: str) -> str | None:
    token = store.get_connection_token(user_id, provider) if provider == "openai" else None
    return runner.api_key_from_connection_token(token)


def run_turn(*, user_id: str, session_id: str, article_revision_id: str) -> None:
    session = store.get_agent_session(user_id, session_id)
    if session is None:
        return
    revision = store.get_article_revision(
        user_id, session["article_id"], article_revision_id
    )
    if revision is None:
        store.update_agent_session_status(user_id, session_id, "failed", "Article revision not found")
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
            article_md=revision["content"], messages=messages,
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
            reply, article_update = _extract_article_update(final_text)
            if article_update is not None and article_update != revision["content"]:
                patch = store.add_patch(
                    user_id,
                    article_id=session["article_id"],
                    label="Queued agent edit",
                    removed=revision["content"],
                    added=article_update,
                    base_revision_id=article_revision_id,
                )
                store.add_agent_output(
                    user_id,
                    session_id,
                    kind="article_patch",
                    reference=patch["id"],
                    metadata={"base_revision_id": article_revision_id},
                )
                store.add_agent_event(
                    user_id, session_id, "article_patch_queued", {"patch_id": patch["id"]}
                )
            store.add_agent_message(user_id, session_id, "assistant", reply)
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
