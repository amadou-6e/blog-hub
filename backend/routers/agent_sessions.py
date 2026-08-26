"""Lifecycle and recovery API for durable agent sessions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

import backend.store as store
import backend.services.agent_chat as agent_chat
import backend.services.article_patches as article_patches
import backend.services.cli_runner as runner
from backend.store.article_revisions import RevisionConflict
from backend.schemas.agent_sessions import (
    AddCheckpointRequest,
    AddMessageRequest,
    AddOutputRequest,
    ChatTurnRequest,
    CloseAgentSessionRequest,
    CompleteToolCallRequest,
    CreateAgentSessionRequest,
    RecordToolCallRequest,
    RequestApprovalRequest,
    ResolveApprovalRequest,
)

router = APIRouter(prefix="/api/agent-sessions", tags=["agent-sessions"])


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc.args[0]))


def _conflict(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _revision_conflict(exc: RevisionConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "revision_conflict",
        "message": str(exc),
        "current": exc.current,
    })


def _current_revision(user_id: str, session: dict, expected_id: str) -> dict:
    article_id = session.get("article_id")
    current = store.get_current_article_revision(user_id, article_id) if article_id else None
    if current is None:
        raise HTTPException(status_code=404, detail="Session article not found")
    if current["id"] != expected_id:
        raise _revision_conflict(RevisionConflict(current))
    return current


def _turn_in_progress(session: dict) -> bool:
    latest_start = -1
    latest_finish = -1
    for event in session.get("events", []):
        if event["kind"] == "turn_started":
            latest_start = event["id"]
        elif event["kind"] == "turn_completed":
            latest_finish = event["id"]
    return latest_start > latest_finish


@router.post("", status_code=201)
def create_session(request: Request, body: CreateAgentSessionRequest):
    try:
        return store.create_agent_session(
            request.state.user_id, provider=body.provider, model=body.model,
            article_id=body.article_id, workspace_id=body.workspace_id,
            title=body.title, metadata=body.metadata,
            expires_in_days=body.expires_in_days,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("")
def list_sessions(
    request: Request, article_id: str | None = Query(default=None, alias="articleId"),
    status: str | None = None, include_archived: bool = Query(False, alias="includeArchived"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
):
    sessions = store.list_agent_sessions(
        request.state.user_id, article_id=article_id, status=status,
        include_archived=include_archived, limit=limit, offset=offset,
    )
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/{session_id}")
def get_session(request: Request, session_id: str):
    session = store.get_agent_session(request.state.user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    return session


@router.post("/{session_id}/messages", status_code=201)
def add_message(request: Request, session_id: str, body: AddMessageRequest):
    try:
        return store.add_agent_message(
            request.state.user_id, session_id, body.role, body.content, body.metadata
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{session_id}/turns", status_code=202)
def run_chat_turn(
    request: Request, session_id: str, body: ChatTurnRequest,
):
    user_id = request.state.user_id
    session = store.get_agent_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    if session["provider"] not in {"anthropic", "openai"}:
        raise HTTPException(status_code=422, detail="Select Anthropic or OpenAI")
    connection = next(
        (item for item in store.list_connections(user_id)
         if item["id"] == session["provider"]), None
    )
    if not connection or connection["status"] != "connected":
        raise HTTPException(status_code=409, detail="Selected provider is not connected")
    if session["status"] == "running" and _turn_in_progress(session):
        raise HTTPException(status_code=409, detail="A response is already running")
    current_revision = _current_revision(user_id, session, body.article_revision_id)
    try:
        applied_patch, applied_revision = article_patches.apply_pending_session_patch(
            user_id=user_id, session_id=session_id
        )
    except RevisionConflict as exc:
        raise _revision_conflict(exc) from exc
    except article_patches.PatchConflict as exc:
        raise _conflict(exc) from exc
    agent_revision = applied_revision or current_revision
    if session["status"] in {"waiting_for_input", "waiting_for_resume", "failed"}:
        store.resume_agent_session(user_id, session_id)
    elif session["status"] != "running":
        raise HTTPException(
            status_code=409, detail=f"Session is {session['status'].replace('_', ' ')}"
        )
    message = store.add_agent_message(user_id, session_id, "user", body.content)
    store.add_agent_event(user_id, session_id, "turn_started", {
        "message_id": message["id"], "article_revision_id": agent_revision["id"],
    })
    job = store.create_job(
        user_id,
        "chat_turn",
        session["article_id"],
        payload={
            "session_id": session_id,
            "article_revision_id": agent_revision["id"],
        },
        queue="agents",
        max_attempts=3,
        timeout_seconds=300,
    )
    return {
        "jobId": job["job_id"],
        "sessionId": session_id,
        "status": "queued",
        "message": message,
        "articleRevisionId": agent_revision["id"],
        "articleChanged": applied_patch is not None,
    }


@router.post("/{session_id}/close")
def close_session(request: Request, session_id: str, body: CloseAgentSessionRequest):
    user_id = request.state.user_id
    session = store.get_agent_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    if session["status"] == "running" and _turn_in_progress(session):
        raise HTTPException(status_code=409, detail="Wait for the current response to finish")
    current_revision = _current_revision(user_id, session, body.article_revision_id)
    try:
        applied_patch, applied_revision = article_patches.apply_pending_session_patch(
            user_id=user_id, session_id=session_id
        )
    except RevisionConflict as exc:
        raise _revision_conflict(exc) from exc
    except article_patches.PatchConflict as exc:
        raise _conflict(exc) from exc
    if session["status"] not in {"completed", "canceled", "expired"}:
        session = store.update_agent_session_status(user_id, session_id, "completed")
    else:
        session = store.get_agent_session(user_id, session_id)
    revision = applied_revision or current_revision
    return {
        "session": session,
        "articleRevisionId": revision["id"],
        "articleChanged": applied_patch is not None,
    }


@router.post("/{session_id}/tool-calls")
def record_tool_call(request: Request, session_id: str, body: RecordToolCallRequest):
    try:
        tool_call, created = store.record_agent_tool_call(
            request.state.user_id, session_id,
            idempotency_key=body.idempotency_key, name=body.name,
            arguments=body.arguments,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    return JSONResponse(
        status_code=201 if created else 200,
        content={"toolCall": tool_call, "created": created},
    )


@router.post("/{session_id}/tool-calls/{tool_call_id}/claim")
def claim_tool_call(request: Request, session_id: str, tool_call_id: str):
    try:
        claimed = store.claim_agent_tool_call(
            request.state.user_id, session_id, tool_call_id
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    return {"claimed": claimed}


@router.post("/{session_id}/tool-calls/{tool_call_id}/complete")
def complete_tool_call(
    request: Request, session_id: str, tool_call_id: str,
    body: CompleteToolCallRequest,
):
    try:
        return store.complete_agent_tool_call(
            request.state.user_id, session_id, tool_call_id,
            result=body.result, error=body.error,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.post("/{session_id}/checkpoints", status_code=201)
def add_checkpoint(request: Request, session_id: str, body: AddCheckpointRequest):
    try:
        return store.add_agent_checkpoint(request.state.user_id, session_id, body.state)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post("/{session_id}/approvals", status_code=201)
def request_approval(request: Request, session_id: str, body: RequestApprovalRequest):
    try:
        return store.request_agent_approval(
            request.state.user_id, session_id, body.request, body.tool_call_id
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.post("/{session_id}/approvals/{approval_id}/resolve")
def resolve_approval(
    request: Request, session_id: str, approval_id: str,
    body: ResolveApprovalRequest,
):
    try:
        return store.resolve_agent_approval(
            request.state.user_id, session_id, approval_id,
            approved=body.approved, response=body.response,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.post("/{session_id}/outputs", status_code=201)
def add_output(request: Request, session_id: str, body: AddOutputRequest):
    try:
        return store.add_agent_output(
            request.state.user_id, session_id, kind=body.kind,
            reference=body.reference, metadata=body.metadata,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post("/{session_id}/resume")
def resume_session(request: Request, session_id: str):
    try:
        return store.resume_agent_session(request.state.user_id, session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.post("/{session_id}/cancel")
def cancel_session(request: Request, session_id: str):
    try:
        try:
            runner.cancel_chat(session_id)
        except runner.RunnerUnavailable:
            pass
        return store.cancel_agent_session(request.state.user_id, session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post("/{session_id}/archive")
def archive_session(request: Request, session_id: str):
    try:
        return store.archive_agent_session(request.state.user_id, session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc


@router.get("/{session_id}/export")
def export_session(request: Request, session_id: str):
    try:
        return store.export_agent_session(request.state.user_id, session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.delete("/{session_id}", status_code=204)
def delete_session(request: Request, session_id: str):
    try:
        store.delete_agent_session(request.state.user_id, session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc
    return Response(status_code=204)
