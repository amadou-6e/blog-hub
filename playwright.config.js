// @ts-check
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

const PYTHON = path.join(__dirname, '.venv', 'Scripts', 'python.exe');

module.exports = defineConfig({
  testDir: './tests',
  outputDir: './tests/results',
  timeout: 15_000,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'tests/results/report.json' }]],

  webServer: {
    command: `"${PYTHON}" -m uvicorn backend.main:app --port 8000 --no-access-log`,
    cwd: __dirname,
    url: 'http://localhost:8000/health',
    reuseExistingServer: true,
    env: { ...process.env, PYTHONPATH: __dirname },
    timeout: 30_000,
  },

  use: {
    baseURL: 'http://localhost:8000',
    trace: 'on-first-retry',
  },

  projects: [
    { name: 'edge', use: { ...devices['Desktop Edge'], channel: 'msedge' } },
  ],
});

