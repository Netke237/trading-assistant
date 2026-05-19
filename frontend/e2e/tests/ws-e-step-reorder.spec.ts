import { test, expect } from '@playwright/test';

async function stubApis(page: import('@playwright/test').Page) {
  await page.route('**/api/regime',    (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
  await page.route('**/api/watchlist', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/news*',     (r) => r.fulfill({ json: [] }));
  await page.route('**/api/portfolio', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/candles/*', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/sector*',   (r) => r.fulfill({ json: [] }));
}

test.describe('WS-E: Step Reorder (CR-01)', () => {

  test('step-1-regime URL renders Market Regime page', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-1-regime');
    await expect(page.getByText('STEP 1 OF 7').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: /Market Regime/i })).toBeVisible();
  });

  test('step-2-universe URL renders Universe page', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-universe');
    await expect(page.getByText('STEP 2 OF 7').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: /Universe/i })).toBeVisible();
  });

  test('step-3-direction URL renders Direction + Horizon page', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await expect(page.getByText('STEP 3 OF 7').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: /Direction/i })).toBeVisible();
  });

  test('old URLs (step-1-universe, step-3-regime) no longer resolve (404)', async ({ page }) => {
    const r1 = await page.goto('/screener/step-1-universe');
    expect(r1?.status()).not.toBe(200);
    const r2 = await page.goto('/screener/step-3-regime');
    expect(r2?.status()).not.toBe(200);
  });

  test('Next from step-1-regime navigates to step-2-universe', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-1-regime');
    await page.getByRole('button', { name: /Next/i }).click();
    await page.waitForURL('**/step-2-universe**');
    await expect(page.getByText('STEP 2 OF 7').first()).toBeVisible();
  });

});
