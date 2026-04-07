# BlogHub — Developer Context

## Architecture

```
blog-hub/
  backend/          FastAPI app (port 8082 in dev, 8000 in tests)
  cli-runner/       Docker container (port 8001) — wraps Claude + Codex CLIs
  screens/          Static HTML frontend (served by FastAPI at /screens/*)
  tests/
    backend/        pytest — FastAPI unit/integration tests (no browser)
    ui/             pytest-playwright — browser tests (require live server)
```

**Docker services:** only `cli-runner` runs in Docker. The FastAPI backend runs locally.

Start backend:
```
cd blog-hub && .venv/Scripts/python.exe -m uvicorn backend.main:app --port 8082
```

Rebuild cli-runner after changes to `cli-runner/main.py` or `cli-runner/Dockerfile`:
```
docker compose build cli-runner && docker compose up -d cli-runner
```

---

## AI Provider Auth — Current State

### Anthropic (Claude)

**Flow:** Loopback OAuth via `claude auth login` (Claude Code CLI).

1. Runner spawns `claude auth login` with `stdin=DEVNULL`.
2. CLI starts an HTTP server on a random port (e.g. 36403) and prints an auth URL to stderr:
   `https://claude.ai/oauth/authorize?...&redirect_uri=http://localhost:36403/callback&...`
3. Runner scans `/proc/net/tcp6` to find the port, then replaces `redirect_uri` in the URL with
   `http://localhost:{port}/callback` (it's already correct, but we normalise it).
4. URL returned to frontend with `flow="cli_browser"`.
5. Browser opens the URL, user authorises on claude.ai.
6. Browser tries to redirect to `http://localhost:36403/callback?code=X&state=Y` — fails
   (port is inside Docker, unreachable from host browser). Page shows connection error.
7. User copies the full address-bar URL and pastes it into the input field in BlogHub.
8. Frontend POSTs to `POST /api/connections/anthropic/submit-code` with `{ code: "<full URL>" }`.
9. Backend forwards to runner `POST /auth/anthropic/submit-code`.
10. Runner parses `code` and `state` from the URL, forwards
    `GET http://[::1]:{port}/callback?code=X&state=Y` to the CLI's internal server.
11. CLI does token exchange with `redirect_uri=http://localhost:{port}/callback` — matches
    what was used in the auth request, so Anthropic accepts.
12. Credentials saved to `/root/.claude/.claude.json` (persisted in `claude-config` Docker volume).
13. Frontend polls `GET /api/connections/anthropic/cli-login-status` every 2s until connected.

**Key files:**
- `cli-runner/main.py` — `auth_login`, `auth_submit_code`, `_find_cli_callback_port`
- `backend/routers/connections.py` — `_cli_oauth_start`, `cli_login_status`
- `screens/settings/v2.html` — `_doCliBrowserLogin`, `_showLoginThrobber`, `submitCode`

**Volume:** `claude-config:/root/.claude`

**Known gotcha:** `CLAUDE_CONFIG_DIR=/root/.claude` must be set in docker-compose env so the CLI
writes to the volume, not to `/root/.claude.json` (outside the volume).

---

### OpenAI (Codex)

**Flow:** Device code OAuth (RFC 8628) via `codex login --device-auth` (OpenAI Codex CLI).

1. Runner spawns `codex login --device-auth`.
2. CLI prints to stdout:
   - URL: `https://auth.openai.com/codex/device`
   - One-time code: e.g. `1NFL-253Z0`
3. Runner extracts both with ANSI-stripped regex scan.
4. Returns `{ flow: "device_code", url: "...", device_code: "1NFL-253Z0" }` to frontend.
5. Browser opens the URL. UI shows the device code prominently so user can copy it.
6. User logs into ChatGPT on that page and enters the device code.
7. **No submit step needed** — the CLI polls OpenAI's token endpoint internally until the
   code is accepted.
8. Frontend polls `GET /api/connections/openai/cli-login-status` every 2s.
9. Runner calls `codex login status` — returns exit 0 when authenticated.
10. Credentials saved to `/root/.codex/` (persisted in `codex-config` Docker volume).

**Key files:**
- `cli-runner/main.py` — `auth_login` (shared), `auth_status` openai branch
- `backend/routers/connections.py` — `_cli_oauth_start` detects `device_code` field
- `backend/schemas/connections.py` — `OAuthStartResponse.device_code`
- `screens/settings/v2.html` — `_doDeviceCodeLogin`, `_showDeviceCodeThrobber`

**Volume:** `codex-config:/root/.codex`

**Rate limit:** OpenAI limits device code requests per IP. If you see 429 errors from
`codex login --device-auth`, wait ~15 minutes before retrying.

**Status:** Flow implemented and wired up end-to-end. Not yet validated with a successful
login due to rate limiting during development. Test when rate limit clears.

---

## Running Tests

```bash
# Backend unit tests (no browser, no Docker needed)
cd blog-hub && .venv/Scripts/python.exe -m pytest tests/backend -v

# UI browser tests (requires backend on :8000 and cli-runner on :8001)
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
.venv/Scripts/python.exe -m pytest tests/ui -m browser --browser chromium -v

# Skip the live login test (requires real Claude account)
.venv/Scripts/python.exe -m pytest tests/ui -m browser --browser chromium -v -k "not login"
```

The Playwright UI test for Claude login (`test_claude_browser_login_full_loopback_flow`) captures
the callback URL from failed network requests via `page.on("request", ...)` — no manual copy needed.
