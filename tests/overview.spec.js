/**
 * overview.spec.js — Full-stack integration tests
 *
 * Strategy
 * --------
 * Tests run against a live FastAPI backend (started via playwright.config.js
 * webServer) serving screens/overview/v4.html as a real HTTP page.
 *
 * Each test:
 *  1. Calls POST /api/dev/reset in beforeEach so the in-memory store starts
 *     from seed state.
 *  2. Navigates to v4.html — which fetches real data from /api/articles.
 *  3. Asserts DOM state (visual) or network calls (contract).
 */

const { test, expect } = require('@playwright/test');

const OVERVIEW_URL = 'http://localhost:8000/screens/overview/v4.html';

// ─── helpers ─────────────────────────────────────────────────────────────────

/** Reset in-memory store to seed data. */
async function resetStore(page) {
  await page.request.post('http://localhost:8000/api/dev/reset');
}

/** Wait until the article table has at least one real data row. */
async function waitForTable(page) {
  await page.waitForSelector('#article-table tr:not(:has(td[colspan]))', { timeout: 8000 });
}

// ─── suite ───────────────────────────────────────────────────────────────────

test.describe('Overview screen', () => {
  test.beforeEach(async ({ page }) => {
    await resetStore(page);
    await page.goto(OVERVIEW_URL);
    await waitForTable(page);
  });

  // ── 1. Initial load ────────────────────────────────────────────────────────

  test('renders article rows on load', async ({ page }) => {
    const rows = page.locator('#article-table tr');
    expect(await rows.count()).toBeGreaterThan(0);
  });

  test('each row shows title, updated timestamp and platform pills', async ({ page }) => {
    const firstRow = page.locator('#article-table tr').first();
    const title = firstRow.locator('td:nth-child(2)');
    await expect(title).not.toBeEmpty();
    const updated = firstRow.locator('td:nth-child(3)');
    await expect(updated).not.toBeEmpty();
    await expect(firstRow.locator('.pill')).toHaveCount(3);
  });

  /**
   * BACKEND CONTRACT:
   *   GET /api/articles?sortBy=updatedAt&sortDir=desc&page=1&pageSize=20
   */
  test('[contract] initial load calls GET /api/articles', async ({ page }) => {
    await resetStore(page);

    const [req] = await Promise.all([
      page.waitForRequest(
        r => r.url().includes('/api/articles') &&
             !r.url().includes('/push') &&
             !r.url().includes('/inspect') &&
             r.method() === 'GET',
        { timeout: 8000 }
      ),
      page.goto(OVERVIEW_URL),
    ]);
    await waitForTable(page);

    const url = new URL(req.url());
    expect(url.searchParams.get('sortBy')).toBe('updatedAt');
    expect(url.searchParams.get('sortDir')).toBe('desc');
    expect(url.searchParams.get('page')).toBe('1');
    expect(url.searchParams.get('pageSize')).toBe('20');
  });

  // ── 2. Row click → side panel ─────────────────────────────────────────────

  test('clicking a row opens the side panel', async ({ page }) => {
    const panel = page.locator('#side-panel');
    await expect(panel).toHaveClass(/opacity-0/);

    await page.locator('#article-table tr').first().click();

    await expect(panel).not.toHaveClass(/opacity-0/);
  });

  test('side panel shows title for the clicked article', async ({ page }) => {
    const firstRow = page.locator('#article-table tr').first();
    const titleText = await firstRow.locator('td:nth-child(2)').innerText();

    await firstRow.click();

    const panelTitle = page.locator('#panel-title');
    await expect(panelTitle).toHaveText(titleText.trim());
  });

  test('side panel shows per-platform destination rows', async ({ page }) => {
    await page.locator('#article-table tr').first().click();
    const dests = page.locator('#panel-destinations > div');
    await expect(dests).toHaveCount(3); // Medium, Hashnode, Dev.to
  });

  test('side panel shows timeline events', async ({ page }) => {
    await page.locator('#article-table tr').first().click();
    const events = page.locator('#panel-timeline > div');
    expect(await events.count()).toBeGreaterThan(0);
  });

  // ── 3. Side panel — close ─────────────────────────────────────────────────

  test('close button hides the side panel', async ({ page }) => {
    await page.locator('#article-table tr').first().click();
    const panel = page.locator('#side-panel');
    await expect(panel).not.toHaveClass(/opacity-0/);

    await panel.locator('button').first().click();
    await expect(panel).toHaveClass(/opacity-0/);
  });

  // ── 4. "+ New article" button ─────────────────────────────────────────────

  test('[contract] "+ New article" is visible and clickable', async ({ page }) => {
    // Intercept POST so we don't navigate away or pollute store
    await page.route('**/api/articles', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201, contentType: 'application/json',
          body: JSON.stringify({ id: 'art_test', title: 'Untitled', createdAt: new Date().toISOString() }),
        });
      } else {
        await route.continue();
      }
    });
    const btn = page.getByRole('button', { name: /new article/i });
    await expect(btn).toBeVisible();
    await btn.click();
  });

  /**
   * BACKEND CONTRACT:
   *   POST /api/articles  { title: "Untitled" }  → 201 { id, title, createdAt }
   */
  test('[contract] "+ New article" click triggers POST /api/articles', async ({ page }) => {
    let capturedBody = null;
    await page.route('**/api/articles', async (route) => {
      if (route.request().method() === 'POST') {
        capturedBody = JSON.parse(route.request().postData() || '{}');
        await route.fulfill({
          status: 201, contentType: 'application/json',
          body: JSON.stringify({ id: 'art_new', title: 'Untitled', createdAt: new Date().toISOString() }),
        });
      } else {
        await route.continue();
      }
    });

    await page.getByRole('button', { name: /new article/i }).click();
    await page.waitForTimeout(300);

    expect(capturedBody).toMatchObject({ title: 'Untitled' });
  });

  // ── 5. Search bar ─────────────────────────────────────────────────────────

  test('search input is visible', async ({ page }) => {
    await expect(page.locator('input[placeholder*="Search"]')).toBeVisible();
  });

  /**
   * BACKEND CONTRACT:
   *   GET /api/articles?q=postgres   (debounced 300 ms after user stops typing)
   */
  test('[contract] typing in search triggers GET /api/articles?q=…', async ({ page }) => {
    const reqPromise = page.waitForRequest(
      r => r.url().includes('/api/articles') && r.url().includes('q=postgres'),
      { timeout: 5000 }
    );
    await page.locator('input[placeholder*="Search"]').fill('postgres');
    const req = await reqPromise;
    expect(req.url()).toContain('q=postgres');
  });

  // ── 6. Status filter chips ────────────────────────────────────────────────

  test('filter chips are present', async ({ page }) => {
    const chips = page.locator('button', { hasText: /All|Drafting|Ready|Error|Published/ });
    expect(await chips.count()).toBeGreaterThan(1);
  });

  /**
   * BACKEND CONTRACT:
   *   GET /api/articles?status=error
   */
  test('[contract] clicking "Error" filter chip triggers GET /api/articles?status=error', async ({ page }) => {
    const reqPromise = page.waitForRequest(
      r => r.url().includes('/api/articles') && r.url().includes('status=error'),
      { timeout: 5000 }
    );
    await page.getByRole('button', { name: /^Error$/i }).click();
    const req = await reqPromise;
    expect(req.url()).toContain('status=error');
  });

  // ── 7. Side panel actions ─────────────────────────────────────────────────

  /**
   * BACKEND CONTRACT:
   *   POST /api/articles/:id/push  → 202 { jobId, status: "running" }
   */
  test('[contract] "Push drafts" click triggers POST /api/articles/:id/push', async ({ page }) => {
    await page.locator('#article-table tr').first().click();

    const reqPromise = page.waitForRequest(
      r => r.url().includes('/push') && r.method() === 'POST',
      { timeout: 5000 }
    );
    await page.getByRole('button', { name: /push drafts/i }).click();
    const req = await reqPromise;
    expect(req.url()).toMatch(/\/api\/articles\/.+\/push/);
  });

  /**
   * BACKEND CONTRACT:
   *   POST /api/articles/:id/inspect  → 202 { jobId, status: "running" }
   */
  test('[contract] "Inspect" click triggers POST /api/articles/:id/inspect', async ({ page }) => {
    await page.locator('#article-table tr').first().click();

    const reqPromise = page.waitForRequest(
      r => r.url().includes('/inspect') && r.method() === 'POST',
      { timeout: 5000 }
    );
    await page.getByRole('button', { name: /inspect/i }).click();
    const req = await reqPromise;
    expect(req.url()).toMatch(/\/api\/articles\/.+\/inspect/);
  });

  // ── 8. Platform connection indicator ──────────────────────────────────────

  test('platform connection badge is visible in the nav', async ({ page }) => {
    const badge = page.locator('text=/\\d+ platforms? connected/i');
    await expect(badge).toBeVisible();
  });

  // ── 9. Bulk checkbox ──────────────────────────────────────────────────────

  test('header checkbox exists', async ({ page }) => {
    await expect(page.locator('thead input[type="checkbox"]')).toBeVisible();
  });

  test('row checkboxes exist for each row', async ({ page }) => {
    const rowCount = await page.locator('#article-table tr').count();
    const checkboxCount = await page.locator('#article-table input[type="checkbox"]').count();
    expect(checkboxCount).toBe(rowCount);
  });

  // ── 10. Action combinations ────────────────────────────────────────────────

  test('open panel → close → reopen: panel shows same article both times', async ({ page }) => {
    const firstRow = page.locator('#article-table tr').first();
    const titleText = (await firstRow.locator('td:nth-child(2)').innerText()).trim();
    const panel = page.locator('#side-panel');

    await firstRow.click();
    await expect(panel).not.toHaveClass(/opacity-0/);
    await expect(page.locator('#panel-title')).toHaveText(titleText);

    await panel.locator('button').first().click();
    await expect(panel).toHaveClass(/opacity-0/);

    await firstRow.click();
    await expect(panel).not.toHaveClass(/opacity-0/);
    await expect(page.locator('#panel-title')).toHaveText(titleText);
  });

  test('open panel for row 1 → click row 2: panel updates to row 2', async ({ page }) => {
    const rows = page.locator('#article-table tr');
    const title1 = (await rows.nth(0).locator('td:nth-child(2)').innerText()).trim();
    const title2 = (await rows.nth(1).locator('td:nth-child(2)').innerText()).trim();

    await rows.nth(0).click();
    await expect(page.locator('#panel-title')).toHaveText(title1);

    await rows.nth(1).click();
    await expect(page.locator('#side-panel')).not.toHaveClass(/opacity-0/);
    await expect(page.locator('#panel-title')).toHaveText(title2);
  });

  test('open panel → click Inspect → push & inspect buttons remain in panel', async ({ page }) => {
    await page.locator('#article-table tr').first().click();
    const panel = page.locator('#side-panel');
    await expect(panel).not.toHaveClass(/opacity-0/);

    const inspectBtn = panel.getByRole('button', { name: /inspect/i });
    const pushBtn    = panel.getByRole('button', { name: /push drafts/i });
    await expect(inspectBtn).toBeVisible();
    await inspectBtn.click();
    await expect(panel).not.toHaveClass(/opacity-0/);
    await expect(pushBtn).toBeVisible();
  });

  test('open panel → click Push drafts → panel stays open', async ({ page }) => {
    await page.locator('#article-table tr').first().click();
    const panel = page.locator('#side-panel');
    await panel.getByRole('button', { name: /push drafts/i }).click();
    await expect(panel).not.toHaveClass(/opacity-0/);
    await expect(page.locator('#panel-destinations')).not.toBeEmpty();
  });

  test('click three rows in sequence: panel titles follow each click', async ({ page }) => {
    const rows = page.locator('#article-table tr');
    const count = await rows.count();
    const n = Math.min(count, 3);

    for (let i = 0; i < n; i++) {
      const expected = (await rows.nth(i).locator('td:nth-child(2)').innerText()).trim();
      await rows.nth(i).click();
      await expect(page.locator('#panel-title')).toHaveText(expected);
    }
  });

  /**
   * [contract] COMBINATION: search then click a result row.
   *
   * BACKEND:
   *   1. GET /api/articles?q=postgres   — on search input
   *   2. Row data comes from the list cache; panel opens without extra GET /:id
   */
  test('[contract] search then click row: emits search call then row-select opens panel', async ({ page }) => {
    const searchReqPromise = page.waitForRequest(
      r => r.url().includes('/api/articles') && r.url().includes('q=postgres'),
      { timeout: 5000 }
    );
    await page.locator('input[placeholder*="Search"]').fill('postgres');
    await searchReqPromise;

    await waitForTable(page);
    await page.locator('#article-table tr').first().click();

    await expect(page.locator('#side-panel')).not.toHaveClass(/opacity-0/);
    const panelTitle = (await page.locator('#panel-title').innerText()).trim();
    expect(panelTitle.length).toBeGreaterThan(0);
  });

  /**
   * [contract] COMBINATION: status filter + platform filter combined.
   *
   * BACKEND:
   *   GET /api/articles?status=error&platform=medium
   */
  test('[contract] status filter + platform filter: combined query params', async ({ page }) => {
    await page.getByRole('button', { name: /^Error$/i }).click();
    await page.waitForTimeout(100);

    const combinedReqPromise = page.waitForRequest(
      r => r.url().includes('status=error') && r.url().includes('platform=medium'),
      { timeout: 5000 }
    );
    await page.getByRole('button', { name: /^Medium$/i }).click();
    const req = await combinedReqPromise;
    expect(req.url()).toContain('status=error');
    expect(req.url()).toContain('platform=medium');
  });

  /**
   * [contract] COMBINATION: search + filter together, then clear search.
   *
   * BACKEND:
   *   1. GET /api/articles?q=postgres&status=error
   *   2. GET /api/articles?status=error   (after clearing search)
   */
  test('[contract] search + filter → clear search: second call drops q param', async ({ page }) => {
    await page.getByRole('button', { name: /^Error$/i }).click();

    const combinedReqPromise = page.waitForRequest(
      r => r.url().includes('q=postgres') && r.url().includes('status=error'),
      { timeout: 5000 }
    );
    await page.locator('input[placeholder*="Search"]').fill('postgres');
    await combinedReqPromise;

    const clearReqPromise = page.waitForRequest(
      r => r.url().includes('/api/articles') &&
           !r.url().includes('q=') &&
           r.url().includes('status=error'),
      { timeout: 5000 }
    );
    await page.locator('input[placeholder*="Search"]').fill('');
    const clearReq = await clearReqPromise;

    expect(clearReq.url()).not.toContain('q=');
    expect(clearReq.url()).toContain('status=error');
  });

  /**
   * [contract] COMBINATION: push drafts → polling → row refresh.
   *
   * BACKEND (in-memory resolves immediately):
   *   1. POST /api/articles/:id/push  → 202 { jobId }
   *   2. GET  /api/jobs/:jobId        → { status: "done" } on first poll (2 s)
   *   3. GET  /api/articles           → refreshed list
   */
  test('[contract] push drafts → polling → row refresh', async ({ page }) => {
    const requests = [];
    page.on('request', r => {
      if (r.url().includes('/api/')) requests.push({ method: r.method(), url: r.url() });
    });

    await page.locator('#article-table tr').first().click();
    await page.getByRole('button', { name: /push drafts/i }).click();

    // Wait long enough for push + 1 poll cycle (2 s) + refresh
    await page.waitForTimeout(3500);

    const pushReq = requests.find(r => r.url.includes('/push') && r.method === 'POST');
    expect(pushReq).toBeDefined();
    expect(pushReq.url).toMatch(/\/api\/articles\/.+\/push/);

    const jobReq = requests.find(r => r.url.includes('/api/jobs/'));
    expect(jobReq).toBeDefined();
  });

  /**
   * [contract] COMBINATION: inspect → gate cell updates after job resolves.
   *
   * BACKEND:
   *   POST /api/articles/:id/inspect → 202
   *   GET  /api/jobs/:jobId          → done (poll 1)
   *   GET  /api/articles             → gate updated in refreshed row
   */
  test('[contract] inspect → gate cell updates after job resolves', async ({ page }) => {
    const firstRow = page.locator('#article-table tr').first();

    await firstRow.click();
    await page.getByRole('button', { name: /inspect/i }).click();

    // Wait for inspect + poll + list refresh
    await page.waitForTimeout(3500);

    const gateAfter = (await firstRow.locator('td:last-child').innerText()).trim();
    // Backend sets gate to "pass" (word_count ≥ 500) or "warn"
    expect(gateAfter).toMatch(/Pass|Warn/i);
  });
});
