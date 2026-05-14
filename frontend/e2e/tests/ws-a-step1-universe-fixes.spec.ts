import { test, expect } from '@playwright/test';

test.describe('WS-A: Step 1 Universe Fixes (CR-05 + WS-51)', () => {

  test('renders 6 cards — Russell 2000 absent', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    await expect(page.getByText('Russell 2000')).not.toBeVisible();
    const cards = page.getByRole('button', {
      name: /S&P 500|Nasdaq-100|Dow 30|SPY ETF|My Watchlist|Custom list/,
    });
    await expect(cards).toHaveCount(6);
  });

  test('SPY card shows "1 symbol" not "1 symbols"', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    const spyCard = page.getByRole('button', { name: /SPY ETF/ });
    await expect(spyCard.getByText('1 symbol', { exact: true })).toBeVisible();
    await expect(spyCard.getByText('1 symbols', { exact: true })).not.toBeVisible();
  });

  test('warning banner is styled (has background color) when price min > max', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    const minInput = page.getByLabel('Minimum stock price in dollars');
    const maxInput = page.getByLabel('Maximum stock price in dollars');
    await minInput.fill('100');
    await maxInput.fill('50');
    const banner = page.locator('#filter-warning');
    await expect(banner).toBeVisible();
    const bg = await banner.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe('rgba(0, 0, 0, 0)');
    expect(bg).not.toBe('transparent');
  });

  test('banner text singular when only price invalid', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('100');
    await page.getByLabel('Maximum stock price in dollars').fill('50');
    await expect(page.getByText(/Fix filter range before proceeding/)).toBeVisible();
    await expect(page.getByText(/both minimums/)).not.toBeVisible();
  });

  test('banner text plural when both price and cap invalid', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('100');
    await page.getByLabel('Maximum stock price in dollars').fill('50');
    await page.getByLabel('Minimum market cap in billions').fill('500');
    await page.getByLabel('Maximum market cap in billions').fill('100');
    await expect(page.getByText(/both minimums/)).toBeVisible();
  });

  test('footer summary hidden when warning active', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('100');
    await page.getByLabel('Maximum stock price in dollars').fill('50');
    await expect(page.getByText(/Filters:/)).not.toBeVisible();
  });

  test('footer summary reappears after fixing invalid filter', async ({ page }) => {
    await page.goto('/screener/step-2-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('50');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await expect(page.getByText(/price \$50/)).toBeVisible();
  });

  test('Watchlist pick sends actual symbols — not the string "Watchlist"', async ({ page }) => {
    let capturedUniverse: unknown = null;

    // Route registration order matters: Playwright uses LIFO — last registered wins.
    // General fallback first (lowest priority)
    await page.route('**/api/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    // syncFromBackend() calls /api/watchlist on mount and overwrites Zustand state.
    // Register AFTER general fallback so it wins over it (LIFO).
    await page.route('**/api/watchlist', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(['AAPL', 'MSFT', 'NVDA']) })
    );
    // Scan capture last = highest LIFO priority
    await page.route('**/api/scan', async (route) => {
      try {
        capturedUniverse = route.request().postDataJSON()?.universe ?? null;
      } catch { /* ignore */ }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ scan_id: 'test', timestamp: new Date().toISOString(), candidates: [], rejected: [] }),
      });
    });

    await page.goto('/screener/step-2-universe');

    // Wait for syncFromBackend to complete — My Watchlist card shows "3 symbols"
    await expect(
      page.getByRole('button', { name: /My Watchlist/ }).getByText('3 symbols')
    ).toBeVisible({ timeout: 5000 });

    await page.getByRole('button', { name: /My Watchlist/ }).click();
    await expect(page.getByRole('button', { name: /My Watchlist/ })).toHaveAttribute('aria-pressed', 'true');

    // Client-side nav to preserve universeStore.pick (no persistence on that store)
    await page.getByRole('button', { name: 'Next: Direction + Horizon' }).click();
    await page.waitForURL('**/step-3-direction**');

    // Click and wait for the scan API to be called
    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/api/scan'), { timeout: 8000 }),
      page.getByRole('button', { name: 'Run Scan' }).click(),
    ]).catch(() => [null]);

    expect(request, 'scan API was never called').not.toBeNull();
    expect(Array.isArray(capturedUniverse)).toBe(true);
    expect(capturedUniverse).not.toEqual(['Watchlist']);
  });

});
