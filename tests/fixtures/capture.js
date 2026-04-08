/**
 * capture.js — Playwright fixture that intercepts all fetch/XHR calls made by
 * the page and records them.  Tests assert on the captured calls to verify
 * which backend endpoints the UI is expected to hit and with what shape.
 *
 * Usage:
 *   const { test, expect } = require('../fixtures/capture');
 *   // captured calls are in test's `captured` fixture
 */

const { test: base, expect } = require('@playwright/test');

/**
 * @typedef {{ method: string, url: string, body: any, status: number, response: any }} ApiCall
 */

exports.test = base.extend({
  /**
   * `captured` — array of API calls made during the test.
   * Populated automatically; read it after interactions.
   */
  captured: async ({ page }, use) => {
    /** @type {ApiCall[]} */
    const calls = [];

    // Intercept every request that looks like an API call.
    // The overview HTML uses mock data only, so we also intercept calls the
    // *real* implementation would make and route them through a stub that
    // records the intent and returns a neutral response.
    await page.route('**/api/**', async (route) => {
      const req = route.request();
      let body = null;
      try { body = JSON.parse(req.postData() || 'null'); } catch { body = req.postData(); }

      // Fulfil with a minimal stub so the UI doesn't crash if it checks status.
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ _stub: true }),
      });

      calls.push({
        method: req.method(),
        url: req.url(),
        body,
        status: 200,
        response: { _stub: true },
      });
    });

    await use(calls);
  },
});

exports.expect = expect;
