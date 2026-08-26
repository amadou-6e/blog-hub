/**
 * UI Contract — Settings screen (Connections)
 *
 * Describes every piece of data the Settings screen reads from the backend,
 * the REST endpoints that supply it, and the write/action operations it triggers.
 *
 * Covers:
 *   - Blog platform connections (Medium, Hashnode, Dev.to)
 *   - AI provider connections (Anthropic/Claude, OpenAI/Codex)
 *   - Browser login flows: loopback OAuth (Anthropic) and device code (OpenAI)
 *
 * Convention:
 *   - All timestamps are ISO-8601 strings (UTC).
 *   - Nullable fields are marked `| null`.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Shared enums
// ─────────────────────────────────────────────────────────────────────────────

export type ConnectionStatus = 'connected' | 'disconnected';

export type ConnectionType = 'platform' | 'ai';

/**
 * Which browser login flow the backend selected for this provider.
 *
 * cli_browser   Loopback OAuth (Anthropic). CLI spawns a local HTTP server;
 *               after authorization the browser redirect fails (Docker port);
 *               user copies the full address-bar URL and pastes it back.
 *
 * device_code   RFC 8628 device authorization (OpenAI Codex). CLI polls
 *               OpenAI internally; user visits the URL and enters the code
 *               shown in the UI. No paste-back step needed.
 *
 * oauth_popup   Legacy Authorization Code popup. Backend exchanges the code
 *               server-side; callback page sends postMessage.
 */
export type OAuthFlow = 'cli_browser' | 'device_code' | 'oauth_popup';

// ─────────────────────────────────────────────────────────────────────────────
// Read models  (backend → UI)
// ─────────────────────────────────────────────────────────────────────────────

/** One entry in the connections list. */
export interface ConnectionInfo {
    id: 'medium' | 'hashnode' | 'devto' | 'anthropic' | 'openai';
    label: string;
    type: ConnectionType;
    status: ConnectionStatus;
    username: string | null;   // email or handle when connected
    authMethod: 'token' | 'oauth_or_token';
    connectedAt: string | null; // ISO-8601
    errorMessage: string | null;
}

/** Response from GET /api/connections */
export interface ConnectionListResponse {
    connections: ConnectionInfo[];
}

/**
 * Response from GET /api/connections/{id}/oauth-start
 *
 * When available is false, browser login is not supported for this provider
 * (missing env vars, CLI not found, etc.) — fall back to API key entry.
 */
export interface OAuthStartResponse {
    available: boolean;
    url: string | null;
    flow: OAuthFlow | null;
    poll_url: string | null;   // relative; poll every 2 s after opening the URL
    device_code: string | null;   // only set when flow === "device_code"
}

/**
 * Response from GET /api/connections/{id}/cli-login-status
 *
 * Polled by the UI every 2 s during a browser login flow.
 */
export interface CliLoginStatus {
    status: 'connected' | 'pending' | 'error';
    username: string | null;
    errorMessage: string | null;
}

/** Response from POST /api/connections/{id}/test */
export interface TestConnectionResponse {
    ok: boolean;
    detail: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Write models  (UI → backend)
// ─────────────────────────────────────────────────────────────────────────────

/** PUT /api/connections/{id} — save or update a token/key */
export interface SaveTokenRequest {
    token: string;
}

export interface SaveTokenResponse {
    id: string;
    status: ConnectionStatus;
    username: string | null;
}

/**
 * POST /api/connections/{id}/submit-code
 *
 * Used only for the cli_browser flow (Anthropic loopback OAuth).
 * Accepts the full address-bar URL from the failed browser redirect:
 *   http://localhost:{PORT}/callback?code=...&state=...
 *
 * Not used for the device_code flow (OpenAI) — the CLI polls internally.
 */
export interface SubmitCodeRequest {
    code: string;   // full callback URL from the browser address bar
}

// ─────────────────────────────────────────────────────────────────────────────
// Endpoint summary
// ─────────────────────────────────────────────────────────────────────────────

/**
 * GET  /api/connections                          → ConnectionListResponse
 * PUT  /api/connections/{id}                     → SaveTokenResponse
 * DELETE /api/connections/{id}                   → { status: "disconnected" }
 * POST /api/connections/{id}/test                → TestConnectionResponse
 * GET  /api/connections/{id}/oauth-start         → OAuthStartResponse
 * POST /api/connections/{id}/submit-code         → { status: "submitted" }
 * GET  /api/connections/{id}/cli-login-status    → CliLoginStatus
 * GET  /api/connections/{id}/browser-connection  → browser profile status
 * POST /api/connections/{id}/browser-connection  → start Skyvern browser login
 * POST /api/connections/{id}/browser-connection/complete → verify closed login tab
 *
 * CLI runner (port 8001, not called directly by the UI):
 * POST /auth/{provider}/login                    → LoginResponse (includes device_code)
 * GET  /auth/{provider}/status                   → StatusResponse
 * POST /auth/{provider}/logout                   → { status: "disconnected" }
 * POST /auth/{provider}/submit-code              (Anthropic only — relay callback URL)
 * GET  /debug/session/{provider}                 (debug — not for production)
 */
