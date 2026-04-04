"""
Connections router — browser login flows and API token management
for blog publishing platforms (Medium, Hashnode, Dev.to) and
AI providers (Anthropic/Claude, OpenAI).

Blog platforms:
  Medium     — OAuth 2.0 popup flow OR API integration token
  Hashnode   — Personal Access Token
  Dev.to     — API Key (Forem)

AI providers:
  Anthropic  — API Key
  OpenAI     — API Key
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

import backend.store.memory as store
from backend.schemas.connections import (
    ConnectionInfo,
    ConnectionListResponse,
    OAuthStartResponse,
    SaveTokenRequest,
    SaveTokenResponse,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])

_VALID_IDS = {"medium", "hashnode", "devto", "anthropic", "openai"}

# ── List ──────────────────────────────────────────────────────────────────────


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
    return {"status": "disconnected"}


# ── Medium OAuth 2.0 ──────────────────────────────────────────────────────────


@router.get("/medium/oauth-start", response_model=OAuthStartResponse)
def oauth_start():
    """
    Returns the Medium authorization URL to open in a popup.
    Requires MEDIUM_CLIENT_ID env var (from medium.com/me/applications).
    Falls back gracefully: available=False when not configured.
    """
    client_id = os.environ.get("MEDIUM_CLIENT_ID")
    if not client_id:
        return OAuthStartResponse(available=False)

    redirect_uri = os.environ.get(
        "MEDIUM_REDIRECT_URI",
        "http://localhost:8000/api/connections/medium/oauth-callback",
    )
    scope = "basicProfile%20publicationsList"
    url = (f"https://medium.com/m/oauth/authorize"
           f"?client_id={client_id}"
           f"&scope={scope}"
           f"&state=bloghub"
           f"&response_type=code"
           f"&redirect_uri={redirect_uri}")
    return OAuthStartResponse(url=url, available=True)


@router.get("/medium/oauth-callback", response_class=HTMLResponse)
async def oauth_callback(code: str | None = None, error: str | None = None):
    """
    Medium redirects here after the user grants access.
    Exchanges the code for an access token, stores it, then closes the popup
    by returning an HTML page that posts a message to the opener window.
    """
    if error or not code:
        return HTMLResponse(_popup_html("error", "medium", error=str(error or "access_denied")))

    client_id = os.environ.get("MEDIUM_CLIENT_ID", "")
    client_secret = os.environ.get("MEDIUM_CLIENT_SECRET", "")
    redirect_uri = os.environ.get(
        "MEDIUM_REDIRECT_URI",
        "http://localhost:8000/api/connections/medium/oauth-callback",
    )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            # Exchange authorisation code for access token
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
                    _popup_html("error", "medium", error="No token in OAuth response"))

            # Fetch profile for username display
            me_resp = await client.get(
                "https://api.medium.com/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            me_data = me_resp.json().get("data", {})
            username = me_data.get("username") or me_data.get("name")

        store.save_connection("medium", token, status="connected", username=username)
        return HTMLResponse(_popup_html("connected", "medium", username=username))

    except Exception as exc:
        return HTMLResponse(_popup_html("error", "medium", error=str(exc)))


def _popup_html(
    status: str,
    platform: str,
    *,
    error: str | None = None,
    username: str | None = None,
) -> str:
    """
    Tiny HTML page shown inside the OAuth popup.
    Posts a message to the opener then closes itself.
    Uses location.origin for postMessage target to restrict to same origin.
    """
    payload: dict = {"type": "oauth-complete", "platform": platform, "status": status}
    if username:
        payload["username"] = username
    if error:
        payload["error"] = error

    payload_json = json.dumps(payload)
    message = "Connected!" if status == "connected" else f"Error: {error}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Connecting…</title>
</head>
<body style="font-family:system-ui;background:#0f1117;color:#c9cfe0;
             display:flex;align-items:center;justify-content:center;
             height:100vh;margin:0;text-align:center;">
  <div>
    <p style="margin:0 0 8px;">{message}</p>
    <p style="margin:0;color:#5a6080;font-size:0.8rem;">You can close this window.</p>
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
