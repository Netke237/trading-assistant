/**
 * @smoke
 * Happy-path scan — all API calls mocked via the standard fixture.
 * Walks through all 7 screener steps, runs a scan on Step 3, then
 * verifies each subsequent step loads with the expected content.
 */

import { test, expect } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

test.describe('Happy-path scan (mocked) @smoke', () => {
  test('full 7-step screener flow — AAPL candidate', async ({ page }) => {
    const screener = new ScreenerPage(page);

    // ── Step 1: Universe ────────────────────────────────────────────────────
    await screener.goto(1);
    await expect(page).toHaveURL(/step-1-universe/);
    await expect(screener.universeTiles.first()).toBeVisible();

    // ── Step 2: Direction ───────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-2-direction/);
    await screener.selectDirection('Bullish');

    // ── Step 3: Regime — run scan ───────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-3-regime/);

    // Wait for the regime data to load before scanning
    await page.waitForLoadState('networkidle');

    // Intercept scan response before clicking so we can wait for it
    const scanResponsePromise = page.waitForResponse(
      (res) => res.url().includes('/api/scan') && res.request().method() === 'POST',
      { timeout: 8000 },
    );

    await screener.clickRunScan();
    await scanResponsePromise;

    // TopBar pill should show COMPLETED
    await expect(page.locator('[class*="pill"]')).toContainText('COMPLETED', { timeout: 8000 });

    // ── Step 4: Ranking ─────────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-4-ranking/);
    // "1 ranked" should appear since mock returns 1 candidate
    await expect(page.getByText(/ranked/i)).toBeVisible();
    // AAPL row should be visible
    await expect(page.getByText('AAPL')).toBeVisible();

    // ── Step 5: Vol / Events ────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-5-vol-events/);
    await expect(page.getByText(/iv rank|implied volatility/i).first()).toBeVisible();

    // ── Step 6: Contracts ───────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-6-contracts/);

    // Wait for contracts to load — the AAPL group header should appear
    await expect(page.getByText('AAPL').first()).toBeVisible({ timeout: 5000 });
    // Contracts count visible
    await expect(page.getByText(/contracts/i).first()).toBeVisible();

    // ── Step 7: Trade Card ──────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-7-trade-card/);
    await expect(page.getByRole('heading', { name: /trade card/i })).toBeVisible({ timeout: 5000 });
    // Score should not be empty
    await expect(page.getByText('AAPL').first()).toBeVisible();
  });

  test('Step 3 scan log shows all-passed state when no rejections', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(3);
    await page.waitForLoadState('networkidle');

    const scanDone = page.waitForResponse(
      (res) => res.url().includes('/api/scan') && res.request().method() === 'POST',
      { timeout: 8000 },
    );
    await screener.clickRunScan();
    await scanDone;

    // The scan log should show "all passed" message (mock has 0 rejections)
    await expect(page.getByText(/all passed/i)).toBeVisible({ timeout: 5000 });
  });
});
