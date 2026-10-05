import { test, expect } from '../fixtures';
import { MOCK_SCAN_CANDIDATE, MOCK_OPTION_CHAIN } from '../fixtures/api-mocks';

for (const width of [1200, 1920]) {
  test(`trade card scores, evidence, handling and alternatives at ${width}px`, async ({ page }) => {
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
    await page.goto('/screener/step-7-trade-card');
    const scores = page.getByRole('button', { name: /Stock & contract scores/ });
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
    await expect(page.getByRole('button', { name: 'Set trade loss budget' })).toBeVisible();
    await page.getByRole('button', { name: /ALTERNATIVES \(2\)/ }).click();
    await expect(page.getByText('Alt 1', { exact: true })).toBeVisible();
    await expect(page.getByText('Alt 2', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
    await page.screenshot({ path: `test-results/trade-card-ui-${width}.png`, fullPage: true });
  });
}

test('Stocks has score disclosure and scans only from Step 4', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  let scans = 0;
  const candidate = {
    symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction: 'Bullish',
    strategy: { strategy: 'pullback_ema', entry_price: 150, stop_price: 145, target_price: 160, rr_ratio: 2, atr: 3, detail: {}, targets: [160, 165, 170] },
    backtest: { n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5, expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok' },
    stock_score: 80, stock_status: 'PASS', shares: 30, dollar_risk: 150, dollar_size: 4500,
    confidence: 0.7, confidence_text: 'High', sentiment: null, fundamentals: null,
  };
  const result = { scan_id: 'stock-ui-followup', timestamp: new Date().toISOString(), candidates: [candidate], rejected: [] };
  await page.route('**/api/stock-scan', async r => { scans++; await r.fulfill({ json: result }); });
  await page.route('**/broker/status', r => r.fulfill({ json: {} }));
  await page.route('**/api/quote/stock?*', r => r.fulfill({ json: { symbol: 'AAPL', price: 150 } }));
  await page.addInitScript(res => localStorage.setItem('bamendjou-scan-store', JSON.stringify({ version: 18, state: {
    stockScanResult: res, screenerMode: 'stocks', context: { direction: 'Bullish', horizon: 'Swing (5-15d)' },
  } })), result);
  await page.goto('/screener/step-7-position-card');
  const scores = page.getByRole('button', { name: /Stock & contract scores/ });
  await expect(scores).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('progressbar', { name: /Total stock score/ })).toBeVisible();
  expect((await scores.boundingBox())!.y).toBeLessThan((await page.getByText('Fundamental Health — no data').boundingBox())!.y);
  await scores.click();
  await expect(page.getByRole('progressbar', { name: /Total stock score/ })).toHaveCount(0);
  await expect(page.getByText('Fundamental Health — no data')).toBeVisible();
  await page.goto('/screener/step-3-direction');
  await expect(page.getByRole('button', { name: 'Run stock scan', exact: true })).toHaveCount(0);
  expect(scans).toBe(0);
  await page.goto('/screener/step-4-stocks');
  await expect(page.getByRole('button', { name: 'Run Stock Scan', exact: true })).toBeVisible();
  expect(scans).toBe(0);
  await page.screenshot({ path: 'test-results/trade-card-ui-stocks.png', fullPage: true });
});
