import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const directory = dirname(fileURLToPath(import.meta.url));
const assets = join(directory, 'assets');
const check = process.argv.includes('--check');
const temporary = mkdtempSync(join(tmpdir(), 'bloghub-settings-assets-'));

try {
  const css = join(temporary, 'settings.css');
  execFileSync(process.execPath, [
    require.resolve('tailwindcss/lib/cli.js'),
    '--config', join(directory, 'tailwind.config.cjs'),
    '--input', join(assets, 'input.css'), '--output', css, '--minify',
  ], { stdio: 'pipe' });
  const generated = new Map([['settings.css', readFileSync(css)]]);
  for (const [family, weights] of [['inter', [400, 500, 600]], ['jetbrains-mono', [400, 500]]]) {
    const source = dirname(require.resolve(`@fontsource/${family}/package.json`));
    generated.set(`fonts/${family}-LICENSE.txt`, readFileSync(join(source, 'LICENSE')));
    for (const weight of weights) {
      const filename = `${family}-latin-${weight}-normal.woff2`;
      generated.set(`fonts/${filename}`, readFileSync(join(source, 'files', filename)));
    }
  }
  let changed = false;
  for (const [name, content] of generated) {
    const destination = join(assets, name);
    if (check) {
      if (!existsSync(destination) || !readFileSync(destination).equals(content)) {
        console.error(`Settings asset is missing or stale: ${name}`);
        changed = true;
      }
    } else {
      mkdirSync(dirname(destination), { recursive: true });
      writeFileSync(destination, content);
    }
  }
  if (changed) {
    console.error('Run npm run generate:settings-assets and commit the generated assets.');
    process.exitCode = 1;
  } else {
    console.log(check ? 'Settings CSS and local fonts match their sources.' : 'Generated Settings CSS and local fonts.');
  }
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
