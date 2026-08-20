# Continuous Integration

GitHub Actions runs the baseline CI workflow for pull requests into `develop`,
pushes to numbered work branches, and manual dispatches.

The default PR checks are intentionally deterministic:

```bash
bash scripts/run-unit-tests.sh
npm run check:contracts
npm run test:playwright:ci
```

The `Unit test gate` job is the required Python gate for ordinary PRs. It runs
pytest with strict marker validation and explicitly excludes tests marked
`integration` or `browser`. Live provider credentials such as `HASHNODE_PAT`,
`DEVTO_API_KEY`, and Medium browser sessions are not required by CI and are
cleared in the baseline workflow.

Playwright/browser coverage is tracked separately in issue #56. Those tests
run in the `Playwright gate` job with `BLOGHUB_DISABLE_AUTH=true` and fixture
state from the in-memory store. Live provider browser login is tagged `@live`
and remains opt-in through `BLOGHUB_LIVE_BROWSER_LOGIN=1`.
