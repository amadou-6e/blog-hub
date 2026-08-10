"""
Agent router — AI generation endpoints for the create-article wizard.

Endpoints:
  GET  /api/agent/providers  — AI provider connection status
  GET  /api/agent/platforms  — Blog platform connection status (create-article destinations)
  POST /api/agent/generate   — Start an async article generation job
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import backend.store as store
import backend.services.agent_service as agent_service

router = APIRouter(prefix="/api/agent", tags=["agent"])

_AI_PROVIDER_IDS = {"anthropic", "openai"}
_BLOG_PLATFORM_IDS = {"medium", "hashnode", "devto"}

# ─── Inline response models ───────────────────────────────────────────────────


class ProviderInfo(BaseModel):
    id: str
    label: str
    configured: bool


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]


class PlatformInfo(BaseModel):
    id: str
    label: str
    status: str  # "connected" | "expired" | "not_configured"
    session_expires_at: str | None = None


class PlatformsResponse(BaseModel):
    platforms: list[PlatformInfo]


class GenerateRequest(BaseModel):
    brief: str = Field(..., min_length=10)
    skill: str = Field(...)
    provider: str = Field(...)  # "claude" | "codex"
    word_count: int = Field(..., alias="wordCount", ge=500, le=4000)
    context_text: str | None = Field(default=None, alias="contextText")
    destinations: list[str] = Field(...)

    model_config = {"populate_by_name": True}


class GenerateAccepted(BaseModel):
    job_id: str = Field(alias="jobId")
    status: str
    article_id: str = Field(alias="articleId")
    session_id: str = Field(alias="sessionId")

    model_config = {"populate_by_name": True}


# ─── Helpers ─────────────────────────────────────────────────────────────────

_PROVIDER_UI_ID = {"anthropic": "claude", "openai": "codex"}
_PROVIDER_RUNNER = {"claude": "anthropic", "codex": "openai"}


def _connection_status_to_platform_status(conn_status: str) -> str:
    """Map internal connection status to the create-article wizard status vocabulary."""
    if conn_status == "connected":
        return "connected"
    if conn_status == "expired":
        return "expired"
    return "not_configured"


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/providers", response_model=ProvidersResponse)
def get_providers(request: Request) -> ProvidersResponse:
    """Return configured AI providers. Used by the provider toggle in step 2."""
    user_id: str = request.state.user_id
    connections = {c["id"]: c for c in store.list_connections(user_id)}
    providers = []
    for conn_id in ("anthropic", "openai"):
        meta = connections.get(conn_id, {})
        providers.append(
            ProviderInfo(
                id=_PROVIDER_UI_ID[conn_id],
                label=meta.get("label", conn_id.capitalize()),
                configured=meta.get("status") == "connected",
            ))
    return ProvidersResponse(providers=providers)


@router.get("/platforms", response_model=PlatformsResponse)
def get_platforms(request: Request) -> PlatformsResponse:
    """Return blog platform connectivity. Used by the destinations step."""
    user_id: str = request.state.user_id
    connections = {c["id"]: c for c in store.list_connections(user_id)}
    platforms = []
    for pid in ("medium", "hashnode", "devto"):
        conn = connections.get(pid, {})
        status = _connection_status_to_platform_status(conn.get("status", "disconnected"))
        platforms.append(
            PlatformInfo(
                id=pid,
                label=conn.get("label", pid.capitalize()),
                status=status,
                session_expires_at=None,
            ))
    return PlatformsResponse(platforms=platforms)


@router.post("/generate", status_code=202)
def generate_article(
    request: Request,
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Start an async article generation job.

    Returns 202 immediately with {jobId, articleId, status}.
    Client navigates to /editor/:articleId and polls GET /api/jobs/:jobId.
    """
    # Validate provider identifier
    if body.provider not in _PROVIDER_RUNNER:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{body.provider}'. Must be 'claude' or 'codex'.",
        )

    user_id: str = request.state.user_id

    # Check that the selected provider has a configured connection
    runner_provider_id = _PROVIDER_RUNNER[body.provider]
    connections = {c["id"]: c for c in store.list_connections(user_id)}
    provider_conn = connections.get(runner_provider_id, {})
    if provider_conn.get("status") != "connected":
        raise HTTPException(
            status_code=400,
            detail=(f"{body.provider.capitalize()} is not configured. "
                    "Add the API key or log in via Settings → AI Providers."),
        )

    # Create the article record (title filled in by background task)
    article = store.create_article(user_id, title="Draft")
    job = store.create_job(user_id, "generate", article["id"])
    session = store.create_agent_session(
        user_id,
        provider=runner_provider_id,
        article_id=article["id"],
        title=body.brief[:240],
        metadata={
            "job_id": job["job_id"],
            "skill": body.skill,
            "word_count": body.word_count,
            "destinations": body.destinations,
        },
    )
    store.add_agent_message(user_id, session["id"], "user", body.brief)

    background_tasks.add_task(
        agent_service.run_generation,
        user_id=user_id,
        job_id=job["job_id"],
        article_id=article["id"],
        brief=body.brief,
        skill=body.skill,
        provider=body.provider,
        word_count=body.word_count,
        context_text=body.context_text,
        destinations=body.destinations,
        session_id=session["id"],
    )

    return JSONResponse(
        status_code=202,
        content={
            "jobId": job["job_id"],
            "articleId": article["id"],
            "status": "running",
            "sessionId": session["id"],
        },
    )
