"""Targeted logout for a shared persisted browser profile."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def domain_matches(domain: object, session_domains: Iterable[str]) -> bool:
    candidate = str(domain or "").lstrip(".").lower()
    return any(
        candidate == allowed or candidate.endswith(f".{allowed}")
        for allowed in (item.lstrip(".").lower() for item in session_domains)
    )


def clear_context_session(context: Any, session_domains: tuple[str, ...]) -> int:
    removed = 0
    for cookie in context.cookies():
        if not domain_matches(cookie.get("domain"), session_domains):
            continue
        context.clear_cookies(
            name=cookie.get("name"),
            domain=cookie.get("domain"),
            path=cookie.get("path") or "/",
        )
        removed += 1
    return removed


def _clear_cookie_snapshot(
    profile_dir: Path, session_domains: tuple[str, ...],
) -> None:
    snapshot = profile_dir / ".skyvern_session_cookies.json"
    try:
        cookies = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return
    if not isinstance(cookies, list):
        return
    retained = [
        cookie for cookie in cookies
        if not isinstance(cookie, dict)
        or not domain_matches(cookie.get("domain"), session_domains)
    ]
    temporary = snapshot.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(retained, separators=(",", ":")), encoding="utf-8")
    temporary.replace(snapshot)


def clear_profile_session(
    profile_dir: Path, session_domains: tuple[str, ...],
) -> int:
    if not session_domains:
        raise ValueError("Browser extension does not declare a session domain")
    if not profile_dir.is_dir():
        return 0

    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=True,
        )
        try:
            removed = clear_context_session(context, session_domains)
        finally:
            context.close()
    _clear_cookie_snapshot(profile_dir, session_domains)
    return removed
