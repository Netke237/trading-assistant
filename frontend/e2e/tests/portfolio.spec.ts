import { test, expect } from '../fixtures';
import { PortfolioPage } from '../pages/PortfolioPage';

test.describe('Portfolio', () => {
  test('loads with empty state', async ({ page }) => {
    const portfolio = new PortfolioPage(page);
    await portfolio.goto();

    await expect(page).toHaveURL('/portfolio');
    await expect(portfolio.emptyStateText).toBeVisible();
  });
});
