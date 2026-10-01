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

/**
 * The mocked AAPL option chain, shared by the `/api/contracts` route below and
 * by any spec that seeds the scan store directly. Exported so there is exactly
 * ONE definition of this shape: a spec that retyped it would drift from the
 * route the moment either changed, and a fixture that silently disagrees with
 * itself is worse than no fixture.
 *
 * Post-split wire shape (PHASE-A-NULL-IVRANK-2026-09-06). `ivRank` and `iv`
 * are two different quantities and the backend sends them RAW and unresolved
 * (routers/contracts.py): `ivRank` is only ever a TRUE PERCENTILE and is null
 * unless IBKR or tastytrade answered; `iv` is only ever an ABSOLUTE 0-100
 * level for that one strike.
 *
 * This chain is on the ABSOLUTE basis, the DEFAULT PRODUCTION CASE: no rank
 * source answers on most chains, so `ivRank` is null and the UI must fall back
 * to `iv` and label it as an absolute level. Until this change the fixture
 * carried `ivRank: 42` with no `iv` — the PRE-split shape — so the mocks fed
 * only the rank branch and would have gone on passing had the split broken.
 *
 * The rank is per SYMBOL (market.py broadcasts one reading over every strike)
 * while `iv` is per STRIKE, so the strikes below carry DIFFERENT absolute
 * values. That is what makes a wrong-field read visible: under the old fixture
 * every strike held the same 42 and reading either field looked identical.
 */
export const MOCK_OPTION_CHAIN = [
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
    ivRank: null,
    ivPercentile: null,
    iv: 42,
    spread: 0.02,
    volume: 1250,
    score: 78,
    contractConfidence: 'PASS',
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
    // No reading for this strike: Tradier returned none and the yfinance
    // backfill did not cover it. A state the pre-split shape could not
    // express, and the one the step-6 sort comparator guards against by
    // sorting nulls last in BOTH directions.
    ivRank: null,
    ivPercentile: null,
    iv: null,
    spread: 0.03,
    volume: 890,
    score: 72,
    contractConfidence: 'PASS',
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
    ivRank: null,
    ivPercentile: null,
    iv: 43.1,
    spread: 0.02,
    volume: 2100,
    score: 75,
    contractConfidence: 'PASS',
  }
];

/** The single AAPL candidate the `/api/scan` route returns. Its
 *  `contractDetails` IS the 185 strike of MOCK_OPTION_CHAIN above, so the two
 *  must agree on basis and on number. */
export const MOCK_SCAN_CANDIDATE = {
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
    // Same strike as the chain row above, so the same basis and the same
    // number: this block IS AAPL 185C, and a candidate whose gate disagreed
    // with its own contract row would be a fixture bug, not a test case.
    ivRank: null,
    ivPercentile: null,
    iv: 42,
    dte: 45,
  },
  entry: { limit: 2.1, maxFill: 2.2, orderType: 'Limit' },
  exit: {
    invalidation: 180,
    premiumStop: 1.0,
    timeStopDays: 30,
    targets: [
      { id: 'tp1', stockPrice: 194.25, estimatedOptionPrice: 3.5, pricingMethod: 'BS repriced (IV-derived)', contractsToSell: 1, status: 'PENDING' },
      { id: 'tp2', stockPrice: 195, estimatedOptionPrice: 4.2, pricingMethod: 'BS repriced (IV-derived)', contractsToSell: 1, status: 'PENDING' },
    ],
  },
  rrRatio: 2.5,
  rrModel: 'BS repriced (IV-derived)',
  finalStatus: 'PASS',
};

/** A clean DOCC-4 health report (exported for docc5-config-health.spec.ts). */
export const CONFIG_HEALTH_CLEAN = {
  ok: true,
  checked: [
    'scoring_rules.yaml parses', 'money blocks: presence, spelling, enabled', 'regime_sizing values',
    'regime blocks (intraday, swing, position)', 'direction_conviction: position and values',
    'top-level families', 'horizons tree: unknown keys', 'risk_rules.yaml parses',
    'contract_rules.yaml parses', 'running config vs disk',
  ],
  not_checked: [
    'money blocks other than regime_sizing: values',
    'required non-money sections and keys (horizons.<h>.*, stock_score_thresholds, '
      + 'confidence_backtest, risk_rules sections)',
    'risk_rules.yaml and contract_rules.yaml contents',
    'single worker assumed; only WEB_CONCURRENCY is detected',
    'copies the frontend fetched at page load (event and IV thresholds)',
  ],
  pid: 4242,
  errors: [] as unknown[],
  warnings: [] as unknown[],
  stale: [] as unknown[],
};

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

  // Step 1 charts fetch QQQ for the NDX panel (page.tsx getCandles('QQQ'))
  await page.route('**/api/candles/QQQ', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(loadCandles('NVDA')),
    });
  });

  // Regime - PASS by default.
  // Register bare + query-string patterns separately so /api/regime/series
  // and /api/regime/intraday-series are not swallowed by a trailing wildcard.
  // omm.state: 'Bull' so alignmentVerdict('Bullish', 'Bull') → PASS (combinedRegime
  // is driven by omm, not overall — see step-1-regime/page.tsx fetchRegime).
  const regimePassBody = JSON.stringify({
    overall: 'PASS',
    headline: 'Market conditions favourable for directional trades',
    metrics: [
      { label: 'SPX Trend', value: '4,185.22', status: 'PASS', trend: 'up' },
      { label: 'NDX Trend', value: '14,221.55', status: 'PASS', trend: 'up' },
      { label: 'VIX', value: '14.2', status: 'PASS', trend: 'down' },
    ],
    omm: {
      state: 'Bull',
      p_stay: 0.8,
      stability: 'Stable',
      regime_age_days: 10,
      avg_regime_duration: 15,
      transition_row: [0.8, 0.1, 0.1],
      state_order: ['Bull', 'Bear', 'Choppy'],
    },
  });
  const fulfillRegimePass = async (route: { fulfill: (opts: { status: number; contentType: string; body: string }) => Promise<void> }) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: regimePassBody });
  };
  await page.route('**/api/regime', fulfillRegimePass);
  await page.route('**/api/regime?*', fulfillRegimePass);

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

  // Contracts — see MOCK_OPTION_CHAIN for the shape and why it is on the
  // absolute basis.
  await page.route('**/api/contracts**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_OPTION_CHAIN),
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
        // The contract rules the scan applied; {} = none overridden. Without it
        // Step 6 takes the "no recorded contract rules" path.
        contract_rules: {},
        candidates: [MOCK_SCAN_CANDIDATE],
        rejected: [],
      }),
    });
  });

  // Step 5 threshold stores (DOCC-3): no silent fallback, so a missing route
  // leaves the IV/event gates unrendered. Values mirror scoring_rules.yaml.
  await page.route('**/api/config/iv-thresholds', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        Intraday: { abs_pass_max: null, abs_caution_max: null, rank_pass_max: null, rank_caution_max: null },
        Swing:    { abs_pass_max: 34, abs_caution_max: 55, rank_pass_max: 34, rank_caution_max: 55 },
        Position: { abs_pass_max: 44, abs_caution_max: 65, rank_pass_max: 44, rank_caution_max: 65 },
      }),
    });
  });
  await page.route('**/api/config/event-thresholds', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        Intraday: { reject_days: 1,  caution_days: 3 },
        Swing:    { reject_days: 21, caution_days: 45 },
        Position: { reject_days: 30, caution_days: 60 },
      }),
    });
  });

  // DOCC-5 config health (DOCC-4's GET /api/config/health): a clean report,
  // so the TopBar chip reads "Config OK" and no banner takes a grid row.
  // Mirrors backend/app/services/config_health.py CHECK_ORDER / NOT_CHECKED.
  await page.route('**/api/config/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(CONFIG_HEALTH_CLEAN),
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
