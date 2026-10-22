import { test, expect } from '../fixtures';
import { MOCK_SCAN_CANDIDATE, MOCK_OPTION_CHAIN } from '../fixtures/api-mocks';

for (const theme of ['dark', 'light']) {
  for (const width of [1200, 1920]) {
  test(`trade card scores, evidence, handling and alternatives at ${width}px (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.route('**/api/quote/stock?*', r => r.fulfill({ json: { symbol: 'AAPL', price: 185.2 } }));
    await page.route('**/api/quote/option?*', r => r.fulfill({ json: { symbol: 'AAPL', price: 2.15 } }));
    await page.route('**/broker/status', r => r.fulfill({ json: {
      ibkr_paper: { configured: false }, tradier_paper: { configured: false },
      alpaca_paper: { configured: false }, tastytrade_paper: { configured: false },
    } }));
    const candidate = {
      ...MOCK_SCAN_CANDIDATE,
      stockExplanation: { symbol: 'AAPL', direction: 'Bullish', score: 82, status: 'PASS',
        evaluated_at: '2026-10-05T12:00:00Z', pass_threshold: 55, caution_threshold: 35,
        unrounded_score: 82, raw_status: 'PASS', horizon: 'Swing', scoring_mode: 'options',
        iv_basis: 'absolute', components: { trend: { raw_score: 85, weight: 0.3, contribution: 25.5 } },
        caps: [], gate_config: {}, weights: { trend: 0.3 } },
      contractExplanation: MOCK_OPTION_CHAIN[0].explanation,
      alternatives: MOCK_OPTION_CHAIN.slice(0, 2).map(alt => ({
        ...alt, mid: alt.price, rrRatio: 2.5, rrModel: MOCK_SCAN_CANDIDATE.rrModel,
        contractBreakdown: MOCK_SCAN_CANDIDATE.contractBreakdown,
        reason: 'Alternative strike with different liquidity',
      })),
    };
    await page.addInitScript(c => localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 18, state: {
      scanResult: { scan_id: 'ui-followup', timestamp: new Date().toISOString(), candidates: [c], rejected: [] },
      context: { direction: 'Bullish', horizon: 'Swing (5-15d)' }, screenerMode: 'options', scanState: 'COMPLETED',
    } })), candidate);
    await page.addInitScript(t => localStorage.setItem('bamendjou:theme', JSON.stringify({ version: 0, state: { theme: t } })), theme);
    await page.goto('/screener/step-7-trade-card');
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    const scores = page.getByRole('button', { name: /Stock & contract scores/ });
    await expect(scores).toHaveAttribute('aria-expanded', 'false');
    await scores.focus();
    await page.keyboard.press('Enter');
    await expect(scores).toHaveAttribute('aria-expanded', 'true');
    const health = page.getByText('Fundamental Health — no data');
    expect((await scores.boundingBox())!.y).toBeLessThan((await health.boundingBox())!.y);
    const stockEvidence = page.getByRole('button', { name: /Captured stock scoring evidence/ });
    await expect(stockEvidence).toHaveAttribute('aria-expanded', 'false');
    const captured = page.getByText(/Captured AAPL evidence/);
    await expect(captured).toBeHidden();
    await stockEvidence.focus();
    await page.keyboard.press('Enter');
    await expect(captured).toBeVisible();
    await page.getByText('Effective gate configuration and weights').click();
    const detail = captured.locator('..').locator('details');
    await expect(detail).toHaveAttribute('open', '');
    await scores.click();
    await expect(captured).toBeHidden();
    await expect(page.getByRole('region', { name: 'Order Entry' })).toBeVisible();
    await scores.click();
    await expect(detail).toHaveAttribute('open', '');
    await stockEvidence.click();
    await expect(captured).toBeHidden();
    const order = page.getByRole('region', { name: 'Order Entry' });
    const exit = page.getByRole('region', { name: 'Exit Plan' });
    const orderValues = await order.locator('[class*="kvRow"]').evaluateAll(rows => rows.map(row => row.children[1].getBoundingClientRect().right));
    expect(Math.max(...orderValues) - Math.min(...orderValues)).toBeLessThan(2);
    const exitValues = await exit.locator('[class*="kvRow"]').evaluateAll(rows => rows.map(row => row.children[1].getBoundingClientRect().right));
    expect(Math.max(...exitValues) - Math.min(...exitValues)).toBeLessThan(2);
    const final = page.getByText('Final Recommendation').locator('..').locator('..');
    await expect(final.getByRole('radiogroup', { name: 'Exit method for this trade' })).toBeVisible();
    const ladder = final.getByRole('radio', { name: 'Ladder', exact: true });
    await ladder.focus();
    await page.keyboard.press('Space');
    await expect(final.getByText('Target not selected', { exact: true })).toBeVisible();
    const target = final.getByRole('radiogroup', { name: 'Target row', exact: true }).getByRole('radio').first();
    await target.focus();
    await page.keyboard.press('Space');
    await expect(target).toHaveAttribute('aria-checked', 'true');
    await expect(final.getByText('Recorded stock target', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Set trade loss budget' })).toBeVisible();
    await page.getByRole('button', { name: /ALTERNATIVES \(2\)/ }).click();
    await expect(page.getByText('Alt 1', { exact: true })).toBeVisible();
    await expect(page.getByText('Alt 2', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    await page.screenshot({ path: test.info().outputPath(`trade-card-ui-${width}-${theme}.png`), fullPage: true });
    await order.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`trade-card-order-${width}-${theme}.png`) });
    await final.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`trade-card-decision-${width}-${theme}.png`) });
  });
}

}
