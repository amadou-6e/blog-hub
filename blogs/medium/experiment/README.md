# Medium Telegraph Pattern Experiment

Purpose: isolate which Markdown/code-block patterns vanish when a `telegra.ph`
page is imported into Medium.

This experiment keeps all suspicious patterns on one public Telegraph page,
imports that page into a real Medium draft, saves the same style of dump used by
the existing integration tests, and writes a per-pattern report.

## What it does

1. Builds a single pattern article from `fixtures/telegraph_breaking_patterns.md`
2. Publishes or updates a Telegraph page
3. Imports that URL into Medium through the real `/p/import` flow
4. Captures:
   - `editor_dump.html`
   - `full_page.html`
   - `meta.json`
   - `pattern_report.json`
5. Reports which pattern sections and code snippets survived

## Why

The current Medium README shows:
- Telegraph is accepted by Medium's import backend
- But some code blocks still vanish after import

The goal here is to reduce that failure to concrete, named pattern cases.

## Files

- `fixtures/telegraph_breaking_patterns.md`
  Source page containing all suspect patterns on one Telegraph page
- `fixtures/telegraph_breaking_patterns_manual.html`
  Manual pre-upload HTML target for the same article; use this when we want to
  reason about or vary the intended source HTML directly instead of only working
  from Markdown
- `telegraph_pattern_lab.py`
  Runner that creates the Telegraph page, imports it into Medium, saves dumps,
  and produces a pattern report

## Run

From `blog-hub/`:

```powershell
.\.venv\Scripts\python.exe blogs\medium\experiment\telegraph_pattern_lab.py
```

## Requirements

- Valid Medium session file
- Playwright installed and usable
- Internet access

Session file resolution order:

1. `MEDIUM_SESSION_FILE`
2. `C:\Users\acisse\Documents\CodeWorkspace\medium-mcp-server\medium-session.json`
3. `article_publishing/config/medium-session.json`

Telegraph token file:

- `blogs/medium/tests/fixtures/telegraph_token.txt`

## Output

Dumps are written under:

- `blogs/medium/tests/fixtures/medium_editor_dump/telegraph_patterns_<timestamp>/`

The most important artifact is:

- `pattern_report.json`

Each pattern entry includes:

- heading found or missing
- anchor snippet found or missing
- expected code snippet found or missing
- actual `<pre>` count in the imported draft

This is the file to inspect when deciding which pattern to reduce next.
