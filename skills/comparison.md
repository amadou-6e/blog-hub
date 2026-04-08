# Skill: Comparison

A comparison article helps the reader choose between options. It must be fair, specific, and end with a concrete recommendation. Vague "it depends" conclusions are not acceptable — always say what it depends on and which choice follows from each condition.

---

## Required sections (in order)

1. **The problem** — what decision the reader is trying to make and why it is not trivial.
2. **Contenders** — a one-paragraph description of each option: what it is, who makes it, its primary design goal.
3. **Evaluation criteria** — the axes on which you will compare them. State these upfront so the reader can weight them for their own context.
4. **Criterion-by-criterion breakdown** — one `###` section per criterion. For each:
   - Describe how each option performs on this axis.
   - Use numbers, benchmarks, or concrete examples where possible.
5. **Summary table** — a markdown table: rows are options, columns are criteria. Use symbols or short ratings, not prose.
6. **Recommendation** — explicit guidance per scenario. "If you need X, use A. If you need Y, use B." At least two distinct scenarios.
7. **What this comparison does not cover** — one short paragraph on scope limitations (version, use case, platform, etc.).

---

## Style rules

- Neutral tone throughout the breakdown sections. Save opinions for the recommendation.
- Every claim of "faster", "simpler", or "more reliable" must be backed by a number, a citation, or a reproducible example.
- The summary table must appear. It is the reader's scannable reference.
- Inline code for all product names used as identifiers, CLI commands, and config keys.

---

## What to avoid

- Comparing things that are not actually alternatives (different layers of the stack).
- Cherry-picking benchmarks that favor one option without disclosing the conditions.
- A recommendation section that says "use whichever fits your needs."
