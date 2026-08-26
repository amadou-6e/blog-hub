# Example BlogHub extension

This package demonstrates the protocol-1 manifest and the separate login and
operations adapters. Its domain and selectors are placeholders; it is not
enabled by default.

Mount the directory into the CLI runner, add that mount point to
`BLOGHUB_EXTENSION_PATHS`, and include `example.local-blog` in
`BLOGHUB_ENABLED_EXTENSIONS`. See `docs/blog-extensions.md` for the trust model
and required tests.
