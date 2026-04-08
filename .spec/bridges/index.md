# View Transitions (Bridges)

Documents every navigation edge between in-scope views. Inspection and Publish are excluded.

---

## Views

| View | File | Purpose | Auth required |
|------|------|---------|---------------|
| Login | `screens/login/v1.html` | Entry point for all unauthenticated users. Handles both login and self-registration. On success redirects to Overview. Checks `/api/auth/me` on load and skips straight to Overview if a session already exists. | No |
| Overview | `screens/overview/v3.html` | Article list, search, filter, status. Primary hub after login. | Yes |
| Create Article | `screens/create-article/v1.html` | Wizard — brief, skill, provider, destinations, generate. | Yes |
| Import Article | `screens/import-article/v1.html` | Platform draft picker or local file upload. | Yes |
| Editor | `screens/editor/v2.html` | Full article editing, review, inspect, publish. | Yes |
| Settings | `screens/settings/v2.html` | Platform connections, AI provider keys. | Yes |

---

## Navigation map

![diagram-1](assets/index/diagram-1.png)

---

## Implementation status

| Bridge | Element | State | Notes |
|--------|---------|-------|-------|
| LG → OV (login) | Form submit — `POST /api/auth/login` 200 | ✅ Works | Redirects to `overview/v3.html` |
| LG → OV (register) | Form submit — `POST /api/auth/register` 201 | ✅ Works | Redirects to `overview/v3.html` |
| LG → OV (session exists) | Page load `/api/auth/me` check | ✅ Works | Auto-redirects if cookie is valid |
| ANY → LG | Middleware 401 on any `/api/*` | ✅ Works | Middleware blocks unauthenticated requests. Screens do not yet auto-redirect on 401 — they receive an error response only. |

<!-- existing rows below -->
| Bridge | Element | State | Notes |
|--------|---------|-------|-------|
| OV → CA | "New Article" split button (left) | Stub | `alert('? /create')` — no navigation |
| OV → IA (platform) | "Import from platform" dropdown item | Missing | Split button dropdown not yet built |
| OV → IA (upload) | "Upload .md" dropdown item | Missing | Split button dropdown not yet built |
| CA → ED | Post-creation redirect | Wrong target | `window.location.href = '../overview/v3.html'` — should go to editor with `?id=` |
| CA → OV | "Articles" nav link | ✅ Works | `href="../overview/v3.html"` |
| CA → ST | "Add in Settings" link | Stub | `alert('→ Settings')` — no navigation |
| CA → IA | "Import from platform" trigger | Missing | IA screen does not exist yet |
| IA → ED | Import complete | ✅ Works | Navigates to `editor/v2.html?id=&title=` on 201 |
| IA → OV | Cancel (returnTo=overview) | ✅ Works | Cancel reads `returnTo` param, routes to `overview/v3.html` |
| IA → CA | Cancel (returnTo=create-article) | ✅ Works | Cancel reads `returnTo` param, routes to `create-article/v1.html` |
| ED → OV | Back button | No handler | Icon `<button>` exists in nav bar, no `onclick` |
| ED → ST | Settings nav link | Missing | No Settings link in the editor nav bar |
| OV → ST | "Settings" nav button | Visual only | `setView('settings')` highlights the tab but never navigates to `settings/v2.html` |
| ST → OV | "Articles" / BlogHub logo | Wrong target | Both point to `/screens/overview/v4.html` — file does not exist (latest is v3) |

---

## Bridge detail

### LG → OV (login)  Login to Overview after successful login

| Field | Value |
|-------|-------|
| Trigger | `POST /api/auth/login` returns 200 |
| Preconditions | Valid email and password |
| URL | `/screens/overview/v3.html` |
| Payload passed | None — session cookie set by server |
| Landing state | Overview, no selection, no filter |
| **Implementation** | **✅ Works** — `window.location.href = '/screens/overview/v3.html'` in submit handler |

---

### LG → OV (register)  Login to Overview after registration

| Field | Value |
|-------|-------|
| Trigger | `POST /api/auth/register` returns 201 |
| Preconditions | Valid email, password ≥ 8 characters, email not already taken |
| URL | `/screens/overview/v3.html` |
| Payload passed | None — session cookie set by server |
| Landing state | Overview, no selection, no filter |
| **Implementation** | **✅ Works** — same redirect as login path |

---

### LG → OV (session exists)  Auto-redirect on page load

| Field | Value |
|-------|-------|
| Trigger | Page load: `GET /api/auth/me` returns 200 |
| Preconditions | Valid `bloghub_session` cookie already present |
| URL | `/screens/overview/v3.html` |
| Payload passed | None |
| Landing state | Overview, no selection |
| Notes | Prevents a logged-in user from seeing the login screen unnecessarily |
| **Implementation** | **✅ Works** — IIFE on page load calls `/api/auth/me`, redirects on 200 |

---

### OV → IA (platform)  Overview to Import Article, platform mode

| Field | Value |
|-------|-------|
| Trigger | Click "Import from platform" in the split button dropdown (nav bar, right side) |
| Preconditions | At least one platform is connected (if none are connected, the item is disabled with an "Add in Settings" tooltip) |
| URL | `/screens/import-article/v1.html?mode=platform&returnTo=overview` |
| Payload passed | `mode=platform`, `returnTo=overview` |
| Landing state | Import Article, platform picker step |
| Notes | `returnTo=overview` tells the IA screen that Cancel should navigate back to Overview, not to Create Article. |
| **Implementation** | **Missing** — split button dropdown does not exist yet. IA screen does not exist yet. |

---

### OV → IA (upload)  Overview to Import Article, upload mode

| Field | Value |
|-------|-------|
| Trigger | Click "Upload .md" in the split button dropdown (nav bar, right side) |
| Preconditions | None |
| URL | `/screens/import-article/v1.html?mode=upload&returnTo=overview` |
| Payload passed | `mode=upload`, `returnTo=overview` |
| Landing state | Import Article, file picker step (skips platform picker) |
| Notes | Unlike platform mode, upload does not require a connected platform. The file is parsed locally before any API call is made. |
| **Implementation** | **Missing** — split button dropdown does not exist yet. IA screen does not exist yet. |

---

### OV → CA  Overview to Create Article

| Field | Value |
|-------|-------|
| Trigger | Click "New Article" button (top-right) |
| Preconditions | None |
| URL | `/screens/create-article/v1.html` |
| Payload passed | None |
| Landing state | Step 1 — Write brief, empty |
| **Implementation** | **Stub** — button fires `alert('? /create')`. Needs `window.location.href` wired. |

---

### CA → ED  Create Article to Editor

| Field | Value |
|-------|-------|
| Trigger | Article creation completes (both new-article and existing-content paths) |
| Preconditions | `POST /api/articles/generate` or `POST /api/articles/import` returned 201 with `{ id, title }` |
| URL | `/screens/editor/v1.html?id=<article-id>` |
| Payload passed | `id` via query string |
| Landing state | Editor loaded with the new article, Write mode, autosave enabled |
| Notes | The workspace (`data/articles/<id>/`) must already exist before navigation. Backend creates it as part of the creation response. |
| **Implementation** | **Wrong target** — `startGeneration()` redirects to `../overview/v3.html` on success. Needs to redirect to `../editor/v1.html?id=<id>` instead. |

---

### CA → OV  Create Article cancelled

| Field | Value |
|-------|-------|
| Trigger | Click "Articles" nav link in top bar |
| Preconditions | None |
| URL | `/screens/overview/v3.html` |
| Payload passed | None |
| Landing state | Overview, no selection, no filter |
| Notes | Any in-progress wizard state is discarded. No partial article is created until the final step fires. |
| **Implementation** | **✅ Works** — `<a href="../overview/v3.html">Articles</a>` in nav bar. |

---

### CA → ST  Create Article to Settings (platform not connected)

| Field | Value |
|-------|-------|
| Trigger | Click "Add in Settings →" inline link when a destination platform shows as disconnected in the Destinations step |
| Preconditions | At least one destination platform is not connected |
| URL | `/screens/settings/v2.html?tab=platforms` |
| Payload passed | `tab=platforms` query param to pre-select the Platforms tab |
| Landing state | Settings, Platforms tab |
| Notes | Wizard state is lost. After connecting in Settings, the user must return to Create Article manually and restart the flow. A future improvement is `?returnTo=create-article` so Settings can redirect back. |
| **Implementation** | **Stub** — link fires `alert('→ Settings')`. Needs `href` set to `../settings/v2.html?tab=platforms`. |

---

### ED → OV  Editor to Overview

| Field | Value |
|-------|-------|
| Trigger | Click "Articles" breadcrumb or BlogHub logo in top bar |
| Preconditions | None (autosave has already persisted any unsaved changes within the 2 s debounce window) |
| URL | `/screens/overview/v3.html` |
| Payload passed | None |
| Landing state | Overview, no selection. The edited article appears in the list with its updated `updatedAt`. |
| Notes | If autosave is in-flight when the user clicks away, the save may be lost. A future guard should block navigation while `PATCH` is pending. |
| **Implementation** | **No handler** — back-arrow `<button>` exists in the nav bar but has no `onclick`. No breadcrumb label rendered. Needs `onclick="window.location.href='../overview/v3.html'"`. |

---

### ED → ST  Editor to Settings

| Field | Value |
|-------|-------|
| Trigger | Click "Settings" nav link in top bar |
| Preconditions | None |
| URL | `/screens/settings/v2.html` |
| Payload passed | None |
| Landing state | Settings, Platforms tab (default) |
| Notes | Same autosave-in-flight risk as ED → OV. |
| **Implementation** | **Missing** — editor nav bar has Review, Inspect, and Publish buttons only. No Settings link exists. |

---

### OV → ST  Overview to Settings

| Field | Value |
|-------|-------|
| Trigger | Click "Settings" nav link in top bar |
| Preconditions | None |
| URL | `/screens/settings/v2.html` |
| Payload passed | None |
| Landing state | Settings, Platforms tab (default) |
| **Implementation** | **Visual only** — `onclick="setView('settings')"` only updates the active tab highlight; it never navigates away from the overview page. Needs `window.location.href = '../settings/v2.html'`. |

---

### ST → OV  Settings to Overview

| Field | Value |
|-------|-------|
| Trigger | Click "Articles" nav link or BlogHub logo in top bar |
| Preconditions | None |
| URL | `/screens/overview/v3.html` |
| Payload passed | None |
| Landing state | Overview, no selection, no filter |
| **Implementation** | **Wrong target** — both the BlogHub logo and "Articles" link point to `/screens/overview/v4.html`, which does not exist. Needs to point to `v3.html`. |

---

---

### CA → IA  Create Article to Import Article

| Field | Value |
|-------|-------|
| Trigger | User selects "Import from platform" in the Existing Content path of the Create Article wizard |
| Preconditions | At least one platform is connected (otherwise the option is disabled with an "Add in Settings" fallback) |
| URL | `/screens/import-article/v1.html?returnTo=create-article` |
| Payload passed | `returnTo=create-article` so the IA screen knows where to send the result |
| Landing state | Import Article — platform picker, showing only connected platforms |
| **Implementation** | **Missing** — IA screen (`screens/import-article/`) does not exist. The trigger in `v1.html` leads into an unimplemented branch of the Existing Content sub-flow. |

---

### IA → ED  Import Article to Editor (draft fetched)

| Field | Value |
|-------|-------|
| Trigger | `POST /api/articles/import` returns 201 |
| Preconditions | Article successfully created in store with body and word count |
| URL | `/screens/editor/v2.html?id=<article-id>&title=<encoded-title>` |
| Payload passed | `id` and `title` via query string |
| Landing state | Editor loaded with the imported article body, Write mode |
| Notes | Import creates an article with `source: "platform"` or `source: "uploaded"` timeline event. No AI generation runs. |
| **Implementation** | **Missing** — IA screen does not exist. |

---

### IA → OV  Import Article cancelled, return to Overview

| Field | Value |
|-------|-------|
| Trigger | Click "Cancel" in the Import Article screen when `returnTo=overview` |
| Preconditions | None |
| URL | `/screens/overview/v3.html` |
| Payload passed | None |
| Landing state | Overview, no selection |
| **Implementation** | **Missing** — IA screen does not exist. |

---

### IA → CA  Import Article cancelled, return to Create Article

| Field | Value |
|-------|-------|
| Trigger | Click "Cancel" in the Import Article screen when `returnTo=create-article` |
| Preconditions | None |
| URL | `/screens/create-article/v1.html` |
| Payload passed | None — wizard restarts from the source selection step |
| Landing state | Create Article, Existing Content path, source picker |
| **Implementation** | **Missing** — IA screen does not exist. |

---

## Import Article screen (not yet built)

The IA screen handles two entry modes, selected via the `mode` query param:

**mode=platform** — import a draft from a connected blog platform
Entry points: OV→IA (platform), CA→IA
- List connected platforms (`GET /api/connections`)
- Fetch and paginate drafts per platform (`GET /api/connections/<platform>/drafts`)
- Show draft title, word count, last updated
- On selection: `POST /api/articles/import { source: "platform", platform, draft_id }` → 201 `{ id, title }` → navigate to editor

**mode=upload** — import a local Markdown file
Entry points: OV→IA (upload)
- File picker (accepts `.md` only)
- Parse locally: extract title from first `# heading`, count words, show preview
- On confirm: `POST /api/articles/import { source: "upload", filename, content }` → 201 `{ id, title }` → navigate to editor

Both modes use the same cancel routing: read `returnTo` param and navigate accordingly.

Spec location: `.spec/views/import-article/`.

---

## Open issues

| # | Description |
|---|-------------|
| B-01 | `CA → ST`: no `returnTo` mechanism — user loses wizard state when going to Settings to connect a platform. |
| B-02 | `ED → OV` / `ED → ST`: no navigation guard while autosave PATCH is in-flight — last edit can be silently lost. |
| B-03 | Overview "New Article" currently creates a blank article and navigates directly to the Editor, bypassing the Create Article wizard. Decide: keep as a quick-create shortcut or always route through the wizard. |
| B-07 | Screens do not yet redirect to Login on 401. When a session expires mid-session, API calls fail silently with a JSON error rather than navigating to `/screens/login/v1.html`. Each screen needs a global fetch wrapper or middleware check. |
| B-04 | `CA → IA`: Create Article wizard "import from platform" trigger not yet wired. `OV → IA`: blocked by B-06. `IA → ED/OV/CA` are now working (IA screen built). |
| B-05 | ~~`POST /api/articles/import` missing~~ — implemented. `GET /api/connections/{platform}/drafts` and `/drafts/{id}` implemented with mock platform data pending real API integration. |
| B-06 | OV nav bar split button (Variant A) is not yet built. Blocks `OV → IA (platform)` and `OV → IA (upload)` bridges. |
