# Editor agent chat

The editor chat uses the authenticated Claude Code and Codex CLI sessions from
the CLI runner. Each conversation is an `agent_session` scoped to its owner and
article. Messages, provider events, tool calls, approvals, and native provider
checkpoints survive page and backend restarts.

## Turn lifecycle

1. The editor creates or resumes a session for the selected connected provider.
2. `POST /api/agent-sessions/{id}/turns` persists the user message and starts a
   background turn.
3. The backend consumes normalized NDJSON from `POST /chat/stream` on the runner.
4. The editor polls session detail while the turn is running and renders partial
   text, tool state, errors, and approvals.
5. The final assistant message is persisted and the session moves to
   `waiting_for_input`.

Canceling a turn terminates the provider process and marks the durable session
as canceled. Reloading the editor restores the latest thread for each provider.
Legacy `article_chat_log` messages remain readable but new model turns are stored
only in the agent-session tables.

## Isolation and approvals

Every turn receives a temporary directory containing only `article.md`. Claude
uses its structured stream and read-only permission policy, so denied operations
become visible approval requests. Codex cannot use its nested Bubblewrap sandbox
inside the Docker runner. BlogHub therefore performs an allowlisted
`read_article` operation, records it as a tool call, and supplies that content to
Codex while instructing it not to invoke shell or file tools. The runner is not
granted bypass-sandbox privileges.

Approval decisions are recorded against the requesting user and session. The
current tool policy is read-only, so chat never updates canonical Markdown.
Write-capable tools must produce reviewable article patches before they can be
enabled in this surface.
