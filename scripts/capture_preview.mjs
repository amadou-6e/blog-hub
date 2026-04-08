import { chromium } from 'playwright';
import fs from 'fs/promises';
import path from 'path';

const [, , pageUrl, outputPath] = process.argv;

if (!pageUrl || !outputPath) {
  console.error('Usage: node capture_preview.mjs <url> <output-path>');
  process.exit(1);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });

let browser;
try {
  browser = await chromium.launch({
    headless: true,
  });
} catch {
  browser = await chromium.launch({
    headless: true,
    channel: 'msedge',
  });
}

try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 1,
  });
  await page.goto(pageUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await page.screenshot({
    path: outputPath,
    fullPage: false,
    type: 'png',
  });
} finally {
  await browser.close();
}
