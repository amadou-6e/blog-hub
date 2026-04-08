# Experiment Fixtures

This folder contains the pre-upload source shapes we are testing for the
Telegraph -> Medium import path.

The goal is to make the source HTML explicit before upload so we can answer:

- which `<pre>/<code>` combinations Medium preserves
- which line-break encodings survive import
- which code-class shapes help or hurt
- which indentation characters remain visible after import
- which combinations preserve multiline structure without flattening

These files are meant to be the source-of-truth inputs for future experiments.
They are intentionally more explicit than the Markdown fixture, because we want
to reason about the exact HTML we expect to exist before Telegraph upload.

## Files

- `catalog.html`
  Human-readable index of the tested fixture families
- `line_break_variants.html`
  Variants for `<br>` versus literal newlines and blank-line handling
- `tag_variants.html`
  Variants for `pre`, `pre+code`, `code`, and plain paragraph shapes
- `code_class_variants.html`
  Variants for raw language classes and `language-*` classes on `code`
- `indentation_variants.html`
  Variants for spaces, tabs, and wider Unicode-space indentation

## Uploaded Telegraph pages

- `catalog.html`
  `https://telegra.ph/Medium-Telegraph-Experiment-Fixture-Catalog-04-05`
- `line_break_variants.html`
  `https://telegra.ph/Line-Break-Variants-04-05`
- `tag_variants.html`
  `https://telegra.ph/Tag-Shape-Variants-04-05`
- `code_class_variants.html`
  `https://telegra.ph/Code-Class-Variants-04-05`
- `indentation_variants.html`
  `https://telegra.ph/Indentation-Variants-04-05`

## How to use these

1. Pick the fixture that matches the question you want to test.
2. Upload or transform that source shape into Telegraph nodes.
3. Import the resulting Telegraph page into Medium.
4. Inspect the resulting draft and dump artifacts.
5. Compare the imported result against the explicit source HTML in this folder.

## Why this matters

Earlier experiments were easier to misread because the source HTML was only
implicit in the Markdown conversion step. These fixtures make the intended input
visible so we can compare:

- source HTML before upload
- Telegraph page after upload
- Medium draft after import

That makes it much easier to tell whether a failure comes from our source shape,
from Telegraph conversion, or from Medium's importer.
