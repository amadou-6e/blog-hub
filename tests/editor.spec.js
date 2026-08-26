const { test, expect } = require('@playwright/test');

test.describe('Article editor reconciliation', () => {
  test('shows and resolves a remote content conflict', async ({ page }) => {
    const conflict = {
      id: 'recon_test',
      articleId: 'art_001',
      platform: 'medium',
      remoteId: 'medium-1',
      localRevisionId: 'rev_local',
      currentRevisionId: 'rev_local',
      baselineFingerprint: 'sha256:base',
      localFingerprint: 'sha256:local',
      remoteFingerprint: 'sha256:remote',
      availability: 'available',
      syncState: 'conflict',
      remoteTitle: 'Remote title',
      remoteContent: '# Remote title\n\nRemote edit.',
      canonicalUrl: null,
      remoteUrl: 'https://medium.com/p/medium-1/edit',
      remoteStatus: 'draft',
      remoteUpdatedAt: '2026-08-23T08:00:00Z',
      metadata: {},
      error: null,
      observedAt: '2026-08-23T08:01:00Z',
    };
    await page.route('**/api/articles/art_001/reconciliation', route => route.fulfill({
      json: { comparisons: [conflict] },
    }));
    await page.route('**/api/articles/art_001/reconciliation/medium/resolve', async route => {
      const request = route.request();
      expect(request.method()).toBe('POST');
      expect(request.postDataJSON().action).toBe('keep_local');
      conflict.syncState = 'local_ahead';
      await route.fulfill({ json: conflict });
    });

    await page.goto('/screens/editor/v2.html?id=art_001');

    const panel = page.locator('#abody-reconciliation');
    await expect(panel).toBeVisible();
    await expect(panel.getByText('Conflict', { exact: true })).toBeVisible();
    await expect(panel.getByText('# Remote title')).toBeVisible();
    const useRemote = panel.getByRole('button', { name: 'Use remote' });
    await expect(useRemote).toBeVisible();
    const buttonBox = await useRemote.boundingBox();
    expect(buttonBox.y + buttonBox.height).toBeLessThanOrEqual(720);
    await panel.getByRole('button', { name: 'Keep local' }).click();
    await expect(panel.getByText('Local changes', { exact: true })).toBeVisible();
  });
});
