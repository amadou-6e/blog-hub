# Continuous Integration

GitHub Actions runs the baseline CI workflow for pull requests into `develop`,
pushes to numbered work branches, and manual dispatches.

The default PR checks are intentionally deterministic:

```bash
bash scripts/run-unit-tests.sh
npm run check:contracts
```

The `Unit test gate` job is the required Python gate for ordinary PRs. It runs
pytest with strict marker validation and explicitly excludes tests marked
`integration` or `browser`. Live provider credentials such as `HASHNODE_PAT`,
`DEVTO_API_KEY`, and Medium browser sessions are not required by CI and are
cleared in the baseline workflow.

Playwright/browser coverage is tracked separately in issue #56. Those tests
need browser setup, screenshots/traces on failure, and fixture-backed provider
states before they become a required CI gate.
