"""Small privileged adapter around Skyvern's browser-session API."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit, urlunsplit

import httpx


SKYVERN_URL = os.environ.get("SKYVERN_URL", "http://skyvern:8000").rstrip("/")
SKYVERN_PUBLIC_APP_URL = os.environ.get(
    "SKYVERN_PUBLIC_APP_URL", "http://localhost:8083"
).rstrip("/")
SKYVERN_CREDENTIALS_FILE = Path(
    os.environ.get("SKYVERN_CREDENTIALS_FILE", "/run/skyvern/credentials.toml")
)
SKYVERN_BROWSER_SESSION_ROOT = Path(
    os.environ.get("SKYVERN_BROWSER_SESSION_ROOT", "/data/skyvern-browser-sessions")
)

_SESSION_ID = re.compile(r"^pbs_[A-Za-z0-9]+$")
_PROFILE_ID = re.compile(r"^bp_[A-Za-z0-9]+$")
_ORG_ID = re.compile(r"^o_[A-Za-z0-9]+$")


class SkyvernUnavailable(RuntimeError):
    pass


def _api_key() -> str:
    configured = os.environ.get("SKYVERN_API_KEY")
    if configured:
        return configured
    try:
        document = tomllib.loads(SKYVERN_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        for config in document.get("skyvern", {}).get("configs", []):
            for organization in config.get("orgs", []):
                credential = organization.get("cred")
                if credential:
                    return credential
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        pass
    raise SkyvernUnavailable("Skyvern local API credential is unavailable")


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    try:
        response = httpx.request(
            method,
            SKYVERN_URL + path,
            headers={"x-api-key": _api_key()},
            json=payload,
            timeout=httpx.Timeout(120, connect=5),
        )
        response.raise_for_status()
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise SkyvernUnavailable(f"Skyvern request failed: {type(exc).__name__}") from exc


def _public_app_url(app_url: str | None, session_id: str) -> str:
    path = f"/browser-session/{session_id}/stream"
    if app_url:
        upstream_path = urlsplit(app_url).path.rstrip("/")
        if upstream_path:
            path = upstream_path
            if not path.endswith("/stream"):
                path += "/stream"
    public = urlsplit(SKYVERN_PUBLIC_APP_URL)
    return urlunsplit(
        (
            public.scheme,
            public.netloc,
            path,
            "embed=true&purpose=hashnode-login",
            "",
        )
    )


def start_hashnode_login(profile_id: str | None = None) -> dict:
    if profile_id is not None and not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("Invalid Skyvern profile id")
    payload = {
        "url": "https://hashnode.com/login",
        "timeout": None,
        # New sessions need an export that can become a profile. Sessions
        # loaded from a profile persist back to that profile automatically.
        "generate_browser_profile": profile_id is None,
        "needs_live_view": True,
    }
    if profile_id:
        payload["browser_profile_id"] = profile_id
    session = _request("POST", "/v1/browser_sessions", payload)
    session_id = session.get("browser_session_id", "")
    organization_id = session.get("organization_id", "")
    if not _SESSION_ID.fullmatch(session_id) or not _ORG_ID.fullmatch(organization_id):
        raise SkyvernUnavailable("Skyvern returned invalid browser identifiers")
    return {
        "session_id": session_id,
        "organization_id": organization_id,
        "app_url": _public_app_url(session.get("app_url"), session_id),
        "status": session.get("status") or "created",
    }


def get_hashnode_login(session_id: str) -> dict:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    session = _request("GET", f"/v1/browser_sessions/{session_id}")
    return {
        "session_id": session_id,
        "status": session.get("status"),
        "app_url": _public_app_url(session.get("app_url"), session_id),
        "completed_at": session.get("completed_at"),
    }


def close_hashnode_login(session_id: str) -> None:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    _request("POST", f"/v1/browser_sessions/{session_id}/close")


def finish_hashnode_login(
    session_id: str,
    profile_name: str,
    profile_id: str | None = None,
    organization_id: str | None = None,
) -> dict:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    close_hashnode_login(session_id)
    if profile_id is not None:
        if organization_id is None:
            raise ValueError("Skyvern organization id is required for a reused profile")
        return {
            "profile_id": profile_id,
            "organization_id": organization_id,
            "profile_dir": str(profile_directory(organization_id, profile_id)),
        }
    profile = _request(
        "POST",
        "/v1/browser_profiles",
        {
            "name": profile_name[:120],
            "description": "BlogHub Hashnode browser login profile",
            "browser_session_id": session_id,
        },
    )
    profile_id = profile.get("browser_profile_id", "")
    organization_id = profile.get("organization_id", "")
    if not _PROFILE_ID.fullmatch(profile_id) or not _ORG_ID.fullmatch(organization_id):
        raise SkyvernUnavailable("Skyvern returned invalid profile identifiers")
    return {
        "profile_id": profile_id,
        "organization_id": organization_id,
        "profile_dir": str(profile_directory(organization_id, profile_id)),
    }


def delete_hashnode_profile(profile_id: str) -> None:
    if not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("Invalid Skyvern profile id")
    _request("DELETE", f"/v1/browser_profiles/{profile_id}")


def profile_directory(organization_id: str, profile_id: str) -> Path:
    if not _ORG_ID.fullmatch(organization_id) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("Invalid Skyvern profile identifiers")
    return SKYVERN_BROWSER_SESSION_ROOT / organization_id / "profiles" / profile_id
