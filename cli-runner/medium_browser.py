"""Medium browser-profile checks for persistent Skyvern sessions."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
def check_medium_profile(*, profile_dir: str) -> dict:
    profile = Path(profile_dir)
    authenticated = _chromium_cookie_db_has_medium_session(profile)
    if not authenticated:
        authenticated = _cookie_snapshot_has_medium_session(profile)
    return {
        "authenticated": authenticated,
        "status": "connected" if authenticated else "login_required",
    }


def _is_medium_session_cookie(domain: object, name: object) -> bool:
    normalized_domain = str(domain or "").lstrip(".")
    return (
        normalized_domain == "medium.com"
        and str(name or "") in {"sid", "uid", "lightstep_guid"}
    )


def _cookie_is_not_expired(expires: object) -> bool:
    try:
        value = float(expires)
    except (TypeError, ValueError):
        return True
    return value < 0 or value > time.time()


def _chromium_cookie_db_has_medium_session(profile: Path) -> bool:
    candidates = [
        profile / "Default" / "Cookies",
        profile / "Cookies",
    ]
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            rows = connection.execute(
                "SELECT host_key, name, expires_utc, value, encrypted_value FROM cookies"
            ).fetchall()
        except sqlite3.Error:
            continue
        finally:
            try:
                connection.close()
            except Exception:
                pass
        has_uid = False
        has_sid = False
        for domain, name, expires_utc, value, encrypted_value in rows:
            if not _is_medium_session_cookie(domain, name):
                continue
            if expires_utc and int(expires_utc) < 10_000_000_000_000_000:
                continue
            if not (value or encrypted_value):
                continue
            has_uid = has_uid or name == "uid"
            has_sid = has_sid or name == "sid"
        if has_uid and has_sid:
            return True
    return False


def _cookie_snapshot_has_medium_session(profile: Path) -> bool:
    snapshot = profile / ".skyvern_session_cookies.json"
    try:
        cookies = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(cookies, list):
        return False
    names = {
        str(cookie.get("name") or "")
        for cookie in cookies
        if isinstance(cookie, dict)
        and _is_medium_session_cookie(cookie.get("domain"), cookie.get("name"))
        and _cookie_is_not_expired(cookie.get("expires"))
        and cookie.get("value")
    }
    return {"sid", "uid"}.issubset(names)
