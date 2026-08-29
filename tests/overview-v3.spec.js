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

  test('Archive removes the article from active results while retaining it in storage', async ({ page }) => {
    await page.locator('.article-card[data-id="art_004"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();

    await expect(page.locator('.article-card[data-id="art_004"]')).toHaveCount(0);
    const retained = await page.request.get('/api/articles/art_004');
    expect(retained.ok()).toBeTruthy();
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
    await page.locator('.article-card[data-id="art_004"] .card-context-trigger').click();
    await page.getByRole('menuitem', { name: 'Delete' }).click();
    await page.locator('.card-delete-confirm').click();

    await expect(page.locator('.article-card[data-id="art_004"]')).toHaveCount(0);
    expect((await page.request.get('/api/articles/art_004')).status()).toBe(404);
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
});
