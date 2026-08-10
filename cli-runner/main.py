"""
CLI Runner — BlogHub
Thin HTTP wrapper around the claude and openai CLIs.
Runs inside a Docker container; exposes port 8001.

Endpoints:
  GET  /health
  POST /auth/{provider}/login     spawn browser login, return auth URL
  GET  /auth/{provider}/status    probe whoami, return connected/pending/error
  POST /auth/{provider}/logout    clear CLI credentials
  POST /tasks/run                 execute a CLI task against article content
"""
from __future__ import annotations

import json as _json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from typing import Iterator, Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,6}\b")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="BlogHub CLI Runner", version="0.1.0")

_RUNNER_HOME = os.environ.get("RUNNER_HOME", "/root")

# ── Provider config ────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "cli":           "claude",
        "login_args":    ["claude", "auth", "login"],
        "whoami_args":   ["claude", "auth", "status"],
        "logout_args":   ["claude", "auth", "logout"],
        # URL is printed to stderr: "If the browser didn't open, visit: https://…"
        "url_stream":    "stderr",
        "url_prefix":    "https://",
        "config_dir":    os.environ.get(
            "CLAUDE_CONFIG_DIR", os.path.join(_RUNNER_HOME, ".claude")
        ),
        "callback_port": int(os.environ.get("CLAUDE_CALLBACK_PORT", "54322")),
    },
    # OpenAI Codex CLI — device code OAuth (RFC 8628).
    # `codex login --device-auth` prints a URL + one-time code to stdout,
    # then polls OpenAI internally until the user enters the code on the web.
    # No loopback server; no submit-code step needed.
    "openai": {
        "cli":          "codex",
        "login_args":   ["codex", "login", "--device-auth"],
        "whoami_args":  ["codex", "login", "status"],
        "logout_args":  ["codex", "logout"],
        "url_stream":   "stdout",
        "url_prefix":   "https://",
        "config_dir":   os.environ.get(
            "CODEX_CONFIG_DIR", os.path.join(_RUNNER_HOME, ".codex")
        ),
    },
}

# ── Process limits ─────────────────────────────────────────────────────────────

TASK_TIMEOUT    = int(os.environ.get("RUNNER_TASK_TIMEOUT",    "60"))
LOGIN_TIMEOUT   = int(os.environ.get("RUNNER_LOGIN_TIMEOUT",   "300"))
MAX_OUTPUT      = int(os.environ.get("RUNNER_MAX_OUTPUT_BYTES", "524288"))

# ── In-memory login session tracking ──────────────────────────────────────────
# { provider: { "proc": Popen, "started_at": float, "url": str | None } }

_login_sessions: dict[str, dict] = {}

# ── Subprocess env allow-list ──────────────────────────────────────────────────

def _build_env(provider: str, api_key: str | None = None) -> dict[str, str]:
    """Return a clean env for CLI subprocesses — never pass os.environ wholesale."""
    cfg = _PROVIDERS[provider]
    env: dict[str, str] = {
        "HOME": _RUNNER_HOME,
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "CLAUDE_CONFIG_DIR": _PROVIDERS["anthropic"]["config_dir"],
        "CODEX_HOME": _PROVIDERS["openai"]["config_dir"],
    }
    if api_key:
        key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        env[key_name] = api_key  # never logged
    return env


def _cli_available(provider: str) -> bool:
    cli = _PROVIDERS[provider].get("cli")
    return bool(cli and shutil.which(cli))


def _openai_key_path() -> str:
    return os.path.join(_PROVIDERS["openai"]["config_dir"], "api_key")


def _openai_read_key() -> str | None:
    try:
        with open(_openai_key_path()) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _openai_write_key(key: str) -> None:
    os.makedirs(_PROVIDERS["openai"]["config_dir"], exist_ok=True)
    with open(_openai_key_path(), "w") as f:
        f.write(key)


def _openai_delete_key() -> None:
    try:
        os.remove(_openai_key_path())
    except FileNotFoundError:
        pass


def _openai_validate_key(key: str) -> tuple[bool, str]:
    """Probe GET /v1/models with the given key. Returns (ok, detail)."""
    import httpx as _httpx
    try:
        resp = _httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return True, "authenticated"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


# ── Schemas ────────────────────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    available: bool
    url: Optional[str] = None
    device_code: Optional[str] = None   # device auth one-time code (OpenAI Codex)
    poll_url: Optional[str] = None
    reason: Optional[str] = None


class StatusResponse(BaseModel):
    status: str
    username: Optional[str] = None
    reason: Optional[str] = None
    error_code: Optional[str] = None


def _safe_reason(value: str | None) -> str:
    """Return an actionable error with auth URLs and one-time codes removed."""
    cleaned = _ANSI_RE.sub("", value or "Provider login failed")
    cleaned = _URL_RE.sub("[redacted-url]", cleaned)
    cleaned = _DEVICE_CODE_RE.sub("[redacted-code]", cleaned)
    cleaned = re.sub(
        r"(?i)((?:code|state|token)=)[^\s&#]+", r"\1[redacted]", cleaned
    )
    return " ".join(cleaned.split())[:300]


def _failure_status(reason: str | None) -> tuple[str, str]:
    safe = _safe_reason(reason)
    lowered = safe.lower()
    if "rate limit" in lowered or "too many requests" in lowered or "429" in lowered:
        return "rate_limited", safe
    if "expired" in lowered:
        return "expired", safe
    if any(item in lowered for item in ("rejected", "denied", "access_denied")):
        return "rejected", safe
    if "timed out" in lowered or "timeout" in lowered:
        return "timed_out", safe
    return "failed", safe


class TaskRequest(BaseModel):
    provider:   str
    task:       str
    article_md: str
    context_md: Optional[str] = None
    args:       list[str] = []
    api_key:    Optional[str] = None


class TaskResponse(BaseModel):
    exit_code: int
    stdout:    str
    stderr:    str
    truncated: bool


class ChatRequest(BaseModel):
    provider: str
    session_id: str
    article_md: str
    messages: list[dict[str, str]] = []
    model: Optional[str] = None
    api_key: Optional[str] = None


_chat_processes: dict[str, subprocess.Popen] = {}


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "providers": {
            p: ("available" if _cli_available(p) else "missing")
            for p in _PROVIDERS
        },
    }


@app.get("/debug/session/{provider}")
def debug_session(provider: str):
    """Expose process health without returning authorization material."""
    session = _login_sessions.get(provider)
    if not session:
        return {"session": None}
    proc = session.get("proc")
    pid = proc.pid if proc else None
    poll = proc.poll() if proc else "no proc"
    descendants = list(_get_descendant_pids(pid)) if pid else []
    all_inodes: set[str] = set()
    for p in descendants:
        all_inodes.update(_get_proc_socket_inodes(p))
    listen_ports = []
    for net_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(net_file) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if len(cols) >= 10 and cols[3] == "0A" and cols[9] in all_inodes:
                        listen_ports.append(int(cols[1].split(":")[1], 16))
        except FileNotFoundError:
            pass
    return {
        "pid": pid,
        "poll": poll,
        "descendants": descendants,
        "socket_inodes": list(all_inodes)[:10],
        "listen_ports": listen_ports,
        "callback_port": session.get("callback_port"),
        "started_at": session.get("started_at"),
        "flow": "device_code" if session.get("device_code") else "browser_callback",
    }


# ── Auth: login ────────────────────────────────────────────────────────────────

@app.post("/auth/{provider}/login", response_model=LoginResponse)
def auth_login(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    if not _cli_available(provider):
        return LoginResponse(available=False, reason=f"{_PROVIDERS[provider]['cli']} binary not found")

    cfg = _PROVIDERS[provider]

    # Cancel any existing login session for this provider
    _cancel_login(provider)

    env = _build_env(provider)

    try:
        proc = subprocess.Popen(
            cfg["login_args"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=False,
            bufsize=0,
        )
    except OSError as exc:
        return LoginResponse(available=False, reason=str(exc))

    # Scan stdout/stderr in background threads.
    # Threads continue collecting after URL is found for debug output.
    url: str | None = None
    device_code: str | None = None
    deadline = time.time() + 15

    collected_stderr: list[str] = []
    collected_stdout: list[str] = []

    # Device code pattern: e.g. "1N2M-HJRYD" (4 alphanum + hyphen + 4-6 alphanum)
    def _scan(stream, lines: list[str]) -> None:
        nonlocal url, device_code
        for raw in stream:
            line = raw.decode("utf-8", errors="replace")
            lines.append(line)
            clean = _ANSI_RE.sub("", line).strip()
            if url is None:
                for word in clean.split():
                    if word.startswith("https://"):
                        url = word.rstrip(".")
                        break
            if device_code is None:
                m = _DEVICE_CODE_RE.search(clean)
                if m:
                    device_code = m.group(0)

    t_out = threading.Thread(target=_scan, args=(proc.stdout, collected_stdout), daemon=True)
    t_err = threading.Thread(target=_scan, args=(proc.stderr, collected_stderr), daemon=True)
    t_out.start()
    t_err.start()

    while time.time() < deadline and url is None:
        time.sleep(0.2)

    if not url:
        proc.terminate()
        reason = "".join(collected_stderr + collected_stdout).strip() or "CLI did not print a login URL"
        return LoginResponse(available=False, reason=_safe_reason(reason))

    if provider == "openai":
        code_deadline = min(deadline, time.time() + 2)
        while time.time() < code_deadline and device_code is None and proc.poll() is None:
            time.sleep(0.1)

    # For device-code flows (OpenAI Codex), the CLI polls internally — no loopback port.
    # For loopback flows (Claude), scan for the callback port the CLI is listening on.
    callback_port: int | None = None
    if provider != "openai":
        callback_port = _find_cli_callback_port(proc.pid, timeout=8.0)

    # Build the loopback URL: replace redirect_uri in the manual URL so the
    # browser is directed to http://localhost:{callback_port}/callback instead of
    # https://platform.claude.com/oauth/code/callback. When the user authorizes,
    # the browser tries to redirect to the loopback address (which is inside the
    # Docker container and unreachable from the host), so the page fails to load
    # but the full callback URL stays in the address bar. The user copies that URL
    # and submits it — we parse out code/state and forward the GET to the internal
    # CLI server. The redirect_uri then matches what the CLI used during the auth
    # request, so Anthropic accepts the token exchange.
    loopback_url = url
    if callback_port:
        loopback_redirect = f"http://localhost:{callback_port}/callback"
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            params["redirect_uri"] = [loopback_redirect]
            new_query = urllib.parse.urlencode(
                {k: v[0] for k, v in params.items()}, quote_via=urllib.parse.quote
            )
            loopback_url = urllib.parse.urlunparse(parsed._replace(query=new_query))
        except Exception:
            loopback_url = url  # fallback: send manual URL as before

    _login_sessions[provider] = {
        "proc":          proc,
        "started_at":    time.time(),
        "url":           loopback_url,
        "callback_port": callback_port,
        "device_code":   device_code,
        "stdout":        collected_stdout,
        "stderr":        collected_stderr,
    }

    return LoginResponse(
        available=True,
        url=loopback_url,
        device_code=device_code,
        poll_url=f"/auth/{provider}/status",
    )


# ── Auth: submit device code ──────────────────────────────────────────────────


class SubmitCodeRequest(BaseModel):
    code: str


@app.post("/auth/{provider}/submit-code")
def auth_submit_code(provider: str, body: SubmitCodeRequest):
    """
    Relay the authorization code from platform.claude.com to the CLI's
    loopback HTTP callback server.

    The CLI (claude auth login) runs a local HTTP server on a random port
    waiting for GET /callback?code=...&state=... — exactly what the browser
    would have sent if the redirect_uri were localhost. We make that request
    directly so no PTY or stdin tricks are needed.

    The code shown on platform.claude.com is "AUTHCODE#STATE" — the user
    copies the full string and we split it here.
    """
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    session = _login_sessions.get(provider)
    if not session:
        raise HTTPException(status_code=409, detail="No active login session — click 'Login with Browser' to start a new one")

    proc = session.get("proc")
    if not proc or proc.poll() is not None:
        _login_sessions.pop(provider, None)
        raise HTTPException(status_code=409, detail="Login process has already exited — start a new login")

    callback_port = session.get("callback_port")
    if not callback_port:
        raise HTTPException(status_code=503, detail="CLI callback port not found — restart the login")

    # Accept two formats:
    # 1. Full callback URL from browser address bar:
    #    http://localhost:{PORT}/callback?code=AUTHCODE&state=STATE
    #    (browser tried to redirect here after authorization but couldn't reach
    #    the Docker-internal port, so the page failed to load and the URL stayed
    #    in the address bar — user copies the full URL)
    # 2. Legacy "AUTHCODE#STATE" string from the manual flow page
    raw = body.code.strip()

    auth_code: str
    state: str

    if raw.startswith("http://localhost") or raw.startswith("http://127.0.0.1"):
        # Full callback URL format
        try:
            parsed_cb = urllib.parse.urlparse(raw)
            qs = urllib.parse.parse_qs(parsed_cb.query)
            auth_code = qs["code"][0]
            state     = qs["state"][0]
        except (KeyError, IndexError):
            raise HTTPException(status_code=422, detail="Callback URL is missing code or state parameters")
    elif "#" in raw:
        auth_code, state = raw.split("#", 1)
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                "Paste the full address-bar URL from your browser "
                "(http://localhost:.../callback?code=...&state=...). "
                "The page will have failed to load — that is expected."
            ),
        )

    import httpx as _httpx
    # The CLI Node process listens on ::1 (IPv6 loopback). Try both ::1 and 127.0.0.1.
    last_err: Exception | None = None
    for host in ("[::1]", "127.0.0.1"):
        try:
            resp = _httpx.get(
                f"http://{host}:{callback_port}/callback",
                params={"code": auth_code, "state": state},
                timeout=15,
                follow_redirects=True,
            )
            if resp.status_code not in (200, 302, 303):
                raise HTTPException(status_code=502, detail=f"CLI callback returned {resp.status_code}: {resp.text[:200]}")
            break
        except _httpx.ConnectError as e:
            last_err = e
            continue
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    else:
        raise HTTPException(status_code=503, detail=f"Could not reach CLI callback on port {callback_port}: {last_err}")

    return {"status": "submitted"}


# ── Auth: status ───────────────────────────────────────────────────────────────

@app.get("/auth/{provider}/status", response_model=StatusResponse)
def auth_status(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    if provider == "openai":
        cfg = _PROVIDERS["openai"]
        session = _login_sessions.get(provider)
        if session and time.time() - session["started_at"] > LOGIN_TIMEOUT:
            _cancel_login(provider)
            return StatusResponse(
                status="timed_out", reason="Login timed out",
                error_code="authorization_timeout",
            )
        env = _build_env("openai")
        try:
            result = subprocess.run(
                cfg["whoami_args"],
                capture_output=True, text=True, env=env, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            status, reason = _failure_status(str(exc))
            return StatusResponse(status=status, reason=reason, error_code=status)
        clean = _ANSI_RE.sub("", result.stdout + result.stderr).strip()
        if result.returncode == 0:
            # Parse email/username from output if present
            username = next((l.strip() for l in clean.splitlines() if "@" in l or l.strip()), None)
            _cancel_login(provider)
            return StatusResponse(status="connected", username=username)
        if session and session.get("proc") and session["proc"].poll() is None:
            return StatusResponse(status="pending")
        output = clean
        if session:
            output += " " + "".join(session.get("stderr", []) + session.get("stdout", []))
            _cancel_login(provider)
        status, reason = _failure_status(output or "not authenticated")
        return StatusResponse(status=status, reason=reason, error_code=status)

    cfg     = _PROVIDERS[provider]
    session = _login_sessions.get(provider)

    # TTL check
    if session and time.time() - session["started_at"] > LOGIN_TIMEOUT:
        _cancel_login(provider)
        return StatusResponse(
            status="timed_out", reason="Login timed out",
            error_code="authorization_timeout",
        )

    env = _build_env(provider)

    try:
        result = subprocess.run(
            cfg["whoami_args"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return StatusResponse(status="pending")
    except OSError as exc:
        status, reason = _failure_status(str(exc))
        return StatusResponse(status=status, reason=reason, error_code=status)

    # Parse output — claude auth status returns JSON on stderr
    raw = (result.stdout + result.stderr).strip()
    username: str | None = None
    logged_in = False

    try:
        data = _json.loads(raw)
        logged_in = bool(data.get("loggedIn") or data.get("logged_in"))
        username  = data.get("username") or data.get("email") or data.get("claudeAiAccount", {}).get("emailAddress")
    except (_json.JSONDecodeError, AttributeError):
        # Plain-text fallback (openai or future CLIs)
        logged_in = result.returncode == 0
        username  = next((l.strip() for l in raw.splitlines() if l.strip()), None)

    if logged_in:
        _cancel_login(provider)
        return StatusResponse(status="connected", username=username)

    if session:
        proc = session.get("proc")
        if proc and proc.poll() is None:
            return StatusResponse(status="pending")
        output = raw + " " + "".join(
            session.get("stderr", []) + session.get("stdout", [])
        )
        _cancel_login(provider)
        status, reason = _failure_status(output)
        return StatusResponse(status=status, reason=reason, error_code=status)

    return StatusResponse(
        status="failed", reason="not authenticated", error_code="not_authenticated"
    )


@app.post("/auth/{provider}/cancel")
def auth_cancel(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    _cancel_login(provider)
    return {"status": "canceled"}


# ── Auth: logout ───────────────────────────────────────────────────────────────

@app.post("/auth/{provider}/logout")
def auth_logout(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    if provider == "openai":
        _cancel_login(provider)
        cfg = _PROVIDERS["openai"]
        env = _build_env("openai")
        try:
            subprocess.run(cfg["logout_args"], env=env, timeout=10, capture_output=True)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return {"status": "disconnected"}

    _cancel_login(provider)
    cfg = _PROVIDERS[provider]
    env = _build_env(provider)

    try:
        subprocess.run(cfg["logout_args"], env=env, timeout=10, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass

    return {"status": "disconnected"}


# ── OpenAI: save API key ───────────────────────────────────────────────────────


class SaveKeyRequest(BaseModel):
    key: str


@app.put("/auth/openai/key")
def openai_save_key(body: SaveKeyRequest):
    """
    Persist an OpenAI API key to the config volume and validate it immediately.
    Returns { status: "connected" } on success or { status: "error", reason } on failure.
    """
    key = body.key.strip()
    if not key:
        raise HTTPException(status_code=422, detail="key must not be empty")
    ok, detail = _openai_validate_key(key)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Key rejected by OpenAI: {detail}")
    _openai_write_key(key)
    return {"status": "connected"}


# ── Tasks: run ─────────────────────────────────────────────────────────────────

def _chat_prompt(
    provider: str, article_path: str, article_md: str,
    messages: list[dict[str, str]],
) -> str:
    history = "\n".join(
        f"{item.get('role', 'user').upper()}: {item.get('content', '')}"
        for item in messages[-20:]
    )
    article_instruction = (
        f"Before answering, inspect {article_path} with an available read tool."
        if provider == "anthropic" else
        "BlogHub already loaded the article through its audited read_article tool. "
        "Do not invoke command execution or file tools; use the supplied article text."
    )
    supplied_article = "" if provider == "anthropic" else f"\n\n<article>\n{article_md}\n</article>"
    return (
        "You are BlogHub's article editing agent. Work only inside this isolated "
        f"directory. {article_instruction} "
        "Discuss the draft precisely and explain any proposed change. Do not modify "
        "article.md unless a later turn explicitly says BlogHub recorded user approval.\n\n"
        f"Article path: {article_path}{supplied_article}\n\nConversation:\n{history}"
    )


def _chat_command(req: ChatRequest, article_path: str) -> list[str]:
    prompt = _chat_prompt(req.provider, article_path, req.article_md, req.messages)
    if req.provider == "anthropic":
        command = [
            "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--permission-mode", "dontAsk",
            "--allowedTools", "Read,Grep,Glob",
        ]
        if req.model:
            command.extend(["--model", req.model])
        return command
    command = [
        "codex", "exec", "--json", "--sandbox", "read-only",
        "--skip-git-repo-check", "--ephemeral",
    ]
    if req.model:
        command.extend(["--model", req.model])
    command.append(prompt)
    return command


def _json_line(payload: dict) -> str:
    return _json.dumps(payload, separators=(",", ":")) + "\n"


def _normalize_chat_event(provider: str, raw: dict) -> list[dict]:
    events: list[dict] = []
    if provider == "anthropic":
        if raw.get("type") == "stream_event":
            event = raw.get("event", {})
            block = event.get("content_block", {})
            delta = event.get("delta", {})
            if event.get("type") == "content_block_start" and block.get("type") == "tool_use":
                events.append({"type": "tool_started", "toolId": block.get("id"),
                               "name": block.get("name", "tool"), "arguments": block.get("input", {})})
            elif event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                events.append({"type": "assistant_delta", "text": delta.get("text", "")})
        elif raw.get("type") == "result":
            if raw.get("result"):
                events.append({"type": "assistant_message", "text": raw["result"]})
            for denial in raw.get("permission_denials", []):
                events.append({"type": "approval_required", "request": denial})
            if raw.get("session_id"):
                events.append({"type": "checkpoint", "nativeSessionId": raw["session_id"]})
        elif raw.get("type") == "user":
            for block in raw.get("message", {}).get("content", []):
                if block.get("type") == "tool_result":
                    events.append({
                        "type": "tool_completed", "toolId": block.get("tool_use_id"),
                        "status": "failed" if block.get("is_error") else "completed",
                        "result": block.get("content"),
                    })
    else:
        event_type = raw.get("type", "")
        item = raw.get("item") or {}
        item_type = item.get("type", "")
        if event_type == "thread.started":
            events.append({"type": "checkpoint", "nativeSessionId": raw.get("thread_id")})
        elif event_type == "item.started" and item_type not in {"agent_message", "reasoning"}:
            arguments = {
                key: value for key, value in {
                    "command": item.get("command"), "query": item.get("query")
                }.items() if value is not None
            }
            events.append({"type": "tool_started", "toolId": item.get("id"),
                           "name": item_type or "tool", "arguments": arguments})
        elif event_type == "item.completed" and item_type == "agent_message":
            events.append({"type": "assistant_message", "text": item.get("text", "")})
        elif event_type == "item.completed" and item_type not in {"reasoning"}:
            events.append({"type": "tool_completed", "toolId": item.get("id"),
                           "name": item_type or "tool", "status": item.get("status", "completed"),
                           "result": item.get("aggregated_output") or item.get("result")})
        elif event_type in {"error", "turn.failed"}:
            events.append({"type": "error", "message": raw.get("message") or str(raw.get("error", "Provider failed"))})
    return events


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    if req.provider not in _PROVIDERS:
        raise HTTPException(422, f"Unknown provider: {req.provider}")
    env = _build_env(req.provider, req.api_key)
    work_dir = tempfile.mkdtemp(prefix="bloghub_chat_")
    article_path = os.path.join(work_dir, "article.md")
    with open(article_path, "w", encoding="utf-8") as article_file:
        article_file.write(req.article_md)

    def generate() -> Iterator[str]:
        stderr: list[str] = []
        try:
            proc = subprocess.Popen(
                _chat_command(req, article_path), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, cwd=work_dir, text=True, bufsize=1,
            )
            _chat_processes[req.session_id] = proc
            yield _json_line({"type": "status", "status": "running"})
            if req.provider == "openai":
                yield _json_line({
                    "type": "tool_started", "toolId": "bloghub-read-article",
                    "name": "read_article", "arguments": {"path": "article.md"},
                })
                yield _json_line({
                    "type": "tool_completed", "toolId": "bloghub-read-article",
                    "name": "read_article", "status": "completed",
                    "result": {"characters": len(req.article_md)},
                })

            def read_stderr() -> None:
                assert proc.stderr is not None
                for line in proc.stderr:
                    stderr.append(line)

            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    raw = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                for event in _normalize_chat_event(req.provider, raw):
                    yield _json_line(event)
            proc.wait(timeout=TASK_TIMEOUT)
            stderr_thread.join(timeout=2)
            if proc.returncode:
                yield _json_line({"type": "error", "message": _safe_reason("".join(stderr))})
            yield _json_line({"type": "done", "exitCode": proc.returncode})
        except (OSError, subprocess.TimeoutExpired) as exc:
            yield _json_line({"type": "error", "message": _safe_reason(str(exc))})
            yield _json_line({"type": "done", "exitCode": 1})
        finally:
            _chat_processes.pop(req.session_id, None)
            shutil.rmtree(work_dir, ignore_errors=True)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/chat/{session_id}/cancel")
def cancel_chat(session_id: str):
    proc = _chat_processes.get(session_id)
    if proc and proc.poll() is None:
        proc.terminate()
    return {"status": "canceled"}

# Allow-listed task slugs and their CLI invocation templates.
# {article_path} is substituted with the path to article.md in the task dir.
_TASK_REGISTRY: dict[str, dict] = {
    "inspect": {
        "anthropic": lambda article_path, context_path: [
            "claude", "-p",
            (
                "You are a technical editor. Review the article at the path below.\n"
                "Output JSON only: {\"gate\": \"pass|warn|fail\", \"issues\": [\"...\"]}\n\n"
                f"Article: {article_path}"
            ),
        ],
        "openai": lambda article_path, context_path: [
            "openai", "chat", "completions",
            "--model", "gpt-4o",
            "--message", f"Review the article at {article_path} for quality and completeness. Output JSON: {{\"gate\": \"pass|warn|fail\", \"issues\": []}}",
        ],
    },
    # generate: prompt is pre-built by the backend and written to article_path.
    # Claude -p reads it and returns the article body as plain text.
    # Codex exec reads the prompt from the file via stdin.
    "generate": {
        "anthropic": lambda article_path, context_path: [
            "claude", "-p",
            open(article_path, encoding="utf-8").read(),
            "--output-format", "text",
        ],
        "openai": lambda article_path, context_path: [
            "codex", "exec",
            "--full-auto",
            "--skip-git-repo-check",
            "--ephemeral",
            open(article_path, encoding="utf-8").read(),
        ],
    },
}

_ALLOWED_ARGS: set[str] = {"--model", "--max-tokens"}


@app.post("/tasks/run", response_model=TaskResponse)
def tasks_run(req: TaskRequest):
    if req.provider not in _PROVIDERS:
        raise HTTPException(422, f"Unknown provider: {req.provider}")

    if req.task not in _TASK_REGISTRY:
        raise HTTPException(422, f"Unknown task: {req.task}. Allowed: {list(_TASK_REGISTRY)}")

    # Validate extra args against allow-list
    for arg in req.args:
        if arg.split("=")[0] not in _ALLOWED_ARGS:
            raise HTTPException(422, f"Disallowed arg: {arg}")

    # Verify authenticated
    env = _build_env(req.provider, req.api_key)
    cfg = _PROVIDERS[req.provider]
    try:
        probe = subprocess.run(cfg["whoami_args"], env=env, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, f"Cannot verify auth: {exc}")
    if probe.returncode != 0:
        raise HTTPException(503, "Provider not authenticated")

    # Build isolated task directory
    work_dir = tempfile.mkdtemp(prefix="bloghub_task_")
    try:
        article_path = os.path.join(work_dir, "article.md")
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(req.article_md)

        context_path: str | None = None
        if req.context_md:
            context_path = os.path.join(work_dir, "context.md")
            with open(context_path, "w", encoding="utf-8") as f:
                f.write(req.context_md)

        task_fn = _TASK_REGISTRY[req.task].get(req.provider)
        if task_fn is None:
            raise HTTPException(422, f"Task '{req.task}' not supported for provider '{req.provider}'")

        cmd = task_fn(article_path, context_path) + req.args

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=work_dir,
            text=True,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        total_bytes   = 0
        truncated     = False

        def _read_stream(stream, chunks: list[str]) -> None:
            nonlocal total_bytes, truncated
            for chunk in iter(lambda: stream.read(4096), ""):
                if truncated:
                    break
                total_bytes += len(chunk.encode())
                if total_bytes > MAX_OUTPUT:
                    truncated = True
                    chunks.append("[output truncated]")
                    break
                chunks.append(chunk)

        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_chunks))
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_chunks))
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=TASK_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.terminate()
            time.sleep(5)
            proc.kill()
            raise HTTPException(504, "Task timed out")
        finally:
            t_out.join(timeout=5)
            t_err.join(timeout=5)

        return TaskResponse(
            exit_code=proc.returncode,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            truncated=truncated,
        )

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cancel_login(provider: str) -> None:
    session = _login_sessions.pop(provider, None)
    if session:
        proc = session.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


@app.on_event("shutdown")
def shutdown_login_processes() -> None:
    """Do not leave provider login subprocesses behind after runner shutdown."""
    for provider in tuple(_login_sessions):
        _cancel_login(provider)


def _get_proc_socket_inodes(pid: int) -> set[str]:
    """Return socket inodes for all file descriptors of the given process."""
    inodes: set[str] = set()
    try:
        fd_dir = f"/proc/{pid}/fd"
        for fd_name in os.listdir(fd_dir):
            try:
                link = os.readlink(f"{fd_dir}/{fd_name}")
                if link.startswith("socket:["):
                    inodes.add(link[8:-1])
            except OSError:
                pass
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
    return inodes


def _get_descendant_pids(root_pid: int) -> set[int]:
    """Return root_pid plus all its descendant PIDs (handles shell-wrapper → node chains)."""
    try:
        all_proc = set(int(p) for p in os.listdir("/proc") if p.isdigit())
    except (FileNotFoundError, PermissionError):
        return {root_pid}

    parent_map: dict[int, int] = {}
    for pid in all_proc:
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("PPid:"):
                        parent_map[pid] = int(line.split()[1])
                        break
        except (FileNotFoundError, PermissionError, ValueError):
            pass

    result: set[int] = set()
    queue = {root_pid}
    while queue:
        current = queue.pop()
        result.add(current)
        children = {p for p, pp in parent_map.items() if pp == current and p not in result}
        queue.update(children)
    return result


def _find_cli_callback_port(pid: int, timeout: float = 10.0) -> int | None:
    """
    Poll until any process in the CLI's process tree starts listening on a TCP port.
    The claude binary is a shell wrapper — the actual Node process is a child.
    The Node process listens on a random port for the OAuth loopback callback.
    """
    runner_ports = {8001, 54322, 54323}
    deadline = time.time() + timeout
    while time.time() < deadline:
        all_inodes: set[str] = set()
        for p in _get_descendant_pids(pid):
            all_inodes.update(_get_proc_socket_inodes(p))

        if all_inodes:
            for net_file in ("/proc/net/tcp", "/proc/net/tcp6"):
                try:
                    with open(net_file) as f:
                        for line in f.readlines()[1:]:
                            cols = line.split()
                            if len(cols) >= 10 and cols[3] == "0A" and cols[9] in all_inodes:
                                port = int(cols[1].split(":")[1], 16)
                                if port not in runner_ports:
                                    return port
                except FileNotFoundError:
                    pass
        time.sleep(0.3)
    return None
