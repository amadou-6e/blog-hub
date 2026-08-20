"""
test_settings.py — Settings screen Playwright tests.

Run against a live backend (port 8000) and cli-runner (port 8001):
    pytest tests/tests_ui/screens/test_settings.py -m browser --browser msedge -v

Claude browser login test:
    The cli-runner spawns `claude auth login`, which starts a local HTTP server
    on a random port inside Docker and returns a loopback auth URL:
        https://claude.ai/oauth/authorize?...&redirect_uri=http://localhost:{PORT}/callback&...
    After the user authorizes, the browser tries to redirect to that localhost
    URL — which fails (port is inside Docker). The callback URL with code+state
    is captured from the failed network request and submitted to the durable,
    provider-neutral auth-flow callback endpoint. The runner forwards it to the
    CLI's internal server, token exchange succeeds, and the card shows Connected.
"""
import re
import pytest
import requests
from urllib.parse import urlparse, parse_qs

from tests.tests_ui.conftest import BASE_URL, RUNNER_URL, SETTINGS_URL

pytestmark = pytest.mark.browser


def _hashnode_browser_payload(status="disconnected", authorization_url=None):
    return {
        "platform": "hashnode",
        "status": status,
        "authorizationUrl": authorization_url,
        "verifiedAt": None,
        "error": None,
    }


def _show_disconnected_hashnode(page):
    page.route(
        f"{BASE_URL}/api/connections/hashnode/browser-connection",
        lambda route: route.fulfill(json=_hashnode_browser_payload()),
    )
    page.reload()
    page.locator("#plat-card-hashnode").get_by_role("button", name="Connect").wait_for()

# ── 1. Initial load ────────────────────────────────────────────────────────────


def test_unauthenticated_settings_redirects_to_login(page):
    page.goto(SETTINGS_URL)
    page.wait_for_url("**/screens/login/v1.html?next=**")
    assert page.url.endswith(
        "/screens/login/v1.html?next=%2Fscreens%2Fsettings%2Fv2.html"
    )


def test_renders_platforms_section_by_default(settings_page):
    settings_page.get_by_role("heading", name="Publishing Platforms").wait_for()


def test_ai_providers_tab_renders_both_cards(ai_providers_page):
    assert ai_providers_page.locator("#ai-wrap-anthropic").is_visible()
    assert ai_providers_page.locator("#ai-wrap-openai").is_visible()


def test_hashnode_connect_opens_method_chooser(settings_page):
    _show_disconnected_hashnode(settings_page)
    card = settings_page.locator("#plat-card-hashnode")

    card.get_by_role("button", name="Connect").click()

    menu = card.locator("#hashnode-method-menu")
    assert menu.get_by_role("button", name=re.compile(r"API token")).is_visible()
    assert menu.get_by_role("button", name=re.compile(r"Browser login")).is_visible()


def test_hashnode_api_token_choice_opens_credential_input(settings_page):
    _show_disconnected_hashnode(settings_page)
    card = settings_page.locator("#plat-card-hashnode")
    card.get_by_role("button", name="Connect").click()
    card.get_by_role("button", name=re.compile(r"API token")).click()

    assert card.locator("#key-input-hashnode").is_visible()


def test_hashnode_browser_login_opens_normal_tab(settings_page, context):
    page = settings_page

    def browser_connection(route):
        if route.request.method == "POST":
            route.fulfill(
                status=201,
                json=_hashnode_browser_payload(
                    "waiting_for_login", f"{BASE_URL}/health"
                ),
            )
        else:
            route.fulfill(json=_hashnode_browser_payload())

    page.route(
        f"{BASE_URL}/api/connections/hashnode/browser-connection",
        browser_connection,
    )
    page.reload()
    page.evaluate("""
      window.__hashnodeOpenCalls = [];
      const nativeOpen = window.open;
      window.open = (...args) => {
        window.__hashnodeOpenCalls.push(args);
        return nativeOpen.apply(window, args);
      };
    """)

    with context.expect_page() as login_tab_info:
        card = page.locator("#plat-card-hashnode")
        card.get_by_role("button", name="Connect").click()
        card.get_by_role("button", name=re.compile(r"Browser login")).click()

    login_tab = login_tab_info.value
    login_tab.wait_for_url(f"{BASE_URL}/health?purpose=hashnode-login")
    open_call = page.evaluate("window.__hashnodeOpenCalls[0]")
    assert open_call == ["about:blank", "_blank"]
    assert page.get_by_role("button", name="I've signed in").count() == 0

    page.route(
        f"{BASE_URL}/api/connections/hashnode/browser-connection/complete",
        lambda route: route.fulfill(
            status=200,
            json={
                "platform": "hashnode",
                "status": "connected",
                "authorizationUrl": None,
                "verifiedAt": "2026-08-19T00:00:00Z",
                "error": None,
            },
        ),
    )
    login_tab.close()
    card = page.locator("#plat-card-hashnode")
    card.get_by_text("Connected", exact=True).wait_for(timeout=5000)
    card.get_by_text("Browser login · Persistent profile", exact=True).wait_for()
    assert login_tab.is_closed()


def test_hashnode_connected_card_only_offers_disconnect(page):
    page.request.post(
        f"{BASE_URL}/api/auth/login",
        data={"email": "seed@example.com", "password": "seed1234", "remember_me": False},
    )
    page.route(
        f"{BASE_URL}/api/connections/hashnode/browser-connection",
        lambda route: route.fulfill(json={
            "platform": "hashnode",
            "status": "connected",
            "authorizationUrl": None,
            "verifiedAt": "2026-08-19T00:00:00Z",
            "error": None,
        }),
    )

    page.goto(SETTINGS_URL)
    card = page.locator("#plat-card-hashnode")
    card.get_by_text("Browser login · Persistent profile", exact=True).wait_for()

    actions = card.get_by_role("button")
    assert actions.count() == 1
    assert actions.first.inner_text() == "Disconnect"
    assert card.get_by_text("Test", exact=True).count() == 0
    assert card.get_by_text("Refresh login", exact=True).count() == 0


@pytest.mark.parametrize(
    ("function_name", "endpoint"),
    [
        ("startHashnodeBrowserLogin", "/api/connections/hashnode/browser-connection"),
        (
            "completeHashnodeBrowserLogin",
            "/api/connections/hashnode/browser-connection/complete",
        ),
        ("disconnectHashnodeBrowser", "/api/connections/hashnode/browser-connection"),
    ],
)
def test_hashnode_browser_actions_redirect_expired_sessions(
    settings_page, function_name, endpoint,
):
    settings_page.route(
        f"{BASE_URL}{endpoint}",
        lambda route: route.fulfill(status=401, json={"detail": "Authentication required"}),
    )

    settings_page.evaluate(f"void {function_name}()")

    settings_page.wait_for_url("**/screens/login/v1.html?next=**")
    assert settings_page.url.endswith(
        "/screens/login/v1.html?next=%2Fscreens%2Fsettings%2Fv2.html"
    )


def test_claude_card_shows_not_configured_on_fresh_store(ai_providers_page):
    card = ai_providers_page.locator("#ai-wrap-anthropic")
    assert card.get_by_text("Not configured").is_visible()


# ── 2. API key flow ────────────────────────────────────────────────────────────


def test_contract_saving_api_key_calls_put(ai_providers_page):
    """PUT /api/connections/anthropic  { token: "sk-ant-test" }  → 200"""
    page = ai_providers_page
    page.locator("#ai-wrap-anthropic").get_by_role("button", name="Add API key").click()

    with page.expect_request(
            lambda r: "/api/connections/anthropic" in r.url and r.method == "PUT") as req_info:
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
    5. Submit the full callback URL to the provider-neutral auth-flow endpoint.
    6. Poll the durable auth flow until connected.
    7. Assert the card shows Connected.
    """
    page.goto(SETTINGS_URL)
    page.get_by_role("button", name="AI Providers").click()
    page.wait_for_selector("#ai-wrap-anthropic", timeout=5000)

    # Capture the new tab that opens when the auth URL is launched
    with context.expect_page() as oauth_tab_info:
        page.locator("#ai-wrap-anthropic").get_by_role("button", name="Login with browser").click()

    oauth_tab = oauth_tab_info.value
    oauth_tab.wait_for_load_state("domcontentloaded")

    # Confirm redirect_uri is a loopback URL, not platform.claude.com
    auth_url = urlparse(oauth_tab.url)
    redirect_uri = parse_qs(auth_url.query)["redirect_uri"][0]
    assert re.match(r"http://localhost:\d+/callback",
                    redirect_uri), (f"Expected loopback redirect_uri, got: {redirect_uri}")
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
        has_text=re.compile(r"authoris|autorisier|allow|grant", re.IGNORECASE)).first
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

    page.bring_to_front()
    callback_input = page.locator("#callback-input-anthropic")
    callback_input.fill(callback_url)
    with page.expect_request(
        lambda req: "/api/connections/auth-flows/" in req.url
        and req.url.endswith("/callback") and req.method == "POST"
    ) as callback_request:
        page.locator("#callback-area-anthropic").get_by_role(
            "button", name="Submit"
        ).click()
    assert callback_request.value.post_data_json["callbackUrl"] == callback_url

    # Verify the CLI itself is authenticated via the runner (not just the in-memory store)
    runner_status = requests.get(f"{RUNNER_URL}/auth/anthropic/status").json()
    assert runner_status["status"] == "connected", (
        f"CLI runner reports not authenticated: {runner_status}")

    # UI should reflect Connected
    page.locator("#ai-wrap-anthropic").get_by_text("Connected").wait_for(timeout=10_000)


def _connection_payload(anthropic="disconnected", openai="disconnected"):
    def item(conn_id, status):
        return {
            "id": conn_id,
            "label": "Anthropic" if conn_id == "anthropic" else "OpenAI",
            "type": "ai",
            "authMethod": "oauth_or_token",
            "status": status,
            "username": "writer@example.com" if status == "connected" else None,
            "connectedAt": "2026-08-10T10:00:00Z" if status == "connected" else None,
            "errorMessage": None,
        }
    return {"connections": [item("anthropic", anthropic), item("openai", openai)]}


def test_callback_flow_uses_shared_contract_and_updates_without_reload(page):
    state = {"connected": False, "polls": 0}

    def connections(route):
        status = "connected" if state["connected"] else "disconnected"
        route.fulfill(json=_connection_payload(anthropic=status))

    def flow_status(route):
        state["polls"] += 1
        state["connected"] = True
        route.fulfill(json={
            "flowId": "auth_callback_1", "provider": "anthropic",
            "flowType": "browser_callback", "status": "connected",
            "username": "writer@example.com", "authorizationUrl": None,
            "deviceCode": None, "errorCode": None, "errorMessage": None,
            "recovery": None, "expiresAt": "2026-08-10T10:05:00Z",
            "createdAt": "2026-08-10T10:00:00Z", "updatedAt": "2026-08-10T10:01:00Z",
        })

    page.route(f"{BASE_URL}/api/connections", connections)
    page.route(f"{BASE_URL}/api/connections/auth-flows/active", lambda route: route.fulfill(json={"flows": []}))
    page.route(f"{BASE_URL}/api/connections/anthropic/auth-flows", lambda route: route.fulfill(status=201, json={
        "flowId": "auth_callback_1", "provider": "anthropic",
        "flowType": "browser_callback", "status": "waiting_for_authorization",
        "authorizationUrl": "https://provider.example/authorize", "deviceCode": None,
        "username": None, "errorCode": None, "errorMessage": None, "recovery": None,
        "expiresAt": "2026-08-10T10:05:00Z", "createdAt": "2026-08-10T10:00:00Z",
        "updatedAt": "2026-08-10T10:00:00Z",
    }))
    page.route(f"{BASE_URL}/api/connections/auth-flows/auth_callback_1/callback", lambda route: route.fulfill(json={
        "flowId": "auth_callback_1", "provider": "anthropic",
        "flowType": "browser_callback", "status": "waiting_for_authorization",
        "authorizationUrl": None, "deviceCode": None, "username": None,
        "errorCode": None, "errorMessage": None, "recovery": None,
        "expiresAt": "2026-08-10T10:05:00Z", "createdAt": "2026-08-10T10:00:00Z",
        "updatedAt": "2026-08-10T10:00:10Z",
    }))
    page.route(f"{BASE_URL}/api/connections/auth-flows/auth_callback_1", flow_status)

    page.goto(SETTINGS_URL)
    page.get_by_role("button", name="AI Providers").click()
    page.evaluate("window.open = () => null")
    page.locator("#ai-wrap-anthropic").get_by_role("button", name="Login with browser").click()
    page.locator("#callback-input-anthropic").fill(
        "http://localhost:54322/callback?code=secret&state=temporary"
    )
    page.locator("#callback-area-anthropic").get_by_role("button", name="Submit").click()
    page.locator("#ai-wrap-anthropic").get_by_text("Connected").wait_for(timeout=7000)
    assert state["polls"] >= 1


def test_callback_poll_does_not_erase_pasted_url(page):
    waiting = {
        "flowId": "auth_callback_1", "provider": "anthropic",
        "flowType": "browser_callback", "status": "waiting_for_authorization",
        "authorizationUrl": "https://provider.example/authorize", "deviceCode": None,
        "username": None, "errorCode": None, "errorMessage": None, "recovery": None,
        "expiresAt": "2026-08-10T10:05:00Z", "createdAt": "2026-08-10T10:00:00Z",
        "updatedAt": "2026-08-10T10:00:00Z",
    }
    page.route(
        f"{BASE_URL}/api/connections",
        lambda route: route.fulfill(json=_connection_payload()),
    )
    page.route(
        f"{BASE_URL}/api/connections/auth-flows/active",
        lambda route: route.fulfill(json={"flows": []}),
    )
    page.route(
        f"{BASE_URL}/api/connections/anthropic/auth-flows",
        lambda route: route.fulfill(status=201, json=waiting),
    )
    page.route(
        f"{BASE_URL}/api/connections/auth-flows/auth_callback_1",
        lambda route: route.fulfill(json=waiting),
    )

    page.goto(SETTINGS_URL)
    page.get_by_role("button", name="AI Providers").click()
    page.evaluate("window.open = () => null")
    page.locator("#ai-wrap-anthropic").get_by_role(
        "button", name="Login with browser"
    ).click()
    callback = page.locator("#callback-input-anthropic")
    callback.fill("http://localhost:54322/callback?code=secret&state=temporary")
    page.wait_for_timeout(2500)

    assert callback.input_value().endswith("code=secret&state=temporary")


def test_device_code_flow_shows_code_and_updates_without_reload(page):
    state = {"connected": False}

    def connections(route):
        status = "connected" if state["connected"] else "timed_out"
        route.fulfill(json=_connection_payload(openai=status))

    def flow_status(route):
        state["connected"] = True
        route.fulfill(json={
            "flowId": "auth_device_1", "provider": "openai", "flowType": "device_code",
            "status": "connected", "username": "writer@example.com",
            "authorizationUrl": None, "deviceCode": None, "errorCode": None,
            "errorMessage": None, "recovery": None, "expiresAt": "2026-08-10T10:05:00Z",
            "createdAt": "2026-08-10T10:00:00Z", "updatedAt": "2026-08-10T10:01:00Z",
        })

    page.route(f"{BASE_URL}/api/connections", connections)
    page.route(f"{BASE_URL}/api/connections/auth-flows/active", lambda route: route.fulfill(json={"flows": []}))
    page.route(f"{BASE_URL}/api/connections/openai/auth-flows", lambda route: route.fulfill(status=201, json={
        "flowId": "auth_device_1", "provider": "openai", "flowType": "device_code",
        "status": "waiting_for_authorization", "authorizationUrl": "https://provider.example/device",
        "deviceCode": "ABCD-EFGH", "username": None, "errorCode": None,
        "errorMessage": None, "recovery": None, "expiresAt": "2026-08-10T10:05:00Z",
        "createdAt": "2026-08-10T10:00:00Z", "updatedAt": "2026-08-10T10:00:00Z",
    }))
    page.route(f"{BASE_URL}/api/connections/auth-flows/auth_device_1", flow_status)

    page.goto(SETTINGS_URL)
    page.get_by_role("button", name="AI Providers").click()
    page.evaluate("window.open = () => null")
    card = page.locator("#ai-wrap-openai")
    card.get_by_role("button", name="Reconnect").click()
    card.get_by_text("Waiting for authorization", exact=True).wait_for()
    card.locator("#auth-flow-row-openai").get_by_text("ABCD-EFGH").wait_for()
    page.locator("#ai-wrap-openai").get_by_text("Connected").wait_for(timeout=7000)


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("expired", "Authorization expired"),
        ("rejected", "Authorization rejected"),
        ("timed_out", "Login timed out"),
        ("rate_limited", "Rate limited"),
        ("failed", "Login failed"),
    ],
)
def test_agent_login_failure_states_are_explicit(page, status, label):
    payload = _connection_payload(anthropic=status)
    payload["connections"][0]["errorMessage"] = "Provider authorization did not complete"
    page.route(
        f"{BASE_URL}/api/connections",
        lambda route: route.fulfill(json=payload),
    )
    page.route(
        f"{BASE_URL}/api/connections/auth-flows/active",
        lambda route: route.fulfill(json={"flows": []}),
    )

    page.goto(SETTINGS_URL)
    page.get_by_role("button", name="AI Providers").click()
    card = page.locator("#ai-wrap-anthropic")
    card.get_by_text(label, exact=True).wait_for()
    card.get_by_text("Provider authorization did not complete", exact=True).wait_for()


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
    page.locator("#ai-wrap-anthropic").get_by_role("button", name=re.compile(r"^remove$",
                                                                             re.I)).click()

    with page.expect_request(
            lambda r: "/api/connections/anthropic" in r.url and r.method == "DELETE") as req_info:
        page.locator("#confirm-anthropic").get_by_role("button", name=re.compile(r"^remove$",
                                                                                 re.I)).click()

    assert req_info.value is not None
