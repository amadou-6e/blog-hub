// @ts-check
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const windowsPython = path.join(__dirname, '.venv', 'Scripts', 'python.exe');
const PYTHON = process.env.PYTHON ||
  (process.platform === 'win32' && fs.existsSync(windowsPython) ? windowsPython : 'python');
const PYTHON_COMMAND = process.env.BLOGHUB_PLAYWRIGHT_PYTHON_COMMAND || `"${PYTHON}"`;
const BASE_URL = process.env.BLOGHUB_TEST_URL || 'http://localhost:8000';

module.exports = defineConfig({
  testDir: './tests',
  testMatch: ['settings.spec.js', 'overview-v3.spec.js', 'editor.spec.js'],
  outputDir: './tests/results/artifacts',
  timeout: 15_000,
  retries: 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['list'], ['html', { outputFolder: 'tests/results/html', open: 'never' }], ['json', { outputFile: 'tests/results/report.json' }]]
    : [['list'], ['json', { outputFile: 'tests/results/report.json' }]],

  webServer: process.env.BLOGHUB_TEST_URL ? undefined : {
    command: `${PYTHON_COMMAND} -m uvicorn backend.main:app --port 8000 --no-access-log`,
    cwd: __dirname,
    url: 'http://localhost:8000/health',
    reuseExistingServer: true,
    env: {
      ...process.env,
      BLOGHUB_DB_PATH: process.env.BLOGHUB_DB_PATH || ':memory:',
      BLOGHUB_DISABLE_AUTH: process.env.BLOGHUB_DISABLE_AUTH || 'true',
      PYTHONPATH: __dirname,
    },
    timeout: 30_000,
  },

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
