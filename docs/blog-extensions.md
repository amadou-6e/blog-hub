# Browser Blog Extensions

BlogHub browser extensions let a trusted administrator add a blog platform by
providing two small Python adapters instead of changing the backend and runner.
The current protocol version is `1`.

## Package shape

An extension directory contains a manifest and importable Python code:

```text
my-blog-extension/
  bloghub_extension.toml
  my_blog_extension.py
  tests/
    fixtures/article.json
    test_contract.py
```

The manifest pins the extension and protocol versions and declares exactly what
the platform supports:

```toml
[extension]
protocol_version = 1
id = "example.my-blog"
platform = "my-blog"
display_name = "My Blog"
version = "1.0.0"
capabilities = ["list_articles", "get_article", "create_draft", "publish"]

[entrypoints]
login = "my_blog_extension:LoginAdapter"
operations = "my_blog_extension:OperationsAdapter"
```

See `examples/blog-extension` for a complete minimal package.

## The two interfaces

`BrowserLoginAdapter` supplies the HTTPS login page and verifies whether a
persisted Skyvern profile is authenticated. It receives a profile path only for
verification. It must return a non-secret status and must never return cookies,
tokens, callback URLs, or page storage.

`BlogOperationsAdapter` declares capabilities and receives a Playwright page
owned by BlogHub. The runner opens and closes the persistent browser context.
The adapter implements only its declared operations and exchanges a normalized
`OperationRequest` and `OperationResult` with core orchestration. Write requests
carry an `ArticleInput`; read requests can carry a remote ID, pagination cursor,
and bounded page size. Remote records use the `RemoteArticle` shape: remote ID,
title, body, status, subtitle, cover and canonical URLs, tags, timestamps,
fingerprint, and platform metadata.

Protocol 1 capabilities are:

- `list_articles`
- `get_article`
- `create_draft`
- `update_article`
- `publish`
- `unpublish`
- `delete`

Operations that can change public content (`update_article`, `publish`,
`unpublish`, and `delete`) require explicit approval at the runner API.
An adapter should also verify the resulting remote state before returning
`success: true`.

## Install and enable

Extensions are executable Python code. Only an administrator may install them.
Mount extension directories read-only into the CLI runner and configure:

```text
BLOGHUB_EXTENSION_PATHS=/extensions
BLOGHUB_ENABLED_EXTENSIONS=bloghub.hashnode,bloghub.medium,example.my-blog
```

`BLOGHUB_EXTENSION_PATHS` is an administrator-controlled allow-list of local
directories. BlogHub does not accept extension uploads through its user API.
Restart the CLI runner after installing or upgrading an extension. The runner
rejects duplicate platforms, malformed entry points, unknown capabilities,
non-HTTPS login URLs, mismatched adapter declarations, and incompatible protocol
versions during registry construction.

Use `GET /browser/extensions` on the runner or
`GET /api/connections/browser-extensions` on the backend to discover installed
platforms and capabilities. Clients should hide actions that are not declared.

## Active-session diagnostics

An authenticated BlogHub user can export the current rendered frame of their
active platform login with
`GET /api/connections/{platform}/browser-connection/screenshot`. The response is
a bounded PNG attachment with `Cache-Control: no-store`. Capture is
provider-neutral and does not close or finalize the Skyvern session.

The image is a point-in-time diagnostic artifact. It contains only visible page
pixels and is not a durable browser profile, login credential, or replacement
for completing the browser handoff. The endpoint is unavailable after the
active login session has been finalized or disconnected.

## Test contract

Extensions can import `assert_extension_contract` and `article_from_fixture`
from `blog_extensions.testing`. Default tests must use fixtures and fake pages;
real account checks belong behind an explicit live or integration marker.

At minimum, cover:

- manifest and entry-point validation
- authenticated and expired profile detection
- every declared operation with deterministic page fixtures
- missing selectors and partial remote responses
- independent verification after writes
- unsupported capabilities
- redaction of errors and diagnostics

## Compatibility

Protocol versions are integers. BlogHub rejects a manifest whose protocol does
not exactly match the runner. Extension releases use semantic versions and are
pinned by the deployment configuration or image. A future protocol change must
ship a migration guide and may keep an older loader only when its security and
result semantics remain unambiguous.

Hashnode is the first operations adapter. Medium is the second login adapter and
currently declares no browser operations; #43 and #67 can add those operations
without adding platform-specific runner routes.
