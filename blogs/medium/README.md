# Medium URL Import — Investigation Log

## Local draft utilities

`blog-hub` now contains its own browser-backed Medium draft utilities in
`blogs/medium/browser_drafts.py`.

Use `MediumBrowserDraftClient.inspect_drafts()` when you need a safer progress
signal than a raw visible count. The returned inventory includes:

- the visible drafts
- the visible draft URLs
- the first visible title

This matters because Medium's drafts page can keep showing the same count while
the visible batch changes after deletions.

## Goal

Automate importing a Markdown article (rendered via `render_medium_markdown`) into Medium as a draft, using Medium's URL import page (`medium.com/p/import`), with clean code blocks and no corruption.

---

## Attempt 1 — DEV.to → Medium (fenced Markdown)

**Approach:** Publish the article to DEV.to via API (fenced code blocks in Markdown body), then import the resulting DEV.to page URL into Medium via Playwright.

**Result:** ✅ Import succeeded — Medium redirected to `/edit`. Draft was created.

**Problem discovered:** DEV.to renders fenced code blocks with full syntax highlighting (`<pre class="highlight cypher"><code><span class="k">MATCH</span>...`). Medium's importer reads those spans and adds a language-selector UI button (`codeBlockMenu-button`) to each code block labelled "Auto (CSS)", "Auto (SQL)" etc. Tests initially seemed to pass because the assertion `assert count >= 0` was a no-op.

---

## Attempt 2 — Fence-to-`<pre>` conversion

**Approach:** Pre-process the Markdown before posting to DEV.to: replace all fenced code blocks with raw HTML `<pre>` tags (HTML-escaped content, no spans). This gives DEV.to no syntax to highlight.

**Result:** ✅ DEV.to published with `<pre class="none", 0 spans>` — confirmed via API.

**Problem discovered after full run:** The Medium draft still had 12 "Auto (...)" language-selector labels. Investigation with `editor_dump.html` showed these are **UI elements** (`<div class="codeBlockMenu-button">`), not content corruption. The test assertions were calling `re.sub(r"<[^>]+>", "", raw)` on the full raw `<pre>` inner HTML — which included the button div text — causing false positives. Code content was actually clean.

---

## Attempt 3 — `<pre><code class="language-none">` hint

**Approach:** Change `_fence_to_pre` to wrap content in `<pre><code class="language-none">` to signal no language detection.

**Result:** ❌ Medium import completely failed — stayed on `/p/import`, never redirected to `/edit`. Cause unknown (possibly DEV.to's rendering of the nested `<code>` tag, or Medium's importer treating the format differently).

**Reverted immediately.**

---

## Attempt 4 — Wait for `contenteditable` before typing URL

**Observed problem:** The diagnostic screenshot showed the import input field was empty after clicking Import. Medium's import page is server-side rendered: `div.js-importUrl` is present in the DOM immediately but only becomes interactive (gains `contenteditable="true"`) after JS hydrates. The selector loop matched the non-interactive SSR div, so `keyboard.type()` typed into a dead element.

**Fix:** Added `page.wait_for_selector('div.js-importUrl[contenteditable="true"]', timeout=30_000)` before the selector loop. Also replaced `keyboard.press("Control+a") + keyboard.type()` with `url_input.fill()` (Playwright's fill is more reliable for contenteditable).

**Result:** ❌ Still failing. The page snippet now showed the DEV.to URL was present in the page text (Medium rendered it in the input), but the import button click produced no redirect after 180s. Likely Medium server-side throttling — many consecutive imports over a few hours may trigger a cooldown.

---

## Test assertion fixes (independent of import success)

### Problem: `test_auto_typescript_corruption_recorded` was always green

Old assertion: `assert count >= 0` — literally always true regardless of count.

**Fix:** Renamed to `test_no_auto_language_corruption`, asserted `auto_in_code == 0`.

### Problem: Phantom and embedded-corrupt checks were false positives

Old logic stripped all tags from raw `<pre>` content (including the `codeBlockMenu-button` UI button text "Auto (CSS)") and flagged any "Auto (...)" occurrence as content corruption.

Proper structure of Medium's editor `<pre>`:
```
<pre class="graf--pre ...">
  <span class="pre--content">   ← actual code here
    <span>MATCH ...</span>
  </span>
  <div class="codeBlockMenu-button ...">  ← UI language selector (NOT content)
    Auto (CSS)
    <svg>...</svg>
  </div>
</pre>
```

**Fix:** Strip `codeBlockMenu-button` div before extracting text:
```python
code_part = re.sub(
    r'<div[^>]*codeBlockMenu-button[^>]*>.*?</div>', '', raw, flags=re.DOTALL)
text = re.sub(r"<[^>]+>", "", code_part).strip()
```

Dry-run on the old `editor_dump.html`: 12 real code blocks, 0 Auto (...) in code content — **both new checks pass** on the existing successful import.

---

## Current state

| Item | Status |
|------|--------|
| DEV.to publish + content reaches Medium | ✅ Confirmed working |
| Code block content in Medium editor | ✅ Clean (12/12 blocks, 0 corruption) |
| Auto (...) labels in editor | ✅ UI-only, not content corruption |
| Test assertion for phantom blocks | ✅ Fixed (strips button div) |
| Test assertion for auto-corruption | ✅ Fixed (checks content only, not UI) |
| Import redirect (Medium → `/edit`) | ❌ Failing — likely rate-limited after ~6 runs in one session |

---

## Known blockers

- **Medium import rate-limiting:** After many consecutive imports the server silently ignores the import button click — the page stays on `/p/import` for 180 s. No error is shown. This resolves after a cooldown period (unknown duration, estimated hours).
- **`rawcdn.githack.com`** — blocked by Medium's import backend (silently rejected, no redirect).
- **GitHub Pages (`*.github.io`)** — also blocked by Medium's import backend.
- **DEV.to** — only confirmed-working import host for the URL import path.

---

## Attempt 5 — telegra.ph as import host

**Approach:** Use the Telegraph API (`api.telegra.ph/createPage`) to publish exact HTML we control, then import that URL into Medium. Telegraph requires no authentication for page creation, does not add syntax highlighting spans, and serves real `text/html` pages.

**Implementation:** Added `TestMediumTelegraphImportDraft` class (10 tests, 42 total). `_markdown_to_telegraph_nodes()` converts Markdown to Telegraph Node arrays: plain `{"tag": "pre", "children": [...]}` nodes, no spans.

**Host status:** ✅ telegra.ph is **accepted** by Medium's import backend (user confirmed manually — Medium redirected to `/edit`). This is the first alternative host that works.

**Code block line breaks (iteration 1):** Initial implementation joined code lines with `"\n"` as a single string child in each `<pre>` node. Medium did not render the newlines — code blocks appeared as single-line blobs.

**Fix:** Changed to interleaved `{"tag": "br"}` nodes between lines, with `"\u00a0"` (non-breaking space) for empty lines:
```python
children = []
for j, cl in enumerate(code_lines):
    if j > 0:
        children.append({"tag": "br"})
    children.append(cl if cl.strip() else "\u00a0")
```
**Result:** ✅ Line breaks rendered correctly in the Medium editor.

**Adjacent code block merging (iteration 2):** When two fenced code blocks appear consecutively in the Markdown with no paragraph between them (e.g. a `bash` pip install block immediately followed by a `python` block), Telegraph emits `</pre><pre>` with no separator. Medium's importer merges these into a single code block, and the first block vanishes.

**Fix:** Insert a `{"tag": "p", "children": ["\u00a0"]}` separator node between any two consecutive `<pre>` nodes:
```python
if nodes and isinstance(nodes[-1], dict) and nodes[-1].get("tag") == "pre":
    nodes.append({"tag": "p", "children": ["\u00a0"]})
nodes.append({"tag": "pre", "children": children})
```
**Remaining issue:** Some code blocks still vanish after import. Root cause not yet confirmed — suspected to be Medium-side handling of `<br>`-heavy `<pre>` content or Telegraph serving content differently server-side vs. browser.

**Published page:** `https://telegra.ph/What-Neo4j-actually-does-and-how-it-fits-into-a-GraphRAG-pipeline-with-a-working-LlamaIndex-example-04-04`

---

## Approach 6 — MCP direct editor publish (next candidate)

**Rationale:** Medium's URL import path is fragile — rate-limited, host-restricted, and merges adjacent code blocks. The `mcp_medium_publish-article` MCP tool drives Medium's editor directly via browser automation, the same path as manual editing. Manual editing is confirmed to work perfectly.

**Advantage over URL import:**
- Skips the import backend entirely — no host allowlist, no rate limits on import.
- Code blocks are typed/pasted directly into Medium's editor, not parsed from HTML.
- Same outcome as the user manually writing an article.

**Status:** Not yet attempted. Next step if Telegraph import continues to drop code blocks.

---

## Approach 7 — GitHub Gist embeds for code-heavy blocks

**Rationale:** Medium accepts pasted public GitHub Gist URLs as iframe embeds in
the editor, even though Gist is not a reliable URL-import source for full
articles.

**Confirmed behavior:** Pasting a public Gist URL into a Medium draft created an
embedded iframe block rather than leaving a plain link.

**Working example:**
- Gist: `https://gist.github.com/amadou-6e/a8f5c233e197228993c77f9413839a79`
- Draft: `https://medium.com/p/4508abd946d0/edit`

**Why this matters:** Worst case, each fragile code block can be published as an
individual public Gist and embedded into the Medium article directly. That would
avoid the URL-import code-block corruption path entirely for the most sensitive
snippets.

**Tradeoff:** This is less elegant than native Medium code blocks and creates
external dependencies per snippet, so it should remain a fallback rather than
the default publishing path.

---

## Import host comparison

| Host | Medium accepts | Code blocks | Notes |
|------|---------------|-------------|-------|
| DEV.to | ✅ | ✅ (with span stripping) | Rate-limited after ~6 imports/session |
| rawcdn.githack.com | ❌ | — | Silently rejected |
| GitHub Pages | ❌ | — | Silently rejected |
| telegra.ph | ✅ | ⚠️ Some vanish | Adjacent blocks merge without separator `<p>` |

---

## Files

| File | Purpose |
|------|---------|
| `tests/test_integration_medium.py` | Integration test suite (42 tests across 3 classes) |
| `tests/fixtures/sample_article.md` | Source article (12 fenced code blocks) |
| `tests/fixtures/telegraph_token.txt` | Persisted Telegraph access token |
| `tests/fixtures/medium_editor_dump/` | Diagnostic dumps from each import run |
| `_render.py` | `render_medium_markdown()` — Markdown → title + body |
