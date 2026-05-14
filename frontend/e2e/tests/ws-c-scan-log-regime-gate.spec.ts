import { test, expect } from '@playwright/test';

const MOCK_SCAN = {
  scan_id: 'test-001',
  timestamp: new Date().toISOString(),
  candidates: [],
  rejected: [
    { symbol: 'AAPL', reason: 'stock score 23 — below pass threshold' },
    { symbol: 'TSLA', reason: 'stock score 31 — below pass threshold' },
    { symbol: 'NVDA', reason: 'contract spread 0.45 — above max_bid_ask_spread_pct' },
    { symbol: 'MSFT', reason: 'stock score 40 — below pass threshold' },
    { symbol: 'AMD',  reason: 'event reject — earnings in 3 days' },
  ],
};

async function stubApis(page: import('@playwright/test').Page) {
  await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
  await page.route('**/api/watchlist',(r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',   (r) => r.fulfill({ json: [] }));
  await page.route('**/api/news*',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/portfolio',(r) => r.fulfill({ json: [] }));
}

test.describe('WS-C: Scan Log + Regime Gate (CR-03 + CR-07)', () => {

  test('scan log shows placeholder before first scan', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await expect(page.getByText('No scan run yet.')).toBeVisible();
  });

  test('scan log shows rejection breakdown after scan', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-2-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'Next: Stock Ranking' }).click();
    await page.getByRole('button', { name: 'Back: Direction + Horizon' }).click();
    await expect(page.getByText(/stock score/i).first()).toBeVisible();
    await expect(page.getByText(/contract spread/i).first()).toBeVisible();
  });

  test('scan log shows stage summary with stock and contract counts', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-2-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'Next: Stock Ranking' }).click();
    await page.getByRole('button', { name: 'Back: Direction + Horizon' }).click();
    // Stage summary must distinguish stock vs contract rejections
    await expect(page.getByText(/stock.*rejected|contract.*rejected/i).first()).toBeVisible();
  });

  test('DTE recommendation is shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-2-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'Next: Stock Ranking' }).click();
    await page.getByRole('button', { name: 'Back: Direction + Horizon' }).click();
    await expect(page.getByText(/DTE.*21.*45|target DTE/i).first()).toBeVisible();
  });

  test('scan log resets when a new scan starts', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      await new Promise((res) => setTimeout(res, 800));
      await route.fulfill({ json: MOCK_SCAN });
    });
    await page.goto('/screener/step-2-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING').first()).not.toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/stock score/i).first()).toBeVisible();
    // Start another scan — log should clear while scanning
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING').first()).toBeVisible();
    // While scanning, old log should not be visible
    await expect(page.getByText(/stock score/i).first()).not.toBeVisible();
  });

  test('CR-07: no regime badge when regime is PASS', async ({ page }) => {
    await stubApis(page); // regime: PASS
    await page.goto('/screener/step-3-direction');
    await expect(page.getByText(/REGIME REJECT/i)).not.toBeVisible();
  });

  test('CR-07: regime badge visible on Direction page when regime is REJECT', async ({ page }) => {
    await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'REJECT', headline: 'Downtrend', metrics: [] } }));
    await page.route('**/api/watchlist',(r) => r.fulfill({ json: [] }));
    await page.route('**/api/alerts',   (r) => r.fulfill({ json: [] }));
    await page.route('**/api/news*',    (r) => r.fulfill({ json: [] }));
    await page.route('**/api/portfolio',(r) => r.fulfill({ json: [] }));
    await page.goto('/screener/step-2-universe');
    // Trigger regime load (step 1 refreshes regime)
    await page.goto('/screener/step-3-direction');
    await expect(page.getByText(/REGIME REJECT/i)).toBeVisible();
  });

  test('CR-07: confirmation dialog shown when scanning Bullish in REJECT regime', async ({ page }) => {
    await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'REJECT', headline: 'Downtrend', metrics: [] } }));
    await page.route('**/api/watchlist',(r) => r.fulfill({ json: [] }));
    await page.route('**/api/alerts',   (r) => r.fulfill({ json: [] }));
    await page.route('**/api/news*',    (r) => r.fulfill({ json: [] }));
    await page.route('**/api/portfolio',(r) => r.fulfill({ json: [] }));
    await page.goto('/screener/step-2-universe');
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Bullish/ }).click();
    // Stub scan so it doesn't actually fire
    await page.route('**/api/scan', (r) => r.fulfill({ json: { scan_id: 'x', timestamp: '', candidates: [], rejected: [] } }));
    await page.getByRole('button', { name: 'Run Scan' }).click();
    // Dialog must appear
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText(/Market regime is REJECT/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Proceed anyway/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Cancel/i })).toBeVisible();
  });

});
