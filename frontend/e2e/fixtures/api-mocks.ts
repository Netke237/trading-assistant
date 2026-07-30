import { Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const FIXTURES_DIR = path.join(process.cwd(), '..', 'backend', 'tests', 'fixtures');

function loadCandles(symbol: string): unknown[] {
  const filePath = path.join(FIXTURES_DIR, `${symbol}_candles.json`);
  if (!fs.existsSync(filePath)) {
    console.warn(`Fixture not found: ${filePath}`);
    return [];
  }
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

export async function setupApiMocks(page: Page): Promise<void> {
  // Candles - serve from pinned fixtures
  const symbols = ['AAPL', 'MSFT', 'NVDA', 'SPY'];
  for (const symbol of symbols) {
    const candles = loadCandles(symbol);
    await page.route(`**/api/candles/${symbol}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(candles),
      });
    });
  }

  // Proxy SPX to SPY fixture, NDX to NVDA fixture
  await page.route('**/api/candles/SPX', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(loadCandles('SPY')),
    });
  });

  await page.route('**/api/candles/NDX', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(loadCandles('NVDA')),
    });
  });

  // Regime - PASS by default
  await page.route('**/api/regime', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        overall: 'PASS',
        headline: 'Market conditions favourable for directional trades',
        metrics: [
          { label: 'SPX Trend', value: '4,185.22', status: 'PASS', trend: 'up' },
          { label: 'NDX Trend', value: '14,221.55', status: 'PASS', trend: 'up' },
          { label: 'VIX', value: '14.2', status: 'PASS', trend: 'down' },
        ],
      }),
    });
  });

  // Sectors
  await page.route('**/api/sectors', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { key: 'XLK', name: 'Technology', changePct: 1.25, status: 'PASS' },
        { key: 'XLF', name: 'Financials', changePct: -0.42, status: 'CAUTION' },
        { key: 'XLE', name: 'Energy', changePct: 0.88, status: 'PASS' },
      ]),
    });
  });

  // Portfolio — return empty list for GET, success for POST
  await page.route('**/api/portfolio', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'created' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  // Watchlist — return empty list for GET, success for POST/DELETE
  await page.route('**/api/watchlist**', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'added' }),
      });
      return;
    }
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'removed' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  // Empty arrays for remaining list endpoints
  const emptyEndpoints = ['/api/alerts', '/api/events', '/api/tradecards'];
  for (const endpoint of emptyEndpoints) {
    await page.route(`**${endpoint}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });
  }

  // News
  await page.route('**/api/news**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: '1',
          symbol: 'AAPL',
          headline: 'Apple announces new product line',
          source: 'Reuters',
          timestamp: '2024-05-01T10:00:00Z',
          sentiment: 'bull',
        },
        {
          id: '2',
          symbol: 'MSFT',
          headline: 'Microsoft earnings beat expectations',
          source: 'Bloomberg',
          timestamp: '2024-05-01T14:30:00Z',
          sentiment: 'bull',
        },
      ]),
    });
  });

  // Contracts
  await page.route('**/api/contracts**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'AAPL|185|2025-05-16|C',
          symbol: 'AAPL',
          strike: 185,
          expiry: '2025-05-16',
          right: 'C',
          dte: 45,
          dteTotal: 45,
          price: 2.15,
          delta: 0.52,
          theta: -0.05,
          ivRank: 42,
          ivPercentile: 38,
          spread: 0.02,
          volume: 1250,
          score: 78,
        },
        {
          id: 'AAPL|190|2025-05-16|C',
          symbol: 'AAPL',
          strike: 190,
          expiry: '2025-05-16',
          right: 'C',
          dte: 45,
          dteTotal: 45,
          price: 1.35,
          delta: 0.38,
          theta: -0.04,
          ivRank: 42,
          ivPercentile: 38,
          spread: 0.03,
          volume: 890,
          score: 72,
        },
        {
          id: 'AAPL|180|2025-05-16|C',
          symbol: 'AAPL',
          strike: 180,
          expiry: '2025-05-16',
          right: 'C',
          dte: 45,
          dteTotal: 45,
          price: 3.45,
          delta: 0.65,
          theta: -0.06,
          ivRank: 42,
          ivPercentile: 38,
          spread: 0.02,
          volume: 2100,
          score: 75,
        },
      ]),
    });
  });

  // Scan endpoint
  await page.route('**/api/scan', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        scan_id: 'test-scan-001',
        timestamp: new Date().toISOString(),
        candidates: [
          {
            symbol: 'AAPL',
            company: 'Apple Inc.',
            price: 185.2,
            direction: 'Bullish',
            status: 'PASS',
            stockScore: 82,
            stockConfidence: 'PASS',
            stockBreakdown: {
              trend: 85,
              pullback: 78,
              trigger: 80,
              event: 90,
              volatility: 75,
            },
            contract: 'AAPL|185|2025-05-16|C',
            contractScore: 78,
            contractConfidence: 'PASS',
            contractBreakdown: {
              dteFit: 80,
              delta: 75,
              ivAttractiveness: 70,
              liquidity: 85,
              spread: 80,
            },
            contractDetails: {
              strike: 185,
              expiry: '2025-05-16',
              right: 'C',
              mid: 2.15,
              delta: 0.52,
              theta: -0.05,
              ivRank: 42,
              dte: 45,
            },
            entry: { limit: 2.1, maxFill: 2.2, orderType: 'Limit' },
            exit: {
              invalidation: 180,
              premiumStop: 1.0,
              timeStopDays: 30,
              targets: [
                { id: 'tp1', stockPrice: 194.25, estimatedOptionPrice: 3.5, pricingMethod: 'delta-approx', contractsToSell: 1, status: 'PENDING' },
                { id: 'tp2', stockPrice: 195, estimatedOptionPrice: 4.2, pricingMethod: 'delta-approx', contractsToSell: 1, status: 'PENDING' },
              ],
            },
            rrRatio: 2.5,
            rrModel: 'BS repriced (IV-derived)',
            finalStatus: 'PASS',
          },
        ],
        rejected: [],
      }),
    });
  });

  // Health check
  await page.route('**/api/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' }),
    });
  });
}
