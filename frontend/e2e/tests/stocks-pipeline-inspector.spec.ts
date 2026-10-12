import { test, expect } from '../fixtures';

const rejected = [
  ...Array.from({ length: 16 }, (_, i) => ({ symbol: `H${i}`, reason: 'insufficient history' })),
  ...Array.from({ length: 195 }, (_, i) => ({ symbol: `S${i}`, reason: 'REJECT score=32' })),
  ...Array.from({ length: 26 }, (_, i) => ({ symbol: `D${i}`, reason: 'direction_conviction: trend 15 < 30 for Bullish Swing' })),
  ...Array.from({ length: 280 }, (_, i) => ({ symbol: `SIG${i}`, reason: 'no breakout_base setup' })),
  { symbol: 'DAY', reason: 'backtest gate: Only 1 trades — need 5' },
];

for (const theme of ['light', 'dark']) {
  test(`Stocks uses the shared inspector with readable groups in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(({ theme, rejected }) => {
      localStorage.setItem('bamendjou:theme', JSON.stringify({ version: 0, state: { theme } }));
      localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 18, state: {
        screenerMode: 'stocks', scanState: 'COMPLETED',
        context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5-15d)' },
        stockScanResult: { scan_id: 'stock-inspector-e2e', timestamp: '2026-10-12T08:00:00Z', candidates: [], rejected,
          pipeline: { scanned: 518, failed_history: 16, failed_score: 195, failed_direction: 26,
            failed_direction_unmeasured: 0, direction_min_trend: 30, failed_regime: 0,
            failed_signal: 280, failed_backtest: 1, failed_shortlist: 0, other_rejected: 0, candidates: 0 },
        },
      } }));
    }, { theme, rejected });
    await page.goto('/screener/step-6-backtest');
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    const opener = page.getByRole('button', { name: 'Filter Breakdown (518 Not Ranked)' });
    await expect(opener).toBeVisible();
    await expect(page.getByText('Pipeline log', { exact: true })).toHaveCount(0);
    await opener.click();
    const inspector = page.getByRole('dialog', { name: 'Pipeline Root-Cause Inspector' });
    await expect(inspector).toBeVisible();
    await expect(inspector.getByText('518 Scanned', { exact: true })).toBeVisible();
    await expect(inspector.getByText('0 Survivors', { exact: true })).toBeVisible();
    await expect(inspector.getByText('View 280 Tickers ▼', { exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`stocks-inspector-${theme}.png`), animations: 'disabled' });
    await inspector.getByRole('textbox').fill('DAY');
    await expect(inspector.getByRole('status')).toContainText('backtest gate: Only 1 trades — need 5');
    await inspector.getByRole('button', { name: 'Plaintext Tree' }).click();
    await expect(inspector.locator('pre')).toContainText('Left: 502');
    await expect(inspector.locator('pre')).toContainText('Left: 307');
    await expect(inspector.locator('pre')).toContainText('Left: 281');
    await inspector.getByRole('button', { name: 'Interactive', exact: true }).click();
    await inspector.getByRole('button', { name: 'View 280 Tickers ▼' }).click();
    await inspector.getByRole('button', { name: 'SIG0', exact: true }).click();
    await expect(inspector.getByRole('textbox')).toHaveValue('SIG0');
    await expect(inspector.getByRole('status')).toContainText('no breakout_base setup');
    expect(await inspector.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(inspector).toHaveCount(0);
    await expect(opener).toBeFocused();
  });
}
