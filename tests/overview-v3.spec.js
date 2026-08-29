const { test, expect } = require('@playwright/test');

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

  test('opens the selected article in the editor', async ({ page }) => {
    await page.locator('.article-card').first().locator('.card-edit').click();
    await expect(page).toHaveURL(/\/screens\/editor\/v2\.html\?id=/);
  });
});
