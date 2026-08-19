"""Verify persisted Hashnode browser profiles without exposing credentials."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time


def check_hashnode_profile(*, profile_dir: str) -> dict:
    """Verify a closed Chromium profile without launching another browser."""
    profile = Path(profile_dir)
    authenticated = _chromium_cookie_db_has_hashnode_session(profile)
    if not authenticated:
        authenticated = _cookie_snapshot_has_hashnode_session(profile)
    return {
        "authenticated": authenticated,
        "status": "connected" if authenticated else "login_required",
    }


def _is_hashnode_session_cookie(domain: object, name: object) -> bool:
    return (
        str(domain or "").lstrip(".") == "hashnode.com"
        and (
            name in {"authjs.session-token", "hashnode-session"}
            or str(name or "").startswith("__Secure-authjs.session-token")
        )
    )


def _chromium_cookie_db_has_hashnode_session(profile: Path) -> bool:
    # Chromium stores expiry as microseconds since 1601-01-01 UTC.
    chrome_now = int((time.time() + 11_644_473_600) * 1_000_000)
    for cookie_db in (profile / "Default" / "Cookies", profile / "Cookies"):
        if not cookie_db.is_file():
            continue
        try:
            connection = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
            try:
                rows = connection.execute(
                    "SELECT host_key, name, expires_utc, length(value), "
                    "length(encrypted_value) FROM cookies"
                )
                if any(
                    _is_hashnode_session_cookie(domain, name)
                    and (int(value_length or 0) + int(encrypted_length or 0) > 0)
                    and (not expires or int(expires) > chrome_now)
                    for domain, name, expires, value_length, encrypted_length in rows
                ):
                    return True
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            continue
    return False


def _cookie_snapshot_has_hashnode_session(profile: Path) -> bool:
    snapshot = profile / ".skyvern_session_cookies.json"
    try:
        cookies = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        cookies = []
    if not isinstance(cookies, list):
        cookies = []
    now = time.time()
    return any(
        isinstance(cookie, dict)
        and _is_hashnode_session_cookie(cookie.get("domain"), cookie.get("name"))
        and bool(cookie.get("value"))
        and (
            not isinstance(cookie.get("expires"), (int, float))
            or cookie["expires"] <= 0
            or cookie["expires"] > now
        )
        for cookie in cookies
    )
