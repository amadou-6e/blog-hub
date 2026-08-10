-- BlogHub SQLite schema.
--
-- This is the single source of truth for the database shape. BlogHub does
-- not migrate schemas in place: when this file changes, delete the runtime
-- database (data/bloghub.db) and let it be recreated fresh. All statements
-- are idempotent so re-running this file against an already-current
-- database is a no-op.

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    remember_me INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    body_path       TEXT,
    word_count      INTEGER NOT NULL DEFAULT 0,
    gate            TEXT NOT NULL DEFAULT 'pending',
    source          TEXT NOT NULL DEFAULT 'native',
    source_platform TEXT,
    canonical_url   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS article_destinations (
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'none',
    label       TEXT,
    url         TEXT,
    draft_id    TEXT,
    error       TEXT,
    PRIMARY KEY (article_id, platform)
);

CREATE TABLE IF NOT EXISTS article_timeline (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    timestamp   TEXT NOT NULL,
    event       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
    platform      TEXT NOT NULL,
    token         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'connected',
    username      TEXT,
    connected_at  TEXT NOT NULL,
    error_message TEXT,
    user_id       TEXT REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (platform, user_id)
);

CREATE TABLE IF NOT EXISTS connection_auth_flows (
    id                       TEXT PRIMARY KEY,
    user_id                  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider                 TEXT NOT NULL,
    flow_type                TEXT NOT NULL,
    status                   TEXT NOT NULL,
    authorization_url_secret TEXT,
    device_code_secret       TEXT,
    username                 TEXT,
    error_code               TEXT,
    error_message            TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    expires_at               TEXT NOT NULL,
    completed_at             TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    article_id   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    result       TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    completed_at TEXT,
    user_id      TEXT REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS article_assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    asset_path  TEXT NOT NULL,
    mime_type   TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(article_id, filename)
);

CREATE TABLE IF NOT EXISTS article_comments (
    id          TEXT PRIMARY KEY,
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,
    text        TEXT NOT NULL,
    anchor      TEXT,
    resolved    INTEGER NOT NULL DEFAULT 0,
    has_patch   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_patches (
    id          TEXT PRIMARY KEY,
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    comment_id  TEXT REFERENCES article_comments(id) ON DELETE SET NULL,
    label       TEXT NOT NULL,
    removed     TEXT NOT NULL,
    added       TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_chat_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id       TEXT REFERENCES articles(id) ON DELETE SET NULL,
    workspace_id     TEXT NOT NULL DEFAULT 'default',
    provider         TEXT NOT NULL,
    model            TEXT,
    title            TEXT,
    status           TEXT NOT NULL,
    metadata_json    TEXT NOT NULL DEFAULT '{}',
    error            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    expires_at       TEXT,
    completed_at     TEXT,
    archived_at      TEXT,
    version          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_session_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    data_json   TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_session_messages (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    sequence      INTEGER NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE TABLE IF NOT EXISTS agent_tool_calls (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    idempotency_key  TEXT NOT NULL,
    name             TEXT NOT NULL,
    arguments_json   TEXT NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'pending',
    result_json      TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    completed_at     TEXT,
    UNIQUE(session_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS agent_approvals (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    tool_call_id   TEXT REFERENCES agent_tool_calls(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'pending',
    request_json   TEXT NOT NULL DEFAULT '{}',
    response_json  TEXT,
    requested_at   TEXT NOT NULL,
    resolved_at    TEXT,
    resolved_by    TEXT
);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    sequence    INTEGER NOT NULL,
    state_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE TABLE IF NOT EXISTS agent_session_outputs (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    reference     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_user_updated
    ON articles(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_user
    ON sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_sessions_expires
    ON sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_jobs_user_status
    ON jobs(user_id, status);

CREATE INDEX IF NOT EXISTS idx_connection_auth_user_provider
    ON connection_auth_flows(user_id, provider, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_connection_auth_active
    ON connection_auth_flows(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_article_timeline_article
    ON article_timeline(article_id);

CREATE INDEX IF NOT EXISTS idx_article_comments_article
    ON article_comments(article_id);

CREATE INDEX IF NOT EXISTS idx_article_patches_article
    ON article_patches(article_id);

CREATE INDEX IF NOT EXISTS idx_article_chat_article
    ON article_chat_log(article_id, id);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_activity
    ON agent_sessions(user_id, last_activity_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_article
    ON agent_sessions(user_id, article_id);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_status
    ON agent_sessions(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_agent_events_session
    ON agent_session_events(session_id, id);

CREATE INDEX IF NOT EXISTS idx_agent_messages_session
    ON agent_session_messages(session_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_tools_session
    ON agent_tool_calls(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_agent_approvals_session
    ON agent_approvals(session_id, status);

CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_session
    ON agent_checkpoints(session_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_outputs_session
    ON agent_session_outputs(session_id, created_at);
