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
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText('Execution Parameters')).toBeVisible();
    await expect(page.getByText('IV Rank pass threshold')).not.toBeVisible();
  });

  test('panel expands to show parameter rows', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await page.getByText('Execution Parameters').click();
    await expect(page.getByText('IV Rank pass threshold')).toBeVisible();
    await expect(page.getByText('RSI floor')).toBeVisible();
    await expect(page.getByText('MACD fast')).toBeVisible();
  });

  test('default values shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    await expect(page.getByText('34')).toBeVisible();
    await expect(page.getByText('44')).toBeVisible();
  });

  test('overrides are sent in scan request when user edits a value', async ({ page }) => {
    let capturedBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { capturedBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-2-direction');
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

  test('reset to defaults clears overrides', async ({ page }) => {
    let lastBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { lastBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-2-direction');
    await page.getByText('Execution Parameters').click();
    await page.getByLabel(/RSI floor/i).fill('55');
    await page.getByRole('button', { name: /Reset to defaults/i }).click();
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    expect(lastBody?.overrides).toEqual({});
  });

  test('switching horizon resets panel to new horizon defaults', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    const eventRejectRow = page.locator('[data-param-key="event_reject_days"]');
    await expect(eventRejectRow.getByText('7', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Position/ }).click();
    await expect(eventRejectRow.getByText('30', { exact: true })).toBeVisible();
    await expect(eventRejectRow.getByText('7', { exact: true })).not.toBeVisible();
  });

});
