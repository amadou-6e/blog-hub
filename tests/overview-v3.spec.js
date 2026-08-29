const { test, expect } = require('@playwright/test');

const OVERVIEW_URL = '/screens/overview/v3.html';

test.describe('Current overview screen', () => {
  test.beforeEach(async ({ page }) => {
    const reset = await page.request.post('/api/dev/reset');
    expect(reset.ok()).toBeTruthy();
    await page.goto(OVERVIEW_URL);
    await page.locator('.article-card').first().waitFor();
  });

  test('renders article cards from the backend', async ({ page }) => {
    await expect(page.locator('.article-card')).not.toHaveCount(0);
    await expect(page.locator('.article-card-title').first()).not.toBeEmpty();
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

  test('opens the selected article in the editor', async ({ page }) => {
    await page.locator('.article-card').first().locator('.card-edit').click();
    await expect(page).toHaveURL(/\/screens\/editor\/v2\.html\?id=/);
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
});
