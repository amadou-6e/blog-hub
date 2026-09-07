# Local validation (#123)

## Real local login stack

From the checkout, run:

```sh
python3 scripts/run-login-validation.py
```

On Windows use `python` instead of `python3`. The launcher requires Python 3.10+
(standard library only), Git, and a running Linux-container Docker engine with
Compose v2. It finds `docker` or `docker.exe`; select an executable explicitly
with `--docker docker.exe` when necessary. WSL Python translates paths for the
Windows Docker executable using `wslpath`. Run Git and Python in the operating
environment that owns the worktree: Windows Git cannot resolve Linux worktree
metadata. Docker Desktop must be able to access the checkout and temporary files.

The first build downloads pinned dependencies and browser images and can take a
long time. Budget roughly 3-4 GB RAM for the build, plus headroom for Skyvern and
multiple Chromium processes; actual peak usage can be higher. Check Docker memory
and disk limits if a run fails or reports OOM. No provider account, personal API key, host Python
packages, or host browser installation is needed. Build-time downloads require
network access; the running test services use an internal Docker network.

The command builds `validation/compose.yml`, starts its `tests` service and
dependencies, waits for its exit, runs mandatory restart coverage, collects safe results, and returns nonzero on
test, setup, artifact, or stack cleanup failure. Defaults are 60 minutes for the
build and 20 minutes total for startup, tests, and restart coverage. Skipped JUnit
cases fail this mandatory real-stack gate; there are no allowed prerequisite skips:

```sh
python3 scripts/run-login-validation.py --build-timeout 3600 --timeout 1200
```

Each invocation owns a random `bloghub-login-<hex>` Compose project and unique
built-image tags. Compose's inherited project/file/profile settings and `.env`
loading are disabled. Personal BlogHub/provider environment variables are not
passed to the Docker command. The launcher refuses published ports, host mounts,
external resources, or resource names that escape its project. It never invokes
the ordinary root Compose stack, reuses its volumes, or runs Docker prune.
The selected Docker context/engine is respected.

The test path is Settings -> backend -> runner -> real Skyvern/CDP -> the local
blog and identity fixture. `fixture.test` and `identity.test` share an HTTPS
certificate trusted through the disposable image's system/NSS CA stores, not an
HTTPS-ignore flag. The trusted extension ID `validation.medium` replaces builtin
Medium only in this stack. It verifies a persisted profile by opening `/account`
and requiring a fresh authenticated marker; cookie presence alone is insufficient.
Current tests cover save/reopen, retained secondary identity after blog logout,
cancellation, server-side expiry, and rejected profile verification. The fixture
also supports a test-only challenge mode; this is not a real provider CAPTCHA test.
This fixture validates the login protocol and persisted-session lifecycle, not
actual Medium selectors, remote provider authentication, or production anti-bot behavior.

BlogHub-owned browser profiles now use shared filesystem leases across login,
verification, logout, and article operations. Contention returns a retryable
conflict without discarding the saved profile. Failed closes and ambiguous start
responses retain ownership conservatively. An ownerless marker needs operator
reconciliation against Skyvern before it can be cleared; do not remove lease
lock files or assume a timeout proves the browser stopped. Browsers started
directly outside the BlogHub runner are not covered by these leases.

After the normal suite, `compose run --no-deps tests` executes
`validation/test_restart.py::test_prepare_restart`. The launcher then restarts
**only backend, runner, and Skyvern**, waits for their health checks, and executes
`validation/test_restart.py::test_after_restart` in another `--no-deps` tests
container. Fixture and Postgres remain alive, as do the named profiles/data/results
volumes. The post-restart test checks saved connection state and performs a real
local article sync. Restart coverage is mandatory, with no skip option. A failed
prepare phase fails the run rather than treating an unprepared restart as evidence.

The authoritative transition source is `settings/settings.drawio`: `edge-m-1`
(connect), `edge-m-2` (sign-in detected), `edge-m-3` (verified), `edge-m-fail`
(failure), `edge-m-disconnect`, `edge-m-reauth`, and `edge-m-cancel-verifying`.
These are the diagram edges to use when reviewing coverage, not an alternate
Mermaid rendering. This list is a coverage reference, not a claim that every
possible provider outcome has been exercised.

| Scenario | Authoritative Draw.io reference |
| --- | --- |
| Login, manual tab closure, saved-profile reopen | `edge-m-1`, `edge-m-2`, `edge-m-3` |
| Disconnect and reconnect with retained secondary identity | `edge-m-disconnect`, `edge-m-reauth` |
| Cancel during verification; reject its late result | `edge-m-cancel-verifying` |
| Rejected verification or expired remote session | `edge-m-fail` |
| Restart and authenticated headless retrieval | Preserve `flow-m-connected` |

Waiting-phase cancellation, controlled challenges, and profile exclusion are
additional regression checks, not claims of separate drawn transitions. No new
visible transition is introduced here: the production fixes restore the existing
Draw.io login, cancellation, and browser-only connection semantics. The full
specification lives in the `amadou-6e/specs` repository at
`projects/blog-hub/views/settings/settings.drawio`.

## Safe results

Each run writes `tests/results/local-login/<project>/metadata.json` and, when the
tests produced them, `login.xml`, `restart-prepare.xml`, `restart-after.xml`, and
`restart.json`. Use `--results-dir PATH` to choose
another parent directory. The metadata records Git revision and initial dirty
status, random project, timestamps, phase, test exit/OOM status, service image IDs,
and cleanup outcome. Library and browser versions are queried inside runner and
Skyvern, including the configured Skyvern Chromium binary, without launching a
new authenticated browser. Unavailable distributions are recorded as null.
The run fails with a fixed safe error if runner and Skyvern do not report matching,
nonnull Patchright versions and matching runner Patchright Chromium/Skyvern
Chromium versions. This prevents reopening a profile with an older browser schema.
Dirty status is a flag, not a source snapshot.

The launcher uses `docker cp` to retrieve `/results` into ignored temporary storage
under `tests/results` before deleting the named results volume. This mounted
checkout location also lets `docker.exe` read the Compose override without WSL
UNC paths. Only allowlisted artifacts leave temporary storage. It rebuilds XML from an
allowlist: known test names, status, and duration only. Failure messages, traceback
bodies, arbitrary properties, stdout/stderr, URLs, and parameter values are not
retained. Known exception class names and safe traceback locations are retained:
only `validation/test_login.py:<digits>` and `validation/test_restart.py:<digits>`.
No source lines, values, exception messages, or URL parameters are retained.
`restart.json` retains only `status: connected` and the validated
`verifiedAt` timestamp. Raw build/service output is deliberately suppressed.
Fixture-only PNG screenshots are retained under known test names (up to eight
tabs per test), plus `login-confirmation.png` and `connected-after-restart.png`.
Images are bounded to 16 MB, 8192 pixels per dimension, and 32 million pixels;
files with embedded text metadata or trailing payloads are rejected. This does
not redact visible pixels: the screenshot contract is local fixture UI only,
never credential/configuration pages. Full Playwright traces are disabled for
this stack because real generated API keys can appear in UI URLs. Trace archives,
browser profiles, cookies, certificates, database contents, and generated
Skyvern credentials are **not exported**. A failed JUnit case identifies the
scenario, but intentionally does not include its raw traceback.

Cleanup always attempts `down --volumes --remove-orphans` for this project's
explicit Compose file, including on Ctrl+C/SIGTERM, then removes only its unique
built-image tags without force. Downloaded base images and build cache remain.
The metadata reports incomplete cleanup. Power loss, SIGKILL, or loss of the
Docker daemon cannot be handled by a process's `finally` block; recover using
the exact project recorded in metadata or the launcher's first output line:

```sh
docker compose --project-name bloghub-login-REPLACE_WITH_RUN_ID --env-file /dev/null -f validation/compose.yml down --volumes --remove-orphans
```

On native Windows use `NUL` instead of `/dev/null`. Do not substitute your personal
Compose project name. This removes project resources even though the temporary
image-tag override has gone; any remaining per-run image tags can be removed by
their exact `bloghub-login-<hex>-image-N:local` names. Never use a global prune for
this recovery. Raw Docker service logs may contain disposable credentials and
must not be pasted into issues or CI artifacts.

## CI gate

`.github/workflows/local-login.yml` runs **Local login validation** on pull
requests touching validation, browser/extension code, Settings, backend connection
code, Skyvern integration/patches, or Compose configuration, and on manual
`workflow_dispatch`. Concurrency is scoped to the workflow/ref, so a new commit
cancels only the superseded run for the same PR, not an unrelated PR's validation.
It receives no external provider credentials. The job uploads
only sanitized reports/metadata and allowlisted fixture screenshots, including
available artifacts on ordinary failures. It has a generous
timeout for the heavy build; a larger runner may be necessary if memory is
exhausted. Repository branch-protection settings must be configured separately
if this check is required for merging. Force-cancelled jobs may not finish cleanup
or artifact collection.

## Existing local UI suite

Settings styling is self-contained in production and validation. Both Settings
HTML versions load `/screens/settings/assets/settings.css`, generated with pinned
Tailwind 3.4.17 from `screens/settings/tailwind.config.cjs` and the actual Settings
HTML class names. The original inline component CSS remains in place. Inter
400/500/600 and JetBrains Mono 400/500 Latin WOFF2 files are copied from pinned
Fontsource 5.3.0 packages, with their licenses, into committed local assets.
System font fallbacks cover glyphs outside those subsets. No Tailwind CDN or
Google Fonts request is required at runtime, including in the internal Docker network.

After editing Settings utility classes or its theme, run:

```sh
npm ci
npm run generate:settings-assets
npm run check:settings-assets
```

The check regenerates into temporary storage and compares CSS, font binaries, and
licenses byte-for-byte without rewriting committed output. It is included in the
existing CI `check:contracts` command, so stale or missing assets fail the check.
The real-stack browser assertion should require the top navigation's computed
display to be `flex`, the body's font family to include `Inter`, and the local
Inter font face to be loaded after `document.fonts.ready`. A screenshot of bare
HTML must not count as a styled Settings-page pass.

`npm run validate:local` remains a separate, lighter suite. Install repository
Python requirements in a virtual environment, run `npm ci`, and install Chromium
with `npx playwright install chromium`. Set `PYTHON` to the virtual environment's
Python executable if needed; Node, Python, and Git must use the same operating
environment as the checkout.

That runner starts its own backend on port 8000, refuses an existing server, uses
disposable database/blob/key storage, strips inherited provider configuration,
excludes live tests, and uses one browser worker. Port 8000 must be available.
Its connection mocks do **not** prove Skyvern login. It deliberately has no
reachable CLI runner. Its separate `tests/results/validation-run.json` records
source/runtime metadata; its ordinary Playwright traces and screenshots are not
sanitized by the login launcher and must not contain real credentials.
