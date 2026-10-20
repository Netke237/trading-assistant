/**
 * @smoke
 * Happy-path scan — all API calls mocked via the standard fixture.
 *
 * Walks the complete 7-step screener flow for Options mode:
 * 1. Step 1: Regime (verifies regime pass, advances)
 * 2. Step 2: Universe (selects S&P 500, advances)
 * 3. Step 3: Direction (selects Bullish, runs mocked scan, advances upon COMPLETED)
 * 4. Step 4: Ranking (verifies ranked candidate AAPL, advances)
 * 5. Step 5: Vol / Events (verifies AAPL candidate volatility and event gate, advances)
 * 6. Step 6: Contracts (verifies AAPL contract chain table, advances)
 * 7. Step 7: Trade Card (verifies AAPL Trade Card display)
 */

import { test, expect } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

test.describe('Happy-path scan (mocked) @smoke', () => {
  test('full 7-step screener flow — AAPL candidate', async ({ page }) => {
    const screener = new ScreenerPage(page);

    // ── Step 1: Regime ──────────────────────────────────────────────────────
    await screener.goto(1);
    await expect(page).toHaveURL(/step-1-regime/);
    await expect(screener.regimeBanner).toBeVisible();

    // ── Step 2: Universe ────────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-2-universe/);
    await screener.selectUniverse('S\\&P 500');

    // ── Step 3: Direction — run scan ────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-3-direction/);
    await screener.selectDirection('Bullish');

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
    await expect(page.getByText(/\d+ ranked/i)).toBeVisible();
    // AAPL row should be visible
    await expect(page.getByText('AAPL').first()).toBeVisible();

    // ── Step 5: Vol / Events ────────────────────────────────────────────────
    await screener.clickNext();
    await expect(page).toHaveURL(/step-5-vol-events/);
    // The mocked chain carries no IV rank (no rank source answered — the common
    // production case), so this row must resolve to the ABSOLUTE basis and be
    // labelled as such: "42.0%", not "42 rank".
    await expect(page.locator('[title^="Implied volatility"]')).toContainText('42.0%');
    await expect(page.locator('[title^="IV rank"]')).toHaveCount(0);
    await expect(page.getByText(/IV ≤ 34 → PASS/)).toBeVisible();

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
    // Candidate AAPL should be visible
    await expect(page.getByText('AAPL').first()).toBeVisible();
  });
});
