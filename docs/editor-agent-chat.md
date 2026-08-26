# Editor agent chat

The editor chat uses the authenticated Claude Code and Codex CLI sessions from
the CLI runner. Each conversation is an `agent_session` scoped to its owner and
article. Messages, provider events, tool calls, approvals, and native provider
checkpoints survive page and backend restarts.

## Turn lifecycle

1. The editor saves its local content as an immutable article revision.
2. The editor creates or resumes a session for the selected connected provider.
3. `POST /api/agent-sessions/{id}/turns` verifies that revision, applies any edit
   queued by the preceding agent turn, and starts the agent from that exact snapshot.
4. The backend consumes normalized NDJSON from `POST /chat/stream` on the runner.
5. The editor polls session detail while the turn is running and renders partial
   text, tool state, errors, and approvals.
6. A revised article returned by the agent is stored as a pending, revision-bound
   patch. It is applied only immediately before the next agent turn or when the
   thread is explicitly closed. A stale patch produces a revision conflict rather
   than overwriting newer editor work.
7. The final assistant message is persisted and the session moves to
   `waiting_for_input`.

An article can give the agent a direct command with an HTML comment marker:

```markdown
<!-- bloghub-agent: Rewrite the introduction using the example below. -->
```

The command may span multiple lines before `-->`. Unmarked prose, quotations,
code, links, and imported content are always treated as article content, not as
agent instructions. Completed command markers are removed from the revised body.

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
current tool policy is read-only. Article changes use BlogHub's structured output
protocol and revision-bound patch service; providers never write canonical
Markdown directly.
