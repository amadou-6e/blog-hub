# Agent web login

BlogHub connects Anthropic and OpenAI CLI agents through one durable web-login
contract. Anthropic currently uses a loopback browser callback; OpenAI currently
uses a device code. The settings UI renders either mechanism from the flow
response and polls the same status endpoint without reloading the page.

## API contract

Start a flow with `POST /api/connections/{provider}/auth-flows`. Active flows can
be recovered after navigation or a backend restart with
`GET /api/connections/auth-flows/active`. Poll one flow at
`GET /api/connections/auth-flows/{flowId}`.

For a browser callback, send the complete localhost callback URL directly to
`POST /api/connections/auth-flows/{flowId}/callback` as:

```json
{"callbackUrl":"http://localhost:54322/callback?code=...&state=..."}
```

For device-code login, open `authorizationUrl`, enter `deviceCode` at the
provider, and continue polling. `DELETE /api/connections/auth-flows/{flowId}`
cancels an unfinished attempt without logging out an already connected agent.
Deleting the connection logs the provider out and removes its flow history.

Flow statuses are `waiting_for_authorization`, `connected`, `expired`,
`rejected`, `timed_out`, `rate_limited`, `failed`, and `canceled`. Terminal error
responses include an `errorCode`, a display-safe `errorMessage`, and recovery
guidance.

## Persistence and secrets

Flow metadata is stored in SQLite. Authorization URLs and device codes are
encrypted with the credential keyring; callback payloads are forwarded directly
to the CLI runner and are never stored. Query credentials are redacted from
application and runner error logs.

After authorization, SQLite stores only an encrypted web-session marker. The
actual CLI credentials live in the runner's `claude-config` and `codex-config`
Docker volumes, outside article workspaces. Back up those volumes if agent login
must survive moving the deployment to a new host. A normal container or backend
restart retains both the durable connection state and the CLI credentials.

Set `AGENT_AUTH_TIMEOUT_SECONDS` for the backend flow expiry and
`RUNNER_LOGIN_TIMEOUT` for the runner process timeout. They should normally have
the same value.

## Development startup

Run `python start.py --reload` to start both the runner and backend. The launcher
first reuses a healthy runner, then tries Docker Compose, and finally starts the
runner locally when an installed `claude` or `codex` binary is available. Local
runner credentials persist under ignored `data/agent-config/` by default.

Use `--runner docker`, `--runner local`, or `--runner external` to require one
mode. `--runner off` deliberately disables agent features. Normal startup fails
instead of silently serving a broken login UI when no provider CLI is available.
