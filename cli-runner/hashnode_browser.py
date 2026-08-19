"""Deterministic Hashnode draft upload through a persisted browser profile."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time

SELECTORS_PATH = Path(__file__).with_name("browser_selectors.json")


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


def _wait_first_visible(page, selectors: list[str], *, timeout_ms: int = 20_000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        locator, selector = _first_visible(page, selectors)
        if locator is not None:
            return locator, selector
        page.wait_for_timeout(250)
    return None, None


def _draft_id(url: str) -> str | None:
    marker = "/draft/"
    return url.rstrip("/").split(marker, 1)[1] if marker in url else None


def _normalized_markdown(markdown: str) -> str:
    normalized = re.sub(
        r'(!\[[^\]]*\]\([^\s)]+)\s+align="center"(\))',
        r"\1\2",
        markdown,
    )
    normalized = re.sub(r"^\*\s{3}", "- ", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"^\s+$", "", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"(^- .+)\n\n(?=- )", r"\1\n", normalized, flags=re.MULTILINE)
    return normalized.strip()


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

            editor_entry, _ = _wait_first_visible(page, selectors["editor_entry"])
            if editor_entry is None:
                raise SelectorFailure("editor_entry")
            editor_entry.click()
            page.wait_for_url("**/draft/**", timeout=30_000)
            previous_draft_url = page.url
            new_draft, _ = _wait_first_visible(
                page, selectors["new_draft"], timeout_ms=60_000
            )
            if new_draft is None:
                raise SelectorFailure("new_draft")
            new_draft.click()
            deadline = time.monotonic() + 30
            while page.url == previous_draft_url and time.monotonic() < deadline:
                page.wait_for_timeout(250)
            if page.url == previous_draft_url:
                raise SelectorFailure("new_draft")

            title_control, _ = _wait_first_visible(page, selectors["title"])
            markdown_mode, _ = _wait_first_visible(page, selectors["markdown_mode"])
            if title_control is None:
                raise SelectorFailure("title")
            if markdown_mode is None:
                raise SelectorFailure("markdown_mode")
            markdown_mode.click()
            content_control, _ = _wait_first_visible(page, selectors["content"])
            if content_control is None:
                raise SelectorFailure("content")

            title_control.fill(title)
            content_control.fill(article_md)
            draft_url = page.url
            draft_id = _draft_id(draft_url)

            # Hashnode autosaves drafts. A reload is the strongest deterministic
            # confirmation available without clicking the public Publish action.
            page.wait_for_timeout(6_000)
            page.reload(wait_until="domcontentloaded", timeout=45_000)
            title_control, _ = _wait_first_visible(page, selectors["title"])
            content_control, _ = _wait_first_visible(
                page, selectors["content"], timeout_ms=2_000
            )
            if content_control is None:
                markdown_mode, _ = _wait_first_visible(page, selectors["markdown_mode"])
                if markdown_mode is not None:
                    markdown_mode.click()
                    content_control, _ = _wait_first_visible(
                        page, selectors["content"]
                    )
            if (
                title_control is None
                or content_control is None
                or title_control.input_value() != title
                or _normalized_markdown(content_control.input_value())
                != _normalized_markdown(article_md)
            ):
                return {
                    "success": False,
                    "error": "Hashnode draft autosave could not be verified",
                    "url": draft_url,
                    "draft_id": draft_id,
                }
            result = {
                "success": True,
                "method": "deterministic",
                "url": draft_url,
                "draft_id": draft_id,
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
