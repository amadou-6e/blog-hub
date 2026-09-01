"""
Connections router — browser login flows and API token management
for blog publishing platforms (Medium, Hashnode, Dev.to) and
AI providers (Anthropic/Claude, OpenAI).

Blog platforms:
  Medium     — OAuth 2.0 Authorization Code popup (server-side code exchange)
               OR manual integration token
  Hashnode   — Personal Access Token
  Dev.to     — API Key (Forem)

AI providers:
  Anthropic  — browser login via claude CLI (loopback redirect, handled by cli-runner)
               OR API Key fallback
  OpenAI     — browser login via openai CLI (loopback redirect, handled by cli-runner)
               OR API Key fallback

CLI operations are delegated to the CLI runner service (see backend/services/cli_runner.py).
The backend never spawns CLI subprocesses directly.
"""
from __future__ import annotations

import json
import hashlib
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, Response

import backend.services.cli_runner as runner
import backend.services.connection_auth as agent_auth
import backend.store as store
from backend.services.hashnode_sync import (
    sync_hashnode_articles,
    sync_hashnode_browser_records,
)
from backend.services.medium_sync import sync_medium_browser_records
from backend.schemas.connections import (
    ActiveAgentAuthFlowsResponse,
    AgentAuthCallbackRequest,
    AgentAuthFlowResponse,
    ConnectionInfo,
    ConnectionListResponse,
    DraftContent,
    DraftListResponse,
    DraftSummary,
    HashnodeSyncResponse,
    MediumSyncResponse,
    OAuthStartResponse,
    SaveTokenRequest,
    SaveTokenResponse,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])

_VALID_IDS = {"medium", "hashnode", "devto", "anthropic", "openai"}
_BLOG_IDS = {"medium", "hashnode", "devto"}
_CLI_IDS = {"anthropic", "openai"}
_PROVIDER_MAP = {"anthropic": "anthropic", "openai": "openai"}
_BROWSER_EXTENSION_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")


def _require_browser_extension_id(platform: str) -> None:
    if not _BROWSER_EXTENSION_ID.fullmatch(platform):
        raise HTTPException(status_code=400, detail="Invalid browser extension id")

# ── Mock draft data ───────────────────────────────────────────────────────────
# Real implementation would call each platform's API with the stored token.
# Medium: GET /v1/users/{userId}/publications and /publications/{pubId}/posts
#   (Note: Medium's API does not expose drafts — only published posts and
#    posts submitted to publications. The mock returns a mix of statuses.)
# Hashnode: GraphQL me { drafts { ... } } and me { posts { ... } }
# Dev.to:   GET /articles/me/unpublished  +  GET /articles/me

_MOCK_DRAFTS: dict[str, list[dict]] = {
    "medium": [
        {
            "id":
                "med-draft-001",
            "title":
                "How I built a distributed cache from scratch",
            "snippet":
                "A deep dive into consistent hashing, sharding strategies, and the night I caused a production outage at 2am.",
            "word_count":
                1840,
            "updated_at":
                "2026-04-03T10:00:00+00:00",
            "status":
                "draft",
            "body":
                "# How I built a distributed cache from scratch\n\nBuilding a distributed cache requires careful thought about consistency, availability, and partition tolerance.\n\n## Consistent hashing\n\nConsistent hashing distributes keys across nodes so that adding or removing a node only remaps a small fraction of keys.\n\n```python\nimport hashlib\n\ndef hash_key(key: str) -> int:\n    return int(hashlib.md5(key.encode()).hexdigest(), 16)\n```\n\n## Sharding strategy\n\nWe chose virtual nodes (vnodes) to balance load across heterogeneous hardware. Each physical node owns 150 virtual positions on the hash ring.\n\n## The 2am incident\n\nA misconfigured replication factor meant one shard had no replicas. When the primary went down, we lost 12 minutes of write traffic before the on-call engineer rerouted requests.\n",
        },
        {
            "id":
                "med-draft-002",
            "title":
                "The case for boring technology in 2026",
            "snippet":
                "Everyone wants the shiny new framework. Here is why your next project should use the dullest tool in the shed.",
            "word_count":
                920,
            "updated_at":
                "2026-03-30T14:00:00+00:00",
            "status":
                "draft",
            "body":
                "# The case for boring technology in 2026\n\nEvery year the JavaScript ecosystem releases approximately forty-seven new frameworks. Every year engineering teams spend weeks evaluating them. Every year most teams would have been better off with what they already had.\n\n## What boring means\n\nBoring technology is battle-tested, well-documented, and has solved most of its edge cases years ago. Postgres is boring. Linux is boring. HTTP is boring. They are also the backbone of almost every successful product you have used today.\n\n## The hidden cost of novelty\n\nNew tools come with undiscovered bugs, sparse documentation, and a community that is still figuring out the right patterns. You will find those bugs in production.\n",
        },
        {
            "id":
                "med-post-003",
            "title":
                "Postgres full-text search vs Elasticsearch",
            "snippet":
                "When does it make sense to reach for a dedicated search engine? I ran the benchmarks so you do not have to.",
            "word_count":
                2300,
            "updated_at":
                "2026-03-20T09:00:00+00:00",
            "status":
                "published",
            "canonical_url":
                "https://acisse.dev/blog/postgres-fts-vs-elasticsearch",
            "body":
                "# Postgres full-text search vs Elasticsearch\n\nFor most applications under 10 million documents, Postgres full-text search is fast enough, cheaper to operate, and dramatically simpler to keep consistent with your primary data.\n\n## Benchmark setup\n\n- Dataset: 2.4 million Stack Overflow posts\n- Hardware: 4-core, 16 GB RAM, NVMe SSD\n- Postgres 16 with `pg_trgm` and `tsvector` indexes\n- Elasticsearch 8.12 with default settings\n\n## Results\n\n| Query type | Postgres p99 | Elasticsearch p99 |\n|---|---|---|\n| Single term | 8 ms | 4 ms |\n| Phrase match | 22 ms | 7 ms |\n| Fuzzy (edit distance 1) | 180 ms | 12 ms |\n\nFuzzy search is where Elasticsearch wins decisively. If your product needs typo-tolerance at scale, the operational overhead is justified.\n",
        },
        {
            "id":
                "med-post-004",
            "title":
                "Why I stopped writing REST APIs",
            "snippet":
                "After years of hand-crafting endpoints, I switched to tRPC and have not looked back.",
            "word_count":
                1200,
            "updated_at":
                "2026-03-05T11:00:00+00:00",
            "status":
                "published",
            "body":
                "# Why I stopped writing REST APIs\n\nI spent five years writing REST APIs. I hand-crafted every endpoint, wrote OpenAPI specs by hand, and maintained client SDKs that were always slightly behind the server. Then I tried tRPC.\n\n## What changed\n\ntRPC gives you end-to-end type safety between your TypeScript server and client with zero code generation. Your API is just a TypeScript module. Your client calls it like a local function.\n\n```typescript\nconst router = t.router({\n  getUser: t.procedure\n    .input(z.object({ id: z.string() }))\n    .query(async ({ input }) => db.users.findById(input.id)),\n});\n```\n\nThe IDE knows the shape of every response. Rename a field and every call site shows a type error immediately.\n",
        },
        {
            "id":
                "med-draft-005",
            "title":
                "Migrating a monolith: what actually worked",
            "snippet":
                "We moved 400k lines of Rails to Go over 18 months. Here is what the blog posts do not tell you.",
            "word_count":
                3100,
            "updated_at":
                "2026-02-14T16:00:00+00:00",
            "status":
                "draft",
            "body":
                "# Migrating a monolith: what actually worked\n\nMost migration blog posts are written by the team that succeeded. They describe the strategy they used after the fact, with the benefit of knowing it worked. This post is different: I will tell you what we tried that failed, and why.\n\n## What we tried first (and abandoned)\n\nWe started with the Strangler Fig pattern. In theory: identify a bounded context, extract it to a new service, route traffic gradually. In practice: our monolith had no bounded contexts. Everything called everything. The dependency graph looked like a bowl of spaghetti someone had already eaten.\n\n## What actually worked\n\nWe stopped thinking about services and started thinking about data ownership. Which team owns which tables? That question had a clear answer, even when the code did not.\n",
        },
    ],
    "hashnode": [
        {
            "id":
                "hn-draft-001",
            "title":
                "Building a CLI tool in Go from zero",
            "snippet":
                "Go has excellent standard library support for building CLIs. No framework needed.",
            "word_count":
                2100,
            "updated_at":
                "2026-04-01T08:00:00+00:00",
            "status":
                "draft",
            "body":
                "# Building a CLI tool in Go from zero\n\nGo's standard library provides everything you need to build a production-quality CLI: `flag` for argument parsing, `os/exec` for subprocess management, and `io` for streaming output.\n\n## Project structure\n\n```\ncmd/\n  root.go      — root command, flag definitions\n  deploy.go    — deploy subcommand\ninternal/\n  config/      — config file loading\n  api/         — HTTP client\nmain.go\n```\n\n## Parsing subcommands without a framework\n\n```go\nfunc main() {\n    if len(os.Args) < 2 {\n        fmt.Fprintln(os.Stderr, \"usage: mytool <command>\")\n        os.Exit(1)\n    }\n    switch os.Args[1] {\n    case \"deploy\":\n        runDeploy(os.Args[2:])\n    default:\n        fmt.Fprintf(os.Stderr, \"unknown command: %s\\n\", os.Args[1])\n        os.Exit(1)\n    }\n}\n```\n",
        },
        {
            "id":
                "hn-draft-002",
            "title":
                "Docker without root: a practical guide",
            "snippet":
                "Running Docker as root in production is a security risk most teams accept silently.",
            "word_count":
                1650,
            "updated_at":
                "2026-03-18T10:00:00+00:00",
            "status":
                "draft",
            "body":
                "# Docker without root: a practical guide\n\nBy default, the Docker daemon runs as root and containers run as root inside their namespace. This matters when a container escape occurs: the attacker has root on the host.\n\n## Rootless Docker\n\nDocker 20.10+ supports rootless mode, where the daemon runs as an unprivileged user:\n\n```bash\ndockerd-rootless-setuptool.sh install\nexport DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock\n```\n\n## USER in Dockerfile\n\nEven without rootless mode, you can drop privileges inside the container:\n\n```dockerfile\nRUN addgroup --system app && adduser --system --ingroup app app\nUSER app\n```\n\nThis does not protect against daemon-level exploits but limits damage from application-level vulnerabilities.\n",
        },
        {
            "id":
                "hn-post-003-xpost",
            "title":
                "Postgres full-text search vs Elasticsearch",
            "snippet":
                "When does it make sense to reach for a dedicated search engine? I ran the benchmarks so you do not have to.",
            "word_count":
                2300,
            "updated_at":
                "2026-03-20T09:00:00+00:00",
            "status":
                "published",
            "canonical_url":
                "https://acisse.dev/blog/postgres-fts-vs-elasticsearch",
            "body":
                "# Postgres full-text search vs Elasticsearch\n\nFor most applications under 10 million documents, Postgres full-text search is fast enough, cheaper to operate, and dramatically simpler to keep consistent with your primary data.\n\n## Benchmark setup\n\n- Dataset: 2.4 million Stack Overflow posts\n- Hardware: 4-core, 16 GB RAM, NVMe SSD\n- Postgres 16 with `pg_trgm` and `tsvector` indexes\n- Elasticsearch 8.12 with default settings\n\n## Results\n\n| Query type | Postgres p99 | Elasticsearch p99 |\n|---|---|---|\n| Single term | 8 ms | 4 ms |\n| Phrase match | 22 ms | 7 ms |\n| Fuzzy (edit distance 1) | 180 ms | 12 ms |\n\nFuzzy search is where Elasticsearch wins decisively. If your product needs typo-tolerance at scale, the operational overhead is justified.\n",
        },
        {
            "id":
                "hn-post-003",
            "title":
                "Rate limiting that actually works",
            "snippet":
                "Token bucket, leaky bucket, sliding window — a principled comparison with real throughput numbers.",
            "word_count":
                1900,
            "updated_at":
                "2026-03-01T12:00:00+00:00",
            "status":
                "published",
            "body":
                "# Rate limiting that actually works\n\nMost rate limiting implementations I have seen in production have one of two problems: they are too coarse (bursts saturate downstream services) or too strict (legitimate traffic is shed during spikes).\n\n## Token bucket\n\nTokens accumulate at a fixed rate up to a maximum capacity. Each request consumes one token. If the bucket is empty, the request is rejected or queued.\n\nPros: allows short bursts up to bucket capacity. Cons: a client that exhausts the bucket during a burst gets nothing for the refill interval.\n\n## Sliding window log\n\nRecord the timestamp of each request. On each new request, count requests in the last N seconds. Reject if count exceeds limit.\n\nPros: precise. Cons: memory scales with request volume. Not practical for high-traffic endpoints without approximation.\n",
        },
    ],
    "devto": [],
}

# ── List ──────────────────────────────────────────────────────────────────────


@router.get("", response_model=ConnectionListResponse)
def list_connections(request: Request):
    user_id: str = request.state.user_id
    return ConnectionListResponse(
        connections=[ConnectionInfo(**c) for c in store.list_connections(user_id)])


@router.get("/browser-extensions")
def list_browser_extensions():
    try:
        return {"extensions": runner.browser_extensions()}
    except runner.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── Provider-neutral AI agent authentication ─────────────────────────────────


def _auth_call(operation):
    try:
        return operation()
    except agent_auth.ConnectionAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/{conn_id}/auth-flows", response_model=AgentAuthFlowResponse, status_code=201,
)
def start_agent_auth_flow(request: Request, conn_id: str):
    user_id: str = request.state.user_id
    return _auth_call(lambda: agent_auth.start(store, user_id, conn_id))


@router.get(
    "/auth-flows/active", response_model=ActiveAgentAuthFlowsResponse,
)
def active_agent_auth_flows(request: Request):
    user_id: str = request.state.user_id
    return ActiveAgentAuthFlowsResponse(
        flows=[
            AgentAuthFlowResponse(**agent_auth.response_for(flow))
            for flow in store.list_active_connection_auth_flows(user_id)
        ]
    )


@router.get("/auth-flows/{flow_id}", response_model=AgentAuthFlowResponse)
def get_agent_auth_flow(request: Request, flow_id: str):
    user_id: str = request.state.user_id
    return _auth_call(lambda: agent_auth.status(store, user_id, flow_id))


@router.post(
    "/auth-flows/{flow_id}/callback", response_model=AgentAuthFlowResponse,
)
def submit_agent_auth_callback(
    request: Request, flow_id: str, body: AgentAuthCallbackRequest,
):
    user_id: str = request.state.user_id
    return _auth_call(
        lambda: agent_auth.submit_callback(
            store, user_id, flow_id, body.callback_url
        )
    )


@router.delete("/auth-flows/{flow_id}", response_model=AgentAuthFlowResponse)
def cancel_agent_auth_flow(request: Request, flow_id: str):
    user_id: str = request.state.user_id
    return _auth_call(lambda: agent_auth.cancel(store, user_id, flow_id))


# ── Save token ────────────────────────────────────────────────────────────────


@router.put("/{conn_id}", response_model=SaveTokenResponse)
def save_token(request: Request, conn_id: str, body: SaveTokenRequest):
    user_id: str = request.state.user_id
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")

    # Validate OpenAI keys before storing — the runner no longer does this.
    if conn_id == "openai":
        try:
            resp = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {body.token}"},
                timeout=8,
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=400,
                                    detail=f"Key rejected by OpenAI: HTTP {resp.status_code}")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502,
                                detail=f"Could not reach OpenAI to validate key: {exc}")

    result = store.save_connection(user_id, conn_id, body.token)
    return SaveTokenResponse(
        id=result["id"],
        status=result["status"],
        username=result.get("username"),
    )


# ── Disconnect ────────────────────────────────────────────────────────────────


@router.delete("/{conn_id}")
def disconnect(request: Request, conn_id: str):
    user_id: str = request.state.user_id
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")
    store.delete_connection_auth_flows(user_id, conn_id)
    store.delete_connection(user_id, conn_id)
    if conn_id in _CLI_IDS:
        # Best-effort: tell the runner to logout; ignore errors
        try:
            runner.logout(conn_id)
        except runner.RunnerUnavailable:
            pass
    return {"status": "disconnected"}


# ── Test connection ───────────────────────────────────────────────────────────


@router.post("/{conn_id}/test")
def test_connection(request: Request, conn_id: str):
    """
    Verify a stored credential is currently valid.

    For AI providers: asks the CLI runner to run whoami.
    For blog platforms: makes a lightweight authenticated API call.
    Returns { ok: bool, detail: str }.
    """
    user_id: str = request.state.user_id
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")

    if conn_id in _CLI_IDS:
        try:
            result = runner.login_status(conn_id)
        except runner.RunnerUnavailable as exc:
            return {"ok": False, "detail": f"Runner unavailable: {exc}"}
        return {
            "ok": result["status"] == "connected",
            "detail": result.get("username") or result.get("reason") or result["status"],
        }

    # Blog platforms: probe the platform API with the stored token
    token = store.get_connection_token(user_id, conn_id)
    if not token:
        return {"ok": False, "detail": "No token stored"}

    try:
        ok, detail = _probe_platform(conn_id, token)
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": ok, "detail": detail}


def _probe_platform(conn_id: str, token: str) -> tuple[bool, str]:
    """Lightweight authenticated probe for each blog platform."""
    headers: dict[str, str]
    url: str

    if conn_id == "medium":
        url = "https://api.medium.com/v1/me"
        headers = {"Authorization": f"Bearer {token}"}
    elif conn_id == "hashnode":
        url = "https://gql.hashnode.com/"
        headers = {"Authorization": token}
        # Minimal GraphQL query for current user
        with httpx.Client(timeout=8) as client:
            resp = client.post(url, json={"query": "{ me { username } }"}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                username = data.get("data", {}).get("me", {}).get("username")
                if username:
                    return True, username
                return False, data.get("errors", [{}])[0].get("message", "auth failed")
            return False, f"HTTP {resp.status_code}"
    elif conn_id == "devto":
        url = "https://dev.to/api/users/me"
        headers = {"api-key": token}
    elif conn_id == "openai":
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {token}"}
    else:
        return False, f"No probe defined for {conn_id}"

    with httpx.Client(timeout=8) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            username = data.get("username") or data.get("data", {}).get("username")
            return True, username or "authenticated"
        return False, f"HTTP {resp.status_code}"


# ── OAuth / browser login start ───────────────────────────────────────────────


@router.get("/{conn_id}/oauth-start", response_model=OAuthStartResponse)
def oauth_start(request: Request, conn_id: str):
    """
    Initiate browser login for a connection.

    Medium:           returns { available, url } for the Authorization Code popup.
    Anthropic/OpenAI: delegates to the CLI runner's /auth/{provider}/login.
                      Runner spawns the CLI, which opens a loopback HTTP server and
                      returns the provider auth URL via stdout.
    """
    if conn_id not in _VALID_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {conn_id}")

    if conn_id == "medium":
        return _medium_oauth_start()

    if conn_id in _CLI_IDS:
        return _cli_oauth_start(conn_id)

    raise HTTPException(status_code=400, detail=f"{conn_id} does not support browser login")


def _medium_oauth_start() -> OAuthStartResponse:
    client_id = os.environ.get("MEDIUM_CLIENT_ID")
    if not client_id:
        return OAuthStartResponse(available=False)

    redirect_uri = os.environ.get(
        "MEDIUM_REDIRECT_URI",
        "http://localhost:8000/api/connections/medium/oauth-callback",
    )
    state = store.create_oauth_state("medium")
    scope = "basicProfile%20publicationsList"
    url = (f"https://medium.com/m/oauth/authorize"
           f"?client_id={client_id}"
           f"&scope={scope}"
           f"&state={state}"
           f"&response_type=code"
           f"&redirect_uri={redirect_uri}")
    return OAuthStartResponse(url=url, available=True)


def _cli_oauth_start(conn_id: str) -> OAuthStartResponse:
    try:
        result = runner.login(conn_id)
    except runner.RunnerUnavailable:
        return OAuthStartResponse(available=False)

    if not result.get("available"):
        return OAuthStartResponse(available=False)

    # Device code flow (e.g. OpenAI Codex): CLI polls internally, no submit needed.
    # Loopback flow (e.g. Anthropic): user copies address-bar URL and submits it.
    device_code = result.get("device_code")
    flow = "device_code" if device_code else "cli_browser"

    return OAuthStartResponse(
        available=True,
        url=result["url"],
        flow=flow,
        device_code=device_code,
        poll_url=f"/api/connections/{conn_id}/cli-login-status",
    )


# ── CLI device code submit ────────────────────────────────────────────────────


class SubmitCodeRequest(BaseModel):
    code: str


def _browser_connection_response(
    platform: str,
    connection: dict | None,
    live_session: dict | None = None,
) -> dict:
    if connection is None:
        return {
            "platform": platform,
            "status": "disconnected",
            "loginPhase": "disconnected",
            "browserSession": None,
            "durableConnection": {
                "status": "disconnected", "profileSaved": False,
            },
        }
    live_authentication = (live_session or {}).get("live_authentication") or {}
    live_authenticated = live_authentication.get("authenticated")
    if connection["status"] == "waiting_for_login" and live_authenticated is True:
        login_phase = "signed_in_pending_save"
    else:
        login_phase = connection["status"]
    return {
        "platform": connection["platform"],
        "status": connection["status"],
        "loginPhase": login_phase,
        "authorizationUrl": (
            connection.get("app_url")
            if connection["status"] == "waiting_for_login"
            else None
        ),
        "verifiedAt": connection.get("verified_at"),
        "error": connection.get("error"),
        "browserSession": ({
            "status": (live_session or {}).get("status", "unknown"),
            "authenticationStatus": live_authentication.get("status", "unknown"),
            "authenticated": live_authenticated,
            "currentUrl": live_authentication.get("url"),
        } if connection.get("skyvern_session_id") else None),
        "durableConnection": {
            "status": connection["status"],
            "profileSaved": bool(connection.get("skyvern_profile_id")),
        },
    }


@router.get("/hashnode/browser-connection")
def get_hashnode_browser_connection(request: Request):
    return get_browser_connection(request, "hashnode")


@router.get("/{conn_id}/browser-connection")
def get_browser_connection(request: Request, conn_id: str):
    _require_browser_extension_id(conn_id)
    connection = store.get_browser_connection(request.state.user_id, conn_id)
    live_session = None
    if (
        connection
        and connection["status"] == "waiting_for_login"
        and connection.get("skyvern_session_id")
    ):
        try:
            live_session = runner.get_browser_login(
                conn_id, connection["skyvern_session_id"]
            )
        except runner.RunnerUnavailable:
            live_session = {
                "status": "unknown",
                "live_authentication": {
                    "status": "unknown", "authenticated": None, "url": None,
                },
            }
    return _browser_connection_response(
        conn_id, connection, live_session,
    )


@router.get("/{conn_id}/browser-connection/screenshot")
def export_browser_connection_screenshot(request: Request, conn_id: str):
    _require_browser_extension_id(conn_id)
    connection = store.get_browser_connection(request.state.user_id, conn_id)
    if (
        not connection
        or connection["status"] != "waiting_for_login"
        or not connection.get("skyvern_session_id")
    ):
        raise HTTPException(
            status_code=409,
            detail=f"No active {conn_id.title()} browser login is available",
        )
    try:
        screenshot = runner.capture_browser_screenshot(
            conn_id, connection["skyvern_session_id"]
        )
    except runner.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=screenshot,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'attachment; filename="bloghub-{conn_id}-browser.png"'
            ),
        },
    )


@router.post("/hashnode/browser-connection", status_code=201)
def start_hashnode_browser_connection(request: Request):
    return start_browser_connection(request, "hashnode")


@router.post("/{conn_id}/browser-connection", status_code=201)
def start_browser_connection(request: Request, conn_id: str):
    _require_browser_extension_id(conn_id)
    previous = store.get_browser_connection(request.state.user_id, conn_id)
    if previous and previous.get("skyvern_session_id") and previous["status"] == "waiting_for_login":
        try:
            runner.cancel_browser_login(conn_id, previous["skyvern_session_id"])
        except runner.RunnerUnavailable:
            pass
    reusable_profile_id = previous.get("skyvern_profile_id") if previous else None
    try:
        session = runner.start_browser_login(conn_id, reusable_profile_id)
    except runner.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    connection = store.start_browser_connection(
        request.state.user_id,
        conn_id,
        session_id=session["session_id"],
        organization_id=session["organization_id"],
        app_url=session["app_url"],
        profile_id=reusable_profile_id,
    )
    return _browser_connection_response(conn_id, connection)


@router.post("/hashnode/browser-connection/complete")
def complete_hashnode_browser_connection(request: Request):
    return complete_browser_connection(request, "hashnode")


@router.post("/{conn_id}/browser-connection/complete")
def complete_browser_connection(request: Request, conn_id: str):
    _require_browser_extension_id(conn_id)
    user_id = request.state.user_id
    connection = store.get_browser_connection(user_id, conn_id)
    if not connection or connection["status"] != "waiting_for_login":
        raise HTTPException(status_code=409, detail=f"No {conn_id.title()} browser login is active")
    store.update_browser_connection(user_id, conn_id, "verifying")
    profile_name = f"bloghub-{conn_id}-" + hashlib.sha256(user_id.encode()).hexdigest()[:16]
    try:
        result = runner.complete_browser_login(
            conn_id,
            connection["skyvern_session_id"],
            profile_name,
            profile_id=connection.get("skyvern_profile_id"),
            organization_id=connection.get("skyvern_organization_id"),
        )
    except runner.RunnerUnavailable as exc:
        current = store.get_browser_connection(user_id, conn_id)
        if (
            current
            and current.get("skyvern_session_id") == connection["skyvern_session_id"]
            and current["status"] == "verifying"
        ):
            store.update_browser_connection(user_id, conn_id, "failed", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    current = store.get_browser_connection(user_id, conn_id)
    if (
        not current
        or current.get("skyvern_session_id") != connection["skyvern_session_id"]
        or current["status"] != "verifying"
    ):
        if result.get("profile_id"):
            try:
                runner.delete_browser_profile(conn_id, result["profile_id"])
            except runner.RunnerUnavailable:
                pass
        return _browser_connection_response(conn_id, None)
    if not result.get("authenticated"):
        failed = store.update_browser_connection(
            user_id, conn_id, "failed",
            profile_id=result.get("profile_id"),
            error=f"{conn_id.title()} sign-in was not completed in the browser",
        )
        return _browser_connection_response(conn_id, failed)
    if result.get("organization_id") != connection["skyvern_organization_id"]:
        if result.get("profile_id"):
            try:
                runner.delete_browser_profile(conn_id, result["profile_id"])
            except runner.RunnerUnavailable:
                pass
        failed = store.update_browser_connection(
            user_id, conn_id, "failed",
            error="Browser profile ownership could not be verified",
        )
        return _browser_connection_response(conn_id, failed)
    connected = store.update_browser_connection(
        user_id, conn_id, "connected", profile_id=result["profile_id"]
    )
    return _browser_connection_response(conn_id, connected)


@router.delete("/hashnode/browser-connection")
def disconnect_hashnode_browser_connection(request: Request):
    return disconnect_browser_connection(request, "hashnode")


@router.delete("/{conn_id}/browser-connection")
def disconnect_browser_connection(request: Request, conn_id: str):
    _require_browser_extension_id(conn_id)
    connection = store.get_browser_connection(request.state.user_id, conn_id)
    if (
        connection
        and connection.get("skyvern_session_id")
        and connection["status"] == "waiting_for_login"
    ):
        try:
            runner.cancel_browser_login(conn_id, connection["skyvern_session_id"])
        except runner.RunnerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if connection and connection.get("skyvern_profile_id"):
        try:
            runner.delete_browser_profile(conn_id, connection["skyvern_profile_id"])
        except runner.RunnerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    store.delete_browser_connection(request.state.user_id, conn_id)
    return {"platform": conn_id, "status": "disconnected"}


@router.post("/{conn_id}/submit-code")
def submit_code(conn_id: str, body: SubmitCodeRequest):
    """
    Relay the device/authorization code the user copied from the browser
    to the CLI runner, which writes it to the waiting CLI process stdin.
    """
    if conn_id not in _CLI_IDS:
        raise HTTPException(status_code=400, detail=f"{conn_id} does not use CLI login")
    try:
        resp = httpx.post(
            f"{runner.CLI_RUNNER_URL}/auth/{conn_id}/submit-code",
            json={"code": body.code},
            timeout=10,
        )
        if resp.status_code == 409:
            raise HTTPException(
                status_code=409,
                detail="No active login session — click 'Login with Browser' to start a new one",
            )
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="CLI runner not reachable")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── CLI login status (poll endpoint) ─────────────────────────────────────────


@router.get("/{conn_id}/cli-login-status")
def cli_login_status(request: Request, conn_id: str):
    """
    Poll endpoint for CLI browser login completion.
    Frontend calls this every 2 s after opening the auth URL.

    Returns:
      { status: "connected", username: "..." }
      { status: "pending" }
      { status: "error",    errorMessage: "..." }
    """
    user_id: str = request.state.user_id
    if conn_id not in _CLI_IDS:
        raise HTTPException(status_code=400, detail=f"{conn_id} does not use CLI login")

    try:
        result = runner.login_status(conn_id)
    except runner.RunnerUnavailable as exc:
        return {"status": "error", "errorMessage": f"Runner unavailable: {exc}"}

    status = result.get("status", "error")

    if status == "connected":
        username = result.get("username")
        store.save_connection(user_id, conn_id, token="cli_session", status="connected", username=username)
        return {"status": "connected", "username": username}

    if status == "pending":
        return {"status": "pending"}

    return {"status": "error", "errorMessage": result.get("reason", "Login failed")}


# ── Platform draft fetchers ───────────────────────────────────────────────────


def _count_words(text: str) -> int:
    return len(text.split())


def _fetch_hashnode_drafts(token: str) -> list[dict]:
    """
    Fetch published posts + drafts for the authenticated Hashnode user.
    Drafts API: me { drafts(first: 50) { edges { node { id title subtitle updatedAt content { markdown } } } } }
    Posts API:  me { posts(first: 50) { edges { node { id title brief updatedAt content { markdown } } } } }
    """
    headers = {"Authorization": token, "Content-Type": "application/json"}
    url = "https://gql.hashnode.com/"

    # drafts uses cursor-based pagination (max first=20)
    # posts uses offset-based pagination (pageSize + page) with nodes (not edges)
    drafts_query = """
    {
      me {
        drafts(first: 20) {
          edges {
            node {
              id
              title
              subtitle
              updatedAt
              coverImage { url }
              content { markdown }
            }
          }
        }
        posts(pageSize: 50, page: 1) {
          nodes {
            id
            title
            brief
            updatedAt
            coverImage { url }
            content { markdown }
          }
        }
      }
    }
    """
    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json={"query": drafts_query}, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if "errors" in data:
        raise HTTPException(status_code=502,
                            detail=data["errors"][0].get("message", "Hashnode API error"))

    me = data.get("data", {}).get("me", {})
    results: list[dict] = []

    for edge in me.get("drafts", {}).get("edges", []):
        node = edge["node"]
        body = node.get("content", {}).get("markdown", "")
        results.append({
            "id": node["id"],
            "title": node.get("title") or "Untitled draft",
            "snippet": node.get("subtitle") or "",
            "status": "draft",
            "word_count": _count_words(body),
            "updated_at": node.get("updatedAt") or "",
            "body": body,
            "cover_image": (node.get("coverImage") or {}).get("url") or None,
        })

    for node in me.get("posts", {}).get("nodes", []):
        body = node.get("content", {}).get("markdown", "")
        results.append({
            "id": node["id"],
            "title": node.get("title") or "Untitled post",
            "snippet": node.get("brief") or "",
            "status": "published",
            "word_count": _count_words(body),
            "updated_at": node.get("updatedAt") or "",
            "body": body,
            "cover_image": (node.get("coverImage") or {}).get("url") or None,
        })

    return results


def _fetch_devto_drafts(token: str) -> list[dict]:
    """
    Fetch unpublished + published articles for the authenticated Dev.to user.
    GET /articles/me/unpublished  — returns drafts
    GET /articles/me              — returns published articles
    GET /articles/{id}            — returns full body_markdown
    """
    headers = {"api-key": token}

    # The listing endpoints (/articles/me/unpublished and /articles/me) both include
    # body_markdown directly — no secondary fetch needed.
    # Note: GET /articles/{id} returns 404 for unpublished drafts (Forem API limitation).
    def _get_list(path: str, status: str) -> list[dict]:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"https://dev.to/api{path}",
                headers=headers,
                params={"per_page": 100},
            )
            resp.raise_for_status()
            items = resp.json()

        results = []
        for a in items:
            results.append({
                "id": str(a["id"]),
                "title": a.get("title") or "Untitled",
                "snippet": a.get("description") or "",
                "status": status,
                "word_count": a.get("reading_time_minutes", 0) * 200,  # rough estimate
                "updated_at": a.get("edited_at") or a.get("published_at") or "",
                "body": a.get("body_markdown") or "",
                "cover_image": a.get("cover_image") or a.get("social_image") or None,
            })
        return results

    unpublished = _get_list("/articles/me/unpublished", "draft")
    published = _get_list("/articles/me", "published")
    return unpublished + published


def _fetch_devto_article_body(token: str, article_id: str) -> str:
    """Fetch full markdown body for a single Dev.to article.

    Uses the listing endpoints (which include body_markdown) rather than
    GET /articles/{id}, which returns 404 for unpublished/draft articles.
    """
    headers = {"api-key": token}
    for path in ("/articles/me/unpublished", "/articles/me"):
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"https://dev.to/api{path}",
                              headers=headers,
                              params={"per_page": 100})
            resp.raise_for_status()
            items = resp.json()
        match = next((a for a in items if str(a["id"]) == article_id), None)
        if match is not None:
            return match.get("body_markdown") or ""
    return ""


# ── Draft list ───────────────────────────────────────────────────────────────


@router.post("/hashnode/sync", response_model=HashnodeSyncResponse)
def sync_hashnode(request: Request):
    """Import Hashnode through browser login for non-Pro or PAT for Pro."""
    user_id: str = request.state.user_id
    browser_connection = store.get_browser_connection(user_id, "hashnode")
    if browser_connection and browser_connection["status"] == "connected":
        try:
            retrieval = runner.hashnode_browser_articles(
                organization_id=browser_connection["skyvern_organization_id"],
                profile_id=browser_connection["skyvern_profile_id"],
            )
        except runner.RunnerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return sync_hashnode_browser_records(user_id, retrieval)

    token = store.get_connection_token(user_id, "hashnode") or os.environ.get("HASHNODE_PAT")
    if not token:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "hashnode_connection_required",
                "message": "Connect Hashnode with browser login or a Pro API token",
            },
        )
    if token == "cli_session":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "hashnode_browser_profile_required",
                "message": "Reconnect Hashnode browser login to restore its profile",
            },
        )
    return sync_hashnode_articles(user_id, token)


@router.post("/medium/sync", response_model=MediumSyncResponse)
def sync_medium(request: Request):
    """Import Medium stories through the connected browser profile."""
    user_id: str = request.state.user_id
    browser_connection = store.get_browser_connection(user_id, "medium")
    if not browser_connection or browser_connection["status"] != "connected":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "medium_browser_connection_required",
                "message": "Connect Medium with browser login before synchronizing",
            },
        )
    try:
        retrieval = runner.medium_browser_articles(
            organization_id=browser_connection["skyvern_organization_id"],
            profile_id=browser_connection["skyvern_profile_id"],
        )
    except runner.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return sync_medium_browser_records(user_id, retrieval)


@router.get("/{conn_id}/drafts", response_model=DraftListResponse)
def list_drafts(
    request: Request,
    conn_id: str,
    page: int = 1,
    per_page: int = 20,
):
    """
    Return a paginated list of articles (drafts + published) for a connected
    blog platform.

    Hashnode: GraphQL me { drafts } + me { posts }
    Dev.to:   GET /articles/me/unpublished  +  GET /articles/me
    Medium:   falls back to _MOCK_DRAFTS (Medium API does not expose drafts)
    """
    user_id: str = request.state.user_id
    if conn_id not in _BLOG_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {conn_id}")

    token = store.get_connection_token(user_id, conn_id)
    browser_connection = (
        store.get_browser_connection(user_id, "medium")
        if conn_id == "medium" else None
    )
    has_medium_browser = bool(
        browser_connection and browser_connection["status"] == "connected"
    )
    if not token and not has_medium_browser:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "platform_not_connected",
                "platform": conn_id
            },
        )

    try:
        if conn_id == "hashnode":
            all_drafts = _fetch_hashnode_drafts(token)
        elif conn_id == "devto":
            all_drafts = _fetch_devto_drafts(token)
        else:
            if has_medium_browser:
                all_drafts = runner.list_medium_browser_articles(
                    organization_id=browser_connection["skyvern_organization_id"],
                    profile_id=browser_connection["skyvern_profile_id"],
                    limit=100,
                )
            else:
                all_drafts = _MOCK_DRAFTS.get(conn_id, [])
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502,
                            detail=f"Platform API error: {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}")

    total = len(all_drafts)
    start = (page - 1) * per_page
    page_items = all_drafts[start:start + per_page]

    return DraftListResponse(
        platform=conn_id,
        drafts=[
            DraftSummary(
                id=d["id"],
                title=d["title"],
                snippet=d.get("snippet") or "",
                status=d["status"],
                word_count=d.get("word_count") or 0,
                updated_at=d.get("updated_at") or "",
                cover_image=d.get("cover_image") or None,
            ) for d in page_items
        ],
        total=total,
        page=page,
        per_page=per_page,
        has_more=(start + per_page) < total,
    )


@router.get("/{conn_id}/drafts/{draft_id}", response_model=DraftContent)
def get_draft(request: Request, conn_id: str, draft_id: str):
    """
    Return the full markdown body of a single article from the platform.
    Fetches from the live platform API for Hashnode and Dev.to.
    """
    user_id: str = request.state.user_id
    if conn_id not in _BLOG_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {conn_id}")

    token = store.get_connection_token(user_id, conn_id)
    browser_connection = (
        store.get_browser_connection(user_id, "medium")
        if conn_id == "medium" else None
    )
    has_medium_browser = bool(
        browser_connection and browser_connection["status"] == "connected"
    )
    if not token and not has_medium_browser:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "platform_not_connected",
                "platform": conn_id
            },
        )

    try:
        if conn_id == "hashnode":
            all_drafts = _fetch_hashnode_drafts(token)
            draft = next((d for d in all_drafts if d["id"] == draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail={"error": "draft_not_found"})
            return DraftContent(**draft)

        elif conn_id == "devto":
            # body_markdown is already included in the listing response; no secondary fetch needed
            all_drafts = _fetch_devto_drafts(token)
            draft = next((d for d in all_drafts if d["id"] == draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail={"error": "draft_not_found"})
            return DraftContent(**draft)

        else:
            if has_medium_browser:
                article = runner.get_medium_browser_article(
                    draft_id,
                    organization_id=browser_connection["skyvern_organization_id"],
                    profile_id=browser_connection["skyvern_profile_id"],
                )
                return DraftContent(**article)
            drafts = _MOCK_DRAFTS.get(conn_id, [])
            draft = next((d for d in drafts if d["id"] == draft_id), None)
            if draft is None:
                raise HTTPException(status_code=404, detail={"error": "draft_not_found"})
            return DraftContent(**draft)

    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502,
                            detail=f"Platform API error: {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Platform API error: {exc}")


# ── Medium OAuth callback ─────────────────────────────────────────────────────


@router.get("/{conn_id}/oauth-callback", response_class=HTMLResponse)
async def oauth_callback(request: Request,
                         conn_id: str,
                         code: str | None = None,
                         state: str | None = None,
                         error: str | None = None):
    if conn_id != "medium":
        raise HTTPException(status_code=400, detail="OAuth callback only valid for medium")

    if error or not code:
        return HTMLResponse(_popup_html("error", conn_id, error=str(error or "access_denied")))

    if not state or not store.consume_oauth_state(state, conn_id):
        return HTMLResponse(_popup_html("error", conn_id, error="Invalid or expired OAuth state"))

    client_id = os.environ.get("MEDIUM_CLIENT_ID", "")
    client_secret = os.environ.get("MEDIUM_CLIENT_SECRET", "")
    redirect_uri = os.environ.get(
        "MEDIUM_REDIRECT_URI",
        "http://localhost:8000/api/connections/medium/oauth-callback",
    )

    try:
        async with __import__("httpx").AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                "https://api.medium.com/v1/tokens",
                json={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            token_data = token_resp.json()
            token = (token_data.get("access_token") or
                     token_data.get("data", {}).get("accessToken"))
            if not token:
                return HTMLResponse(
                    _popup_html("error", conn_id, error="No token in OAuth response"))

            me_resp = await client.get(
                "https://api.medium.com/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            me_data = me_resp.json().get("data", {})
            username = me_data.get("username") or me_data.get("name")

        user_id: str = request.state.user_id
        store.save_connection(user_id, conn_id, token, status="connected", username=username)
        return HTMLResponse(_popup_html("connected", conn_id, username=username))

    except Exception as exc:
        return HTMLResponse(_popup_html("error", conn_id, error=str(exc)))


def _popup_html(status: str,
                platform: str,
                *,
                error: str | None = None,
                username: str | None = None) -> str:
    payload: dict = {"type": "oauth-complete", "platform": platform, "status": status}
    if username:
        payload["username"] = username
    if error:
        payload["error"] = error

    payload_json = json.dumps(payload)
    message = "Connected!" if status == "connected" else f"Error: {error}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Connecting…</title></head>
<body style="font-family:system-ui;background:#0f1117;color:#c9cfe0;
             display:flex;align-items:center;justify-content:center;
             height:100vh;margin:0;text-align:center;">
  <div>
    <p style="margin:0 0 8px;">{message}</p>
    <p style="margin:0;color:#5a6080;font-size:.8rem;">You can close this window.</p>
  </div>
  <script>
    (function () {{
      var payload = {payload_json};
      if (window.opener) {{
        window.opener.postMessage(payload, location.origin);
        window.close();
      }}
    }})();
  </script>
</body>
</html>"""
