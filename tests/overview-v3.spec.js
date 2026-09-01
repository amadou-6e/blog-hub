const { test, expect } = require('@playwright/test');
const SidebarState = require('../screens/overview/sidebar-state.js');

const OVERVIEW_URL = '/screens/overview/v3.html';

async function seedArticles(page, count, prefix = 'Filter lifecycle filler') {
  for (let index = 0; index < count; index += 1) {
    const response = await page.request.post('/api/articles', {
      data: { title: `${prefix} ${String(index).padStart(4, '0')}` },
    });
    expect(response.ok()).toBeTruthy();
  }
}

async function visibleCardIds(page) {
  return page.locator('.article-card').evaluateAll(cards => cards.map(card => card.dataset.id));
}
test.describe('Overview sidebar state unit logic', () => {
  test('normalizes missing and partial destinations as unavailable', () => {
    const destinations = SidebarState.normalizeDestinations({
      medium: { status: 'draft', label: '' },
      hashnode: { status: 'unknown', label: '<b>remote</b>' },
    });

    expect(destinations.medium).toMatchObject({ status: 'draft', label: 'Draft' });
    expect(destinations.hashnode).toMatchObject({ status: 'none', label: 'Unavailable' });
    expect(destinations.devto).toMatchObject({ status: 'none', label: 'Unavailable' });
  });

  test('resolves selection only from the current collection', () => {
    const first = { id: 'first' };
    const second = { id: 'second' };

    expect(SidebarState.selectedArticle([first, second], 'second')).toBe(second);
    expect(SidebarState.selectedArticle([first], 'second')).toBeNull();
    expect(SidebarState.selectedArticle([], 'second')).toBeNull();
  });

  test('derives explicit empty and active-job panel states', () => {
    const article = {
      id: 'article-1',
      title: '',
      destinations: {},
      timeline: null,
      action: { kind: 'push', label: 'Push drafts \u2192', bg: '#6366f1' },
    };

    const idle = SidebarState.panelModel(article, null);
    expect(idle.title).toBe('Untitled article');
    expect(idle.timeline).toEqual([]);
    expect(idle.destinations.every(item => item.label === 'Unavailable')).toBe(true);

    const busy = SidebarState.panelModel(article, 'inspect');
    expect(busy.primaryAction).toMatchObject({ label: 'Inspecting\u2026', disabled: true });
    expect(busy.inspectDisabled).toBe(true);
  });
});

test.describe('Current overview screen', () => {
  test.beforeEach(async ({ page }) => {
    const reset = await page.request.post('/api/dev/reset');
    expect(reset.ok()).toBeTruthy();
    await page.goto(OVERVIEW_URL);
    await expect(page.locator('#article-count')).not.toHaveText('— articles');
  });

  test('renders article cards from the backend', async ({ page }) => {
    await expect(page.locator('.article-card')).not.toHaveCount(0);
    await expect(page.locator('.article-card-title').first()).not.toBeEmpty();
  });

  test('requests a remote sync when Overview reloads', async ({ page }) => {
    let refreshRequests = 0;
    await page.route('**/api/jobs/sync-refresh', async route => {
      refreshRequests += 1;
      await route.fulfill({ json: { jobs: [], count: 0 } });
    });

    await page.reload();
    await expect.poll(() => refreshRequests).toBe(1);
  });

  test('shows all platform preview tabs on each card', async ({ page }) => {
    const firstCard = page.locator('.article-card').first();
    await expect(firstCard.locator('.plat-tab')).toHaveCount(3);
    await expect(firstCard.locator('.plat-tab')).toHaveText(['Medium', 'Hashnode', 'Dev.to']);
  });

  test('filters cards by title without losing the matching article', async ({ page }) => {
    const firstTitle = await page.locator('.article-card-title').first().innerText();
    await page.locator('#search-input').fill(firstTitle);

    await expect(page.locator('.article-card')).toHaveCount(1);
    await expect(page.locator('.article-card-title')).toHaveText(firstTitle);
  });

  test('debounces rapid search and finds matches beyond the first 100 articles', async ({ page }) => {
    test.setTimeout(60_000);
    const target = await page.request.post('/api/articles', {
      data: { title: 'Unique deep pagination target' },
    });
    expect(target.ok()).toBeTruthy();
    await seedArticles(page, 110);

    let secondPageRequests = 0;
    page.on('request', request => {
      if (request.url().includes('/api/articles?') && request.url().includes('page=2')) {
        secondPageRequests += 1;
      }
    });

    await page.reload();
    await expect(page.locator('.article-card')).toHaveCount(100);
    await page.locator('#search-input').pressSequentially('Unique deep pagination target', { delay: 4 });

    await expect(page.locator('.article-card')).toHaveCount(1);
    await expect(page.locator('.article-card-title')).toHaveText('Unique deep pagination target');
    await expect(page.locator('#article-count')).toHaveText('1 article');
    expect(secondPageRequests).toBe(1);
  });

  test('settled search clears selection and Escape restores only the results', async ({ page }) => {
    const card = page.locator('.article-card').first();
    await card.locator('.article-card-title').click();
    await expect(page.locator('#side-panel')).not.toHaveClass(/hidden/);

    const input = page.locator('#search-input');
    await input.fill('no article has this title');
    await expect(page.locator('#no-results')).toBeVisible();
    await expect(page.locator('#article-count')).toHaveText('0 articles');
    await expect(page.locator('#side-panel')).toHaveClass(/hidden/);
    expect(await page.evaluate(() => selectedId)).toBeNull();

    await input.press('Escape');
    await expect(input).toHaveValue('');
    await expect(page.locator('.article-card')).toHaveCount(6);
    await expect(page.locator('.article-card.selected')).toHaveCount(0);
    await expect(page.locator('#side-panel')).toHaveClass(/hidden/);
    expect(await page.evaluate(() => selectedId)).toBeNull();
  });

  test('status and platform filters clear excluded selections', async ({ page }) => {
    const published = page.locator('.article-card[data-id="art_003"]');
    await published.locator('.article-card-title').click();
    await expect(page.locator('#side-panel')).not.toHaveClass(/hidden/);

    await page.locator('#sf-drafting').click();
    await expect(page.locator('#side-panel')).toHaveClass(/hidden/);
    expect(await page.evaluate(() => selectedId)).toBeNull();

    await page.locator('#sf-all').click();
    const mediumOnly = page.locator('.article-card[data-id="art_004"]');
    await mediumOnly.locator('.article-card-title').click();
    await expect(page.locator('#side-panel')).not.toHaveClass(/hidden/);

    await page.locator('#pf-hashnode').click();
    await expect(page.locator('#side-panel')).toHaveClass(/hidden/);
    expect(await page.evaluate(() => selectedId)).toBeNull();
  });

  test('keeps status single-select and combines platforms with OR semantics', async ({ page }) => {
    const response = await page.request.get('/api/articles?page=1&pageSize=100');
    const items = (await response.json()).items;

    await page.locator('#sf-drafting').click();
    await page.locator('#sf-ready').click();
    await expect(page.locator('.pill-filter.active')).toHaveCount(1);
    await expect(page.locator('#sf-ready')).toHaveClass(/active/);
    const readyIds = items
      .filter(item => Object.values(item.destinations).some(destination => destination.status === 'ready'))
      .map(item => item.id)
      .sort();
    expect((await visibleCardIds(page)).sort()).toEqual(readyIds);

    await page.locator('#sf-all').click();
    await page.locator('#pf-hashnode').click();
    await page.locator('#pf-devto').click();
    await expect(page.locator('.pill-platform.active')).toHaveCount(2);
    const platformIds = items
      .filter(item => ['hashnode', 'devto'].some(platform => item.destinations[platform].status !== 'none'))
      .map(item => item.id)
      .sort();
    expect((await visibleCardIds(page)).sort()).toEqual(platformIds);
  });

  test('ignores an older page response after a newer search settles', async ({ page }) => {
    test.setTimeout(60_000);
    const target = await page.request.post('/api/articles', {
      data: { title: 'Newest settled query target' },
    });
    expect(target.ok()).toBeTruthy();
    await seedArticles(page, 110, 'Older query filler');
    await page.reload();
    await expect(page.locator('#load-more-status')).toHaveText('Showing 100 of 117 articles', { timeout: 15_000 });
    await expect(page.locator('.article-card')).toHaveCount(100);

    let delayed = false;
    await page.route('**/api/articles?**', async route => {
      if (!delayed && route.request().url().includes('page=2')) {
        delayed = true;
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      try {
        await route.continue();
      } catch (error) {
        // An AbortController may retire the superseded request before continue().
      }
    });

    const input = page.locator('#search-input');
    await input.fill('Older query filler');
    await page.waitForRequest(request => request.url().includes('/api/articles?') && request.url().includes('page=2'));
    await input.fill('Newest settled query target');

    await expect(page.locator('.article-card')).toHaveCount(1);
    await expect(page.locator('.article-card-title')).toHaveText('Newest settled query target');
    await expect(page.locator('#article-count')).toHaveText('1 article');
    await page.unroute('**/api/articles?**');
  });

  test('treats an aborted overview reload as a superseded request', async ({ page }) => {
    const article = await page.evaluate(() => ARTICLES[0]);
    let articleRequests = 0;
    await page.route('**/api/articles?**', async route => {
      articleRequests += 1;
      if (articleRequests === 1) {
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      try {
        await route.fulfill({ json: { items: [article], total: 1 } });
      } catch (error) {
        // The first routed request can be retired before its delayed response.
      }
    });
    await page.route('**/api/connections', route => route.fulfill({ json: { connections: [] } }));

    await page.evaluate(() => {
      window.firstOverviewReload = loadOverview();
    });
    await expect.poll(() => articleRequests).toBe(1);
    const results = await page.evaluate(() => Promise.allSettled([
      window.firstOverviewReload,
      loadOverview(),
    ]));

    expect(results.map(result => result.status)).toEqual(['fulfilled', 'fulfilled']);
    await expect(page.locator('.article-card')).not.toHaveCount(0);
    expect(articleRequests).toBeGreaterThanOrEqual(2);
  });

  test('opens the selected article in the editor', async ({ page }) => {
    await page.locator('.article-card').first().locator('.card-edit').click();
    await expect(page).toHaveURL(/\/screens\/editor\/v2\.html\?id=/);
  });

  test('does not reload articles when recovery finds no active job', async ({ page }) => {
    let articleReloads = 0;
    page.on('request', request => {
      if (request.url().includes('/api/articles?')) articleReloads += 1;
    });
    await page.route('**/api/jobs?article_id=*&active=true&limit=10', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ jobs: [] }),
    }));

    const recovery = page.waitForResponse(
      response => response.url().includes('/api/jobs?article_id=')
    );
    await page.locator('.article-card').first().click();
    await recovery;

    expect(articleReloads).toBe(0);
    await expect(page.locator('#panel-job-region')).toBeHidden();
  });

  test('stops an abandoned job poller when switching cards', async ({ page }) => {
    const cards = page.locator('.article-card');
    const firstId = await cards.nth(0).getAttribute('data-id');
    const secondId = await cards.nth(1).getAttribute('data-id');
    await page.route('**/api/jobs?article_id=*&active=true&limit=10', route => {
      const articleId = new URL(route.request().url()).searchParams.get('article_id');
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: articleId === firstId ? [{
          jobId: 'job_switch', articleId: firstId, operation: 'push', status: 'running',
          pollUrl: '/api/jobs/job_switch', pollAfterMs: 5000, retryable: false,
        }] : [] }),
      });
    });

    await cards.nth(0).click();
    await expect(page.locator('#panel-job-title')).toHaveText('Running');
    expect(await page.evaluate(id => jobLifecycle.pollTokens.has(id), firstId)).toBe(true);

    await cards.nth(1).click();
    await expect.poll(() => page.evaluate(id => ({
      state: jobLifecycle.state(id),
      polling: jobLifecycle.pollTokens.has(id),
    }), firstId)).toEqual({ state: null, polling: false });
    expect(secondId).not.toBe(firstId);
  });

  test('marks unavailable scheduling as disabled', async ({ page }) => {
    const articleId = await page.evaluate(() => {
      const article = ARTICLES[0];
      article.action = {
        ...article.action,
        kind: 'schedule',
        label: 'Schedule →',
      };
      render();
      return article.id;
    });

    await page.locator(`.article-card[data-id="${articleId}"]`).click();
    await expect(page.locator('#panel-primary-btn')).toBeDisabled();
    await expect(page.locator('#panel-primary-btn')).toHaveAttribute(
      'title', 'Publishing queue is not available yet'
    );
  });

  test('submits one inspection and prevents duplicate actions while queued', async ({ page }) => {
    let submissions = 0;
    await page.route('**/api/articles/*/inspect', async route => {
      submissions += 1;
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          jobId: 'job_inspect_once', status: 'queued',
          pollUrl: '/api/jobs/job_inspect_once', pollAfterMs: 5000,
        }),
      });
    });
    await page.route('**/api/jobs/job_inspect_once', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_inspect_once', operation: 'inspect', status: 'queued',
        pollUrl: '/api/jobs/job_inspect_once', pollAfterMs: 5000,
      }),
    }));

    await page.locator('.article-card').first().click();
    const inspect = page.locator('#panel-inspect-btn');
    await inspect.click();
    await inspect.click({ force: true });

    await expect(page.locator('#panel-job-title')).toHaveText('Queued');
    await expect(inspect).toBeDisabled();
    expect(submissions).toBe(1);
  });

  test('recovers a running job after reload and supports durable cancel and retry', async ({ page }) => {
    await page.locator('.article-card').first().click();
    const articleId = await page.locator('.article-card').first().getAttribute('data-id');
    let recoveryRequests = 0;
    await page.route('**/api/jobs?article_id=*&active=true&limit=10', route => {
      recoveryRequests += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [{
          jobId: 'job_recovered', articleId, operation: 'push', status: 'running',
          pollUrl: '/api/jobs/job_recovered', pollAfterMs: 5000, retryable: false,
        }] }),
      });
    });
    await page.route('**/api/jobs/job_recovered', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_recovered', articleId, operation: 'push', status: 'running',
        pollUrl: '/api/jobs/job_recovered', pollAfterMs: 5000, retryable: false,
      }),
    }));
    await page.route('**/api/jobs/job_recovered/cancel', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_recovered', articleId, operation: 'push', status: 'canceled',
        pollUrl: '/api/jobs/job_recovered', pollAfterMs: 5000,
        retryable: true, error: 'Canceled by user',
      }),
    }));
    await page.route('**/api/jobs/job_recovered/retry', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_recovered', articleId, operation: 'push', status: 'queued',
        pollUrl: '/api/jobs/job_recovered', pollAfterMs: 5000, retryable: false,
      }),
    }));

    await page.reload();
    await page.locator('.article-card').first().waitFor();
    await expect(page.locator('#panel-job-title')).toHaveText('Running');
    expect(recoveryRequests).toBe(1);

    await page.locator('#panel-cancel-job-btn').click();
    await expect(page.locator('#panel-job-title')).toHaveText('Canceled');
    await expect(page.locator('#panel-job-error')).toHaveText('Canceled by user');
    await page.locator('#panel-retry-job-btn').click();
    await expect(page.locator('#panel-job-title')).toHaveText('Queued');
  });

  test('shows a backend terminal timeout inline and refreshes after completion', async ({ page }) => {
    let status = 'failed';
    let articleRefreshes = 0;
    page.on('request', request => {
      if (request.method() === 'GET' && /\/api\/articles\?/.test(request.url())) articleRefreshes += 1;
    });
    await page.route('**/api/articles/*/inspect', route => route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_timeout', status: 'queued',
        pollUrl: '/api/jobs/job_timeout', pollAfterMs: 10,
      }),
    }));
    await page.route('**/api/jobs/job_timeout', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_timeout', operation: 'inspect', status,
        pollUrl: '/api/jobs/job_timeout', pollAfterMs: 10,
        retryable: true,
        error: status === 'failed' ? 'Job exceeded its 60 second backend timeout' : null,
      }),
    }));
    await page.route('**/api/jobs/job_timeout/retry', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        jobId: 'job_timeout', operation: 'inspect', status: 'queued',
        pollUrl: '/api/jobs/job_timeout', pollAfterMs: 10, retryable: false,
      }),
    }));

    await page.locator('.article-card').first().click();
    await page.locator('#panel-inspect-btn').click();
    await expect(page.locator('#panel-job-title')).toHaveText('Action failed');
    await expect(page.locator('#panel-job-error')).toContainText('backend timeout');

    status = 'completed';
    await page.locator('#panel-retry-job-btn').click();
    await expect(page.locator('#panel-job-region')).toBeHidden();
    expect(articleRefreshes).toBeGreaterThan(0);
  });

  test('renders all gate states and keeps Pending passive', async ({ page }) => {
    await expect(page.locator('.card-gate[data-state="pass"]')).toHaveCount(3);
    await expect(page.locator('.card-gate[data-state="warn"]')).toHaveCount(1);
    await expect(page.locator('.card-gate[data-state="fail"]')).toHaveCount(1);
    const pending = page.locator('.card-gate[data-state="pending"]');
    await expect(pending).toHaveCount(1);
    await expect(pending).toHaveText('PENDING');
    await expect(pending).not.toHaveAttribute('role', 'button');
  });

  test('gate keyboard activation opens Inspection without selecting the card', async ({ page }) => {
    const card = page.locator('.article-card[data-id="art_001"]');
    await card.locator('.card-gate').press('Enter');

    await expect(page).toHaveURL(/\/screens\/inspection\/v1\.html\?id=art_001$/);
  });

  test('context menu supports keyboard open, Escape, and focus restoration', async ({ page }) => {
    const trigger = page.locator('.article-card[data-id="art_001"] .card-context-trigger');
    await trigger.focus();
    await trigger.press('Enter');
    await expect(page.getByRole('menu')).toBeVisible();
    await expect(page.getByRole('menuitem')).toHaveCount(4);
    await page.keyboard.press('ArrowDown');
    await expect(page.getByRole('menuitem', { name: 'Duplicate' })).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('menu')).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test('outside click closes the context menu', async ({ page }) => {
    const trigger = page.locator('.article-card[data-id="art_001"] .card-context-trigger');
    await trigger.click();
    await expect(page.getByRole('menu')).toBeVisible();

    await page.locator('#article-count').click();
    await expect(page.getByRole('menu')).toHaveCount(0);
  });

  test('context Edit opens the correct article', async ({ page }) => {
    await page.locator('.article-card[data-id="art_002"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Edit' }).click();

    await expect(page).toHaveURL(/\/screens\/editor\/v2\.html\?id=art_002$/);
  });

  test('Duplicate creates and selects exactly one copy', async ({ page }) => {
    await page.locator('.article-card[data-id="art_001"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Duplicate' }).click();

    const copies = page.locator('.article-card', { hasText: 'Copy of Building a Vector DB' });
    await expect(copies).toHaveCount(1);
    await expect(copies).toHaveClass(/selected/);
  });

  test('Archive removes the article from active results and active APIs', async ({ page }) => {
    let idempotencyKey = null;
    page.on('request', request => {
      if (request.url().endsWith('/api/articles/art_004/archive')) {
        idempotencyKey = request.headers()['idempotency-key'];
      }
    });
    await page.locator('.article-card[data-id="art_004"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();

    await expect(page.locator('.article-card[data-id="art_004"]')).toHaveCount(0);
    const retained = await page.request.get('/api/articles/art_004');
    expect(retained.status()).toBe(404);
    expect(idempotencyKey).toBeTruthy();
  });

  test('Delete uses inline confirmation and Cancel sends no request', async ({ page }) => {
    let deleteRequests = 0;
    page.on('request', request => {
      if (request.method() === 'DELETE' && request.url().endsWith('/api/articles/art_004')) {
        deleteRequests += 1;
      }
    });
    await page.locator('.article-card[data-id="art_004"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Delete' }).click();
    await expect(page.getByRole('group', { name: /Delete Graph Neural Networks/ })).toBeVisible();

    await page.locator('.card-delete-cancel').click();
    await expect(page.getByRole('menu')).toBeVisible();
    expect(deleteRequests).toBe(0);
  });

  test('confirmed Delete removes an unpublished article', async ({ page }) => {
    let idempotencyKey = null;
    page.on('request', request => {
      if (request.method() === 'DELETE' && request.url().endsWith('/api/articles/art_004')) {
        idempotencyKey = request.headers()['idempotency-key'];
      }
    });
    await page.locator('.article-card[data-id="art_004"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Delete' }).click();
    await page.locator('.card-delete-confirm').click();

    await expect(page.locator('.article-card[data-id="art_004"]')).toHaveCount(0);
    expect((await page.request.get('/api/articles/art_004')).status()).toBe(404);
    expect(idempotencyKey).toBeTruthy();
  });

  test('published delete conflict remains inline and preserves the article', async ({ page }) => {
    const card = page.locator('.article-card[data-id="art_003"]');
    await card.locator('.card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Delete' }).click();
    await page.locator('.card-delete-confirm').click();

    await expect(card.getByRole('alert')).toContainText('Cannot delete published article');
    await expect(card).toBeVisible();
    await page.locator('#article-count').click();
    await expect(card.getByRole('alert')).toBeVisible();
  });

  test('mutation 404 remains inline on the affected card', async ({ page }) => {
    await page.route('**/api/articles/art_002/duplicate', route => route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { error: 'not_found', message: 'Article not found.' } }),
    }));
    const card = page.locator('.article-card[data-id="art_002"]');
    await card.locator('.card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Duplicate' }).click();

    await expect(card.getByRole('alert')).toContainText('Article not found');
  });

  test('refreshes selected details after an article action completes', async ({ page }) => {
    const firstCard = page.locator('.article-card').first();
    const articleId = await firstCard.getAttribute('data-id');
    await firstCard.click();
    const originalTitle = await page.locator('#panel-title').innerText();

    const originalPayload = await page.request.get('/api/articles?sortBy=updatedAt&sortDir=desc&page=1&pageSize=100');
    const refreshed = await originalPayload.json();
    const selected = refreshed.items.find(item => item.id === articleId);
    selected.title = `${originalTitle} refreshed`;
    selected.destinations.medium = { status: 'published', label: 'Published now', url: 'https://medium.com/test' };
    selected.recentTimeline = [{ timestamp: '2026-08-29T12:00:00Z', event: 'Published to Medium' }];

    await page.route(`**/api/articles/${articleId}/inspect`, route => route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ jobId: 'job-sidebar-refresh', status: 'queued' }),
    }));
    let pollCount = 0;
    await page.route('**/api/jobs/job-sidebar-refresh', route => {
      pollCount += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: pollCount === 1 ? 'running' : 'completed' }),
      });
    });
    await page.route('**/api/articles?*', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(refreshed),
    }));

    await page.locator('#panel-inspect-btn').click();
    await expect(page.locator('#panel-primary-btn')).toHaveText('Inspecting\u2026');
    await expect(page.locator('#panel-primary-btn')).toBeDisabled();

    await expect(page.locator('#panel-title')).toHaveText(`${originalTitle} refreshed`);
    await expect(page.locator('#panel-destinations')).toContainText('Published now');
    await expect(page.locator('#panel-timeline')).toContainText('Published to Medium');
    await expect(page.locator(`.article-card[data-id="${articleId}"] .article-card-title`))
      .toHaveText(`${originalTitle} refreshed`);
  });

  test('switches every sidebar field to the newly selected article', async ({ page }) => {
    const cards = page.locator('.article-card');
    const firstTitle = await cards.nth(0).locator('.article-card-title').innerText();
    const secondTitle = await cards.nth(1).locator('.article-card-title').innerText();

    await cards.nth(0).click();
    const firstDestinations = await page.locator('#panel-destinations').innerText();
    const firstTimeline = await page.locator('#panel-timeline').innerText();
    await expect(page.locator('#panel-title')).toHaveText(firstTitle);

    await cards.nth(1).click();
    await expect(page.locator('#panel-title')).toHaveText(secondTitle);
    await expect(page.locator('#panel-title')).not.toHaveText(firstTitle);
    expect(await page.locator('#panel-destinations').innerText()).not.toBe(firstDestinations);
    expect(await page.locator('#panel-timeline').innerText()).not.toBe(firstTimeline);
  });

  test('renders remote sidebar text safely and handles partial article data', async ({ page }) => {
    const payload = {
      items: [{
        id: 'partial-article',
        title: 'Partial article',
        updatedAt: '2026-08-29T12:00:00Z',
        wordCount: 0,
        gate: 'pending',
        destinations: {
          medium: { status: 'draft', label: '<img src=x onerror="window.sidebarInjected=true">' },
        },
        recentTimeline: [{
          timestamp: '2026-08-29T12:00:00Z',
          event: '<svg onload="window.sidebarInjected=true"></svg>',
        }],
      }],
      total: 1,
      page: 1,
      pageSize: 100,
    };
    await page.route('**/api/articles?*', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    }));

    await page.reload();
    await expect(page.locator('#article-count')).toHaveText('1 article');
    await page.locator('.article-card').click();

    await expect(page.locator('#panel-destinations')).toContainText('<img src=x');
    await expect(page.locator('#panel-destinations')).toContainText('Unavailable');
    await expect(page.locator('#panel-timeline')).toContainText('<svg onload=');
    await expect(page.locator('#panel-destinations img')).toHaveCount(0);
    await expect(page.locator('#panel-timeline svg')).toHaveCount(0);
    expect(await page.evaluate(() => window.sidebarInjected)).toBeUndefined();
  });

  test('shows an explicit empty timeline and clears removed selections', async ({ page }) => {
    const firstCard = page.locator('.article-card').first();
    await firstCard.click();
    await page.evaluate(() => {
      ARTICLES[0].timeline = [];
      render();
    });
    await expect(page.locator('#panel-timeline')).toHaveText('No activity yet.');

    await page.evaluate(() => {
      ARTICLES = ARTICLES.filter(article => article.id !== selectedId);
      render();
    });
    await expect(page.locator('#side-panel')).toHaveClass(/hidden/);
    expect(await page.evaluate(() => selectedId)).toBeNull();
  });

  test('OV-S14 clears selection when filtering excludes the selected article', async ({ page }) => {
    const firstCard = page.locator('.article-card').first();
    await firstCard.click();
    await expect(page.locator('#side-panel')).not.toHaveClass(/hidden/);

    await page.locator('#search-input').fill('definitely no matching article');

    await expect(page.locator('.article-card')).toHaveCount(0);
    await expect(page.locator('#side-panel')).toHaveClass(/hidden/);
    await expect(page.locator('#panel-title')).toHaveText('');
    expect(await page.evaluate(() => selectedId)).toBeNull();
  });

  test('keeps Articles active without faking another active tab', async ({ page }) => {
    const originalUrl = page.url();

    await page.locator('#nav-articles').press('Enter');

    await expect(page).toHaveURL(originalUrl);
    await expect(page.locator('#nav-articles')).toHaveCSS('border-bottom-color', 'rgb(99, 102, 241)');
    await expect(page.locator('#nav-platforms')).toHaveCSS('border-bottom-color', 'rgba(0, 0, 0, 0)');
  });

  test('opens the Platforms section in Settings', async ({ page }) => {
    await page.locator('#nav-platforms').click();

    await expect(page).toHaveURL(/\/screens\/settings\/v2\.html\?section=platforms$/);
    await expect(page.locator('#section-platforms')).toBeVisible();
    await expect(page.locator('.nav-btn[data-section="platforms"]')).toHaveClass(/active/);
  });

  test('opens Settings with keyboard activation', async ({ page }) => {
    await page.locator('#nav-settings').press('Enter');

    await expect(page).toHaveURL(/\/screens\/settings\/v2\.html$/);
  });

  test('ignores an invalid Settings section without breaking initialization', async ({ page }) => {
    await page.goto('/screens/settings/v2.html?section=x%22%5D');

    await expect(page.getByRole('heading', { name: 'Publishing Platforms' })).toBeVisible();
    await expect(page.locator('.nav-btn[data-section="platforms"]')).toHaveClass(/active/);
  });

  test('shows unavailable queue actions as disabled controls', async ({ page }) => {
    await expect(page.locator('#nav-queue')).toBeDisabled();
    await expect(page.locator('#panel-schedule-btn')).toBeDisabled();

    const scheduledArticleId = await page.evaluate(() =>
      ARTICLES.find(article => article.action.kind === 'schedule')?.id || null
    );
    expect(scheduledArticleId).not.toBeNull();
    await page.locator(`.article-card[data-id="${scheduledArticleId}"]`).click();
    await expect(page.locator('#panel-primary-btn')).toBeDisabled();
    await expect(page.locator('#panel-primary-btn')).toHaveText('Schedule →');
  });

  test('panel Edit opens the selected article and preserves its identifier', async ({ page }) => {
    const card = page.locator('.article-card').first();
    const articleId = await card.getAttribute('data-id');
    await card.click();

    await page.locator('#panel-edit-btn').press('Enter');

    await expect(page).toHaveURL(/\/screens\/editor\/v2\.html\?id=/);
    expect(new URL(page.url()).searchParams.get('id')).toBe(articleId);
  });

  test('editor destinations encode article identifiers safely', async ({ page }) => {
    const destination = await page.evaluate(() => articleEditorUrl('article / ? & value'));
    const parsed = new URL(destination, page.url());

    expect(parsed.pathname).toBe('/screens/editor/v2.html');
    expect(parsed.searchParams.get('id')).toBe('article / ? & value');
  });
});
