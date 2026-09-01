/**
 * settings.spec.js — Settings screen integration tests
 *
 * Strategy
 * --------
 * Tests run against a live FastAPI backend (started via playwright.config.js
 * webServer) serving screens/settings/v2.html as a real HTTP page.
 *
 * Each test:
 *  1. Calls POST /api/dev/reset in beforeEach so the in-memory store starts
 *     from seed state (all AI providers disconnected).
 *  2. Navigates to v2.html — which fetches real data from /api/connections.
 *  3. Asserts DOM state (visual) or network calls (contract).
 *
 * Claude browser login test:
 *  The cli-runner spawns `claude auth login`, which starts a local HTTP server
 *  on a random port inside Docker and returns a loopback auth URL:
 *    https://claude.ai/oauth/authorize?...&redirect_uri=http://localhost:{PORT}/callback&...
 *  After the user authorizes, the browser tries to redirect to that localhost
 *  URL — which fails (port is inside Docker, unreachable from the host).
 *  The callback URL with code+state is captured from the failed network
 *  request and submitted to /api/connections/anthropic/submit-code.
 *  The runner forwards it to the CLI's internal server, token exchange
 *  succeeds, and the connection shows as Connected.
 */

const { test, expect } = require('@playwright/test');

const SETTINGS_URL = 'http://localhost:8000/screens/settings/v2.html';

// ─── helpers ─────────────────────────────────────────────────────────────────

async function resetStore(page) {
  await page.request.post('http://localhost:8000/api/dev/reset');
}

/** Switch to the AI Providers tab and wait for it to render. */
async function openAiProviders(page) {
  await page.getByRole('button', { name: 'AI Providers' }).click();
  await page.waitForSelector('#ai-wrap-anthropic', { timeout: 5000 });
}

/**
 * Extract the loopback callback URL from the failed network request that
 * results when the browser tries to redirect to http://localhost:{PORT}/callback
 * after the user authorizes on claude.ai.
 *
 * Returns the full URL string, e.g.:
 *   http://localhost:36403/callback?code=...&state=...
 */
async function captureCallbackUrl(page, port) {
  const requests = await page.evaluate(() =>
    performance.getEntriesByType('resource').map(e => e.name)
  );
  // Try performance API first (may not include failed navigations)
  const fromPerf = requests.find(u => u.startsWith(`http://localhost:${port}/callback`));
  if (fromPerf) return fromPerf;

  // Fallback: read the current URL (chrome-error page keeps the failed URL
  // available in the frame's document.URL in some Chromium versions)
  const frameUrl = await page.evaluate(() => document.URL);
  if (frameUrl && frameUrl.startsWith(`http://localhost:${port}/callback`)) return frameUrl;

  return null;
}

// ─── suite ───────────────────────────────────────────────────────────────────

test.describe('Settings screen', () => {
  test.beforeEach(async ({ page }) => {
    await resetStore(page);
    await page.goto(SETTINGS_URL);
  });

  // ── 1. Initial load ─────────────────────────────────────────────────────────

  test('renders platform connections section by default', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Publishing Platforms' })).toBeVisible();
  });

  test('AI Providers tab renders Claude and OpenAI cards', async ({ page }) => {
    await openAiProviders(page);
    await expect(page.locator('#ai-wrap-anthropic')).toBeVisible();
    await expect(page.locator('#ai-wrap-openai')).toBeVisible();
  });

  test('Claude card shows Not configured on fresh store', async ({ page }) => {
    await openAiProviders(page);
    const card = page.locator('#ai-wrap-anthropic');
    await expect(card.getByText('Not configured')).toBeVisible();
  });

  // ── 2. API key flow ─────────────────────────────────────────────────────────

  /**
   * BACKEND CONTRACT:
   *   PUT /api/connections/anthropic  { token: "sk-ant-test" }  → 200 { id, status }
   */
  test('[contract] saving an API key calls PUT /api/connections/anthropic', async ({ page }) => {
    await openAiProviders(page);
    await page.locator('#ai-wrap-anthropic').getByRole('button', { name: 'Add API key' }).click();

    const reqPromise = page.waitForRequest(
      r => r.url().includes('/api/connections/anthropic') && r.method() === 'PUT',
      { timeout: 5000 }
    );
    await page.locator('#key-input-anthropic').fill('sk-ant-test');
    await page.locator('#ai-wrap-anthropic').getByRole('button', { name: 'Save' }).click();
    const req = await reqPromise;

    const body = JSON.parse(req.postData() || '{}');
    expect(body.token).toBe('sk-ant-test');
  });

  test('[contract] connected Hashnode browser profile only offers disconnect', async ({ page }) => {
    await page.route('**/api/connections/hashnode/browser-connection', route => route.fulfill({
      json: {
        platform: 'hashnode',
        status: 'connected',
        authorizationUrl: null,
        verifiedAt: '2026-08-20T08:00:00Z',
        error: null,
      },
    }));
    await page.reload();

    const card = page.locator('#plat-card-hashnode');
    await expect(card.getByRole('button')).toHaveText(['Disconnect']);
    await expect(card.getByText('Refresh login', { exact: true })).toHaveCount(0);
    await expect(card.getByText('Test', { exact: true })).toHaveCount(0);
  });

  test('[contract] connected Medium browser profile only offers disconnect', async ({ page }) => {
    await page.route('**/api/connections/medium/browser-connection', route => route.fulfill({
      json: {
        platform: 'medium',
        status: 'connected',
        authorizationUrl: null,
        verifiedAt: '2026-08-20T08:00:00Z',
        error: null,
      },
    }));
    await page.reload();

    const card = page.locator('#plat-card-medium');
    await expect(card.getByRole('button')).toHaveText(['Disconnect']);
  });

  test('Medium live login finalizes automatically while the tab stays open', async ({ page, context }) => {
    let completeRequests = 0;
    let started = false;
    let completed = false;
    const authorizationUrl = 'http://localhost:8000/health';
    await page.route('**/api/connections/medium/browser-connection/complete', route => {
      completeRequests += 1;
      completed = true;
      return route.fulfill({ json: {
        platform: 'medium', status: 'connected', loginPhase: 'connected', authorizationUrl: null,
      }});
    });
    await page.route('**/api/connections/medium/browser-connection', route => {
      if (route.request().method() === 'GET' && completed) {
        return route.fulfill({ json: {
          platform: 'medium', status: 'connected', loginPhase: 'connected',
          authorizationUrl: null, verifiedAt: '2026-08-20T08:00:00Z', error: null,
        }});
      }
      if (route.request().method() === 'GET' && !started) {
        return route.fulfill({ json: {
          platform: 'medium', status: 'disconnected', loginPhase: 'disconnected',
          authorizationUrl: null, verifiedAt: null, error: null,
        }});
      }
      if (route.request().method() === 'POST') started = true;
      const loginPhase = route.request().method() === 'POST'
        ? 'waiting_for_login' : 'signed_in_pending_save';
      return route.fulfill({
        status: route.request().method() === 'POST' ? 201 : 200,
        json: {
          platform: 'medium', status: 'waiting_for_login', loginPhase,
          authorizationUrl, verifiedAt: null, error: null,
        },
      });
    });
    await page.reload();

    const loginTabPromise = context.waitForEvent('page');
    const card = page.locator('#plat-card-medium');
    await card.getByRole('button', { name: 'Connect' }).click();
    await card.getByRole('button', { name: /Browser login/ }).click();
    const loginTab = await loginTabPromise;
    await loginTab.waitForURL('**/health?*');

    await expect(card.getByText('Connected', { exact: true })).toBeVisible();
    expect(completeRequests).toBe(1);
    expect(loginTab.isClosed()).toBe(false);

    await page.reload();
    await expect(page.locator('#plat-card-medium').getByText(
      'Connected', { exact: true },
    )).toBeVisible();
    await loginTab.close();
  });

  test('a stuck verifying login can be canceled', async ({ page }) => {
    let canceled = false;
    await page.route('**/api/connections/medium/browser-connection', route => {
      if (route.request().method() === 'DELETE') {
        canceled = true;
        return route.fulfill({ json: {
          platform: 'medium', status: 'disconnected', loginPhase: 'disconnected',
        }});
      }
      return route.fulfill({ json: {
        platform: 'medium', status: 'verifying', loginPhase: 'verifying',
        authorizationUrl: null, verifiedAt: null, error: null,
      }});
    });
    await page.reload();

    const card = page.locator('#plat-card-medium');
    await expect(card.getByText('Verifying login', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Cancel' }).click();

    expect(canceled).toBe(true);
    await expect(card.getByText('Not connected', { exact: true })).toBeVisible();
  });

  test('Skyvern confirms automatic handoff and leaves closure to the user', async ({ page }) => {
    test.skip(!process.env.BLOGHUB_SKYVERN_UI_URL, 'Patched Skyvern UI is opt-in.');
    await page.goto('http://localhost:8000/health');
    await page.evaluate(() => {
      window.addEventListener('message', event => {
        if (event.data?.type !== 'bloghub-browser-login-ready') return;
        event.source.postMessage({
          type: 'bloghub-browser-login-state',
          platform: event.data.platform,
          loginPhase: 'signed_in_pending_save',
        }, event.origin);
        setTimeout(() => event.source.postMessage({
          type: 'bloghub-browser-login-state',
          platform: event.data.platform,
          loginPhase: 'connected',
        }, event.origin), 50);
      });
    });
    const skyvernUrl = new URL(
      '/browser-session/pbs_test/stream', process.env.BLOGHUB_SKYVERN_UI_URL,
    );
    skyvernUrl.searchParams.set('purpose', 'medium-login');
    skyvernUrl.searchParams.set('returnOrigin', 'http://localhost:8000');

    const popupPromise = page.waitForEvent('popup');
    await page.evaluate(url => window.open(url, '_blank'), skyvernUrl.href);
    const popup = await popupPromise;
    await expect(popup.getByRole('heading', {
      name: 'Medium connected',
    })).toBeVisible();
    await expect(popup.getByText(
      'Your connection is saved and verified. You can close this tab and return to BlogHub.',
      { exact: true },
    )).toBeVisible();
    expect(popup.isClosed()).toBe(false);

    const closed = popup.waitForEvent('close');
    await popup.getByRole('button', { name: 'Close tab' }).click();
    await closed;
    expect(popup.isClosed()).toBe(true);
  });

  // ── 3. Browser login flow ────────────────────────────────────────────────────

  /**
   * Full Claude browser-login flow (requires live cli-runner on port 8001).
   *
   * Steps:
   *  1. Click "Login with browser" — runner spawns claude auth login, returns
   *     a loopback auth URL (redirect_uri=http://localhost:{PORT}/callback).
   *  2. A new tab opens at claude.ai/oauth/authorize with that redirect_uri.
   *  3. Authorize — claude.ai redirects the browser to the loopback callback URL.
   *  4. The redirect fails (port is inside Docker), but the URL is captured from
   *     the failed network request.
   *  5. The full callback URL is submitted via POST /api/connections/anthropic/submit-code.
   *  6. Poll /api/connections/anthropic/cli-login-status until connected.
   *  7. Assert the card shows Connected.
   */
  test('Claude browser login: full loopback OAuth flow @live', async ({ page, context }) => {
    test.skip(!process.env.BLOGHUB_LIVE_BROWSER_LOGIN, 'Live provider login is opt-in.');

    await openAiProviders(page);

    // Start login — runner spawns claude auth login and returns the loopback URL
    const oauthTabPromise = context.waitForEvent('page');
    await page.locator('#ai-wrap-anthropic').getByRole('button', { name: 'Login with browser' }).click();

    const oauthTab = await oauthTabPromise;
    await oauthTab.waitForLoadState('domcontentloaded');

    // Confirm the redirect_uri is a loopback URL, not platform.claude.com
    const authUrl = new URL(oauthTab.url());
    const redirectUri = authUrl.searchParams.get('redirect_uri');
    expect(redirectUri).toMatch(/^http:\/\/localhost:\d+\/callback$/);

    const callbackPort = new URL(redirectUri).port;

    // Intercept the failed callback redirect before it triggers chrome-error
    const callbackUrlPromise = new Promise((resolve) => {
      oauthTab.on('request', req => {
        const u = req.url();
        if (u.startsWith(`http://localhost:${callbackPort}/callback`)) {
          resolve(u);
        }
      });
    });

    // Authorize (page may already be logged in; button label varies by locale)
    await oauthTab.waitForSelector('button', { timeout: 10000 });
    const authorizeBtn = oauthTab.getByRole('button').filter({ hasText: /authoris|autorisier|allow|grant/i }).first();
    await authorizeBtn.click();

    // Grab the callback URL from the failed redirect
    const callbackUrl = await Promise.race([
      callbackUrlPromise,
      new Promise((_, reject) => setTimeout(() => reject(new Error('callback URL not captured within 15 s')), 15000)),
    ]);

    expect(callbackUrl).toContain('code=');
    expect(callbackUrl).toContain('state=');

    // Submit the callback URL to the backend
    const submitRes = await page.request.post(
      'http://localhost:8000/api/connections/anthropic/submit-code',
      { data: { code: callbackUrl } }
    );
    expect(submitRes.status()).toBe(200);

    // Poll cli-login-status until connected (up to 20 s)
    await expect.poll(
      async () => {
        const r = await page.request.get('http://localhost:8000/api/connections/anthropic/cli-login-status');
        const body = await r.json();
        return body.status;
      },
      { timeout: 20000, intervals: [1000] }
    ).toBe('connected');

    // UI should reflect Connected without a page reload (the poll in the UI updates it)
    await page.bringToFront();
    await expect(
      page.locator('#ai-wrap-anthropic').getByText('Connected')
    ).toBeVisible({ timeout: 10000 });
  });

  // ── 4. Disconnect ────────────────────────────────────────────────────────────

  /**
   * BACKEND CONTRACT:
   *   DELETE /api/connections/anthropic  → 200 { status: "disconnected" }
   */
  test('[contract] Remove button calls DELETE /api/connections/anthropic', async ({ page }) => {
    // Pre-seed a connected state via API
    await page.request.put('http://localhost:8000/api/connections/anthropic', {
      data: { token: 'sk-ant-seed' },
    });
    await page.reload();
    await openAiProviders(page);

    // "Remove" opens a confirmation popover; the confirm button inside also says "Remove"
    await page.locator('#ai-wrap-anthropic').getByRole('button', { name: /^remove$/i }).click();

    const reqPromise = page.waitForRequest(
      r => r.url().includes('/api/connections/anthropic') && r.method() === 'DELETE',
      { timeout: 5000 }
    );
    // Click the confirm button inside the popover (#confirm-anthropic)
    await page.locator('#confirm-anthropic').getByRole('button', { name: /^remove$/i }).click();
    await reqPromise;
  });
});
