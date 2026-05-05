import { test, expect } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

test.describe('Screener Steps 1-3 @smoke', () => {
  test('Step 1 - universe page loads with selectable tiles', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(1);

    await expect(page).toHaveURL(/step-1-universe/);
    await expect(screener.universeTiles.first()).toBeVisible();

    await screener.selectUniverse('S\\&P 500');
    const selectedTile = page.locator('[aria-pressed="true"], [class*="active"], [class*="selected"]').first();
    await expect(selectedTile).toBeVisible();
  });

  test('Step 1 - next button navigates to Step 2', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(1);
    await screener.clickNext();
    await expect(page).toHaveURL(/step-2-direction/);
  });

  test('Step 2 - direction toggle works', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(2);

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
    await expect(page).toHaveURL(/step-3-regime/);
  });

  test('Step 3 - regime banner and charts render', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(3);

    await expect(page).toHaveURL(/step-3-regime/);
    await expect(screener.regimeBanner).toBeVisible();

    // Charts should render (canvas elements with size > 0)
    await expect(screener.spxChart).toBeVisible();
    await expect(screener.ndxChart).toBeVisible();

    await expect(screener.spxChart).toBeVisible();
    await expect(screener.ndxChart).toBeVisible();
  });

  test('Step 3 - metric grid and sector heatmap visible', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(3);

    await expect(screener.metricGrid).toBeVisible();
    await expect(screener.sectorHeatmap).toBeVisible();
  });
});

test.describe('Screener Step 3 REJECT dialog @smoke', () => {
  test('shows confirmation dialog when regime is REJECT', async ({ page }) => {
    // Override the regime route to return REJECT
    await page.route('**/api/regime', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          overall: 'REJECT',
          headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
          metrics: [
            { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
            { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
            { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
          ],
        }),
      });
    });

    const screener = new ScreenerPage(page);
    await screener.goto(3);
    
    // Reload to ensure fresh store with overridden REJECT regime
    await page.reload();
    await page.waitForLoadState('networkidle');

    await expect(screener.regimeBanner).toBeVisible();
    await expect(page.getByRole('banner').getByText('REJECT')).toBeVisible();

    // Wait a bit for Zustand store to settle after reload
    await page.waitForTimeout(1000);
    
    await screener.clickNext();
    await expect(screener.rejectDialog).toBeVisible();
    await expect(page.getByText(/regime flagged as reject/i)).toBeVisible();

    await screener.proceedAnywayButton.click();
    await expect(page).toHaveURL(/step-4-ranking/);
  });
});
