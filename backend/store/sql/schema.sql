-- BlogHub SQLite schema.
--
-- This is the single source of truth for the database shape. Additive changes
-- are idempotent and migrate in place when BlogHub opens an older database.
-- Destructive changes require an explicit migration and recovery plan.

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
    archived_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_id_user
    ON articles(id, user_id);

CREATE INDEX IF NOT EXISTS idx_articles_user_archived
    ON articles(user_id, archived_at);

CREATE TABLE IF NOT EXISTS article_duplicate_requests (
    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_article_id   TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    duplicate_article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    created_at          TEXT NOT NULL,
    PRIMARY KEY (user_id, source_article_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS article_mutation_requests (
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id      TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('archive', 'delete')),
    idempotency_key TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (user_id, article_id, action, idempotency_key)
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

CREATE TABLE IF NOT EXISTS article_revisions (
    id                 TEXT PRIMARY KEY,
    article_id         TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    revision_number    INTEGER NOT NULL,
    title              TEXT NOT NULL,
    content            TEXT NOT NULL,
    source             TEXT NOT NULL,
    description        TEXT,
    created_by         TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at         TEXT NOT NULL,
    base_revision_id   TEXT REFERENCES article_revisions(id) ON DELETE SET NULL,
    restored_from_id   TEXT REFERENCES article_revisions(id) ON DELETE SET NULL,
    UNIQUE(article_id, revision_number)
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
    job_id              TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    article_id          TEXT,
    status              TEXT NOT NULL DEFAULT 'queued',
    payload_json        TEXT NOT NULL DEFAULT '{}',
    queue               TEXT NOT NULL DEFAULT 'default',
    priority            INTEGER NOT NULL DEFAULT 0,
    idempotency_key     TEXT,
    max_attempts        INTEGER NOT NULL DEFAULT 3,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    available_at        TEXT,
    claimed_by          TEXT,
    lease_expires_at    TEXT,
    heartbeat_at        TEXT,
    timeout_seconds     INTEGER NOT NULL DEFAULT 300,
    cancel_requested_at TEXT,
    checkpoint_json     TEXT,
    result              TEXT,
    error               TEXT,
    terminal_error      TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT,
    completed_at        TEXT,
    expires_at          TEXT,
    user_id             TEXT REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_retry_requests (
    job_id           TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (job_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS job_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    attempt      INTEGER NOT NULL,
    worker_id    TEXT NOT NULL,
    status       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    heartbeat_at TEXT,
    finished_at  TEXT,
    error        TEXT,
    UNIQUE(job_id, attempt)
);

CREATE TABLE IF NOT EXISTS job_effects (
    job_id       TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    effect_key   TEXT NOT NULL,
    status       TEXT NOT NULL,
    attempt      INTEGER NOT NULL,
    result_json  TEXT,
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY(job_id, effect_key)
);

CREATE TABLE IF NOT EXISTS sync_schedules (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    next_run_at     TEXT NOT NULL,
    last_enqueued_at TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(user_id, platform)
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

CREATE TABLE IF NOT EXISTS remote_article_identities (
    user_id                   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform                  TEXT NOT NULL,
    remote_id                 TEXT NOT NULL,
    article_id                TEXT NOT NULL,
    remote_content_fingerprint TEXT,
    subtitle                  TEXT,
    cover_asset_id            INTEGER REFERENCES article_assets(id) ON DELETE SET NULL,
    last_sync_status          TEXT CHECK (
        last_sync_status IS NULL OR
        last_sync_status IN ('succeeded', 'partial', 'failed')
    ),
    last_sync_result_json     TEXT,
    last_sync_error           TEXT,
    remote_created_at         TEXT,
    remote_updated_at         TEXT,
    last_sync_started_at      TEXT,
    last_synced_at            TEXT,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    PRIMARY KEY (user_id, platform, remote_id),
    FOREIGN KEY (article_id, user_id)
        REFERENCES articles(id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remote_reconciliation_observations (
    id                    TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL,
    article_id            TEXT NOT NULL,
    platform              TEXT NOT NULL,
    remote_id             TEXT NOT NULL,
    local_revision_id     TEXT REFERENCES article_revisions(id) ON DELETE SET NULL,
    baseline_fingerprint  TEXT,
    local_fingerprint     TEXT NOT NULL,
    remote_fingerprint    TEXT,
    availability          TEXT NOT NULL,
    sync_state            TEXT NOT NULL,
    remote_title          TEXT,
    remote_content        TEXT,
    canonical_url         TEXT,
    remote_url            TEXT,
    remote_status         TEXT,
    remote_updated_at     TEXT,
    metadata_json         TEXT,
    error                 TEXT,
    observed_at           TEXT NOT NULL,
    FOREIGN KEY (user_id, platform, remote_id)
        REFERENCES remote_article_identities(user_id, platform, remote_id)
        ON DELETE CASCADE,
    FOREIGN KEY (article_id, user_id)
        REFERENCES articles(id, user_id) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS article_patch_revisions (
    patch_id         TEXT PRIMARY KEY REFERENCES article_patches(id) ON DELETE CASCADE,
    base_revision_id TEXT NOT NULL REFERENCES article_revisions(id) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS browser_publish_runs (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id         TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    article_revision_id TEXT NOT NULL REFERENCES article_revisions(id) ON DELETE RESTRICT,
    platform           TEXT NOT NULL,
    mode               TEXT NOT NULL DEFAULT 'draft',
    status             TEXT NOT NULL,
    result_json        TEXT,
    error              TEXT,
    created_at         TEXT NOT NULL,
    approved_at        TEXT,
    completed_at       TEXT
);

CREATE TABLE IF NOT EXISTS browser_connections (
    user_id                 TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform                TEXT NOT NULL,
    status                  TEXT NOT NULL,
    skyvern_session_id      TEXT,
    skyvern_organization_id TEXT NOT NULL,
    skyvern_profile_id      TEXT,
    app_url                 TEXT,
    error                   TEXT,
    verified_at             TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    PRIMARY KEY (user_id, platform)
);

CREATE TABLE IF NOT EXISTS connection_health (
    user_id                  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform                 TEXT NOT NULL,
    status                   TEXT NOT NULL,
    reason                   TEXT NOT NULL,
    source                   TEXT NOT NULL,
    authoritative            INTEGER NOT NULL DEFAULT 0,
    verified_at              TEXT,
    stale_at                 TEXT,
    next_check_at            TEXT,
    retry_at                 TEXT,
    diagnostics_json         TEXT NOT NULL DEFAULT '{}',
    verification_lease_until TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    PRIMARY KEY (user_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_articles_user_updated
    ON articles(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_user
    ON sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_sessions_expires
    ON sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_jobs_user_status
    ON jobs(user_id, status);

CREATE INDEX IF NOT EXISTS idx_jobs_queue_claim
    ON jobs(queue, status, available_at, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_jobs_lease
    ON jobs(status, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created
    ON jobs(user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_user_idempotency
    ON jobs(user_id, kind, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_job_attempts_job
    ON job_attempts(job_id, attempt);

CREATE INDEX IF NOT EXISTS idx_sync_schedules_due
    ON sync_schedules(enabled, next_run_at);

CREATE INDEX IF NOT EXISTS idx_connection_auth_user_provider
    ON connection_auth_flows(user_id, provider, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_connection_auth_active
    ON connection_auth_flows(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_article_timeline_article
    ON article_timeline(article_id);

CREATE INDEX IF NOT EXISTS idx_article_revisions_article
    ON article_revisions(article_id, revision_number DESC);

CREATE INDEX IF NOT EXISTS idx_remote_articles_local_article
    ON remote_article_identities(user_id, article_id);

CREATE INDEX IF NOT EXISTS idx_reconciliation_article_platform
    ON remote_reconciliation_observations(
        user_id, article_id, platform, observed_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_article_comments_article
    ON article_comments(article_id);

CREATE INDEX IF NOT EXISTS idx_article_patches_article
    ON article_patches(article_id);

CREATE INDEX IF NOT EXISTS idx_article_patch_revisions_base
    ON article_patch_revisions(base_revision_id);

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

CREATE INDEX IF NOT EXISTS idx_browser_publish_user_article
    ON browser_publish_runs(user_id, article_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_browser_connections_status
    ON browser_connections(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_connection_health_due
    ON connection_health(status, next_check_at, retry_at);
