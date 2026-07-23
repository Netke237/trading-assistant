import { test, expect } from '@playwright/test';

async function stubApis(page: import('@playwright/test').Page) {
  await page.route('**/api/regime',    (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
  await page.route('**/api/watchlist', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/news*',     (r) => r.fulfill({ json: [] }));
  await page.route('**/api/portfolio', (r) => r.fulfill({ json: [] }));
}

test.describe('WS-D: Execution Parameters Panel (CR-02)', () => {

  test('panel is collapsed by default on Step 2', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await expect(page.getByText('Execution Parameters')).toBeVisible();
    await expect(page.getByText('IV Rank pass threshold')).not.toBeVisible();
  });

  test('default values shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    await expect(page.locator('[data-param-key="iv_rank_pass_max"]').getByText('34')).toBeVisible();
    await expect(page.locator('[data-param-key="rsi_floor"]').getByText('38')).toBeVisible();
    await expect(page.locator('[data-param-key="volume_multiplier"]').getByText('1.5')).toBeVisible();
  });

  test('overrides are sent in scan request when user edits a value', async ({ page }) => {
    let capturedBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { capturedBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-3-direction');
    await page.getByText('Execution Parameters').click();
    const rsiInput = page.getByLabel(/RSI floor/i);
    await rsiInput.fill('50');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    expect(capturedBody).toBeDefined();
    const overrides = capturedBody!.overrides as Record<string, unknown>;
    expect(overrides).toBeDefined();
    expect(overrides['rsi_floor']).toBe(50);
  });

  test('switching horizon resets panel to new horizon defaults', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    const eventRejectRow = page.locator('[data-param-key="event_reject_days"]');
    await expect(eventRejectRow.getByText('21', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Position/ }).click();
    await expect(eventRejectRow.getByText('30', { exact: true })).toBeVisible();
    await expect(eventRejectRow.getByText('21', { exact: true })).not.toBeVisible();
  });

  test('Custom horizon (inherited from a long preset) shows that horizon\'s defaults, not the static Custom table', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Annual/ }).click();
    const customBtn = page.getByRole('button', { name: /Custom/ });
    await customBtn.click();
    await expect(customBtn).toHaveAttribute('aria-pressed', 'true');
    await page.getByText('Execution Parameters').click();
    // Position's values (holdMax=200 resolves to Position via scoringHorizonForHold).
    // The static PARAM_DEFAULTS_PER_HORIZON.Custom entry mirrors Swing and would show 38/34 instead.
    await expect(page.locator('[data-param-key="rsi_floor"]').getByText('37', { exact: true })).toBeVisible();
    await expect(page.locator('[data-param-key="iv_rank_pass_max"]').getByText('44', { exact: true })).toBeVisible();
  });

  test('Custom horizon (inherited from a long preset) sends that horizon\'s overrides to an Options-mode scan', async ({ page }) => {
    let capturedBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { capturedBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Annual/ }).click();
    const customBtn = page.getByRole('button', { name: /Custom/ });
    await customBtn.click();
    await expect(customBtn).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    const overrides = capturedBody?.overrides as Record<string, unknown> | undefined;
    // Position's values (executionParamDefaults.ts:34); the static Custom/Swing-mirrored
    // values (executionParamDefaults.ts:106,109) would be additive_ma_period:20, rs_period:20,
    // rs_benchmark:'NDX' instead. fast_ema/slow_ema happen to be equal across Position and
    // Custom (both 50/200) so aren't useful assertions here.
    expect(overrides?.additive_ma_period).toBe(50);
    expect(overrides?.rs_period).toBe(50);
    expect(overrides?.rs_benchmark).toBe('SPX');
  });

  test('Custom horizon (inherited from a long preset) sends that horizon\'s overrides to a Stocks-mode scan too', async ({ page }) => {
    let capturedBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/stock-scan', async (route) => {
      try { capturedBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: 'Stocks' }).click();
    await page.getByRole('button', { name: /Annual/ }).click();
    const customBtn = page.getByRole('button', { name: /Custom/ });
    await customBtn.click();
    await expect(customBtn).toHaveAttribute('aria-pressed', 'true');
    // Client-side nav to Step 4-stocks — scanOverrides isn't persisted, so a page.goto here would lose it.
    await page.getByRole('button', { name: /^Next/ }).click();
    await expect(page).toHaveURL(/step-4-stocks/);
    await page.getByRole('button', { name: /Pullback/ }).click();
    await page.getByRole('button', { name: 'Run Stock Scan' }).click();
    // exact: true — Step 4-stocks has a permanent subtitle ("Scanning full SP500
    // universe for stock setups") that a plain substring match on "SCANNING" would
    // also match, regardless of actual scan state. The real ScanIndicator (in
    // NavRail, mounted on every screener page) renders the standalone text "SCANNING".
    await expect(page.getByText('SCANNING', { exact: true })).not.toBeVisible({ timeout: 10000 });
    const overrides = capturedBody?.overrides as Record<string, unknown> | undefined;
    expect(overrides?.additive_ma_period).toBe(50);
    expect(overrides?.rs_period).toBe(50);
  });

});
