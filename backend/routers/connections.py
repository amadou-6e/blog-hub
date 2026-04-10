"""
Connections router — browser login flows and API token management
for blog publishing platforms (Medium, Hashnode, Dev.to) and
AI providers (Anthropic/Claude, OpenAI).

Blog platforms:
  Medium     — OAuth 2.0 Authorization Code popup (server-side code exchange)
               OR manual integration token
  Hashnode   — Personal Access Token
  Dev.to     — API Key (Forem)

AI providers:
  Anthropic  — browser login via claude CLI (loopback redirect, handled by cli-runner)
               OR API Key fallback
  OpenAI     — browser login via openai CLI (loopback redirect, handled by cli-runner)
               OR API Key fallback

CLI operations are delegated to the CLI runner service (see backend/services/cli_runner.py).
The backend never spawns CLI subprocesses directly.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse

from blogs.hashnode.client import HashnodeClient, HashnodeError
from blogs.devto.client import DevToClient, DevToError

import backend.services.cli_runner as runner
import backend.store as store
from backend.schemas.connections import (
    ConnectionInfo,
    ConnectionListResponse,
    DraftContent,
    DraftListResponse,
    DraftSummary,
    OAuthStartResponse,
    SaveTokenRequest,
    SaveTokenResponse,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])

_VALID_IDS = {"medium", "hashnode", "devto", "anthropic", "openai"}
_BLOG_IDS = {"medium", "hashnode", "devto"}
_CLI_IDS = {"anthropic", "openai"}
_PROVIDER_MAP = {"anthropic": "anthropic", "openai": "openai"}

_MOCK_DRAFTS: dict[str, list[dict]] = {
    # Medium has no public API for drafts — show empty list rather than fake content.
    "medium": [],
}

# ── Helpers — real platform API calls ────────────────────────────────────────

_log = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(tz=timezone.utc).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _snippet(body: str, chars: int = 200) -> str:
    return body[:chars].replace("\n", " ").strip()


def _list_platform_drafts(conn_id: str, token: str) -> list[dict]:
    """Return a list of draft dicts from the real platform API.
    Falls back to [] on any error so the endpoint never 500s due to upstream issues."""
    try:
        if conn_id == "hashnode":
            client = HashnodeClient(token)
            articles = client.list_all_drafts(page_size=20)
            articles += client.list_published_articles(post_first=50)
            return [{
                "id": a.article_id,
                "title": a.title,
                "snippet": _snippet(a.body_markdown),
                "word_count": _word_count(a.body_markdown),
                "updated_at": _iso(a.updated_at),
                "status": "published" if a.published else "draft",
                "canonical_url": a.canonical_url,
                "cover_image": a.cover_image_url,
                "body": a.body_markdown,
            } for a in articles]

        if conn_id == "devto":
            client = DevToClient(token)
            articles = client.list_my_articles(per_page=100)
            return [{
                "id": str(a.article_id),
                "title": a.title,
                "snippet": a.description or _snippet(a.body_markdown),
                "word_count": _word_count(a.body_markdown),
                "updated_at": _iso(a.updated_at),
                "status": "published" if a.published else "draft",
                "canonical_url": a.canonical_url,
                "cover_image": a.cover_image,
                "body": a.body_markdown,
            } for a in articles]

    except (HashnodeError, DevToError, Exception) as exc:  # noqa: BLE001
        _log.warning("Failed to fetch drafts for %s: %s", conn_id, exc)

    # Medium has no public API for drafts; return empty list.
    return _MOCK_DRAFTS.get(conn_id, [])


def _fetch_draft(conn_id: str, draft_id: str, token: str) -> dict | None:
    """Fetch a single draft's full content from the platform API."""
    try:
        # For Hashnode: try a direct by-ID query first (avoids list pagination limits)
        if conn_id == "hashnode":
            client = HashnodeClient(token)
            article = client.get_draft_by_id(draft_id)
            if article:
                return {
                    "id": article.article_id,
                    "title": article.title,
                    "word_count": _word_count(article.body_markdown),
                    "updated_at": _iso(article.updated_at),
                    "status": "published" if article.published else "draft",
                    "canonical_url": article.canonical_url,
                    "cover_image": article.cover_image_url,
                    "body": article.body_markdown,
                }
        drafts = _list_platform_drafts(conn_id, token)
        return next((d for d in drafts if d["id"] == draft_id), None)
    except Exception as exc:  # noqa: BLE001
        _log.warning("_fetch_draft failed for %s/%s: %s", conn_id, draft_id, exc)
        return None


@router.get("", response_model=ConnectionListResponse)
def list_connections():
    return ConnectionListResponse(
        connections=[ConnectionInfo(**c) for c in store.list_connections()])


# ── Save token ────────────────────────────────────────────────────────────────


@router.put("/{conn_id}", response_model=SaveTokenResponse)
def save_token(conn_id: str, body: SaveTokenRequest):
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")
    result = store.save_connection(conn_id, body.token)
    return SaveTokenResponse(
        id=result["id"],
        status=result["status"],
        username=result.get("username"),
    )


# ── Disconnect ────────────────────────────────────────────────────────────────


@router.delete("/{conn_id}")
def disconnect(conn_id: str):
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")
    store.delete_connection(conn_id)
    if conn_id in _CLI_IDS:
        # Best-effort: tell the runner to logout; ignore errors
        try:
            runner.logout(conn_id)
        except runner.RunnerUnavailable:
            pass
    return {"status": "disconnected"}


# ── Test connection ───────────────────────────────────────────────────────────


@router.post("/{conn_id}/test")
def test_connection(conn_id: str):
    """
    Verify a stored credential is currently valid.

    For AI providers: asks the CLI runner to run whoami.
    For blog platforms: makes a lightweight authenticated API call.
    Returns { ok: bool, detail: str }.
    """
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")

    if conn_id in _CLI_IDS:
        try:
            result = runner.login_status(conn_id)
        except runner.RunnerUnavailable as exc:
            return {"ok": False, "detail": f"Runner unavailable: {exc}"}
        return {
            "ok": result["status"] == "connected",
            "detail": result.get("username") or result.get("reason") or result["status"],
        }

    # Blog platforms: probe the platform API with the stored token
    token = store.get_connection_token(conn_id)
    if not token:
        return {"ok": False, "detail": "No token stored"}

    try:
        ok, detail = _probe_platform(conn_id, token)
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": ok, "detail": detail}


def _probe_platform(conn_id: str, token: str) -> tuple[bool, str]:
    """Lightweight authenticated probe for each blog platform."""
    headers: dict[str, str]
    url: str

    if conn_id == "medium":
        url = "https://api.medium.com/v1/me"
        headers = {"Authorization": f"Bearer {token}"}
    elif conn_id == "hashnode":
        url = "https://gql.hashnode.com/"
        headers = {"Authorization": token}
        # Minimal GraphQL query for current user
        with httpx.Client(timeout=8) as client:
            resp = client.post(url, json={"query": "{ me { username } }"}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                username = data.get("data", {}).get("me", {}).get("username")
                if username:
                    return True, username
                return False, data.get("errors", [{}])[0].get("message", "auth failed")
            return False, f"HTTP {resp.status_code}"
    elif conn_id == "devto":
        url = "https://dev.to/api/users/me"
        headers = {"api-key": token}
    elif conn_id == "openai":
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {token}"}
    else:
        return False, f"No probe defined for {conn_id}"

    with httpx.Client(timeout=8) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            username = data.get("username") or data.get("data", {}).get("username")
            return True, username or "authenticated"
        return False, f"HTTP {resp.status_code}"


# ── OAuth / browser login start ───────────────────────────────────────────────


@router.get("/{conn_id}/oauth-start", response_model=OAuthStartResponse)
def oauth_start(conn_id: str):
    """
    Initiate browser login for a connection.

    Medium:           returns { available, url } for the Authorization Code popup.
    Anthropic/OpenAI: delegates to the CLI runner's /auth/{provider}/login.
                      Runner spawns the CLI, which opens a loopback HTTP server and
                      returns the provider auth URL via stdout.
    """
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")

    if conn_id == "medium":
        return _medium_oauth_start()

    if conn_id in _CLI_IDS:
        return _cli_oauth_start(conn_id)

    raise HTTPException(status_code=400, detail=f"{conn_id} does not support browser login")


def _medium_oauth_start() -> OAuthStartResponse:
    client_id = os.environ.get("MEDIUM_CLIENT_ID")
    if not client_id:
        return OAuthStartResponse(available=False)

    redirect_uri = os.environ.get(
        "MEDIUM_REDIRECT_URI",
        "http://localhost:8000/api/connections/medium/oauth-callback",
    )
    state = store.create_oauth_state("medium")
    scope = "basicProfile%20publicationsList"
    url = (f"https://medium.com/m/oauth/authorize"
           f"?client_id={client_id}"
           f"&scope={scope}"
           f"&state={state}"
           f"&response_type=code"
           f"&redirect_uri={redirect_uri}")
    return OAuthStartResponse(url=url, available=True)


def _cli_oauth_start(conn_id: str) -> OAuthStartResponse:
    try:
        result = runner.login(conn_id)
    except runner.RunnerUnavailable:
        return OAuthStartResponse(available=False)

    if not result.get("available"):
        return OAuthStartResponse(available=False)

    # Device code flow (e.g. OpenAI Codex): CLI polls internally, no submit needed.
    # Loopback flow (e.g. Anthropic): user copies address-bar URL and submits it.
    device_code = result.get("device_code")
    flow = "device_code" if device_code else "cli_browser"

    return OAuthStartResponse(
        available=True,
        url=result["url"],
        flow=flow,
        device_code=device_code,
        poll_url=f"/api/connections/{conn_id}/cli-login-status",
    )


# ── CLI device code submit ────────────────────────────────────────────────────


class SubmitCodeRequest(BaseModel):
    code: str


@router.post("/{conn_id}/submit-code")
def submit_code(conn_id: str, body: SubmitCodeRequest):
    """
    Relay the device/authorization code the user copied from the browser
    to the CLI runner, which writes it to the waiting CLI process stdin.
    """
    if conn_id not in _CLI_IDS:
        raise HTTPException(status_code=400, detail=f"{conn_id} does not use CLI login")
    try:
        resp = httpx.post(
            f"{runner.CLI_RUNNER_URL}/auth/{conn_id}/submit-code",
            json={"code": body.code},
            timeout=10,
        )
        if resp.status_code == 409:
            raise HTTPException(
                status_code=409,
                detail="No active login session — click 'Login with Browser' to start a new one",
            )
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="CLI runner not reachable")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── CLI login status (poll endpoint) ─────────────────────────────────────────


@router.get("/{conn_id}/cli-login-status")
def cli_login_status(conn_id: str):
    """
    Poll endpoint for CLI browser login completion.
    Frontend calls this every 2 s after opening the auth URL.

    Returns:
      { status: "connected", username: "..." }
      { status: "pending" }
      { status: "error",    errorMessage: "..." }
    """
    if conn_id not in _CLI_IDS:
        raise HTTPException(status_code=400, detail=f"{conn_id} does not use CLI login")

    try:
        result = runner.login_status(conn_id)
    except runner.RunnerUnavailable as exc:
        return {"status": "error", "errorMessage": f"Runner unavailable: {exc}"}

    status = result.get("status", "error")

    if status == "connected":
        username = result.get("username")
        store.save_connection(conn_id, token="cli_session", status="connected", username=username)
        return {"status": "connected", "username": username}

    if status == "pending":
        return {"status": "pending"}

    return {"status": "error", "errorMessage": result.get("reason", "Login failed")}


# ── Draft list ───────────────────────────────────────────────────────────────


@router.get("/{conn_id}/drafts", response_model=DraftListResponse)
def list_drafts(
    conn_id: str,
    page: int = 1,
    per_page: int = 20,
):
    """
    Return a paginated list of articles (drafts + published) for a connected
    blog platform.

    Hashnode and Dev.to: calls real platform APIs via the blog clients.
    Medium: returns mock data (Medium's public API does not expose drafts).
    """
    if conn_id not in _BLOG_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {conn_id}")

    if not store.get_connection_token(conn_id):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "platform_not_connected",
                "platform": conn_id
            },
        )

    token = store.get_connection_token(conn_id)
    all_drafts = _list_platform_drafts(conn_id, token)
    total = len(all_drafts)
    start = (page - 1) * per_page
    page_items = all_drafts[start:start + per_page]

    return DraftListResponse(
        platform=conn_id,
        drafts=[
            DraftSummary(
                id=d["id"],
                title=d["title"],
                word_count=d.get("word_count", 0),
                updated_at=d.get("updated_at", ""),
                status=d.get("status", "draft"),
                snippet=d.get("snippet", ""),
                cover_image=d.get("cover_image"),
            ) for d in page_items
        ],
        total=total,
        page=page,
        per_page=per_page,
        has_more=(start + per_page) < total,
    )


@router.get("/{conn_id}/drafts/{draft_id}", response_model=DraftContent)
def get_draft(conn_id: str, draft_id: str):
    """
    Return the full markdown body of a single article from the platform.

    Real implementation would call the platform API with the stored token
    to fetch the canonical draft content.
    """
    if conn_id not in _BLOG_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {conn_id}")

    if not store.get_connection_token(conn_id):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "platform_not_connected",
                "platform": conn_id
            },
        )

    token = store.get_connection_token(conn_id)
    draft_dict = _fetch_draft(conn_id, draft_id, token)
    if draft_dict is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "draft_not_found"},
        )

    return DraftContent(
        id=draft_dict["id"],
        title=draft_dict["title"],
        word_count=draft_dict.get("word_count", 0),
        updated_at=draft_dict.get("updated_at", ""),
        status=draft_dict.get("status", "draft"),
        body=draft_dict.get("body", ""),
        canonical_url=draft_dict.get("canonical_url"),
        cover_image=draft_dict.get("cover_image"),
    )


# ── Medium OAuth callback ─────────────────────────────────────────────────────


@router.get("/{conn_id}/oauth-callback", response_class=HTMLResponse)
async def oauth_callback(conn_id: str,
                         code: str | None = None,
                         state: str | None = None,
                         error: str | None = None):
    if conn_id != "medium":
        raise HTTPException(status_code=400, detail="OAuth callback only valid for medium")

    if error or not code:
        return HTMLResponse(_popup_html("error", conn_id, error=str(error or "access_denied")))

    if not state or not store.consume_oauth_state(state, conn_id):
        return HTMLResponse(_popup_html("error", conn_id, error="Invalid or expired OAuth state"))

    client_id = os.environ.get("MEDIUM_CLIENT_ID", "")
    client_secret = os.environ.get("MEDIUM_CLIENT_SECRET", "")
    redirect_uri = os.environ.get(
        "MEDIUM_REDIRECT_URI",
        "http://localhost:8000/api/connections/medium/oauth-callback",
    )

    try:
        async with __import__("httpx").AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                "https://api.medium.com/v1/tokens",
                json={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            token_data = token_resp.json()
            token = (token_data.get("access_token") or
                     token_data.get("data", {}).get("accessToken"))
            if not token:
                return HTMLResponse(
                    _popup_html("error", conn_id, error="No token in OAuth response"))

            me_resp = await client.get(
                "https://api.medium.com/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            me_data = me_resp.json().get("data", {})
            username = me_data.get("username") or me_data.get("name")

        store.save_connection(conn_id, token, status="connected", username=username)
        return HTMLResponse(_popup_html("connected", conn_id, username=username))

    except Exception as exc:
        return HTMLResponse(_popup_html("error", conn_id, error=str(exc)))


def _popup_html(status: str,
                platform: str,
                *,
                error: str | None = None,
                username: str | None = None) -> str:
    payload: dict = {"type": "oauth-complete", "platform": platform, "status": status}
    if username:
        payload["username"] = username
    if error:
        payload["error"] = error

    payload_json = json.dumps(payload)
    message = "Connected!" if status == "connected" else f"Error: {error}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Connecting…</title></head>
<body style="font-family:system-ui;background:#0f1117;color:#c9cfe0;
             display:flex;align-items:center;justify-content:center;
             height:100vh;margin:0;text-align:center;">
  <div>
    <p style="margin:0 0 8px;">{message}</p>
    <p style="margin:0;color:#5a6080;font-size:.8rem;">You can close this window.</p>
  </div>
  <script>
    (function () {{
      var payload = {payload_json};
      if (window.opener) {{
        window.opener.postMessage(payload, location.origin);
        window.close();
      }}
    }})();
  </script>
</body>
</html>"""
