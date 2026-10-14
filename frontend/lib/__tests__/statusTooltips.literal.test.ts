/*
 * statusTooltips.ts — every sentence builder pinned against a LITERAL string.
 *
 * WHY THIS FILE EXISTS (SCREENER-PINNING-PASS, decision
 * AUTOTRADE-ALERT-AND-SCREENER-WORK-ORDER-2026-09-20 item 3). Screener rounds
 * 5, 6 and 7 each found the same thing: the rendered copy was correct and the
 * tests vouching for it were circular -- they rebuilt the expected string with
 * the SAME builder the page rendered with, so a defect inside a builder moved
 * expectation and actual together. Round 7 measured swapping evReject/evCaution
 * inside eventVolGateTooltip shipping the full suite green.
 *
 * THE RULES THIS FILE KEEPS, so the next edit does not undo them:
 *   - every expectation is a hand-written literal and a whole-string `toBe`;
 *     nothing here calls production code to build an expected value;
 *   - numbers are chosen so no two interpolated slots share a value, so a swap
 *     of any two changes the string;
 *   - a builder that interpolates a number is pinned at two argument sets, so a
 *     value baked into the builder passes one and fails the other;
 *   - where the builder itself decides a band, the value AT the edge and the
 *     value just past it are both pinned.
 * The literals were derived by hand from the rule each sentence states, not by
 * running the builder and pasting its output.
 */
import {
  GENERIC_STATUS_TOOLTIP,
  positionStatusTooltip,
  stockStatusTooltip,
  regimeStatusTooltip,
  regimeMetricTooltip,
  regimeNoDataTooltip,
  gateDrivers,
  gateDriverPhrase,
  eventVolGateTooltip,
  winRateTooltip,
  backtestGateTooltip,
  stockScanGateTooltip,
  contractScoreTooltip,
  contractBreakdownTooltip,
  regimeFitTooltip,
  safetyFlagTooltip,
  fundamentalScoreTooltip,
  riskStatusTooltip,
  scanPipelineStatusTooltip,
  alertStatusTooltip,
  eventProximityGateTooltip,
  ruleContributionTooltip,
  type GateDrivers,
} from '@/lib/statusTooltips';
import type {
  OptionContract, ContractScoreBreakdown, PortfolioRiskMetrics, RiskLimits,
} from '@/types/domain';

const GENERIC = {
  PASS:    'Strong signal — all key scoring components cleared the threshold. Good base to proceed at normal size.',
  CAUTION: 'Borderline signal — qualifies but has notable weaknesses. Review the component breakdown before committing capital.',
  REJECT:  'Signal below the quality gate. Consider skipping this candidate or waiting for a cleaner setup.',
  PENDING: 'Scoring is still in progress. Status will update once all components are evaluated.',
  NO_DATA: 'Insufficient price or volume data to score this.',
};

describe('GENERIC_STATUS_TOOLTIP', () => {
  it('is exactly the five sentences', () => {
    expect(GENERIC_STATUS_TOOLTIP).toEqual(GENERIC);
  });
});

describe('positionStatusTooltip', () => {
  it.each([
    ['PASS',    'Position status: healthy — no known issues since entry.'],
    ['CAUTION', 'Position status: flagged — review this position, something about it warrants a closer look.'],
    ['REJECT',  'Position status: at risk — this position has triggered a warning condition.'],
    ['PENDING', 'Position status is not actively tracked post-entry — this reflects the state at order time, not a live re-score.'],
    ['NO_DATA', 'No status data available for this position.'],
  ] as const)('%s', (s, expected) => {
    expect(positionStatusTooltip(s)).toBe(expected);
  });
});

describe('stockStatusTooltip — the 55/35 band, at and past each edge', () => {
  it('55 is PASS (the edge is inclusive)', () => {
    expect(stockStatusTooltip('PASS', 55)).toBe(
      'Composite stock score: 55/100 (≥55 PASS, 35-54 CAUTION, <35 REJECT — raw band: PASS). '
      + GENERIC.PASS,
    );
  });
  it('54 is CAUTION', () => {
    expect(stockStatusTooltip('CAUTION', 54)).toBe(
      'Composite stock score: 54/100 (≥55 PASS, 35-54 CAUTION, <35 REJECT — raw band: CAUTION). '
      + GENERIC.CAUTION,
    );
  });
  it('35 is CAUTION (inclusive); a REJECT badge on it says it was capped', () => {
    expect(stockStatusTooltip('REJECT', 35)).toBe(
      'Composite stock score: 35/100 (≥55 PASS, 35-54 CAUTION, <35 REJECT — raw band: CAUTION), '
      + 'capped to REJECT by a confidence/regime/fundamentals/pullback-timing gate. '
      + GENERIC.REJECT,
    );
  });
  it('34 is REJECT, uncapped', () => {
    expect(stockStatusTooltip('REJECT', 34)).toBe(
      'Composite stock score: 34/100 (≥55 PASS, 35-54 CAUTION, <35 REJECT — raw band: REJECT). '
      + GENERIC.REJECT,
    );
  });
  it('a PASS-band score shown as CAUTION is capped', () => {
    expect(stockStatusTooltip('CAUTION', 81)).toBe(
      'Composite stock score: 81/100 (≥55 PASS, 35-54 CAUTION, <35 REJECT — raw band: PASS), '
      + 'capped to CAUTION by a confidence/regime/fundamentals/pullback-timing gate. '
      + GENERIC.CAUTION,
    );
  });
});

describe('regimeStatusTooltip', () => {
  it.each([
    ['PASS',    'Regime supports fresh directional trades — broad-market health (SPX/NDX vs. 200-EMA, VIX) is aligned. Proceed as scanned.'],
    ['CAUTION', 'Regime is mixed — proceed, but position-size smaller and tighten stops than you would in a clean PASS regime.'],
    ['REJECT',  'Regime opposes fresh directional trades. Wait or fade — running a scan anyway carries elevated risk.'],
    ['PENDING', 'Regime is still being computed.'],
    ['NO_DATA', 'Not enough index/VIX history to compute a regime state.'],
  ] as const)('%s', (s, expected) => {
    expect(regimeStatusTooltip(s)).toBe(expected);
  });
});

describe('regimeMetricTooltip — the three labels backend/app/routers/regime.py emits', () => {
  it.each([
    ['VIX', 'PASS',    'VIX is in a calm band — low fear, supportive of risk-taking.'],
    ['VIX', 'CAUTION', 'VIX is elevated — markets are pricing in more uncertainty than usual.'],
    ['VIX', 'REJECT',  'VIX is spiking — high fear regime, directional trades carry outsized risk.'],
    ['VIX', 'PENDING', 'VIX level not yet available.'],
    ['SPX trend (200 EMA)', 'PASS',    'S&P 500 is trading above its 200-day EMA — the longer-term trend is up.'],
    ['SPX trend (200 EMA)', 'CAUTION', 'S&P 500 is hovering near its 200-day EMA — the longer-term trend is losing conviction.'],
    ['SPX trend (200 EMA)', 'REJECT',  'S&P 500 is trading below its 200-day EMA — the longer-term trend is down.'],
    ['SPX trend (200 EMA)', 'PENDING', 'S&P 500 trend not yet available.'],
    ['NDX trend (200 EMA)', 'PASS',    'Nasdaq 100 is trading above its 200-day EMA — the longer-term trend is up.'],
    ['NDX trend (200 EMA)', 'REJECT',  'Nasdaq 100 is trading below its 200-day EMA — the longer-term trend is down.'],
    ['NDX trend (200 EMA)', 'NO_DATA', 'Nasdaq 100 trend not yet available.'],
  ] as const)('%s / %s', (label, s, expected) => {
    expect(regimeMetricTooltip(label, s)).toBe(expected);
  });
});

describe('regimeNoDataTooltip', () => {
  it.each([
    ['insufficient_history', 'Not enough price history yet for the regime model to compute a state for this horizon.'],
    ['insufficient_data',    'Not enough price history yet for the regime model to compute a state for this horizon.'],
    ['unavailable',          'The regime model (hmmlearn) isn’t available in this environment — falling back to the order-book model where possible.'],
  ] as const)('%s', (r, expected) => {
    expect(regimeNoDataTooltip(r)).toBe(expected);
  });
});

/* ── Step 5's per-row gate tooltip ────────────────────────────────────── */

const drivers = (over: Partial<GateDrivers>): GateDrivers => ({
  iv: false, event: false, ivMissing: false, hasIv: true, ivGated: true, ...over,
});

describe('gateDriverPhrase — every arm, whole', () => {
  it.each([
    ['IV side at the gate, a reading',      drivers({ iv: true }),                                   'IV rank', 'measured checks: IV rank'],
    ['IV side at the gate, absolute basis', drivers({ iv: true }),                                   'IV',      'measured checks: IV'],
    ['IV side at the gate, no reading',     drivers({ iv: true, ivMissing: true, hasIv: false }),    'IV',      'no measured check. Missing volatility reading is not a measured driver'],
    ['event only',                          drivers({ event: true }),                                'IV rank', 'measured checks: event proximity'],
    ['both, a reading',                     drivers({ iv: true, event: true }),                      'IV rank', 'measured checks: IV rank and event proximity'],
    ['both, a reading, absolute basis',     drivers({ iv: true, event: true }),                      'IV',      'measured checks: IV and event proximity'],
    ['both, no reading',                    drivers({ iv: true, event: true, ivMissing: true, hasIv: false }), 'IV', 'measured checks: event proximity. Missing volatility reading is not a measured driver'],
    ['PASS, gated, a reading',              drivers({}),                                             'IV rank', 'nothing — this row is clear on both'],
    ['PASS, gated, no reading',             drivers({ hasIv: false }),                               'IV',      'nothing — the event window is clear, and the volatility side had no reading to judge'],
    ['PASS, ungated, a reading',            drivers({ ivGated: false }),                             'IV rank', 'nothing — the event window is clear, and this horizon does not gate on volatility'],
    ['PASS, ungated, no reading',           drivers({ ivGated: false, hasIv: false }),               'IV',      'nothing — the event window is clear, and this horizon does not gate on volatility'],
  ])('%s', (_name, d, noun, expected) => {
    expect(gateDriverPhrase(d, noun)).toBe(expected);
  });
});

describe('eventVolGateTooltip — round 7 F2: the window cannot be stated backwards', () => {
  it('Swing window, rank basis, both sides CAUTION', () => {
    expect(eventVolGateTooltip({
      ivRank: 45, ivBasis: 'rank', ivStatus: 'CAUTION',
      nextEventDays: 30, proxStatus: 'CAUTION',
      evReject: 21, evCaution: 45, gate: 'CAUTION',
      drivers: drivers({ iv: true, event: true }),
    })).toBe(
      'Gate shows the worse of IV rank and event proximity. IV rank 45 (CAUTION); '
      + "next event in 30d vs. this horizon's reject <21d / caution <45d window (CAUTION). "
      + 'Driven by: measured checks: IV rank and event proximity.',
    );
  });

  it('Position window -- both numbers come from the arguments', () => {
    expect(eventVolGateTooltip({
      ivRank: 12, ivBasis: 'rank', ivStatus: 'PASS',
      nextEventDays: 8, proxStatus: 'REJECT',
      evReject: 30, evCaution: 60, gate: 'REJECT',
      drivers: drivers({ event: true }),
    })).toBe(
      'Gate shows the worse of IV rank and event proximity. IV rank 12 (PASS); '
      + "next event in 8d vs. this horizon's reject <30d / caution <60d window (REJECT). "
      + 'Driven by: measured checks: event proximity.',
    );
  });

  it('absolute basis names the quantity "IV" and prints one decimal', () => {
    expect(eventVolGateTooltip({
      ivRank: 61.84, ivBasis: 'absolute', ivStatus: 'REJECT',
      nextEventDays: null, proxStatus: 'PASS',
      evReject: 21, evCaution: 45, gate: 'REJECT',
      drivers: drivers({ iv: true }),
    })).toBe(
      'Gate shows the worse of IV and event proximity. '
      + 'IV 61.8% — an absolute level, no rank source available (REJECT); '
      + 'no known upcoming event. Driven by: measured checks: IV.',
    );
  });

  it('no reading at all', () => {
    expect(eventVolGateTooltip({
      ivRank: null, ivBasis: 'none', ivStatus: 'CAUTION',
      nextEventDays: 50, proxStatus: 'PASS',
      evReject: 21, evCaution: 45, gate: 'CAUTION',
      drivers: drivers({ iv: true, ivMissing: true, hasIv: false }),
    })).toBe(
      'Gate shows the worse of IV and event proximity. IV: no data; '
      + "next event in 50d vs. this horizon's reject <21d / caution <45d window (PASS). "
      + 'Driven by: no measured check. Missing volatility reading is not a measured driver.',
    );
  });

  it('a clean row on a horizon that does not gate on volatility', () => {
    expect(eventVolGateTooltip({
      ivRank: 95, ivBasis: 'rank', ivStatus: 'PASS',
      nextEventDays: 4, proxStatus: 'PASS',
      evReject: 1, evCaution: 3, gate: 'PASS',
      drivers: drivers({ ivGated: false }),
    })).toBe(
      'Gate shows the worse of IV rank and event proximity. IV rank 95 (PASS); '
      + "next event in 4d vs. this horizon's reject <1d / caution <3d window (PASS). "
      + 'Driven by: nothing — the event window is clear, and this horizon does not gate on volatility.',
    );
  });
});

/* ── Backtest / win-rate cells ────────────────────────────────────────── */

describe('winRateTooltip', () => {
  it('three bands, every number from its own argument', () => {
    expect(winRateTooltip(0.47, 0.55, 0.40))
      .toBe('Historical backtest win rate: 47% (≥55% good, 40%-55% borderline, <40% weak).');
  });
  it('a second argument set', () => {
    expect(winRateTooltip(0.62, 0.50, 0.35))
      .toBe('Historical backtest win rate: 62% (≥50% good, 35%-50% borderline, <35% weak).');
  });
  it('two bands when there is no caution floor', () => {
    expect(winRateTooltip(0.38, 0.45))
      .toBe('Historical backtest win rate: 38% (≥45% good, below borderline).');
  });
});

describe('backtestGateTooltip — the three-clause gate', () => {
  const base = { winRate: 0.6, nTrades: 25, expectancy: 0.35, minWinRate: 0.5, minTrades: 20 };
  const RULE = 'Needs ≥20 historical trades, ≥50% win rate, and non-negative expectancy per trade.';

  it('PASS', () => {
    expect(backtestGateTooltip({ ...base, passes: true }))
      .toBe(`${RULE} This setup: 25 trades, 60% win rate, 0.35 expectancy. PASS.`);
  });
  it('a second argument set, so no threshold is baked in', () => {
    expect(backtestGateTooltip({
      passes: true, winRate: 0.71, nTrades: 40, expectancy: 1.2, minWinRate: 0.55, minTrades: 30,
    })).toBe(
      'Needs ≥30 historical trades, ≥55% win rate, and non-negative expectancy per trade. '
      + 'This setup: 40 trades, 71% win rate, 1.20 expectancy. PASS.',
    );
  });
  it('fails on expectancy alone, and says so', () => {
    expect(backtestGateTooltip({ ...base, expectancy: -0.12, passes: false })).toBe(
      `${RULE} This setup: 25 trades, 60% win rate, -0.12 expectancy. `
      + 'Fails on expectancy despite clearing trades/win-rate. REJECT — falls short of the gate.',
    );
  });
  it('the expectancy clause holds AT both edges (>= minTrades, >= minWinRate)', () => {
    expect(backtestGateTooltip({
      passes: false, winRate: 0.5, nTrades: 20, expectancy: -0.01, minWinRate: 0.5, minTrades: 20,
    })).toBe(
      `${RULE} This setup: 20 trades, 50% win rate, -0.01 expectancy. `
      + 'Fails on expectancy despite clearing trades/win-rate. REJECT — falls short of the gate.',
    );
  });
  it('one trade short: no expectancy clause', () => {
    expect(backtestGateTooltip({ ...base, nTrades: 19, expectancy: -0.12, passes: false })).toBe(
      `${RULE} This setup: 19 trades, 60% win rate, -0.12 expectancy. REJECT — falls short of the gate.`,
    );
  });
});

describe('stockScanGateTooltip', () => {
  it('PASS', () => {
    expect(stockScanGateTooltip({
      passes: true, winRate: 0.58, nTrades: 33, expectancy: 0.4, minWinRate: 0.45, minTrades: 15,
    })).toBe(
      'Needs ≥15 historical trades, ≥45% win rate, and non-negative expectancy per trade — same backtest gate Step 6 shows. '
      + 'This setup: 33 trades, 58% win rate, 0.40 expectancy. PASS.',
    );
  });
  it('CAUTION, a second argument set', () => {
    expect(stockScanGateTooltip({
      passes: false, winRate: 0.41, nTrades: 9, expectancy: -0.25, minWinRate: 0.5, minTrades: 20,
    })).toBe(
      'Needs ≥20 historical trades, ≥50% win rate, and non-negative expectancy per trade — same backtest gate Step 6 shows. '
      + 'This setup: 9 trades, 41% win rate, -0.25 expectancy. CAUTION — falls short of the gate.',
    );
  });
});

/* ── Contract score badges ────────────────────────────────────────────── */

function contract(over: Partial<OptionContract>): OptionContract {
  // In every preferred band unless overridden: DTE 21-60, |delta| 0.30-0.70,
  // IV rank <= 55, spread <= 8% of price, volume >= 200.
  return {
    id: 'X|100|2026-12-01|C', symbol: 'X', strike: 100, expiry: '2026-12-01', right: 'C',
    dte: 40, dteTotal: 40, price: 4, delta: 0.5, theta: -0.05,
    ivRank: 30, iv: null, ivPercentile: 30, spread: 0.2, volume: 900,
    score: 70, contractConfidence: 'PASS',
    ...over,
  } as OptionContract;
}
const CONTRACT_BASE = 'Composite contract score — combines DTE fit, delta, IV, liquidity, and spread quality.';

describe('contractScoreTooltip — each weakness, whole, and the band edges', () => {
  it('everything in range, including every inclusive edge', () => {
    for (const c of [
      contract({}),
      contract({ dte: 21 }), contract({ dte: 60 }),
      contract({ delta: 0.30 }), contract({ delta: -0.70 }),
      contract({ ivRank: 55 }),
      contract({ ivRank: null, iv: 55 }),
      contract({ spread: 0.32, price: 4 }),   // exactly 8%
      contract({ volume: 200 }),
    ]) {
      expect(contractScoreTooltip(c)).toBe(`${CONTRACT_BASE} All components are within their preferred ranges.`);
    }
  });
  it.each([
    ['DTE below',    contract({ dte: 20 }),                'DTE 20d (preferred 21-60d)'],
    ['DTE above',    contract({ dte: 61 }),                'DTE 61d (preferred 21-60d)'],
    ['delta low',    contract({ delta: 0.29 }),            'delta 0.29 (preferred 0.30-0.70)'],
    ['put delta',    contract({ delta: -0.72 }),           'delta -0.72 (preferred 0.30-0.70)'],
    ['IV rank',      contract({ ivRank: 56 }),             'IV rank 56 (prefer ≤55)'],
    ['absolute IV',  contract({ ivRank: null, iv: 61.84 }), 'IV 61.8% (prefer ≤55%)'],
    ['spread',       contract({ spread: 0.5, price: 4 }),  'spread 12.5% of price (prefer ≤8%)'],
    ['volume',       contract({ volume: 150 }),            'volume 150 (prefer ≥200)'],
  ])('%s', (_n, c, weakness) => {
    expect(contractScoreTooltip(c)).toBe(`${CONTRACT_BASE} Weakest: ${weakness}.`);
  });
  it('names the first weakness and counts the rest', () => {
    expect(contractScoreTooltip(contract({ dte: 14, delta: 0.25, ivRank: 60, spread: 0.5, volume: 150 })))
      .toBe(`${CONTRACT_BASE} Weakest: DTE 14d (preferred 21-60d) (+4 more).`);
    expect(contractScoreTooltip(contract({ delta: 0.8, volume: 10 })))
      .toBe(`${CONTRACT_BASE} Weakest: delta 0.80 (preferred 0.30-0.70) (+1 more).`);
  });
});

describe('contractBreakdownTooltip', () => {
  const b = (over: Partial<ContractScoreBreakdown>): ContractScoreBreakdown =>
    ({ dteFit: 80, delta: 75, ivAttractiveness: 70, liquidity: 65, spread: 60, ...over });

  it('no detail on the weakest: its score', () => {
    expect(contractBreakdownTooltip(b({ spread: 12 })))
      .toBe(`${CONTRACT_BASE} Weakest: spread (12/100).`);
  });
  it('the lowest wins; the first on a tie', () => {
    expect(contractBreakdownTooltip(b({ delta: 18, liquidity: 18 })))
      .toBe(`${CONTRACT_BASE} Weakest: delta (18/100).`);
  });
  it('with detail on the weakest: its detail text', () => {
    expect(contractBreakdownTooltip(b({
      dteFit: 22, dteDetail: { dte: 9, preferred_min: 21, preferred_max: 60 } as never,
    }))).toBe(`${CONTRACT_BASE} Weakest: DTE fit — 9d · target 21-60d.`);
  });
});

/* ── Regime fit, fundamentals, safety flags ───────────────────────────── */

describe('regimeFitTooltip', () => {
  it.each([
    ['PASS',    'PASS',    'Pullback EMA tends to work well in a clean regime — recommended right now.'],
    ['CAUTION', 'CAUTION', 'Pullback EMA is workable in a mixed regime but not ideal — size down or wait for confirmation.'],
    ['REJECT',  'REJECT',  'Pullback EMA tends to underperform in an unfavorable regime — avoid until conditions change.'],
    ['PASS',    'REJECT',  'Pullback EMA tends to work well in an unfavorable regime — recommended right now.'],
    ['REJECT',  'PASS',    'Pullback EMA tends to underperform in a clean regime — avoid until conditions change.'],
    ['CAUTION', 'NO_DATA', 'Pullback EMA is workable in an unfavorable regime but not ideal — size down or wait for confirmation.'],
  ] as const)('fit %s in a %s regime', (fit, regime, expected) => {
    expect(regimeFitTooltip('Pullback EMA', fit, regime)).toBe(expected);
  });
});

describe('safetyFlagTooltip', () => {
  it.each([
    ['negative_equity',  'Total liabilities exceed total assets — shareholders’ equity is negative. A serious balance-sheet red flag.'],
    ['extreme_leverage', 'Debt-to-equity ratio is far above a safe threshold — the company is heavily leveraged and more exposed to rate/earnings shocks.'],
    ['going_concern_doubt', 'Balance-sheet safety flag: going concern doubt.'],
  ])('%s', (flag, expected) => {
    expect(safetyFlagTooltip(flag)).toBe(expected);
  });
});

describe('fundamentalScoreTooltip — the stricter 65/40 band', () => {
  it.each([
    ['overall', 65, 'Overall fundamental health, 0–100 (strong). Blends growth (35%), quality (35%), and risk (30%).'],
    ['overall', 64, 'Overall fundamental health, 0–100 (middling). Blends growth (35%), quality (35%), and risk (30%).'],
    ['growth',  40, 'Growth sub-score, 0–100 (middling) — revenue/earnings trajectory from EDGAR filings.'],
    ['growth',  39, 'Growth sub-score, 0–100 (weak) — revenue/earnings trajectory from EDGAR filings.'],
    ['quality', 90, 'Quality sub-score, 0–100 (strong) — margins and profitability.'],
    ['risk',    12, 'Risk sub-score, 0–100 (weak, higher = safer) — leverage and balance-sheet strength.'],
  ] as const)('%s at %i', (kind, score, expected) => {
    expect(fundamentalScoreTooltip(kind, score)).toBe(expected);
  });
});

/* ── RiskPanel ────────────────────────────────────────────────────────── */

describe('riskStatusTooltip — per-band comparators, as riskStore.computeMetrics applies them', () => {
  // Caps chosen so 80% of each COUNT cap has a fractional part >= .5 (7 -> 5.6,
  // 12 -> 9.6): floor and round then disagree, so the comparator is actually
  // discriminated. (Round 3: a cap of 9 -> 7.2 did NOT -- floor and round are
  // both 7 -- and Math.round on the daily band shipped green.)
  const limits: RiskLimits = {
    maxTotalExposurePct: 0.5, maxConcurrentPositions: 7, maxSingleTradeExposurePct: 0.2,
    maxDailyRecommendations: 12, portfolioValue: 100_000, maxLossPerTradePct: 0.0375, maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
  };
  const m = (over: Partial<PortfolioRiskMetrics>): PortfolioRiskMetrics => ({
    totalExposurePct: 0.1, concurrentPositions: 1, dailyRecommendations: 1,
    largestConcentrationPct: 0.05, largestConcentrationSymbol: 'MSFT', stockExposurePct: 0, largestStockConcentrationPct: 0, largestStockConcentrationSymbol: '—', status: 'PASS', ...over,
  });

  it.each([
    // exposure: REJECT strictly above the cap, CAUTION strictly above 80% of it
    ['exposure', m({ totalExposurePct: 0.40 }), '40% of a 50% limit (PASS).'],
    ['exposure', m({ totalExposurePct: 0.41 }), '41% of a 50% limit (CAUTION).'],
    ['exposure', m({ totalExposurePct: 0.50 }), '50% of a 50% limit (CAUTION).'],
    ['exposure', m({ totalExposurePct: 0.51 }), '51% of a 50% limit (REJECT).'],
    // positions: REJECT at-or-above the cap, CAUTION at-or-above floor(80%) = 5
    ['positions', m({ concurrentPositions: 4 }), '4 of a 7 limit (PASS).'],
    ['positions', m({ concurrentPositions: 5 }), '5 of a 7 limit (CAUTION).'],
    ['positions', m({ concurrentPositions: 7 }), '7 of a 7 limit (REJECT).'],
    // concentration: like exposure
    ['concentration', m({ largestConcentrationPct: 0.2 }),  '20% of a 20% limit (CAUTION).'],
    ['concentration', m({ largestConcentrationPct: 0.21 }), '21% of a 20% limit (REJECT).'],
    // daily: like positions, floor(9.6) = 9
    ['daily', m({ dailyRecommendations: 8 }),  '8 of a 12 limit (PASS).'],
    ['daily', m({ dailyRecommendations: 9 }),  '9 of a 12 limit (CAUTION).'],
    ['daily', m({ dailyRecommendations: 12 }), '12 of a 12 limit (REJECT).'],
  ] as const)('%s', (metric, metrics, expected) => {
    expect(riskStatusTooltip(metrics, limits, metric)).toBe(expected);
  });

  it('all within bounds', () => {
    expect(riskStatusTooltip(m({}), limits)).toBe(
      'All portfolio risk limits (exposure, positions, concentration, daily recommendations) are comfortably within bounds.',
    );
  });
  it('names the worst band', () => {
    expect(riskStatusTooltip(m({ concurrentPositions: 5, largestConcentrationPct: 0.25 }), limits))
      .toBe('Driven by largest option position (MSFT): 25% of a 20% limit (REJECT).');
  });
  it('names a stock band against the STOCK cap (STOCK-SENDS)', () => {
    expect(riskStatusTooltip(m({ largestStockConcentrationPct: 0.25, largestStockConcentrationSymbol: 'AAPL' }), limits))
      .toBe('Driven by largest stock position (AAPL): 25% of a 20% limit (REJECT).');
    expect(riskStatusTooltip(m({ stockExposurePct: 0.9 }), limits, 'stockExposure'))
      .toBe('90% of a 100% limit (CAUTION).');
  });
  it('a CAUTION alone', () => {
    expect(riskStatusTooltip(m({ dailyRecommendations: 10 }), limits))
      .toBe('Driven by today’s recommendations: 10 of a 12 limit (CAUTION).');
  });
  it('on a tie of verdicts, the first band in panel order', () => {
    expect(riskStatusTooltip(m({ totalExposurePct: 0.6, concurrentPositions: 7 }), limits))
      .toBe('Driven by option exposure: 60% of a 50% limit (REJECT).');
  });
});

/* ── Pipeline, alerts, events, per-rule cells ─────────────────────────── */

describe('scanPipelineStatusTooltip', () => {
  it.each([
    ['IDLE',      'No scan has been run yet this session.'],
    ['SCANNING',  'Scan is currently running.'],
    ['COMPLETED', 'Scan finished successfully.'],
    ['FAILED',    'Scan failed — check backend connection or scan settings.'],
    ['PARTIAL',   'Scan completed but some candidates could not be fully scored.'],
    ['CANCELLED', 'Scan was cancelled before completion.'],
  ] as const)('%s', (s, expected) => {
    expect(scanPipelineStatusTooltip(s)).toBe(expected);
  });
});

describe('alertStatusTooltip', () => {
  it.each([
    ['Critical', 'Critical alert — needs immediate attention (e.g. a stop or invalidation level was hit).'],
    ['Action',   'Action alert — a condition worth reviewing soon (e.g. a target or gate change).'],
    ['Info',     'Informational alert — no action required.'],
  ])('%s', (k, expected) => {
    expect(alertStatusTooltip(k)).toBe(expected);
  });
});

describe('eventProximityGateTooltip', () => {
  it.each(['PASS', 'REJECT'] as const)('%s', (s) => {
    expect(eventProximityGateTooltip(s)).toBe(
      `Event-proximity gate: ${s}. Reflects how close this event is to a scan's reject/caution window for the relevant horizon.`,
    );
  });
});

describe('ruleContributionTooltip — the branches this file owns', () => {
  it('confidence: the backend interpretation when there is one', () => {
    expect(ruleContributionTooltip('confidence', 'CAUTION', { interpretation: 'Thin sample: 6 trades.' }))
      .toBe('Thin sample: 6 trades.');
  });
  it('confidence: the fixed sentence otherwise', () => {
    expect(ruleContributionTooltip('confidence', 'CAUTION', {}))
      .toBe('Backtest-based confidence gate — demotes status when historical confidence is thin.');
  });
  it('regime: conviction and stability', () => {
    expect(ruleContributionTooltip('regime', 'CAUTION', { conviction_pct: 62.4, stability: 'stable' }))
      .toBe('Regime gate — 62% conviction, stable. Demotes status when the broader regime doesn’t support this direction.');
  });
  it('regime: conviction alone, a second value', () => {
    expect(ruleContributionTooltip('regime', 'REJECT', { conviction_pct: 38.6 }))
      .toBe('Regime gate — 39% conviction. Demotes status when the broader regime doesn’t support this direction.');
  });
  it('regime: nothing to quote', () => {
    expect(ruleContributionTooltip('regime', 'REJECT', undefined))
      .toBe('Regime gate — demotes status when the broader market regime doesn’t support this direction.');
  });
  it('fundamentals', () => {
    expect(ruleContributionTooltip('fundamentals', 'REJECT', {}))
      .toBe('Fundamentals gate — demotes status for weak (or, when Bearish, unexpectedly strong) company financials.');
  });
  it('an unknown rule falls back to the generic sentence for ITS status', () => {
    expect(ruleContributionTooltip('momentum', 'CAUTION', {})).toBe(GENERIC.CAUTION);
    expect(ruleContributionTooltip('momentum', 'REJECT', {})).toBe(GENERIC.REJECT);
  });
  it('a known rule whose detail helper has nothing to say falls back the same way', () => {
    // trendDetailText({}) returns `d.method`, which is undefined here.
    expect(ruleContributionTooltip('trend', 'PASS', {})).toBe(GENERIC.PASS);
  });
});
