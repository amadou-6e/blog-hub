const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function pythonExecutable(env = process.env, root = path.resolve(__dirname, '..'), platform = process.platform) {
  if (env.PYTHON) return env.PYTHON;
  const local = path.join(root, '.venv', ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']));
  return fs.existsSync(local) ? local : platform === 'win32' ? 'python' : 'python3';
}

function pythonRuntime(python, env) {
  const result = spawnSync(python, ['-c',
    'import json, sys, uvicorn; print(json.dumps(dict(executable=sys.executable, version=sys.version.split()[0], platform=sys.platform, uvicorn=uvicorn.__version__)))',
  ], { env, encoding: 'utf8', timeout: 10_000 });
  if (result.error || result.status !== 0) {
    const reason = result.error ? `: ${result.error.message}` : ` (exit ${result.status})`;
    throw new Error(`Cannot run Python with uvicorn (${python})${reason}. Set PYTHON to a same-platform virtualenv with the repository requirements installed.`);
  }
  const runtime = JSON.parse(result.stdout);
  if (runtime.platform !== process.platform) {
    throw new Error(`Node (${process.platform}) and Python (${runtime.platform}) must use the same operating environment. Set PYTHON to a matching executable.`);
  }
  return runtime;
}

function validationEnvironment(parent, directory) {
  const env = { ...parent };
  for (const key of Object.keys(env)) {
    if (/^(BLOGHUB_|CLI_RUNNER_|SKYVERN_|HASHNODE_|MEDIUM_|DEVTO_|ANTHROPIC_|OPENAI_)/.test(key)) {
      delete env[key];
    }
  }
  return {
    ...env,
    BLOGHUB_VALIDATION: 'true',
    BLOGHUB_DISABLE_AUTH: 'true',
    BLOGHUB_DB_PATH: path.join(directory, 'bloghub.db'),
    BLOGHUB_BLOBS_DIR: path.join(directory, 'blobs'),
    BLOGHUB_CREDENTIAL_KEY_FILE: path.join(directory, 'keys.json'),
    CLI_RUNNER_URL: 'http://127.0.0.1:1',
  };
}

function main() {
  const root = path.resolve(__dirname, '..');
  if (process.env.BLOGHUB_TEST_URL) {
    throw new Error('Isolated validation cannot use BLOGHUB_TEST_URL. Unset it to launch an owned server.');
  }
  const cli = require.resolve('@playwright/test/cli');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'bloghub-validation-'));
  try {
    const env = validationEnvironment(process.env, directory);
    env.PYTHON = pythonExecutable(env, root);
    const python = pythonRuntime(env.PYTHON, env);
    const revision = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' });
    if (revision.status !== 0) throw new Error(
      'Cannot identify the validation source revision. Run Node and Git in the same environment that created the worktree (Windows or WSL).',
    );
    const changes = spawnSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' });
    if (changes.status !== 0) throw new Error('Cannot identify local source changes.');
    const report = {
      revision: revision.stdout.trim(),
      dirty: Boolean(changes.stdout.trim()),
      node: process.version,
      nodeExecutable: process.execPath,
      platform: process.platform,
      python,
      playwright: require('@playwright/test/package.json').version,
      startedAt: new Date().toISOString(),
      suite: 'local-ui',
    };
    fs.mkdirSync(path.join(root, 'tests/results'), { recursive: true });
    fs.writeFileSync(path.join(root, 'tests/results/validation-run.json'), JSON.stringify(report, null, 2));
    console.log(`Local UI validation: ${report.revision}${report.dirty ? ' (with local changes)' : ''}`);
    const result = spawnSync(process.execPath, [
      cli, 'test', '--grep-invert', '@live',
    ], { cwd: root, env, stdio: 'inherit' });
    if (result.error) throw result.error;
    process.exitCode = result.status ?? 1;
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

module.exports = { validationEnvironment, pythonExecutable, pythonRuntime };
if (require.main === module) {
  try { main(); } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
