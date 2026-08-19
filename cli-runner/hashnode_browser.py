"""Deterministic Hashnode draft upload through a persisted browser profile."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time

SELECTORS_PATH = Path(__file__).with_name("browser_selectors.json")
_ALLOWED_ACTIONS = ("title", "content", "save_draft")


class SelectorFailure(RuntimeError):
    def __init__(self, action: str):
        super().__init__(f"Hashnode control not found: {action}")
        self.action = action


def _first_visible(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1200):
                return locator, selector
        except Exception:
            continue
    return None, None


def upload_hashnode_draft(
    *, profile_dir: str, title: str, article_md: str,
) -> dict:
    from patchright.sync_api import sync_playwright

    selectors = json.loads(SELECTORS_PATH.read_text(encoding="utf-8"))
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile_dir, headless=True, viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(selectors["editor_url"], wait_until="domcontentloaded", timeout=45000)
            if any(part in page.url.lower() for part in ("signin", "login", "onboard")):
                return {
                    "success": False,
                    "error": "Hashnode browser session is not authenticated",
                    "manual_handoff": {
                        "reason": "hashnode_login_required",
                        "url": "https://hashnode.com/login",
                    },
                }

            controls = {}
            for action in _ALLOWED_ACTIONS:
                locator, _ = _first_visible(page, selectors[action])
                if locator is None:
                    raise SelectorFailure(action)
                controls[action] = locator

            controls["title"].fill(title)
            controls["content"].fill(article_md)
            before_url = page.url
            controls["save_draft"].click()
            page.wait_for_timeout(1800)
            if page.locator("text=/error|failed/i").first.is_visible(timeout=500):
                return {"success": False, "error": "Hashnode reported that the draft was not saved"}
            saved_signal = page.locator("text=/draft saved|saved to drafts|saved successfully/i").first
            if page.url == before_url and not saved_signal.is_visible(timeout=1200):
                return {"success": False, "error": "Hashnode draft save could not be verified"}
            result = {
                "success": True,
                "method": "deterministic",
                "url": page.url if "/draft" in page.url else None,
                "draft_id": page.url.rstrip("/").split("/")[-1] if "/draft/" in page.url else None,
            }
        finally:
            context.close()

    return result


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
