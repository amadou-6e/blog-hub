# Agent session persistence

BlogHub stores agent work as a user-owned session linked to an optional article,
workspace, provider, and model. A session contains ordered messages, lifecycle
events, idempotent tool calls, approval decisions, checkpoints, and references
to generated patches, assets, files, or articles.

The lifecycle is:

`running` -> `waiting_for_input` / `waiting_for_approval` /
`waiting_for_resume` -> `completed` / `failed` / `canceled` / `expired`

On process startup, sessions left in `running` become `waiting_for_resume`. They
are never automatically replayed. Tool calls have a session-scoped idempotency
key and an atomic claim operation, preventing a recovered worker from executing
an already claimed call twice.
Claimed calls become `interrupted` after restart and require explicit
reconciliation; pending, never-claimed calls remain claimable.

## API

The `/api/agent-sessions` resource supports creating, listing, inspecting,
resuming, canceling, archiving, exporting, and deleting sessions. Child routes
record messages, tool calls, approvals, checkpoints, and output references.
Every query is scoped to the authenticated user.

Article generation creates a session automatically and returns `sessionId`
alongside `jobId` and `articleId`. The brief and generated response survive
browser and process restarts.

## Retention and recovery

Sessions expire after 30 days by default. Startup cleanup deletes terminal
sessions older than `BLOGHUB_AGENT_SESSION_RETENTION_DAYS` (default: 90). Export
a session before archival or deletion when an audit record is required.

Session payloads are sanitized before serialization. Credential-shaped fields
and common authorization values are replaced with `[REDACTED]`; provider
credentials remain exclusively in credential storage and are never copied into
messages, checkpoints, approvals, tool arguments, events, or outputs.
