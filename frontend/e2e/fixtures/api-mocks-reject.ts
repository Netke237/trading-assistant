import { Page } from '@playwright/test';
import { setupApiMocks } from './api-mocks';

export async function setupRejectMocks(page: Page): Promise<void> {
  await setupApiMocks(page);

  // Override regime to REJECT
  await page.route('**/api/regime', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        overall: 'REJECT',
        headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
        metrics: [
          { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
          { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
          { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
        ],
      }),
    });
  });
}
