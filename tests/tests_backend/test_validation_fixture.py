from __future__ import annotations

from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
import sys
import time
import types
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli-runner"))

from blog_extensions import Capability, ExtensionRegistry, OperationNotSupported, OperationRequest
from blog_extensions.profile_sessions import clear_context_session
from blog_extensions.registry import get_registry
from validation.fixture import BLOG, IDENTITY, create_app


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            self.fields[attrs["name"]] = attrs["value"]


@pytest.fixture
def client():
    with TestClient(create_app(), base_url=BLOG, follow_redirects=False) as client:
        yield client


@pytest.fixture
def extension():
    return ExtensionRegistry([ROOT / "validation/extension"], enabled={"validation.medium"}).get("medium")


def begin(client):
    response = client.get(BLOG + "/login")
    assert response.status_code == 200
    assert "Continue with test identity" in response.text
    flow = Inputs(response.text).fields["state"]
    return client.get(IDENTITY + "/authorize", params={"state": flow}), flow


def sign_in(client):
    response, flow = begin(client)
    assert response.status_code == 200
    assert "Sign in test identity" in response.text
    response = client.post(IDENTITY + "/authorize", data={"state": flow})
    assert response.status_code == 303
    assert "Max-Age=86400" in response.headers["set-cookie"]
    callback = response.headers["location"]
    response = client.get(callback)
    assert response.headers["location"] == BLOG + "/account"
    assert "Max-Age=86400" in response.headers["set-cookie"]
    return client.get(BLOG + "/account"), callback


def test_identity_login_persistent_separate_cookies_and_account(client):
    response, callback = sign_in(client)
    assert response.status_code == 200
    assert 'data-testid="authenticated-account"' in response.text
    assert response.headers["cache-control"] == "no-store"
    cookies = {cookie.name: cookie for cookie in client.cookies.jar}
    assert set(cookies) == {"blog_session", "test_identity"}
    for name, domain in [("blog_session", ".fixture.test"), ("test_identity", ".identity.test")]:
        cookie = cookies[name]
        assert cookie.domain == domain
        assert cookie.secure and not cookie.discard
        assert cookie.expires > time.time() + 86000
        assert cookie.has_nonstandard_attr("HttpOnly")
        assert cookie.get_nonstandard_attr("SameSite") == "lax"
    assert client.get(callback).status_code == 400


def test_clearing_only_blog_cookies_preserves_identity_and_skips_sign_in(client, extension):
    sign_in(client)

    class Context:
        def cookies(self):
            return [{"name": c.name, "domain": c.domain, "path": c.path}
                    for c in client.cookies.jar]

        def clear_cookies(self, **kwargs):
            client.cookies.delete(**kwargs)

    assert extension.login.session_domains() == ("fixture.test",)
    assert clear_context_session(Context(), extension.login.session_domains()) == 1
    assert client.cookies.get("test_identity")
    assert client.get("/account").headers["location"] == BLOG + "/login"
    response, _ = begin(client)
    assert response.status_code == 303
    assert "Sign in test identity" not in response.text
    callback = client.get(response.headers["location"])
    assert callback.headers["location"] == BLOG + "/account"
    assert 'data-testid="authenticated-account"' in client.get("/account").text


@pytest.mark.parametrize("mode,path,status", [
    ("reject_verification", "/account", 401),
    ("challenge", "/challenge", 403),
])
def test_control_modes_deny_account_without_deleting_cookie(client, mode, path, status):
    sign_in(client)
    cookie = client.cookies.get("blog_session")
    assert client.post("/control", json={"mode": mode}).json()["ok"]
    response = client.get("/account", follow_redirects=True)
    assert response.url.path == path
    assert response.status_code == status
    assert 'data-testid="authenticated-account"' not in response.text
    assert client.cookies.get("blog_session") == cookie
    client.post("/control", json={"mode": "normal"})
    assert client.get("/account").status_code == 200


@pytest.mark.parametrize("target,identity_survives", [("blog", True), ("all", False)])
def test_expiry_revokes_stale_blog_cookie(client, target, identity_survives):
    sign_in(client)
    cookie = client.cookies.get("blog_session")
    client.post("/control", json={"action": "expire", "target": target})
    assert client.cookies.get("blog_session") == cookie
    assert client.get("/account").headers["location"] == BLOG + "/login"
    response, _ = begin(client)
    assert response.status_code == (303 if identity_survives else 200)


def test_identity_expiry_does_not_revoke_blog(client):
    sign_in(client)
    client.post("/control", json={"action": "expire", "target": "identity"})
    assert client.get("/account").status_code == 200
    client.cookies.delete("blog_session", domain=".fixture.test")
    response, _ = begin(client)
    assert response.status_code == 200
    assert "Sign in test identity" in response.text


def test_reset_invalidates_both_sessions_and_clears_mode(client):
    sign_in(client)
    client.post("/control", json={"mode": "reject_verification"})
    assert client.post("/control", json={"action": "reset"}).json()["mode"] == "normal"
    assert client.get("/account").status_code == 303
    assert begin(client)[0].status_code == 200
    assert client.post("/control", json={"mode": "invalid"}).status_code == 422


def test_challenge_blocks_identity_sign_in(client):
    _, flow = begin(client)
    client.post("/control", json={"mode": "challenge"})
    response = client.post(IDENTITY + "/authorize", data={"state": flow})
    assert response.headers["location"] == BLOG + "/challenge"
    assert not client.cookies.get("test_identity")


def test_callback_requires_browser_state_and_unexpired_code(client):
    _, flow = begin(client)
    response = client.post(IDENTITY + "/authorize", data={"state": flow})
    callback = response.headers["location"]
    client.cookies.delete("login_state", domain=".fixture.test")
    assert client.get(callback).status_code == 400
    assert not client.cookies.get("blog_session")
    _, flow = begin(client)
    response = client.post(IDENTITY + "/authorize", data={"state": flow})
    callback = response.headers["location"]
    code = parse_qs(urlsplit(callback).query)["code"][0]
    client.app.state.fixture.codes[code] = (flow, time.time() - 1)
    assert client.get(callback).status_code == 400


def test_wrong_hosts_and_forged_authorization_are_rejected(client):
    assert client.get("https://external.test/login").status_code == 400
    assert client.get(IDENTITY + "/account").status_code == 404
    assert client.get(BLOG + "/authorize?state=forged").status_code == 404
    assert client.post(IDENTITY + "/authorize", data={"state": "forged"}).status_code == 400
    assert client.get(IDENTITY + "/authorize?state=forged").status_code == 400


def test_enabled_manifest_excludes_builtin_medium(monkeypatch):
    monkeypatch.setenv("BLOGHUB_ENABLED_EXTENSIONS", "validation.medium")
    monkeypatch.setenv("BLOGHUB_EXTENSION_PATHS", str(ROOT / "validation/extension"))
    get_registry.cache_clear()
    try:
        registry = get_registry()
        assert [item["id"] for item in registry.descriptors()] == ["validation.medium"]
        assert registry.get("medium").login.login_url == BLOG + "/login"
    finally:
        get_registry.cache_clear()


def probe():
    return {"url": BLOG + "/account", "cookies": [{
        "name": "blog_session", "domain": ".fixture.test",
        "expires": time.time() + 3600, "present": True,
    }]}


@pytest.mark.parametrize("url", [BLOG + "/login", IDENTITY + "/account",
    "http://fixture.test/account", "https://fixture.test.evil/account",
    "https://fixture.test:444/account", "https://user@fixture.test/account",
    BLOG + "/challenge", BLOG + "/verification-rejected"])
def test_live_probe_requires_exact_account_url(extension, url):
    evidence = probe()
    assert extension.login.verify_live_session(evidence)["authenticated"]
    evidence["url"] = url
    assert not extension.login.verify_live_session(evidence)["authenticated"]


@pytest.mark.parametrize("change", [
    {"domain": "identity.test"}, {"domain": "sub.fixture.test"},
    {"name": "test_identity"}, {"present": False}, {"expires": 0},
    {"expires": -1}, {"expires": "bad"}, {"expires": None},
])
def test_live_probe_requires_live_blog_cookie(extension, change):
    evidence = probe()
    evidence["cookies"][0].update(change)
    assert not extension.login.verify_live_session(evidence)["authenticated"]


class Page:
    def __init__(self, *, marker=True, url=BLOG + "/account", status=200, count="0"):
        self.marker, self.url, self.status, self.count = marker, url, status, count
        self.visited = []

    def goto(self, url, **kwargs):
        self.visited.append((url, kwargs))
        return types.SimpleNamespace(status=self.status)

    def locator(self, selector):
        return types.SimpleNamespace(
            is_visible=lambda: self.marker,
            get_attribute=lambda name: self.count,
        )


@pytest.mark.parametrize("marker,url,status,expected", [
    (True, BLOG + "/account", 200, True),
    (False, BLOG + "/account", 200, False),
    (True, BLOG + "/login", 200, False),
    (True, BLOG + "/account", 401, False),
])
def test_profile_launches_patchright_and_requires_fresh_account_marker(
    extension, tmp_path, monkeypatch, marker, url, status, expected,
):
    page = Page(marker=marker, url=url, status=status)
    launches, closed = [], []
    context = types.SimpleNamespace(pages=[page], close=lambda: closed.append(True))

    def launch(*args, **kwargs):
        launches.append((args, kwargs))
        return context

    @contextmanager
    def playwright():
        yield types.SimpleNamespace(chromium=types.SimpleNamespace(launch_persistent_context=launch))

    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    module = types.ModuleType("patchright.sync_api")
    module.sync_playwright = playwright
    monkeypatch.setitem(sys.modules, "patchright.sync_api", module)
    adapter_module = sys.modules[type(extension.login).__module__]
    trusted_context = object()

    def trusted_ca(*, cafile):
        assert cafile == "/certs/ca.crt"
        return trusted_context

    def configuration(url, **kwargs):
        assert url == BLOG + "/control"
        assert kwargs == {"verify": trusted_context, "timeout": 5}
        return types.SimpleNamespace(raise_for_status=lambda: None,
                                     json=lambda: {"verification_delay": 0})

    monkeypatch.setattr(adapter_module, "ssl", types.SimpleNamespace(create_default_context=trusted_ca))
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(get=configuration))
    assert extension.login.verify_profile(tmp_path)["authenticated"] is expected
    assert launches == [((str(tmp_path),), {"headless": True})]
    assert closed == [True]
    assert page.visited[0][0] == BLOG + "/account"


def test_missing_profile_fails_without_launch(extension, tmp_path):
    assert not extension.login.verify_profile(tmp_path / "missing")["authenticated"]


def test_operations_require_account_and_explicit_empty_article_list(extension):
    operations = extension.operations
    request = OperationRequest()
    result = operations.execute(Page(), Capability.LIST_ARTICLES, request)
    assert result == {"success": True, "status": "connected", "articles": [], "next_cursor": None}
    assert not operations.execute(Page(marker=False), Capability.LIST_ARTICLES, request)["success"]
    assert not operations.execute(Page(count="1"), Capability.LIST_ARTICLES, request)["success"]
    challenge = operations.execute(Page(url=BLOG + "/challenge", status=403), Capability.LIST_ARTICLES, request)
    assert operations.operation_health(Capability.LIST_ARTICLES, challenge)["status"] == "temporarily_blocked"
    with pytest.raises(OperationNotSupported):
        operations.execute(Page(), Capability.PUBLISH, request)
