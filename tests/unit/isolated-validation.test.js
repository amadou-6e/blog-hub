const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { validationEnvironment, pythonExecutable, pythonRuntime } = require('../../scripts/run-isolated-validation.cjs');

test('Python discovery uses an explicit executable, platform virtualenv, then platform default', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bloghub-python-test-'));
  try {
    assert.equal(pythonExecutable({ PYTHON: '/explicit/python' }, root, 'linux'), '/explicit/python');
    for (const platform of ['linux', 'darwin', 'win32']) {
      const windows = platform === 'win32';
      assert.equal(pythonExecutable({}, root, platform), windows ? 'python' : 'python3');
      const local = path.join(root, '.venv', ...(windows ? ['Scripts', 'python.exe'] : ['bin', 'python']));
      fs.mkdirSync(path.dirname(local), { recursive: true });
      fs.writeFileSync(local, '');
      assert.equal(pythonExecutable({}, root, platform), local);
      fs.rmSync(local);
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('missing Python fails with an actionable prerequisite error', () => {
  assert.throws(() => pythonRuntime(path.join(os.tmpdir(), 'missing-bloghub-python', 'python'), process.env),
    /Set PYTHON to a same-platform virtualenv/);
});

test('Python preflight records runtime details and rejects a different OS', { skip: process.platform === 'win32' }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bloghub-runtime-test-'));
  const executable = path.join(root, 'python');
  const env = { ...process.env, PATH: `${path.dirname(process.execPath)}${path.delimiter}${process.env.PATH || ''}` };
  try {
    const runtime = { executable, version: '3.12.3', platform: process.platform, uvicorn: '0.52.4' };
    const writeRuntime = () => fs.writeFileSync(executable,
      `#!/usr/bin/env node\nconsole.log(${JSON.stringify(JSON.stringify(runtime))});\n`, { mode: 0o755 });
    writeRuntime();
    assert.deepEqual(pythonRuntime(executable, env), runtime);
    runtime.platform = 'win32';
    writeRuntime();
    assert.throws(() => pythonRuntime(executable, env), /must use the same operating environment/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('isolated validation discards inherited production connections and storage', () => {
  const parent = {
    PATH: '/usr/bin', PYTHON: 'python3',
    BLOGHUB_DB_PATH: '/production/db', BLOGHUB_CREDENTIAL_KEY: 'secret',
    CLI_RUNNER_URL: 'http://production', SKYVERN_API_KEY: 'secret',
    MEDIUM_SESSION_FILE: '/personal/session', HASHNODE_PAT: 'secret',
    BLOGHUB_LIVE_BROWSER_LOGIN: '1', BLOGHUB_PLAYWRIGHT_PYTHON_COMMAND: 'unsafe command',
  };
  const env = validationEnvironment(parent, '/temporary');
  assert.equal(env.BLOGHUB_DB_PATH, path.join('/temporary', 'bloghub.db'));
  assert.equal(env.CLI_RUNNER_URL, 'http://127.0.0.1:1');
  for (const name of ['BLOGHUB_CREDENTIAL_KEY', 'SKYVERN_API_KEY', 'MEDIUM_SESSION_FILE',
    'HASHNODE_PAT', 'BLOGHUB_LIVE_BROWSER_LOGIN', 'BLOGHUB_PLAYWRIGHT_PYTHON_COMMAND']) {
    assert.equal(env[name], undefined);
  }
  assert.equal(env.PYTHON, 'python3');
  assert.equal(parent.CLI_RUNNER_URL, 'http://production');
});

test('isolated configuration refuses server reuse and retains first-failure evidence', () => {
  const result = spawnSync(process.execPath, ['-e',
    'const c=require("./playwright.config.js"); console.log(JSON.stringify({reuse:c.webServer.reuseExistingServer,workers:c.workers,trace:c.use.trace}));',
  ], {
    cwd: path.resolve(__dirname, '../..'),
    env: validationEnvironment(process.env, '/temporary'), encoding: 'utf8',
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { reuse: false, workers: 1, trace: 'retain-on-failure' });
});

test('isolated runner rejects externally supplied backend URLs before starting', () => {
  const result = spawnSync(process.execPath, ['scripts/run-isolated-validation.cjs'], {
    cwd: path.resolve(__dirname, '../..'),
    env: { ...process.env, BLOGHUB_TEST_URL: 'http://production.invalid' }, encoding: 'utf8',
  });
  assert.ifError(result.error);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /cannot use BLOGHUB_TEST_URL/);
});

test('Playwright uses the explicitly selected Python, including paths with spaces', () => {
  const python = path.join(os.tmpdir(), 'validation environment', 'bin', 'python');
  const result = spawnSync(process.execPath, ['-e',
    'console.log(JSON.stringify(require("./playwright.config.js").webServer.command));',
  ], {
    cwd: path.resolve(__dirname, '../..'),
    env: { ...validationEnvironment(process.env, '/temporary'), PYTHON: python }, encoding: 'utf8',
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout), `"${python}" -m uvicorn backend.main:app --port 8000 --no-access-log`);
});
