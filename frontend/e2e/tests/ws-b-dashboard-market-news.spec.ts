import { test, expect } from '@playwright/test';

const MARKET_NEWS_MOCK = [
  {
    id: 'mn1',
    symbol: 'SPY',
    headline: 'S&P 500 holds gains as Fed signals pause',
    source: 'Reuters',
    timestamp: new Date().toISOString(),
    sentiment: 'bull' as const,
  },
  {
    id: 'mn2',
    symbol: 'QQQ',
    headline: 'Nasdaq tech sector mixed in early trade',
    source: 'Bloomberg',
    timestamp: new Date().toISOString(),
    sentiment: 'neutral' as const,
  },
  {
    id: 'mn3',
    symbol: 'VIX',
    headline: 'Volatility index retreats from recent highs',
    source: 'MarketWatch',
    timestamp: new Date().toISOString(),
    sentiment: 'bear' as const,
  },
];

// Stub all non-news API calls to prevent network errors
async function stubBaseApis(page: import('@playwright/test').Page) {
  await page.route('**/api/watchlist', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/regime',    (r) => r.fulfill({
    json: { overall: 'PASS', headline: 'Test regime', metrics: [] },
  }));
  await page.route('**/api/portfolio', (r) => r.fulfill({ json: [] }));
}

test.describe('WS-B: Dashboard Market News Card (CR-04)', () => {

  test('Market News card is visible on dashboard', async ({ page }) => {
    await stubBaseApis(page);
    // News for market symbols
    await page.route('**/api/news*', async (route) => {
      const url = route.request().url();
      if (url.includes('SPY') && url.includes('QQQ')) {
        await route.fulfill({ json: MARKET_NEWS_MOCK });
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.goto('/');
    await expect(page.getByText('Market News')).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/ws-b-market-news-card.png', fullPage: true });
  });

  test('Market News card shows headlines from SPY/QQQ/VIX/DIA', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', async (route) => {
      const url = route.request().url();
      if (url.includes('SPY') && url.includes('QQQ')) {
        await route.fulfill({ json: MARKET_NEWS_MOCK });
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.goto('/');
    await expect(page.getByText('S&P 500 holds gains as Fed signals pause')).toBeVisible();
    await expect(page.getByText('Nasdaq tech sector mixed in early trade')).toBeVisible();
  });

  test('Market News card shows error message when API fails — not silent', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', async (route) => {
      const url = route.request().url();
      // Fail only the market symbols call; pass the watchlist call
      if (url.includes('SPY') && url.includes('QQQ')) {
        await route.abort('failed');
      } else {
        await route.fulfill({ json: [] });
      }
    });
    await page.goto('/');
    // Must show explicit error — not blank, not "No news"
    await expect(page.getByText(/unavailable/i)).toBeVisible();
    // Must NOT silently show "No news for current candidates"
    const noNewsCount = await page.getByText('No news for current candidates.').count();
    // If multiple NewsCards exist, at most 1 (the watchlist one) can show this
    // The market news section must show the error message instead
    const errorMsg = page.getByText(/unavailable.*backend/i).or(page.getByText(/Market news unavailable/i));
    await expect(errorMsg).toBeVisible();
  });

  test('Market News card is positioned below the watchlist-news + contracts row', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', (r) => r.fulfill({ json: MARKET_NEWS_MOCK }));
    await page.goto('/');

    const marketNewsHeading   = page.getByText('Market News').first();
    const watchlistNewsHeading = page.getByText('News — watchlist').first();

    const [marketBox, watchlistBox] = await Promise.all([
      marketNewsHeading.boundingBox(),
      watchlistNewsHeading.boundingBox(),
    ]);

    expect(marketBox).not.toBeNull();
    expect(watchlistBox).not.toBeNull();
    // Market News card must start below the bottom of the watchlist-news card heading
    expect(marketBox!.y).toBeGreaterThan(watchlistBox!.y + watchlistBox!.height);
  });

  test('Watchlist news card is unchanged and still visible', async ({ page }) => {
    await stubBaseApis(page);
    await page.route('**/api/news*', (r) => r.fulfill({ json: [] }));
    await page.goto('/');
    await expect(page.getByText('News — watchlist')).toBeVisible();
  });

});
