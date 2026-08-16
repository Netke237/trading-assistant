import { test, expect } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

test.describe('Screener Steps 1-3 @smoke', () => {
  test('Step 2 - universe page loads with selectable tiles', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(2);

    await expect(page).toHaveURL(/step-2-universe/);
    await expect(screener.universeTiles.first()).toBeVisible();

    await screener.selectUniverse('S\\&P 500');
    const selectedTile = page.locator('[aria-pressed="true"], [class*="active"], [class*="selected"]').first();
    await expect(selectedTile).toBeVisible();
  });

  test('Step 2 - universe selection sends correct payload to scan API', async ({ page }) => {
    const screener = new ScreenerPage(page);

    // Listen for scan API calls before any navigation
    let scanPayload: unknown = null;
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/api/scan')) {
        scanPayload = req.postDataJSON();
      }
    });

    // Select SP 500 on Step 2 (Universe — persisted in Zustand)
    await screener.goto(2);
    await screener.selectUniverse('S\\&P 500');

    // RunScanButton is mounted on Step 3 (Direction) — navigate there to trigger the scan
    await screener.goto(3);
    await screener.clickRunScan();

    // Wait for scan to complete
    await page.waitForTimeout(2000);
    expect(scanPayload).not.toBeNull();
    const payload = scanPayload as Record<string, unknown>;
    expect(payload.universe).toEqual(['SP500']);
    expect(payload.direction).toBeDefined();
    expect(payload.horizon).toBeDefined();
  });

  test('Step 2 - next button navigates to Step 3', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(2);
    await screener.clickNext();
    await expect(page).toHaveURL(/step-3-direction/);
  });

  test('Step 3 - direction toggle works', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(3);

    await expect(screener.bullishButton).toBeVisible();
    await expect(screener.bearishButton).toBeVisible();

    await screener.selectDirection('Bullish');
    await expect(screener.bullishButton).toBeVisible();

    await screener.selectDirection('Bearish');
    await expect(screener.bearishButton).toBeVisible();
  });

  test('Step 2 - next navigates to Step 3', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(2);
    await screener.clickNext();
    await expect(page).toHaveURL(/step-3-direction/);
  });

  test('Step 1 - regime banner and charts render', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(1);

    await expect(page).toHaveURL(/step-1-regime/);
    await expect(screener.regimeBanner).toBeVisible();

    // Charts should render (canvas elements with size > 0)
    await expect(screener.spxChart).toBeVisible();
    await expect(screener.ndxChart).toBeVisible();

    await expect(screener.spxChart).toBeVisible();
    await expect(screener.ndxChart).toBeVisible();
  });

  test('Step 1 - metric grid and sector heatmap visible', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(1);

    await expect(screener.metricGrid).toBeVisible();
    await expect(screener.sectorHeatmap).toBeVisible();
  });
});

test.describe('Screener Step 1 REJECT dialog @smoke', () => {
  test('shows confirmation dialog when regime is REJECT', async ({ page }) => {
    // Override the regime route to return REJECT (bare + query-string;
    // avoid swallowing /api/regime/series with a trailing wildcard)
    const regimeRejectBody = JSON.stringify({
      overall: 'REJECT',
      headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
      metrics: [
        { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
        { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
        { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
      ],
      omm: {
        state: 'Bear',
        p_stay: 0.7,
        stability: 'Stable',
        regime_age_days: 5,
        avg_regime_duration: 12,
        transition_row: [0.1, 0.7, 0.2],
        state_order: ['Bull', 'Bear', 'Choppy'],
      },
    });
    const fulfillRegimeReject = async (route: { fulfill: (opts: { status: number; contentType: string; body: string }) => Promise<void> }) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: regimeRejectBody });
    };
    await page.route('**/api/regime', fulfillRegimeReject);
    await page.route('**/api/regime?*', fulfillRegimeReject);

    const screener = new ScreenerPage(page);
    await screener.goto(1);

    await expect(screener.regimeBanner).toBeVisible();
    await expect(page.getByRole('banner').getByText('REJECT')).toBeVisible();

    // Wait for StepNavBar to reflect the REJECT regime from Zustand store
    await expect(page.locator('nav[aria-label="Screener step navigation"]')).toHaveAttribute('data-regime', 'REJECT');

    await screener.clickNext();
    await expect(screener.rejectDialog).toBeVisible();
    await expect(page.getByText(/regime flagged as reject/i)).toBeVisible();

    await screener.proceedAnywayButton.click();
    await expect(page).toHaveURL(/step-2-universe/);
  });
});
