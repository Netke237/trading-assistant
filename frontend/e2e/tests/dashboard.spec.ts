import { test, expect } from '../fixtures';
import { DashboardPage } from '../pages/DashboardPage';

test.describe('Dashboard @smoke', () => {
  test('loads without console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await expect(page).toHaveURL('/dashboard');

    expect(consoleErrors).toHaveLength(0);
  });

  test('renders regime banner with status badge', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto();

    await expect(dashboard.regimeSection).toBeVisible();
    const badge = page.locator('[class*="badge"], [class*="status"]').first();
    await expect(badge).toBeVisible();
  });

  test('shows watchlist section', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await expect(page.getByText(/watchlist/i).first()).toBeVisible();
  });

  test('shows portfolio section', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await expect(page.getByText(/portfolio/i).first()).toBeVisible();
  });

  test('shows alerts section', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await expect(page.getByText(/alerts/i).first()).toBeVisible();
  });

  test('nav rail links to all major pages', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto();

    await expect(dashboard.navLinkScreener).toBeVisible();
    await expect(dashboard.navLinkWatchlist).toBeVisible();
    await expect(dashboard.navLinkPortfolio).toBeVisible();
    await expect(dashboard.navLinkCalendar).toBeVisible();
    await expect(dashboard.navLinkSettings).toBeVisible();
  });
});
