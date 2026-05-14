import { test, expect } from '@playwright/test';

// NOT importing from '../fixtures' — we bypass the mock setup fixture intentionally.
// This test uses the real backend throughout; only the scan body is transformed
// (min_stock_score threshold lowered) via route.fetch() so we get real candidates
// even when current market scores are below the default pass threshold.

test.describe('WS-F: Full Screener Flow — Steps 1–7 (Real Backend) @e2e', () => {
  test.setTimeout(90_000);

  test('completes all 7 steps with real backend candidates', async ({ page }) => {
    // Transform the scan request: lower score thresholds so the real backend
    // returns candidates. route.fetch() forwards the modified body to localhost:8000
    // and we fulfill with whatever the backend actually returns.
    await page.route('**/api/scan', async (route) => {
      const body = (route.request().postDataJSON() ?? {}) as Record<string, unknown>;
      body['overrides'] = {
        ...((body['overrides'] as Record<string, unknown>) ?? {}),
        min_stock_score: 20,
        min_contract_score: 20,
      };
      const response = await route.fetch({ postData: JSON.stringify(body) });
      await route.fulfill({ response });
    });

    // ── Step 1: Market Regime ──────────────────────────────────────────────
    // Direct page.goto() is fine here — no store state needed yet.
    await page.goto('/screener/step-1-regime');
    await expect(page).toHaveURL(/step-1-regime/);
    await expect(page.getByRole('heading', { name: 'Market Regime' })).toBeVisible({ timeout: 10_000 });

    // ── Step 2: Universe ───────────────────────────────────────────────────
    // All subsequent navigations use the StepNavBar Next button (client-side
    // router.push) so universeStore and scanStore survive in memory.
    // Scope to the nav element to avoid ambiguity with other "Next" text on the page.
    const nextBtn = page.locator('nav[aria-label="Screener step navigation"] button').last();

    await nextBtn.click();
    await expect(page).toHaveURL(/step-2-universe/);

    // Select Custom universe and paste a small symbol list
    await page.getByRole('button', { name: /Custom list/i }).click();
    await expect(page.getByRole('button', { name: /Custom list/i })).toHaveAttribute('aria-pressed', 'true');
    await page.getByLabel('Custom ticker list').fill('META AAPL MSFT');

    // ── Step 3: Direction + Horizon ────────────────────────────────────────
    await nextBtn.click();
    await expect(page).toHaveURL(/step-3-direction/);

    // Keep default Bullish + Swing, run the scan.
    // Promise.all avoids the race where the response arrives before waitForResponse resolves.
    const [scanResponse] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/api/scan') && r.status() === 200,
        { timeout: 30_000 },
      ),
      page.getByRole('button', { name: /run scan/i }).click(),
    ]);

    const scanData = await scanResponse.json() as { candidates: Array<{ symbol: string }> };
    expect(scanData.candidates.length, 'scan must return at least one candidate').toBeGreaterThan(0);
    const firstSymbol = scanData.candidates[0]!.symbol;

    // Wait for FAB to return to idle (scan state COMPLETED)
    await expect(page.getByRole('button', { name: /run scan/i })).toBeEnabled({ timeout: 30_000 });

    // ── Step 4: Stock Ranking ──────────────────────────────────────────────
    await nextBtn.click();
    await expect(page).toHaveURL(/step-4-ranking/);
    // Assert the panel header "N ranked" — this text is in a flex container (not a 0-width 1fr cell)
    await expect(page.getByText(/\d+\s+ranked/)).toBeVisible({ timeout: 10_000 });

    // ── Step 5: Vol + Events ───────────────────────────────────────────────
    await nextBtn.click();
    await expect(page).toHaveURL(/step-5-vol-events/);
    // Symbol column is 72px fixed (not 1fr) in step-5, so Data spans are safely sized
    await expect(page.getByRole('heading', { name: /Volatility.*Events|Vol.*Events/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(firstSymbol).first()).toBeVisible({ timeout: 10_000 });

    // ── Step 6: Contracts ──────────────────────────────────────────────────
    await nextBtn.click();
    await expect(page).toHaveURL(/step-6-contracts/);
    // Page title becomes "Contracts — <SYMBOL>" once selectedSymbol is set
    await expect(
      page.getByRole('heading', { name: new RegExp(`Contracts — ${firstSymbol}`) }),
    ).toBeVisible({ timeout: 10_000 });

    // ── Step 7: Trade Card ─────────────────────────────────────────────────
    await nextBtn.click();
    await page.waitForURL(/step-7-trade-card/, { timeout: 15_000 });
    // Trade Card heading confirms we're on the right page
    await expect(page.getByRole('heading', { name: 'Trade Card' })).toBeVisible({ timeout: 10_000 });
    // CandidateNav shows the active symbol in a min-width:96px container (safe bounding box)
    await expect(page.getByText(firstSymbol).first()).toBeVisible({ timeout: 10_000 });
  });
});
