import { test, expect } from '../fixtures';
import { CONFIG_HEALTH_CLEAN } from '../fixtures/api-mocks';

// DOCC-5: the config-health chip and frame-wide banner, on two pages that share
// the frame. The fixture's clean route is overridden per test (later routes win).
const PAGES = ['/dashboard', '/screener/step-1-regime'];

test.describe('DOCC-5 config health', () => {
  for (const path of PAGES) {
    test(`clean: chip reads Config OK, no banner (${path})`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole('button', { name: /^Config OK · 10 checks$/ })).toBeVisible();
      await expect(page.locator('#config-health-banner')).toHaveCount(0);
    });

    test(`error payload: the banner shows the error (${path})`, async ({ page }) => {
      await page.route('**/api/config/health', (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...CONFIG_HEALTH_CLEAN, ok: false,
          errors: [{
            file: 'scoring_rules.yaml', path: 'regime_sizing.full_conviction_pct',
            message: 'must be a number between 0 and 100',
            blocks: 'the stock scan and every auto-trade fire',
          }],
        }),
      }));
      await page.goto(path);
      const banner = page.locator('#config-health-banner');
      await expect(banner).toBeVisible();
      await expect(banner).toContainText('Config error: 1 problem in scoring_rules.yaml');
      await expect(banner).toContainText('must be a number between 0 and 100');
      await expect(page.getByRole('button', { name: 'Config error' })).toBeVisible();
    });
  }

  test('a 500 shows "Config health unknown"', async ({ page }) => {
    await page.route('**/api/config/health', (route) =>
      route.fulfill({ status: 500, contentType: 'text/plain', body: 'boom' }));
    await page.goto('/dashboard');
    await expect(page.locator('#config-health-banner')).toContainText('Config health unknown');
  });
});
