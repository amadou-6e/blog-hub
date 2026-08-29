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
