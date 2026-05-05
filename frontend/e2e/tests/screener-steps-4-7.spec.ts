import { test, expect } from '../fixtures';
import { ScreenerPage } from '../pages/ScreenerPage';

test.describe('Screener Steps 4-7 @wip', () => {
  test.fixme('Step 4 - loads without crash, empty table expected', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(4);
    await expect(page).toHaveURL(/step-4-ranking/);
    await expect(screener.rankingTable).toBeVisible();
  });

  test.fixme('Step 5 - loads without crash, IV section renders', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(5);
    await expect(page).toHaveURL(/step-5-vol-events/);
    await expect(screener.ivSection).toBeVisible();
  });

  test.fixme('Step 6 - loads without crash, contracts table renders', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(6);
    await expect(page).toHaveURL(/step-6-contracts/);
    await expect(screener.contractsTable).toBeVisible();
  });

  test.fixme('Step 7 - loads without crash, empty trade card state', async ({ page }) => {
    const screener = new ScreenerPage(page);
    await screener.goto(7);
    await expect(page).toHaveURL(/step-7-trade-card/);
    await expect(screener.tradeCardEmptyState).toBeVisible();
  });
});
