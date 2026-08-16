import { Page } from '@playwright/test';
import { setupApiMocks } from './api-mocks';

export async function setupRejectMocks(page: Page): Promise<void> {
  await setupApiMocks(page);

  // Override regime to REJECT (bare + query-string; avoid swallowing /api/regime/series)
  const regimeRejectBody = JSON.stringify({
    overall: 'REJECT',
    headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
    metrics: [
      { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
      { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
      { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
    ],
    omm: {
      state: 'Bear',
      p_stay: 0.7,
      stability: 'Stable',
      regime_age_days: 5,
      avg_regime_duration: 12,
      transition_row: [0.1, 0.7, 0.2],
      state_order: ['Bull', 'Bear', 'Choppy'],
    },
  });
  const fulfillRegimeReject = async (route: { fulfill: (opts: { status: number; contentType: string; body: string }) => Promise<void> }) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: regimeRejectBody });
  };
  await page.route('**/api/regime', fulfillRegimeReject);
  await page.route('**/api/regime?*', fulfillRegimeReject);
}
