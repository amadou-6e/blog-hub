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

## AI Provider Auth

Anthropic and OpenAI use the durable provider-neutral flow documented in
`docs/agent-web-login.md`:

1. `POST /api/connections/{provider}/auth-flows` starts browser or device-code login.
2. The UI opens `authorizationUrl` and renders either the loopback callback input or
   `deviceCode` from `flowType`.
3. Anthropic callbacks are sent to
   `POST /api/connections/auth-flows/{flowId}/callback`. OpenAI's CLI polls the
   device-code provider directly.
4. The UI polls `GET /api/connections/auth-flows/{flowId}`. Active flows resume from
   `GET /api/connections/auth-flows/active` after navigation or backend restart.
5. Connected CLI credentials persist in the `claude-config` and `codex-config`
   volumes; SQLite contains only an encrypted web-session marker.

The shared states are `waiting_for_authorization`, `connected`, `expired`,
`rejected`, `timed_out`, `rate_limited`, `failed`, and `canceled`. Callback
payloads are forwarded directly and never stored or logged.

**Key files:**
- `backend/services/connection_auth.py` - durable flow orchestration
- `backend/store/connection_auth.py` - encrypted flow persistence
- `backend/routers/connections.py` - authenticated HTTP contract
- `cli-runner/main.py` - provider CLI processes and normalized status
- `screens/settings/v2.html` - no-reload flow UI

`CLAUDE_CONFIG_DIR=/root/.claude` must remain set in Docker Compose so Claude
writes credentials into the mounted volume.

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
