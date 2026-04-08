# Skill: Deep Dive

A technical deep-dive goes beneath the surface of a topic. The reader already knows the basics — your job is to explain how it actually works, where it breaks, and how practitioners use it.

---

## Required sections (in order)

1. **Introduction** — one paragraph: the problem this technology solves and why it matters now.
2. **How it works** — explain the underlying mechanism. Use diagrams or ASCII art if they help. No hand-waving.
3. **Core concepts** — define the key primitives or abstractions. Code examples for each.
4. **Implementation walkthrough** — a complete, runnable example. Build it from scratch. Explain every non-obvious line.
5. **Edge cases and gotchas** — what the official docs gloss over. Things that will bite a reader in production.
6. **Performance characteristics** — when does it shine, when does it struggle, and how to measure it.
7. **Real-world usage** — how production systems actually use this (patterns, caveats, alternatives considered).
8. **Summary** — three to five bullet points. No fluff.

---

## Style rules

- Third person or direct address ("the library does X" / "you configure Y"). Pick one and hold it.
- Every claim is backed by a code example, benchmark, or source.
- Code blocks use the correct language identifier (` ```go `, ` ```sql `, etc.).
- Inline code for all identifiers, flags, file names, and values.
- No marketing language. No superlatives without numbers.
- Section headers are `##` level. Sub-sections are `###`.

---

## What to avoid

- Reproducing what the official README already says.
- Explaining basics the target reader already knows.
- Ending with "I hope you found this useful."
