# Medium Telegraph Findings

## Confirmed

- The strongest current Telegraph -> Medium URL-import shape is plain `pre`
  with literal newlines and no nested `code` tag.
- Long multiline blocks can survive import without splitting when they are
  emitted as plain `pre` content with literal newlines.
- The current surviving long-block example is `Pattern 07` from
  `fixtures/telegraph_breaking_patterns.md`.
- A stricter flattening check is now required. Marker survival alone is not
  enough to judge code-block fidelity.

## Supporting artifacts

- Best plain-`pre` draft:
  `https://medium.com/p/5336610b7a75/edit`
- Best plain-`pre` report:
  `blogs/medium/tests/fixtures/medium_editor_dump/telegraph_patterns_pre_newline_nbsp_20260405T122208/pattern_report.json`

## Ruled out so far

- Classless `pre + code` is unstable and has previously stalled on import.
- `code` alone imports, but it loses block structure.
- Adding `class="language-*"` or raw language classes to `code` does not beat
  plain `pre`.
- Changing indentation encoding alone on the plain `pre` path does not prevent
  flattening.
- On the stronger `pre + code + raw language class + newline` path, Pattern 07
  keeps its full multiline structure, but Medium still normalizes visible
  leading indentation so raw spaces, `NBSP`, and tabs end up looking the same in
  the imported HTML.

## Current best split result

- For full multiline preservation of `Pattern 07`, the best current source shape
  is:
  - `tag_mode = pre_code`
  - `code_class_mode = raw_language`
  - `line_break_mode = newline`
  - `empty_line_mode = nbsp`
- Example drafts:
  - `https://medium.com/p/10349d113fe1/edit`
  - `https://medium.com/p/3d0b10ff5616/edit`
  - `https://medium.com/p/e32c0a13a0e0/edit`
- These preserve all 12 non-empty lines in `Pattern 07`, but do not preserve
  distinct visible indentation widths.

## Pattern 07 target block

Original source block from `fixtures/telegraph_breaking_patterns.md`:

```python
def pattern_seven():
    rows = []
    for index in range(20):
        rows.append({
            "marker": "PATTERN-07-CODE",
            "index": index,
            "value": index * 3,
        })
    return rows

result = pattern_seven()
for row in result:
    print(row["marker"], row["index"], row["value"])
```

## Next check

- Compare indentation encodings while keeping the winning plain-`pre` block
  shape fixed:
  - raw leading spaces
  - leading non-breaking spaces
  - grouped leading non-breaking spaces

## GitHub Gist embed

- Medium accepts a pasted public GitHub Gist URL in the editor and converts it
  into an embedded iframe block.
- Test Gist:
  `https://gist.github.com/amadou-6e/a8f5c233e197228993c77f9413839a79`
- Test draft:
  `https://medium.com/p/4508abd946d0/edit`
- Dump dir:
  `blogs/medium/tests/fixtures/medium_editor_dump/gist_embed_20260405T235132/`
- In the editor dump, the Gist appears as:
  - `figure.graf--iframe`
  - `iframe src="/media/907f922ac579f23dfa1f91a0055f2597?postId=4508abd946d0"`
- The original Gist URL is not left behind as a plain anchor in the editor DOM.
- This does not solve URL-import fidelity, but it is a viable code-preserving
  fallback for Medium articles when imported code blocks are unreliable.
