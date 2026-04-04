/**
 * scripts/generate-types.mjs
 *
 * Generates TypeScript types from all spec swagger.yaml files in .spec/backend/.
 * Output goes to contracts/generated/{service}.ts
 *
 * Uses openapi-typescript CLI (ships with the package).
 * Run: node scripts/generate-types.mjs
 *      or: npm run generate:types
 */

import { mkdirSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const specDir = join(root, ".spec", "backend");
const outDir = join(root, "contracts", "generated");

// Resolve the CLI binary — on Windows .bin uses .cmd wrappers
const binBase = join(root, "node_modules", ".bin", "openapi-typescript");
const cli = process.platform === "win32" && existsSync(binBase + ".cmd")
  ? binBase + ".cmd"
  : binBase;

mkdirSync(outDir, { recursive: true });

/**
 * Recursively find all swagger.yaml files under a directory.
 * Returns [{service, path}]
 */
function findSwaggerFiles(dir, results = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      findSwaggerFiles(full, results);
    } else if (entry.name === "swagger.yaml") {
      const service = full.replace(specDir, "").split(/[\\/]/).filter(Boolean)[0];
      results.push({ service, path: full });
    }
  }
  return results.sort((a, b) => a.service.localeCompare(b.service));
}

const files = findSwaggerFiles(specDir);

if (files.length === 0) {
  console.error("No swagger.yaml files found under", specDir);
  process.exit(1);
}

console.log(`Generating TypeScript types from ${files.length} swagger spec file(s):\n`);

let hadError = false;

for (const { service, path: swaggerPath } of files) {
  const outPath = join(outDir, `${service}.ts`);
  try {
    execFileSync(cli, [swaggerPath, "-o", outPath], {
      stdio: "pipe",
      shell: process.platform === "win32",  // cmd.exe needed for .cmd wrapper on Windows
    });
    console.log(`  ✓  ${service.padEnd(20)} → contracts/generated/${service}.ts`);
  } catch (err) {
    const stderr = err.stderr?.toString() || err.message;
    console.error(`  ✗  ${service}: ${stderr.slice(0, 200)}`);
    hadError = true;
  }
}

console.log();
if (hadError) {
  console.error("Some files failed to generate. See errors above.");
  process.exit(1);
} else {
  console.log("Done. Run `npm run check:types` to validate TS compatibility.");
}

