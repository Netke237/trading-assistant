import { test, expect } from '../fixtures';

test.describe('Calendar', () => {
  test('loads and renders event section', async ({ page }) => {
    await page.goto('/calendar');

    await expect(page).toHaveURL('/calendar');
    await expect(page.getByText(/calendar/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /today/i })).toBeVisible();
  });

  test('no hardcoded date artifact visible', async ({ page }) => {
    await page.goto('/calendar');

    const bodyText = await page.locator('body').textContent();
    expect(bodyText).not.toMatch(/April 18|2026-04-18/);
  });
});
