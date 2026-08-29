const { test, expect } = require('@playwright/test');
const SidebarState = require('../screens/overview/sidebar-state.js');

const OVERVIEW_URL = '/screens/overview/v3.html';

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
