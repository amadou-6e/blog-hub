# Article revisions and autosave

BlogHub treats every material article save as an immutable revision. A revision
contains the complete title and Markdown body, its source (`user`, `agent`,
`import`, `restore`, or `system`), its author, creation time, and the revision it
was based on. Saving unchanged content does not create another revision; a manual
checkpoint does.

Agent-generated patches record the revision they target. This allows the editor
to reject or regenerate a patch when its base no longer matches the article head.

Editor saves must include the revision ID that was current when editing began.
The API rejects a stale revision with `409 revision_conflict` and returns the
latest title and content. The editor then requires an explicit choice: use the
latest saved version, overwrite it with the recovered local draft, or create
conflict markers for manual merging. A restore uses the same concurrency check
and creates a new head revision, preserving all intervening revisions.

The browser stores unsaved drafts in `localStorage` per article. Successful saves
remove that recovery copy. Network failures leave it in place and retry when the
browser comes online; reloads recover it or open conflict resolution when the
server has moved on.

Revisions are retained indefinitely. Automated pruning is intentionally disabled
until workspace retention policy and portable export are implemented. The
additive schema update bootstraps one initial revision from every existing article
the first time schema version 4 is opened.
