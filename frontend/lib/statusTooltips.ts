/*
 * statusTooltips — hover-explanation copy for every PASS/CAUTION/REJECT/PENDING/NO_DATA
 * flag in the app. Centralized here so the same status vocabulary reads the same way
 * everywhere, and so dynamic explanations (which sub-check drove a gate, which risk
 * limit is closest to its cap) stay in sync with the thresholds that actually compute
 * the badge's color instead of drifting into stale hardcoded copy.
 */
import type { Status } from '@/lib/status';
import type { OptionContract, ContractScoreBreakdown } from '@/types/domain';
import type { ScanState } from '@/lib/scanStore';
import type { PortfolioRiskMetrics, RiskLimits } from '@/types/domain';
import {
  trendDetailText,
  pullbackDetailText,
  triggerDetailText,
  eventDetailText,
  volDetailText,
  dteDetailText,
  deltaDetailText,
  ivDetailText,
  liquidityDetailText,
  spreadDetailText,
} from '@/lib/scoreDetailText';
import type { TrendDetail, PullbackDetail, TriggerDetail, EventDetail, VolDetail } from '@/types/domain';

/** Generic composite-score explanation — the fallback for any bare Status badge
 *  that has no richer domain-specific reason available at its call site. */
export const GENERIC_STATUS_TOOLTIP: Record<Status, string> = {
  PASS:    'Strong signal — all key scoring components cleared the threshold. Good base to proceed at normal size.',
  CAUTION: 'Borderline signal — qualifies but has notable weaknesses. Review the component breakdown before committing capital.',
  REJECT:  'Signal below the quality gate. Consider skipping this candidate or waiting for a cleaner setup.',
  PENDING: 'Scoring is still in progress. Status will update once all components are evaluated.',
  NO_DATA: 'Insufficient price or volume data to score this.',
};

/** Portfolio table's per-position status badge. Deliberately NOT the same copy as
 *  GENERIC_STATUS_TOOLTIP — that wording ("skip this candidate", "proceed at normal
 *  size") is written for a not-yet-entered scan candidate, not a position already
 *  held. lib/portfolioStore.ts currently sets every position's `status` to 'PENDING'
 *  at creation and never updates it, so the PENDING case is the one that will
 *  actually render in practice — its copy says so honestly instead of implying a
 *  live scoring process that will "update soon" (it won't). */
export function positionStatusTooltip(status: Status): string {
  switch (status) {
    case 'PASS':    return 'Position status: healthy — no known issues since entry.';
    case 'CAUTION': return 'Position status: flagged — review this position, something about it warrants a closer look.';
    case 'REJECT':  return 'Position status: at risk — this position has triggered a warning condition.';
    case 'PENDING': return 'Position status is not actively tracked post-entry — this reflects the state at order time, not a live re-score.';
    case 'NO_DATA': return 'No status data available for this position.';
  }
}

/** Composite stock-score badge with the actual score attached (Step 7 Position Card).
 *  The score->status band mapping (55/35, backend/app/scoring/stock_scorer.py's
 *  _status_from_score) is only the STARTING verdict — four demote-only gates
 *  (pullback timing veto, confidence, regime, fundamentals) can cap it lower
 *  server-side, so a CAUTION/REJECT badge doesn't necessarily mean the raw score
 *  itself was borderline. Don't state the band as the sole explanation. */
export function stockStatusTooltip(status: Status, score: number): string {
  const band = score >= 55 ? 'PASS' : score >= 35 ? 'CAUTION' : 'REJECT';
  const capped = band !== status;
  return `Composite stock score: ${score}/100 (≥55 PASS, 35-54 CAUTION, <35 REJECT — raw band: ${band})`
    + (capped ? `, capped to ${status} by a confidence/regime/fundamentals/pullback-timing gate.` : '.')
    + ` ${GENERIC_STATUS_TOOLTIP[status]}`;
}

/** Regime-specific wording — distinct from the generic composite-score copy above. */
export function regimeStatusTooltip(status: Status): string {
  switch (status) {
    case 'PASS':    return 'Regime supports fresh directional trades — broad-market health (SPX/NDX vs. 200-EMA, VIX) is aligned. Proceed as scanned.';
    case 'CAUTION': return 'Regime is mixed — proceed, but position-size smaller and tighten stops than you would in a clean PASS regime.';
    case 'REJECT':  return 'Regime opposes fresh directional trades. Wait or fade — running a scan anyway carries elevated risk.';
    case 'PENDING': return 'Regime is still being computed.';
    case 'NO_DATA': return 'Not enough index/VIX history to compute a regime state.';
  }
}

/** Per-metric explanation for the SPX/NDX-vs-200-EMA and VIX metric-grid badges.
 *  `label` is one of the 3 literal strings backend/app/routers/regime.py emits. */
export function regimeMetricTooltip(label: string, status: Status): string {
  if (label.includes('VIX')) {
    switch (status) {
      case 'PASS':    return 'VIX is in a calm band — low fear, supportive of risk-taking.';
      case 'CAUTION': return 'VIX is elevated — markets are pricing in more uncertainty than usual.';
      case 'REJECT':  return 'VIX is spiking — high fear regime, directional trades carry outsized risk.';
      default:        return 'VIX level not yet available.';
    }
  }
  const index = label.includes('NDX') ? 'Nasdaq 100' : 'S&P 500';
  switch (status) {
    case 'PASS':    return `${index} is trading above its 200-day EMA — the longer-term trend is up.`;
    case 'CAUTION': return `${index} is hovering near its 200-day EMA — the longer-term trend is losing conviction.`;
    case 'REJECT':  return `${index} is trading below its 200-day EMA — the longer-term trend is down.`;
    default:        return `${index} trend not yet available.`;
  }
}

/** Why a horizon's regime state couldn't be computed. */
export function regimeNoDataTooltip(reason: 'insufficient_data' | 'unavailable' | 'insufficient_history'): string {
  switch (reason) {
    case 'insufficient_history':
    case 'insufficient_data':
      return 'Not enough price history yet for the regime model to compute a state for this horizon.';
    case 'unavailable':
      return 'The regime model (hmmlearn) isn’t available in this environment — falling back to the order-book model where possible.';
  }
}

/** Step 5 Vol+Events GATE badge — composes which of IV rank vs. event proximity
 *  drove the worst-status result, quoting the live per-horizon window. */
export function eventVolGateTooltip(args: {
  ivRank: number | null;
  ivStatus: Status;
  nextEventDays: number | null;
  proxStatus: Status;
  evReject: number;
  evCaution: number;
  gate: Status;
}): string {
  const { ivRank, ivStatus, nextEventDays, proxStatus, evReject, evCaution, gate } = args;
  const ivPart = ivRank == null
    ? 'IV rank: no data'
    : `IV rank ${ivRank} (${ivStatus})`;
  const evPart = nextEventDays == null
    ? 'no known upcoming event'
    : `next event in ${nextEventDays}d vs. this horizon's reject <${evReject}d / caution <${evCaution}d window (${proxStatus})`;
  const driver = gate === ivStatus && gate !== proxStatus ? 'IV rank' : gate === proxStatus && gate !== ivStatus ? 'event proximity' : 'both';
  return `Gate shows the worse of IV rank and event proximity. ${ivPart}; ${evPart}. Driven by: ${driver}.`;
}

/** Bare win-rate cells that sit next to (but separately from) a GATE badge — several
 *  pages show the historical backtest win rate with its own color bands that don't
 *  always match the neighboring gate's threshold; state this cell's own band rather
 *  than imply it's the gate. */
export function winRateTooltip(winRate: number, passMin: number, cautionMin?: number): string {
  const pct = (n: number) => `${(n * 100).toFixed(0)}%`;
  const bands = cautionMin != null
    ? `≥${pct(passMin)} good, ${pct(cautionMin)}-${pct(passMin)} borderline, <${pct(cautionMin)} weak`
    : `≥${pct(passMin)} good, below borderline`;
  return `Historical backtest win rate: ${pct(winRate)} (${bands}).`;
}

/** Step 6 Backtest GATE badge — mirrors backend/app/services/strategy_backtest.py's
 *  `passes = win_rate >= min_win_rate and n_trades >= min_trades and expectancy >= 0`.
 *  All three clauses must hold — quoting only trades/win-rate produces a
 *  self-contradictory tooltip whenever a negative-expectancy setup fails the
 *  gate despite clearing the other two. */
export function backtestGateTooltip(args: {
  passes: boolean;
  winRate: number;
  nTrades: number;
  expectancy: number;
  minWinRate: number;
  minTrades: number;
}): string {
  const { passes, winRate, nTrades, expectancy, minWinRate, minTrades } = args;
  const rule = `Needs ≥${minTrades} historical trades, ≥${(minWinRate * 100).toFixed(0)}% win rate, and non-negative expectancy per trade.`;
  const actual = `This setup: ${nTrades} trades, ${(winRate * 100).toFixed(0)}% win rate, ${expectancy.toFixed(2)} expectancy.`;
  const why = !passes && nTrades >= minTrades && winRate >= minWinRate && expectancy < 0
    ? ' Fails on expectancy despite clearing trades/win-rate.'
    : '';
  return `${rule} ${actual}${why} ${passes ? 'PASS.' : 'REJECT — falls short of the gate.'}`;
}

/** Step 4 Stocks GATE column — this is the SAME `passes_gate` field Step 6 shows,
 *  not a separate earlier-stage gate; the row only *lists* candidates down to a
 *  40% win rate (see the filter above this table), it doesn't change the gate. */
export function stockScanGateTooltip(args: {
  passes: boolean;
  winRate: number;
  nTrades: number;
  expectancy: number;
  minWinRate: number;
  minTrades: number;
}): string {
  const { passes, winRate, nTrades, expectancy, minWinRate, minTrades } = args;
  const rule = `Needs ≥${minTrades} historical trades, ≥${(minWinRate * 100).toFixed(0)}% win rate, and non-negative expectancy per trade — same backtest gate Step 6 shows.`;
  const actual = `This setup: ${nTrades} trades, ${(winRate * 100).toFixed(0)}% win rate, ${expectancy.toFixed(2)} expectancy.`;
  return `${rule} ${actual} ${passes ? 'PASS.' : 'CAUTION — falls short of the gate.'}`;
}

// Soft-rank preferred bands mirrored from backend/config/contract_rules.yaml
// (no live endpoint for these — same reasoning as eventThresholdsStore's FALLBACK).
const CONTRACT_PREFERRED = {
  dte: { min: 21, max: 60 },
  delta: { min: 0.30, max: 0.70 },
  ivRankMax: 55,
  spreadPctMax: 0.08,
  volumeMin: 200,
};

/** Step 6 Contracts / Watchlist Contracts-tab per-contract score badge.
 *  OptionContract carries no per-component detail objects (those only exist on
 *  ContractScoreBreakdown for TradeCardData/AlternativeContract), so this is a
 *  best-effort heuristic over the fields OptionContract actually has. */
export function contractScoreTooltip(c: OptionContract): string {
  const spreadPct = c.price > 0 ? c.spread / c.price : 0;
  const weaknesses: string[] = [];
  if (c.dte < CONTRACT_PREFERRED.dte.min || c.dte > CONTRACT_PREFERRED.dte.max) {
    weaknesses.push(`DTE ${c.dte}d (preferred ${CONTRACT_PREFERRED.dte.min}-${CONTRACT_PREFERRED.dte.max}d)`);
  }
  if (Math.abs(c.delta) < CONTRACT_PREFERRED.delta.min || Math.abs(c.delta) > CONTRACT_PREFERRED.delta.max) {
    weaknesses.push(`delta ${c.delta.toFixed(2)} (preferred ${CONTRACT_PREFERRED.delta.min.toFixed(2)}-${CONTRACT_PREFERRED.delta.max.toFixed(2)})`);
  }
  if (c.ivRank > CONTRACT_PREFERRED.ivRankMax) {
    weaknesses.push(`IV rank ${c.ivRank} (prefer ≤${CONTRACT_PREFERRED.ivRankMax})`);
  }
  if (spreadPct > CONTRACT_PREFERRED.spreadPctMax) {
    weaknesses.push(`spread ${(spreadPct * 100).toFixed(1)}% of price (prefer ≤${(CONTRACT_PREFERRED.spreadPctMax * 100).toFixed(0)}%)`);
  }
  if (c.volume < CONTRACT_PREFERRED.volumeMin) {
    weaknesses.push(`volume ${c.volume.toLocaleString()} (prefer ≥${CONTRACT_PREFERRED.volumeMin.toLocaleString()})`);
  }
  const base = 'Composite contract score — combines DTE fit, delta, IV rank, liquidity, and spread quality.';
  if (weaknesses.length === 0) return `${base} All components are within their preferred ranges.`;
  return `${base} Weakest: ${weaknesses[0]}${weaknesses.length > 1 ? ` (+${weaknesses.length - 1} more)` : ''}.`;
}

/** AlternativeContractRow's contractConfidence badge. Unlike contractScoreTooltip
 *  above (OptionContract, no per-component detail), AlternativeContract carries a
 *  full ContractScoreBreakdown — use the real sub-scores/detail objects instead of
 *  re-deriving a heuristic. `alt.reason` (rendered separately, already visible)
 *  explains the trade-off vs. the primary contract, not the confidence verdict —
 *  don't reuse it here. */
export function contractBreakdownTooltip(b: ContractScoreBreakdown): string {
  const components: Array<{ label: string; score: number; text?: string }> = [
    { label: 'DTE fit', score: b.dteFit, text: dteDetailText(b.dteDetail) },
    { label: 'delta', score: b.delta, text: deltaDetailText(b.deltaDetail) },
    { label: 'IV rank', score: b.ivAttractiveness, text: ivDetailText(b.ivDetail) },
    { label: 'liquidity', score: b.liquidity, text: liquidityDetailText(b.liquidityDetail) },
    { label: 'spread', score: b.spread, text: spreadDetailText(b.spreadDetail) },
  ];
  const weakest = components.reduce((min, c) => (c.score < min.score ? c : min), components[0]);
  const base = 'Composite contract score — combines DTE fit, delta, IV rank, liquidity, and spread quality.';
  return weakest.text
    ? `${base} Weakest: ${weakest.label} — ${weakest.text}.`
    : `${base} Weakest: ${weakest.label} (${weakest.score}/100).`;
}

export type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';

/** Step 5 Strategy / Step 4 Stocks "Recommended/Neutral/Avoid" regime-fit badge.
 *  (Step 2 Universe's picker cards are a different concept — today's index/sector
 *  price move, not a strategy's fit to the regime — and have their own local
 *  `cardStatusTooltip` in step-2-universe/page.tsx.) */
export function regimeFitTooltip(strategyLabel: string, fit: RegimeFit, regimeStatus: Status): string {
  const regimeWord = regimeStatus === 'PASS' ? 'a clean' : regimeStatus === 'CAUTION' ? 'a mixed' : 'an unfavorable';
  switch (fit) {
    case 'PASS':    return `${strategyLabel} tends to work well in ${regimeWord} regime — recommended right now.`;
    case 'CAUTION': return `${strategyLabel} is workable in ${regimeWord} regime but not ideal — size down or wait for confirmation.`;
    case 'REJECT':  return `${strategyLabel} tends to underperform in ${regimeWord} regime — avoid until conditions change.`;
  }
}

const SAFETY_FLAG_TOOLTIP: Record<string, string> = {
  negative_equity: 'Total liabilities exceed total assets — shareholders’ equity is negative. A serious balance-sheet red flag.',
  extreme_leverage: 'Debt-to-equity ratio is far above a safe threshold — the company is heavily leveraged and more exposed to rate/earnings shocks.',
};

/** Lookup for FundamentalHealthCard's safety-flag chips. Falls back to a generic
 *  message for any flag not in the known list (currently exhaustive per
 *  backend/app/scoring/fundamentals_scorer.py). */
export function safetyFlagTooltip(flag: string): string {
  return SAFETY_FLAG_TOOLTIP[flag] ?? `Balance-sheet safety flag: ${flag.replace(/_/g, ' ')}.`;
}

/** FundamentalHealthCard's 4 score cells (overall/growth/quality/risk). */
export function fundamentalScoreTooltip(kind: 'overall' | 'growth' | 'quality' | 'risk', score: number): string {
  const band = score >= 65 ? 'strong' : score >= 40 ? 'middling' : 'weak';
  switch (kind) {
    case 'overall': return `Overall fundamental health, 0–100 (${band}). Blends growth (35%), quality (35%), and risk (30%).`;
    case 'growth':  return `Growth sub-score, 0–100 (${band}) — revenue/earnings trajectory from EDGAR filings.`;
    case 'quality': return `Quality sub-score, 0–100 (${band}) — margins and profitability.`;
    case 'risk':    return `Risk sub-score, 0–100 (${band}, higher = safer) — leverage and balance-sheet strength.`;
  }
}

/** RiskPanel's combined RiskBadge, and (with `metric` set) each of the 4 individual Stat cells.
 *  Comparators mirror lib/riskStore.ts's computeMetrics exactly (per-band, not uniform):
 *  exposure/concentration reject strictly above the cap; positions/daily reject at-or-above
 *  it and floor their 80% caution threshold — using a single `>= cap` rule for all four (as
 *  an earlier version of this function did) makes the badge color and the tooltip disagree
 *  right at the boundary. */
export function riskStatusTooltip(
  metrics: PortfolioRiskMetrics,
  limits: RiskLimits,
  metric?: 'exposure' | 'positions' | 'concentration' | 'daily',
): string {
  const bands: Array<{
    key: 'exposure' | 'positions' | 'concentration' | 'daily';
    label: string;
    value: number;
    cap: number;
    fmt: (n: number) => string;
    statusFor: (value: number, cap: number) => Status;
  }> = [
    {
      key: 'exposure', label: 'total exposure', value: metrics.totalExposurePct, cap: limits.maxTotalExposurePct,
      fmt: (n) => `${(n * 100).toFixed(0)}%`,
      statusFor: (v, c) => v > c ? 'REJECT' : v > c * 0.8 ? 'CAUTION' : 'PASS',
    },
    {
      key: 'positions', label: 'concurrent positions', value: metrics.concurrentPositions, cap: limits.maxConcurrentPositions,
      fmt: (n) => `${n}`,
      statusFor: (v, c) => v >= c ? 'REJECT' : v >= Math.floor(c * 0.8) ? 'CAUTION' : 'PASS',
    },
    {
      key: 'concentration', label: `largest position (${metrics.largestConcentrationSymbol})`, value: metrics.largestConcentrationPct, cap: limits.maxSingleTradeExposurePct,
      fmt: (n) => `${(n * 100).toFixed(0)}%`,
      statusFor: (v, c) => v > c ? 'REJECT' : v > c * 0.8 ? 'CAUTION' : 'PASS',
    },
    {
      key: 'daily', label: 'today’s recommendations', value: metrics.dailyRecommendations, cap: limits.maxDailyRecommendations,
      fmt: (n) => `${n}`,
      statusFor: (v, c) => v >= c ? 'REJECT' : v >= Math.floor(c * 0.8) ? 'CAUTION' : 'PASS',
    },
  ];

  if (metric) {
    const b = bands.find((x) => x.key === metric)!;
    const s = b.statusFor(b.value, b.cap);
    return `${b.fmt(b.value)} of a ${b.fmt(b.cap)} limit (${s}).`;
  }

  const worst = bands
    .map((b) => ({ ...b, status: b.statusFor(b.value, b.cap) }))
    .sort((a, b2) => (a.status === 'REJECT' ? 0 : a.status === 'CAUTION' ? 1 : 2) - (b2.status === 'REJECT' ? 0 : b2.status === 'CAUTION' ? 1 : 2))[0];
  if (worst.status === 'PASS') return 'All portfolio risk limits (exposure, positions, concentration, daily recommendations) are comfortably within bounds.';
  return `Driven by ${worst.label}: ${worst.fmt(worst.value)} of a ${worst.fmt(worst.cap)} limit (${worst.status}).`;
}

/** contextRail "Option scan"/"Stock scan" rows and ScanIndicator's dot — a different
 *  axis from the trading-signal Status: "did the scan job run," not a score verdict. */
export function scanPipelineStatusTooltip(scanState: ScanState): string {
  switch (scanState) {
    case 'IDLE':      return 'No scan has been run yet this session.';
    case 'SCANNING':  return 'Scan is currently running.';
    case 'COMPLETED': return 'Scan finished successfully.';
    case 'FAILED':    return 'Scan failed — check backend connection or scan settings.';
    case 'PARTIAL':   return 'Scan completed but some candidates could not be fully scored.';
    case 'CANCELLED': return 'Scan was cancelled before completion.';
  }
}

/** contextRail "Latest Alert" badge — explains the alert kind, not the reason
 *  (the reason is already shown as adjacent visible text). */
export function alertStatusTooltip(kind: string): string {
  if (kind === 'Critical') return 'Critical alert — needs immediate attention (e.g. a stop or invalidation level was hit).';
  if (kind === 'Action')   return 'Action alert — a condition worth reviewing soon (e.g. a target or gate change).';
  return 'Informational alert — no action required.';
}

/** calendar page's per-event dot and the contextRail "Upcoming Events" dot — same
 *  copy, deduped here instead of the two call sites carrying their own literal. */
export function eventProximityGateTooltip(status: Status): string {
  return `Event-proximity gate: ${status}. Reflects how close this event is to a scan's reject/caution window for the relevant horizon.`;
}

/** Analysis page per-rule cards and ValidationTable's five per-rule cells.
 *  Backend rule names (backend/app/scoring/stock_scorer.py) are lowercase:
 *  trend/pullback/trigger/event/vol, plus up to 3 gate-appended rules:
 *  confidence/regime/fundamentals. */
export function ruleContributionTooltip(name: string, status: Status, detail: Record<string, unknown> | undefined): string {
  const d = detail ?? {};
  switch (name) {
    case 'trend':     return trendDetailText(d as unknown as TrendDetail) ?? GENERIC_STATUS_TOOLTIP[status];
    case 'pullback':  return pullbackDetailText(d as unknown as PullbackDetail) ?? GENERIC_STATUS_TOOLTIP[status];
    case 'trigger':   return triggerDetailText(d as unknown as TriggerDetail) ?? GENERIC_STATUS_TOOLTIP[status];
    case 'event':     return eventDetailText(d as unknown as EventDetail) ?? GENERIC_STATUS_TOOLTIP[status];
    case 'vol':       return volDetailText(d as unknown as VolDetail) ?? GENERIC_STATUS_TOOLTIP[status];
    case 'confidence': {
      const interpretation = typeof d.interpretation === 'string' ? d.interpretation : undefined;
      return interpretation ?? 'Backtest-based confidence gate — demotes status when historical confidence is thin.';
    }
    case 'regime': {
      const pct = typeof d.conviction_pct === 'number' ? d.conviction_pct : undefined;
      const stability = typeof d.stability === 'string' ? d.stability : undefined;
      return pct != null
        ? `Regime gate — ${pct.toFixed(0)}% conviction${stability ? `, ${stability}` : ''}. Demotes status when the broader regime doesn’t support this direction.`
        : 'Regime gate — demotes status when the broader market regime doesn’t support this direction.';
    }
    case 'fundamentals':
      return 'Fundamentals gate — demotes status for weak (or, when Bearish, unexpectedly strong) company financials.';
    default:
      return GENERIC_STATUS_TOOLTIP[status];
  }
}
