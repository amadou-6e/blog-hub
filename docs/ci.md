# Continuous Integration

GitHub Actions runs the baseline CI workflow for pull requests into `develop`,
pushes to numbered work branches, and manual dispatches.

The default checks are intentionally deterministic:

```bash
python -m pytest
npm run check:contracts
```

`pytest.ini` excludes tests marked `integration` or `browser` from the default
Python run. Live provider credentials such as `HASHNODE_PAT`, `DEVTO_API_KEY`,
and Medium browser sessions are not required by CI and should not be used by the
baseline workflow.

Playwright/browser coverage is tracked separately in issue #56. Those tests
need browser setup, screenshots/traces on failure, and fixture-backed provider
states before they become a required CI gate.
