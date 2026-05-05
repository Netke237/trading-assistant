import { test, expect } from '../fixtures';
import { WatchlistPage } from '../pages/WatchlistPage';

test.describe('Watchlist', () => {
  test('loads with Stocks tab active', async ({ page }) => {
    const watchlist = new WatchlistPage(page);
    await watchlist.goto();

    await expect(page).toHaveURL('/watchlist');
    await expect(watchlist.stocksTab).toBeVisible();
  });

  test('shows empty state when no starred symbols', async ({ page }) => {
    const watchlist = new WatchlistPage(page);
    await watchlist.goto();

    await expect(watchlist.emptyStateText).toBeVisible();
  });

  test('can switch to Contracts tab', async ({ page }) => {
    const watchlist = new WatchlistPage(page);
    await watchlist.goto();

    await watchlist.switchToContractsTab();
    await expect(watchlist.contractsTab).toBeVisible();
  });
});
