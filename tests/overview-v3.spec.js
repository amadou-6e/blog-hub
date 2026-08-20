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
});
