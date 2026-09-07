"""Isolated HTTPS fixture; never mount this test-only control API in production.

Run one worker: uvicorn validation.fixture:app --host 0.0.0.0 --port 443
--ssl-certfile /certs/tls.crt --ssl-keyfile /certs/tls.key
The certificate must cover fixture.test and identity.test.
Both login buttons occupy (48, 128, 264, 44), center (180, 150), in CSS pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import secrets
import time
from typing import Literal
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field


BLOG = "https://fixture.test"
IDENTITY = "https://identity.test"
MAX_AGE = 86400
BLOG_COOKIE = "blog_session"
IDENTITY_COOKIE = "test_identity"


@dataclass
class State:
    mode: str = "normal"
    verification_delay: int = 0
    blog: dict[str, float] = field(default_factory=dict)
    identity: dict[str, float] = field(default_factory=dict)
    flows: dict[str, float] = field(default_factory=dict)
    codes: dict[str, tuple[str, float]] = field(default_factory=dict)


class Control(BaseModel):
    verification_delay: int | None = Field(default=None, ge=0, le=20)
    mode: Literal["normal", "reject_verification", "challenge"] | None = None
    action: Literal["reset", "expire"] | None = None
    target: Literal["blog", "identity", "all"] = "blog"


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title><style>'
        'body{font:18px system-ui;color:#202124;background:#fff;margin:0}'
        'main{max-width:680px;margin:0;padding:40px 48px}h1{margin:0 0 24px}'
        'button{position:absolute;left:48px;top:128px;width:264px;height:44px;'
        'font:inherit;padding:0;background:#17643a;color:white;'
        'border:0;border-radius:4px;cursor:pointer}a{color:#17643a}'
        f'</style></head><body><main><h1>{escape(title)}</h1>{body}</main></body></html>',
        status_code=status_code,
    )


def _cookie(response, name: str, value: str, domain: str, max_age: int = MAX_AGE):
    response.set_cookie(name, value, max_age=max_age, domain=domain,
                        secure=True, httponly=True, samesite="lax", path="/")


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.fixture = State()

    @app.middleware("http")
    async def isolate_hosts(request: Request, call_next):
        host = request.url.hostname
        identity_path = request.url.path == "/authorize"
        if host not in {"fixture.test", "identity.test"}:
            return _page("Unknown fixture host", "", 400)
        if request.url.path not in {"/health", "/control"}:
            if (identity_path and host != "identity.test") or (
                not identity_path and host != "fixture.test"
            ):
                return _page("Not found", "", 404)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action https://fixture.test https://identity.test; frame-ancestors 'none'"
        )
        return response

    def state() -> State:
        return app.state.fixture

    def valid(store: dict[str, float], token: str | None) -> bool:
        return bool(token and store.get(token, 0) > time.time())

    def authorize_flow(flow: str):
        if not valid(state().flows, flow):
            raise HTTPException(400, "Invalid or expired login flow")

    def callback_redirect(flow: str):
        code = secrets.token_urlsafe(32)
        state().codes[code] = (flow, time.time() + 120)
        return RedirectResponse(
            BLOG + "/callback?" + urlencode({"code": code, "state": flow}), 303,
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "fixture": True}

    @app.get("/control")
    def inspect_control():
        return {"mode": state().mode, "verification_delay": state().verification_delay}

    @app.post("/control")
    def control(command: Control):
        if command.action == "reset":
            app.state.fixture = State()
        elif command.action == "expire":
            if command.target in {"blog", "all"}:
                state().blog.clear()
            if command.target in {"identity", "all"}:
                state().identity.clear()
            state().codes.clear()
            state().flows.clear()
        if command.mode is not None:
            state().mode = command.mode
        if command.verification_delay is not None:
            state().verification_delay = command.verification_delay
        return {"mode": state().mode, "ok": True}

    @app.get("/")
    def home():
        return RedirectResponse(BLOG + "/account", 303)

    @app.get("/login")
    def login():
        if state().mode == "challenge":
            return RedirectResponse(BLOG + "/challenge", 303)
        flow = secrets.token_urlsafe(32)
        state().flows[flow] = time.time() + 600
        response = _page("Fixture Blog", (
            '<form method="get" action="https://identity.test/authorize">'
            f'<input type="hidden" name="state" value="{flow}">'
            '<button type="submit">Continue with test identity</button></form>'
        ))
        _cookie(response, "login_state", flow, "fixture.test", 600)
        return response

    @app.get("/authorize")
    def authorize(request: Request, state: str):
        flow = state
        authorize_flow(flow)
        current = app.state.fixture
        if current.mode == "challenge":
            return RedirectResponse(BLOG + "/challenge", 303)
        if valid(current.identity, request.cookies.get(IDENTITY_COOKIE)):
            return callback_redirect(flow)
        return _page("Test identity", (
            '<form method="post" action="https://identity.test/authorize">'
            f'<input type="hidden" name="state" value="{escape(flow, quote=True)}">'
            '<button type="submit">Sign in test identity</button></form>'
        ))

    @app.post("/authorize")
    async def sign_in(request: Request):
        body = parse_qs((await request.body()).decode("utf-8"))
        flow = body.get("state", [""])[0]
        authorize_flow(flow)
        if state().mode == "challenge":
            return RedirectResponse(BLOG + "/challenge", 303)
        token = secrets.token_urlsafe(32)
        state().identity[token] = time.time() + MAX_AGE
        response = callback_redirect(flow)
        _cookie(response, IDENTITY_COOKIE, token, "identity.test")
        return response

    @app.get("/callback")
    def callback(request: Request, code: str, state: str):
        current = app.state.fixture
        record = current.codes.pop(code, None)
        if (not record or record[0] != state or record[1] <= time.time()
                or request.cookies.get("login_state") != state
                or not valid(current.flows, state)):
            raise HTTPException(400, "Invalid or expired callback")
        current.flows.pop(state, None)
        token = secrets.token_urlsafe(32)
        current.blog[token] = time.time() + MAX_AGE
        response = RedirectResponse(BLOG + "/account", 303)
        _cookie(response, BLOG_COOKIE, token, "fixture.test")
        response.delete_cookie("login_state", domain="fixture.test", secure=True,
                               httponly=True, samesite="lax")
        return response

    @app.get("/account")
    def account(request: Request):
        if state().mode == "challenge":
            return RedirectResponse(BLOG + "/challenge", 303)
        if state().mode == "reject_verification":
            # Live probes deliberately see the expected cookie and account URL;
            # reopening the profile must still reject this marker-free response.
            return rejected()
        if not valid(state().blog, request.cookies.get(BLOG_COOKIE)):
            return RedirectResponse(BLOG + "/login", 303)
        return _page("Your account", (
            '<p data-testid="authenticated-account">Signed in as test identity</p>'
            '<section data-testid="article-list" data-count="0">'
            '<h2>Articles</h2><p>No articles yet.</p></section>'
        ))

    @app.get("/challenge")
    def challenge():
        return _page("Verification challenge", '<p data-testid="challenge">'
                     'Test challenge requires intervention.</p>', 403)

    @app.get("/verification-rejected")
    def rejected():
        return _page("Verification rejected", '<p data-testid="verification-rejected">'
                     'Account verification was rejected.</p>', 401)

    return app


app = create_app()
