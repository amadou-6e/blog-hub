# Skill: Tutorial

A tutorial takes the reader from zero to a working result. Every step must be verifiable. The reader should be able to follow along in a terminal or editor and end up with something that runs.

---

## Required sections (in order)

1. **What you will build** — one paragraph and a screenshot or code snippet of the end result.
2. **Prerequisites** — an explicit list: tools, versions, accounts, prior knowledge. No assumptions.
3. **Setup** — environment, dependencies, project scaffolding. One command per step. Show expected output.
4. **Step N: [descriptive title]** — repeat as many times as needed. Each step:
   - States what it accomplishes in one sentence.
   - Shows the full code or command.
   - Explains what each non-obvious line does.
   - Ends with a verification: "Run X. You should see Y."
5. **Common pitfalls** — the top three to five things that go wrong and how to fix them.
6. **Next steps** — two or three directions the reader can take from here, with links or pointers.

---

## Style rules

- Second person throughout ("you", "your").
- Every command is in a fenced code block with the shell type (` ```bash `).
- Show expected terminal output after commands that produce it.
- File paths are inline code. Full file contents use a code block with the file name as a comment on the first line.
- Numbered lists for steps. Bullet lists for options and pitfalls.
- If the reader needs to make a choice (e.g., database driver), offer a default and explain it.

---

## What to avoid

- Skipping steps because they seem obvious.
- Commands without context ("just run this").
- Prerequisites buried in the middle of a step.
- Ending without a working, testable result.
