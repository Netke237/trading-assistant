import { test, expect } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

test.describe('Screener Steps 4-7 @wip', () => {
  // No scan is seeded before these navigate straight to their step URL, so every step renders
  // its no-data empty state (a plain text message, by design -- there is no "empty table" in
  // this app). These smoke-test that each step loads without crashing in that state.
  test('Step 4 - loads without crash, empty state expected', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(4);
    await expect(page).toHaveURL(/step-4-ranking/);
    await expect(page.getByText(/run a scan to see ranked candidates/i)).toBeVisible();
  });

  test('Step 5 - loads without crash, IV section renders', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(5);
    await expect(page).toHaveURL(/step-5-vol-events/);
    await expect(screener.ivSection).toBeVisible();
  });

  test('Step 6 - loads without crash, empty state expected', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(6);
    await expect(page).toHaveURL(/step-6-contracts/);
    await expect(page.getByText(/run a scan to see contracts/i)).toBeVisible();
  });

  test('Step 7 - loads without crash, empty trade card state', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(7);
    await expect(page).toHaveURL(/step-7-trade-card/);
    await expect(screener.tradeCardEmptyState).toBeVisible();
  });
});
