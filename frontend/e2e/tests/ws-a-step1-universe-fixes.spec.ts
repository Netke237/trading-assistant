import { test, expect } from '@playwright/test';

test.describe('WS-A: Step 1 Universe Fixes (CR-05 + WS-51)', () => {

  test('renders 6 cards — Russell 2000 absent', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await expect(page.getByText('Russell 2000')).not.toBeVisible();
    const cards = page.getByRole('button', {
      name: /S&P 500|Nasdaq-100|Dow 30|SPY ETF|My Watchlist|Custom list/,
    });
    await expect(cards).toHaveCount(6);
  });

  test('SPY card shows "1 symbol" not "1 symbols"', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    const spyCard = page.getByRole('button', { name: /SPY ETF/ });
    await expect(spyCard).toBeVisible();
    await expect(spyCard).toContainText('1 symbol');
    await expect(spyCard).not.toContainText('1 symbols');
  });

  test('warning banner is styled (has background color) when price min > max', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    const banner = page.locator('#filter-warning');
    await expect(banner).toBeVisible();
    const bg = await banner.evaluate(
      (el) => getComputedStyle(el).backgroundColor,
    );
    expect(bg).not.toBe('rgba(0, 0, 0, 0)');
    expect(bg).not.toBe('transparent');
    await page.screenshot({ path: 'e2e/screenshots/ws-a-banner-styled.png', fullPage: false });
  });

  test('banner text singular when only price invalid', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await expect(page.locator('#filter-warning')).toContainText('Fix filter range before');
    await expect(page.locator('#filter-warning')).not.toContainText('ranges');
  });

  test('banner text plural when both price and cap invalid', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await page.getByLabel(/Minimum market cap/).fill('50');
    await page.getByLabel(/Maximum market cap/).fill('10');
    await expect(page.locator('#filter-warning')).toContainText('Fix filter ranges');
  });

  test('footer summary hidden when warning active', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await expect(page.getByText(/Filters: price/)).not.toBeVisible();
  });

  test('footer summary reappears after fixing invalid filter', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    // Clear the invalid max, then type a valid one to ensure onChange fires
    await page.getByLabel('Maximum stock price in dollars').clear();
    await page.getByLabel('Maximum stock price in dollars').fill('300');
    await expect(page.locator('#filter-warning')).not.toBeVisible();
    await expect(page.locator('[class*="filtersFooter"]')).toBeVisible();
  });

  test('Watchlist pick sends actual symbols — not the string "Watchlist"', async ({ page }) => {
    let capturedUniverse: unknown = null;

    // Intercept scan endpoint — capture payload, return empty success
    await page.route(
      (url) => url.pathname === '/api/scan',
      async (route) => {
        try {
          capturedUniverse = route.request().postDataJSON()?.universe ?? null;
        } catch { /* ignore */ }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ scan_id: 'test', timestamp: new Date().toISOString(), candidates: [], rejected: [] }),
        });
      },
    );

    // Stub other backend API calls so page loads cleanly
    await page.route(
      (url) => url.pathname.startsWith('/api/') && url.pathname !== '/api/scan',
      async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      },
    );

    // Select Watchlist on Step 1
    await page.goto('/screener/step-1-universe');
    await page.getByRole('button', { name: /My Watchlist/ }).click();
    await expect(page.getByRole('button', { name: /My Watchlist/ })).toHaveAttribute('aria-pressed', 'true');

    // Navigate to Dashboard where RunScanButton is mounted
    await page.getByRole('link', { name: /Exit Workflow/ }).click();
    await page.waitForURL('/dashboard');
    await page.getByRole('button', { name: 'Run Scan' }).click();

    // Wait for scan to finish (SCANNING pill disappears)
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });

    expect(capturedUniverse).not.toBeNull();
    expect(Array.isArray(capturedUniverse)).toBe(true);
    expect(capturedUniverse).not.toEqual(['Watchlist']);
  });

});
