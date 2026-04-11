"""
test_settings.py — Settings screen Playwright tests.

Run against a live backend (port 8000) and cli-runner (port 8001):
    pytest tests/ui/test_settings.py -m browser --browser msedge -v

Claude browser login test:
    The cli-runner spawns `claude auth login`, which starts a local HTTP server
    on a random port inside Docker and returns a loopback auth URL:
        https://claude.ai/oauth/authorize?...&redirect_uri=http://localhost:{PORT}/callback&...
    After the user authorizes, the browser tries to redirect to that localhost
    URL — which fails (port is inside Docker). The callback URL with code+state
    is captured from the failed network request and submitted to
    POST /api/connections/anthropic/submit-code. The runner forwards it to the
    CLI's internal server, token exchange succeeds, and the card shows Connected.
"""
import re
import pytest
import requests
from urllib.parse import urlparse, parse_qs

from tests.tests_ui.conftest import BASE_URL, RUNNER_URL, SETTINGS_URL

pytestmark = pytest.mark.browser


# ── 1. Initial load ────────────────────────────────────────────────────────────

def test_renders_platforms_section_by_default(settings_page):
    settings_page.get_by_role("heading", name="Publishing Platforms").wait_for()


def test_ai_providers_tab_renders_both_cards(ai_providers_page):
    assert ai_providers_page.locator("#ai-wrap-anthropic").is_visible()
    assert ai_providers_page.locator("#ai-wrap-openai").is_visible()


def test_claude_card_shows_not_configured_on_fresh_store(ai_providers_page):
    card = ai_providers_page.locator("#ai-wrap-anthropic")
    assert card.get_by_text("Not configured").is_visible()


# ── 2. API key flow ────────────────────────────────────────────────────────────

def test_contract_saving_api_key_calls_put(ai_providers_page):
    """PUT /api/connections/anthropic  { token: "sk-ant-test" }  → 200"""
    page = ai_providers_page
    page.locator("#ai-wrap-anthropic").get_by_role("button", name="Add API key").click()

    with page.expect_request(
        lambda r: "/api/connections/anthropic" in r.url and r.method == "PUT"
    ) as req_info:
        page.locator("#key-input-anthropic").fill("sk-ant-test")
        page.locator("#ai-wrap-anthropic").get_by_role("button", name="Save").click()

    body = req_info.value.post_data_json
    assert body["token"] == "sk-ant-test"


# ── 3. Browser login flow ──────────────────────────────────────────────────────

def test_claude_browser_login_full_loopback_flow(page, context):
    """
    Full Claude browser-login via the loopback OAuth flow.

    1. Click "Login with browser" — runner returns a loopback auth URL
       (redirect_uri=http://localhost:{PORT}/callback).
    2. A new tab opens at claude.ai/oauth/authorize.
    3. Authorize — claude.ai redirects to the loopback callback URL.
    4. Redirect fails (port is inside Docker); callback URL is captured from
       the failed network request via Playwright's request listener.
    5. Submit the full callback URL to POST /api/connections/anthropic/submit-code.
    6. Poll cli-login-status until connected.
    7. Assert the card shows Connected.
    """
    page.goto(SETTINGS_URL)
    page.get_by_role("button", name="AI Providers").click()
    page.wait_for_selector("#ai-wrap-anthropic", timeout=5000)

    # Capture the new tab that opens when the auth URL is launched
    with context.expect_page() as oauth_tab_info:
        page.locator("#ai-wrap-anthropic").get_by_role(
            "button", name="Login with browser"
        ).click()

    oauth_tab = oauth_tab_info.value
    oauth_tab.wait_for_load_state("domcontentloaded")

    # Confirm redirect_uri is a loopback URL, not platform.claude.com
    auth_url = urlparse(oauth_tab.url)
    redirect_uri = parse_qs(auth_url.query)["redirect_uri"][0]
    assert re.match(r"http://localhost:\d+/callback", redirect_uri), (
        f"Expected loopback redirect_uri, got: {redirect_uri}"
    )
    callback_port = urlparse(redirect_uri).port

    # Listen for the failed redirect to capture code + state
    captured: list[str] = []

    def on_request(req):
        if req.url.startswith(f"http://localhost:{callback_port}/callback"):
            captured.append(req.url)

    oauth_tab.on("request", on_request)

    # Authorize (button label varies by browser locale)
    oauth_tab.wait_for_selector("button", timeout=10_000)
    authorize_btn = oauth_tab.get_by_role("button").filter(
        has_text=re.compile(r"authoris|autorisier|allow|grant", re.IGNORECASE)
    ).first
    authorize_btn.click()

    # Wait for the callback URL to be captured (up to 15 s)
    oauth_tab.wait_for_function(
        "() => window.location.href.startsWith('http://localhost')",
        timeout=15_000,
    )
    # Fallback: read directly from the page URL after navigation attempt
    callback_url = captured[0] if captured else oauth_tab.url

    assert "code=" in callback_url
    assert "state=" in callback_url

    # Submit the callback URL to the backend
    res = requests.post(
        f"{BASE_URL}/api/connections/anthropic/submit-code",
        json={"code": callback_url},
    )
    assert res.status_code == 200

    # Poll the backend's cli-login-status until connected (up to 20 s)
    import time
    deadline = time.time() + 20
    backend_status = None
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/connections/anthropic/cli-login-status")
        backend_status = r.json().get("status")
        if backend_status == "connected":
            break
        time.sleep(1)
    assert backend_status == "connected", f"Backend status: {backend_status}"

    # Verify the CLI itself is authenticated via the runner (not just the in-memory store)
    runner_status = requests.get(f"{RUNNER_URL}/auth/anthropic/status").json()
    assert runner_status["status"] == "connected", (
        f"CLI runner reports not authenticated: {runner_status}"
    )

    # UI should reflect Connected
    page.bring_to_front()
    page.locator("#ai-wrap-anthropic").get_by_text("Connected").wait_for(timeout=10_000)


# ── 4. Disconnect ──────────────────────────────────────────────────────────────

def test_contract_remove_calls_delete(ai_providers_page):
    """DELETE /api/connections/anthropic → 200 { status: "disconnected" }"""
    page = ai_providers_page

    # Pre-seed a connected anthropic token
    requests.put(
        f"{BASE_URL}/api/connections/anthropic",
        json={"token": "sk-ant-seed"},
    )
    page.reload()
    page.get_by_role("button", name="AI Providers").click()
    page.wait_for_selector("#ai-wrap-anthropic", timeout=5000)

    # "Remove" opens a confirmation popover; confirm button inside also says "Remove"
    page.locator("#ai-wrap-anthropic").get_by_role("button", name=re.compile(r"^remove$", re.I)).click()

    with page.expect_request(
        lambda r: "/api/connections/anthropic" in r.url and r.method == "DELETE"
    ) as req_info:
        page.locator("#confirm-anthropic").get_by_role(
            "button", name=re.compile(r"^remove$", re.I)
        ).click()

    assert req_info.value is not None
