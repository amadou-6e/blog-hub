"""Small privileged adapter around Skyvern's browser-session API."""
from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import re
import secrets
import struct
import tomllib
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect as websocket_connect


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


_SCREENSHOT_MAX_BYTES = 12 * 1024 * 1024
_SCREENSHOT_MAX_DIMENSION = 4096
_SCREENSHOT_MAX_PIXELS = 16_000_000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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


def _public_app_url(app_url: str | None, session_id: str, purpose: str) -> str:
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
            f"embed=true&purpose={purpose}",
            "",
        )
    )


_LOGIN_URLS = {
    "hashnode": "https://hashnode.com/login",
    "medium": "https://medium.com/m/signin",
}


def start_browser_login(
    platform: str,
    profile_id: str | None = None,
    *,
    login_url: str | None = None,
) -> dict:
    # The fallback keeps old direct callers working. The runner passes the URL
    # from the installed extension manifest through its login adapter.
    login_url = login_url or _LOGIN_URLS.get(platform)
    if login_url is None:
        raise ValueError(f"{platform} does not support browser login")
    parsed_login = urlsplit(login_url)
    if parsed_login.scheme != "https" or not parsed_login.netloc:
        raise ValueError("Browser login URL must use HTTPS")
    if profile_id is not None and not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("Invalid Skyvern profile id")
    payload = {
        "url": login_url,
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
        "app_url": _public_app_url(session.get("app_url"), session_id, f"{platform}-login"),
        "status": session.get("status") or "created",
    }


def start_hashnode_login(profile_id: str | None = None) -> dict:
    return start_browser_login("hashnode", profile_id)


def start_medium_login(profile_id: str | None = None) -> dict:
    return start_browser_login("medium", profile_id)


def get_browser_login(session_id: str, platform: str = "hashnode") -> dict:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    session = _request("GET", f"/v1/browser_sessions/{session_id}")
    return {
        "session_id": session_id,
        "status": session.get("status"),
        "app_url": _public_app_url(session.get("app_url"), session_id, f"{platform}-login"),
        "completed_at": session.get("completed_at"),
    }


def get_live_browser_probe(session_id: str) -> dict:
    """Read sanitized authentication evidence without finalizing the browser."""
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    try:
        base = urlsplit(SKYVERN_URL)
        scheme = "wss" if base.scheme == "https" else "ws"
        client_id = secrets.token_urlsafe(18)
        query = (
            f"apikey={quote(_api_key(), safe='')}"
            f"&client_id={quote(client_id, safe='')}"
        )
        socket_url = urlunsplit((
            scheme,
            base.netloc,
            f"/v1/stream/messages/browser_session/{session_id}",
            query,
            "",
        ))
        with websocket_connect(
            socket_url, open_timeout=5, close_timeout=2,
        ) as websocket:
            websocket.send('{"kind":"get-login-state"}')
            for _ in range(5):
                payload = json.loads(websocket.recv(timeout=10))
                if payload.get("kind") == "login-state":
                    return _sanitize_live_probe(payload)
        raise SkyvernUnavailable("Skyvern live session probe returned no state")
    except SkyvernUnavailable:
        raise
    except (OSError, TimeoutError, ValueError, WebSocketException) as exc:
        raise SkyvernUnavailable("Skyvern live session probe failed") from exc


def capture_browser_screenshot(session_id: str) -> bytes:
    """Capture one bounded PNG frame without mutating or closing the session."""
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    session = get_browser_login(session_id)
    if session.get("status") != "running":
        raise SkyvernUnavailable("Skyvern browser session is not running")
    base = urlsplit(SKYVERN_URL)
    scheme = "wss" if base.scheme == "https" else "ws"
    socket_url = urlunsplit((
        scheme,
        base.netloc,
        f"/v1/stream/browser_sessions/{session_id}",
        f"apikey={quote(_api_key(), safe='')}",
        "",
    ))
    try:
        with websocket_connect(
            socket_url,
            open_timeout=5,
            close_timeout=2,
            max_size=(_SCREENSHOT_MAX_BYTES * 2),
        ) as websocket:
            for _ in range(10):
                payload = json.loads(websocket.recv(timeout=15))
                if not isinstance(payload, dict):
                    raise SkyvernUnavailable("Skyvern returned an invalid screenshot")
                encoded = payload.get("screenshot")
                if not encoded:
                    continue
                if payload.get("format") != "png" or not isinstance(encoded, str):
                    raise SkyvernUnavailable("Skyvern returned an invalid screenshot")
                if len(encoded) > ((_SCREENSHOT_MAX_BYTES + 2) // 3) * 4:
                    raise SkyvernUnavailable("Skyvern screenshot exceeds the size limit")
                try:
                    screenshot = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise SkyvernUnavailable("Skyvern returned an invalid screenshot") from exc
                _validate_screenshot_png(screenshot)
                return screenshot
        raise SkyvernUnavailable("Skyvern screenshot stream returned no frame")
    except SkyvernUnavailable:
        raise
    except (OSError, TimeoutError, ValueError, WebSocketException) as exc:
        raise SkyvernUnavailable("Skyvern screenshot capture failed") from exc


def _validate_screenshot_png(screenshot: bytes) -> None:
    if len(screenshot) > _SCREENSHOT_MAX_BYTES:
        raise SkyvernUnavailable("Skyvern screenshot exceeds the size limit")
    if len(screenshot) < 24 or not screenshot.startswith(_PNG_SIGNATURE):
        raise SkyvernUnavailable("Skyvern returned an invalid screenshot")
    if screenshot[12:16] != b"IHDR":
        raise SkyvernUnavailable("Skyvern returned an invalid screenshot")
    width, height = struct.unpack(">II", screenshot[16:24])
    if (
        not width
        or not height
        or width > _SCREENSHOT_MAX_DIMENSION
        or height > _SCREENSHOT_MAX_DIMENSION
        or width * height > _SCREENSHOT_MAX_PIXELS
    ):
        raise SkyvernUnavailable("Skyvern screenshot dimensions exceed the limit")


def _sanitize_live_probe(payload: dict) -> dict:
    raw_url = str(payload.get("url") or "")
    parsed = urlsplit(raw_url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    url = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    cookies = []
    for raw in payload.get("cookies", [])[:256]:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        domain = raw.get("domain")
        if not isinstance(name, str) or not isinstance(domain, str):
            continue
        cookies.append({
            "name": name[:256],
            "domain": domain[:256],
            "expires": raw.get("expires"),
            "present": bool(raw.get("present")),
        })
    return {"url": url, "cookies": cookies}


def get_hashnode_login(session_id: str) -> dict:
    return get_browser_login(session_id, "hashnode")


def get_medium_login(session_id: str) -> dict:
    return get_browser_login(session_id, "medium")


def close_browser_login(session_id: str) -> None:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    _request("POST", f"/v1/browser_sessions/{session_id}/close")


def close_hashnode_login(session_id: str) -> None:
    close_browser_login(session_id)


def close_medium_login(session_id: str) -> None:
    close_browser_login(session_id)


def finish_browser_login(
    session_id: str,
    profile_name: str,
    platform: str,
    profile_id: str | None = None,
    organization_id: str | None = None,
) -> dict:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid Skyvern session id")
    close_browser_login(session_id)
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
            "description": f"BlogHub {platform.title()} browser login profile",
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


def finish_hashnode_login(
    session_id: str,
    profile_name: str,
    profile_id: str | None = None,
    organization_id: str | None = None,
) -> dict:
    return finish_browser_login(
        session_id,
        profile_name,
        "hashnode",
        profile_id=profile_id,
        organization_id=organization_id,
    )


def finish_medium_login(
    session_id: str,
    profile_name: str,
    profile_id: str | None = None,
    organization_id: str | None = None,
) -> dict:
    return finish_browser_login(
        session_id,
        profile_name,
        "medium",
        profile_id=profile_id,
        organization_id=organization_id,
    )


def delete_browser_profile(profile_id: str) -> None:
    if not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("Invalid Skyvern profile id")
    _request("DELETE", f"/v1/browser_profiles/{profile_id}")


def delete_hashnode_profile(profile_id: str) -> None:
    delete_browser_profile(profile_id)


def delete_medium_profile(profile_id: str) -> None:
    delete_browser_profile(profile_id)


def profile_directory(organization_id: str, profile_id: str) -> Path:
    if not _ORG_ID.fullmatch(organization_id) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("Invalid Skyvern profile identifiers")
    return SKYVERN_BROWSER_SESSION_ROOT / organization_id / "profiles" / profile_id
