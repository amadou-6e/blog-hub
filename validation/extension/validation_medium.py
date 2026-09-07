"""Trusted local-only replacement for Medium in the isolated validation stack."""
from __future__ import annotations

from pathlib import Path
import ssl
import time
from urllib.parse import urlsplit

from blog_extensions import (
    BlogOperationsAdapter, BrowserLoginAdapter, Capability,
    OperationNotSupported, OperationRequest,
)


ACCOUNT_URL = "https://fixture.test/account"
ACCOUNT_MARKER = '[data-testid="authenticated-account"]'


def _account_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "fixture.test"
                and parsed.port in {None, 443} and parsed.path == "/account"
                and parsed.username is None and parsed.password is None)
    except (TypeError, ValueError):
        return False


def _result(authenticated: bool) -> dict:
    return {"authenticated": authenticated,
            "status": "connected" if authenticated else "login_required"}


def _live_cookie(cookie: dict) -> bool:
    try:
        expires = float(cookie.get("expires"))
    except (TypeError, ValueError):
        return False
    return (cookie.get("name") == "blog_session"
            and str(cookie.get("domain", "")).lstrip(".") == "fixture.test"
            and cookie.get("present") is True
            and expires > time.time())


def _authenticated_page(page) -> bool:
    response = page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=30000)
    return bool(response and response.status == 200 and _account_url(page.url)
                and page.locator(ACCOUNT_MARKER).is_visible())


class LoginAdapter(BrowserLoginAdapter):
    platform = "medium"
    login_url = "https://fixture.test/login"

    def verify_live_session(self, probe: dict) -> dict:
        return _result(_account_url(probe.get("url", "")) and any(
            _live_cookie(cookie) for cookie in probe.get("cookies", [])
            if isinstance(cookie, dict)
        ))

    def verify_profile(self, profile_dir: Path) -> dict:
        if not profile_dir.is_dir():
            return _result(False)
        from patchright.sync_api import sync_playwright
        import httpx

        configuration = httpx.get(
            "https://fixture.test/control",
            verify=ssl.create_default_context(cafile="/certs/ca.crt"), timeout=5,
        )
        configuration.raise_for_status()
        time.sleep(configuration.json().get("verification_delay", 0))

        # Use the image's trusted CA, never ignore HTTPS errors or inspect cookie
        # files as proof: the server must accept this profile on a fresh request.
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir), headless=True,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                return _result(_authenticated_page(page))
            finally:
                context.close()


class OperationsAdapter(BlogOperationsAdapter):
    platform = "medium"
    capabilities = frozenset({Capability.LIST_ARTICLES})

    def execute(self, page, operation: Capability, request: OperationRequest) -> dict:
        if operation not in self.capabilities:
            raise OperationNotSupported(self.platform, operation.value)
        if not _authenticated_page(page):
            challenge = urlsplit(page.url).path == "/challenge"
            return {"success": False, "articles": [],
                    "error": "Verification challenge" if challenge else "Authentication required"}
        listing = page.locator('[data-testid="article-list"]')
        if not listing.is_visible() or listing.get_attribute("data-count") != "0":
            return {"success": False, "articles": [], "error": "Unexpected fixture article list"}
        return {"success": True, "status": "connected", "articles": [], "next_cursor": None}
