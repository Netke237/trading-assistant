import type { OptionsPipeline, RejectedEntry } from './scanStore';
import type { DteWindow } from '@/types/domain';

// Turns the options scan's pipeline counters and rejected list into the
// staged drop-off model the PipelineInspector renders.
//
// Everything here is DERIVED from what the backend recorded — nothing is
// estimated. Where the backend gave a count but no per-symbol reasons for a
// stage (an older stored result, a truncated list), a sub-rule's count is
// `null` and renders as "—"; it is never apportioned by a fixed ratio. Where
// the stage counts do not add up to scanned − survivors (a result stored
// before a counter existed), the gap is shown as "Not attributed", never
// folded into a stage. Rule thresholds appear in a label only when the scan
// echoed them in `contract_rules` (the Step-3 overrides); otherwise the label
// names the rule and the YAML it lives in, never a literal that can drift.
//
// The reason strings matched below are the backend's, in
// backend/app/routers/scan.py (the `_is_*` bucket predicates around the
// OptionsPipeline build) and backend/app/scoring/contract_validator.py (the
// hard-reject codes). Change one there and the matching table here must move
// with it — the parser tests are written against those exact strings.

// Mirrors backend `_SHORTLIST_REASON_PREFIX` (and scanLogTotals' SHORTLIST_REASON_PREFIX).
const SHORTLIST_PREFIX = 'Shortlist cap:';
const DIRECTION_PREFIX = 'direction_conviction:';
const DIRECTION_UNMEASURED_PREFIX = 'direction_conviction_unmeasured:';

export type StageId =
  | 'errors'
  | 'data-filters'
  | 'pre-screen'
  | 'chain-window'
  | 'contract-rules'
  | 'direction-shortlist';

export interface DiagnosticSubRule {
  id: string;
  label: string;
  /** Symbols this rule removed; null when the stage has a count but no
   *  per-symbol reasons to attribute it with. */
  count: number | null;
  ruleExplanation: string;
  symbols: string[];
}

export interface DiagnosticStage {
  id: StageId;
  title: string;
  droppedCount: number;
  remainingCount: number;
  pctOfTotal: number;
  isBottleneck: boolean;
  ruleSummary: string;
  subRules: DiagnosticSubRule[];
  allSymbols: string[];
  /** Set when the stage's sub-rule counts cannot be read as a partition —
   *  missing reasons, extra reasons, or one symbol counted under several rules. */
  note?: string;
}

export interface SymbolDiagnosticResult {
  symbol: string;
  status: 'SURVIVOR' | 'REJECTED';
  stageName: string;
  primaryReason: string;
  detailedReason: string;
  breakdown?: Record<string, number>;
  /** The lowest WEIGHTED component in the breakdown (gate-cap entries excluded). */
  weakestComponent?: string;
}

export interface PrimaryBottleneck {
  stageId: StageId;
  stageTitle: string;
  droppedCount: number;
  pctOfTotal: number;
  insight: string;
  suggestedAction: string;
  adjustHref: string | null;
  adjustLabel: string | null;
}

export interface PipelineDiagnosticReport {
  scanned: number;
  candidatesCount: number;
  /** scanned − survivors: everything not ranked, shortlist trims included. */
  totalDropped: number;
  /** null when nothing was dropped — there is no bottleneck to name. */
  primaryBottleneck: PrimaryBottleneck | null;
  stages: DiagnosticStage[];
  /** Set when the stage counts exceed scanned − survivors (inconsistent counters). */
  reconciliationNote?: string;
  asciiTree: string;
  /** null = the symbol is neither a survivor nor in the recorded rejects. */
  lookupSymbol: (ticker: string) => SymbolDiagnosticResult | null;
}

export interface PipelineDiagnosticOptions {
  /** `ScanResult.contract_rules` — the Step-3 contract-rule overrides the scan applied. */
  contractRules?: Record<string, number> | null;
  /** `ScanResult.dte_window` — the scan's expiry window. */
  dteWindow?: DteWindow;
}

// ── Classification ──────────────────────────────────────────────────────────

/** The weighted score components. The breakdown also carries gate-cap
 *  entries (`regime` is always 0, `fundamentals` and `confidence` are on
 *  other scales) — those are not components and are never "weakest". */
const WEIGHTED_COMPONENTS = ['trend', 'pullback', 'trigger', 'event', 'vol'];
const COMPONENT_LABELS: Record<string, string> = {
  trend: 'Trend', pullback: 'Pullback', trigger: 'Trigger', event: 'Event', vol: 'Vol',
};

/** The lowest-scoring weighted component; ties go to the earlier component.
 *  `excludeVol` for the pre-screen, which scores vol with no IV — a fixed
 *  placeholder, not a measurement. */
export function weakestComponent(bd?: Record<string, number>, excludeVol = false): string | undefined {
  if (!bd) return undefined;
  const keys = WEIGHTED_COMPONENTS.filter(
    (k) => Number.isFinite(bd[k]) && !(excludeVol && k === 'vol'),
  );
  if (keys.length === 0) return undefined;
  return keys.reduce((best, k) => (bd[k] < bd[best] ? k : best));
}

/** Contract-validator reject code → sub-rule id (one per threshold). */
const CONTRACT_CODE_RULE: Record<string, string> = {
  stock_score_below_threshold: 'min-stock-score',
  spread_too_wide: 'spread',
  volume_too_low: 'volume',
  open_interest_too_low: 'oi',
  delta_too_low_far_otm: 'delta-low',
  delta_too_high_deep_itm: 'delta-high',
  iv_too_high: 'iv-abs',
  iv_rank_too_high: 'iv-rank',
  dte_too_short: 'dte',
  dte_too_long: 'dte',
  contract_score_below_caution: 'low-score',
  too_many_soft_failures: 'soft-failures',
};

/** The reject codes in a "contracts rejected: code(n), code(n); best …" reason. */
export function contractCodes(reason: string): string[] {
  const i = reason.indexOf('contracts rejected:');
  if (i === -1) return [];
  const detail = reason.slice(i + 'contracts rejected:'.length).split(';')[0];
  return Array.from(detail.matchAll(/([a-z_]+)\(\d+\)/g), (m) => m[1]);
}

interface Classified {
  stage: StageId;
  subRules: string[];
}

export function classifyReason(entry: RejectedEntry): Classified {
  const reason = entry.reason ?? '';
  if (reason.includes('price filter')) return { stage: 'data-filters', subRules: ['price'] };
  if (reason.includes('cap filter')) return { stage: 'data-filters', subRules: ['cap'] };
  if (reason.includes('no market data') || reason.startsWith('regime data unavailable:')) {
    return { stage: 'data-filters', subRules: ['missing-data'] };
  }
  if (reason.startsWith('Pre-screen:')) {
    const weak = weakestComponent(entry.breakdown, true);
    return { stage: 'pre-screen', subRules: [weak ? `weak-${weak}` : 'no-breakdown'] };
  }
  if (reason.startsWith(DIRECTION_UNMEASURED_PREFIX)) return { stage: 'pre-screen', subRules: ['trend-unmeasured'] };
  if (reason === 'no option chain') return { stage: 'chain-window', subRules: ['no-chain'] };
  if (reason.startsWith('Score gate:')) return { stage: 'contract-rules', subRules: ['score-gate'] };
  if (reason.includes('contracts rejected')) {
    const rules = new Set<string>();
    for (const code of contractCodes(reason)) rules.add(CONTRACT_CODE_RULE[code] ?? 'other-contract');
    if (rules.size === 0) rules.add('other-contract');   // "all contracts rejected", no codes
    return { stage: 'contract-rules', subRules: Array.from(rules) };
  }
  if (reason.startsWith(DIRECTION_PREFIX)) return { stage: 'direction-shortlist', subRules: ['direction'] };
  if (reason.startsWith(SHORTLIST_PREFIX)) return { stage: 'direction-shortlist', subRules: ['shortlist'] };
  // The backend's residual bucket (`other_rejected`): per-symbol exceptions —
  // often an empty reason — and any reason no predicate matches. These can
  // happen at ANY step, so they are not placed in the funnel's order.
  return { stage: 'errors', subRules: ['unclassified'] };
}

// ── Labels ──────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(4)));
}

function ruleValue(rules: Record<string, number> | null | undefined, key: string): number | undefined {
  const v = rules?.[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

interface SubRuleDef { id: string; label: string; explanation: string }

const STATUS_CAVEAT = 'REJECT comes from the score band or from a demote-only gate cap (regime, fundamentals, confidence); the recorded breakdown cannot tell which.';

function contractSubRuleDefs(rules: Record<string, number> | null | undefined): SubRuleDef[] {
  // One sub-rule per threshold, so a label's threshold is the one its symbols failed.
  const thresholdRule = (
    id: string, base: string, key: string, render: (v: number) => string, what: string,
  ): SubRuleDef => {
    const v = ruleValue(rules, key);
    return {
      id,
      label: v !== undefined ? `${base} (${render(v)})` : base,
      explanation: `${what} ${v !== undefined
        ? 'Threshold: the Step-3 override this scan recorded.'
        : `Threshold: contract_rules.yaml \`${key}\` (no Step-3 override recorded for this scan).`}`,
    };
  };
  return [
    { id: 'score-gate', label: 'Score Gate (re-scored with IV)',
      explanation: `Re-scored once the chain supplied IV, and the status was REJECT. ${STATUS_CAVEAT}` },
    thresholdRule('min-stock-score', 'Stock Score Below Contract Minimum', 'min_stock_score',
      (v) => `< ${fmtNum(v)}`, 'Every contract was rejected because the stock score is below the minimum the contract rules require.'),
    thresholdRule('spread', 'Spread Too Wide', 'max_bid_ask_spread_pct',
      (v) => `> ${fmtNum(v * 100)}% of mid`, 'Bid-ask spread as a share of mid above the maximum.'),
    thresholdRule('volume', 'Volume Too Low', 'min_volume',
      (v) => `< ${fmtNum(v)}`, 'Daily contract volume below the floor.'),
    thresholdRule('oi', 'Open Interest Too Low', 'min_open_interest',
      (v) => `< ${fmtNum(v)}`, 'Open interest below the floor.'),
    thresholdRule('delta-low', 'Delta Too Low (far OTM)', 'min_delta',
      (v) => `< ${fmtNum(v)}`, 'Absolute delta below the floor.'),
    thresholdRule('delta-high', 'Delta Too High (deep ITM)', 'max_delta',
      (v) => `> ${fmtNum(v)}`, 'Absolute delta above the cap.'),
    thresholdRule('iv-abs', 'Absolute IV Above Ceiling', 'max_iv_abs',
      (v) => `> ${fmtNum(v)}`, 'Absolute implied volatility above the ceiling.'),
    thresholdRule('iv-rank', 'IV Rank Above Ceiling', 'max_iv_rank',
      (v) => `> ${fmtNum(v)}`, 'IV rank (a true percentile) above the ceiling.'),
    { id: 'dte', label: 'Expiry Outside DTE Limits',
      explanation: 'Contract expiry shorter or longer than the validator\'s DTE limits (widened for the hold window).' },
    { id: 'low-score', label: 'Contract Score Below Caution',
      explanation: 'Contracts cleared every hard rule but scored below the caution threshold.' },
    { id: 'soft-failures', label: 'Too Many Soft Failures',
      explanation: 'Contracts missed too many preferred (soft) thresholds.' },
    { id: 'other-contract', label: 'Other / Unnamed Contract Rejects',
      explanation: 'All contracts rejected with no reason code, or with a code this view does not recognise.' },
  ];
}

// ── Report ──────────────────────────────────────────────────────────────────

function pct(part: number, whole: number): number {
  return whole > 0 ? Math.round((part / whole) * 100) : 0;
}

function finite(n: number | null | undefined): number | undefined {
  return typeof n === 'number' && Number.isFinite(n) ? n : undefined;
}

export function parsePipelineDiagnostics(
  pipeline?: OptionsPipeline,
  rejected: RejectedEntry[] = [],
  survivorSymbols: string[] = [],
  options: PipelineDiagnosticOptions = {},
): PipelineDiagnosticReport {
  const candidatesCount = survivorSymbols.length;
  const scanned = finite(pipeline?.scanned) ?? rejected.length + candidatesCount;
  const totalDropped = Math.max(0, scanned - candidatesCount);

  // symbol → entry, and stage/sub-rule → symbols
  const symbolMap = new Map<string, RejectedEntry>();
  const bySub = new Map<string, string[]>();      // `${stage}/${sub}` → symbols
  const byStage = new Map<StageId, string[]>();
  for (const r of rejected) {
    const sym = r.symbol.toUpperCase();
    symbolMap.set(sym, r);
    const c = classifyReason(r);
    const st = byStage.get(c.stage) ?? [];
    st.push(sym);
    byStage.set(c.stage, st);
    for (const s of c.subRules) {
      const key = `${c.stage}/${s}`;
      const list = bySub.get(key) ?? [];
      list.push(sym);
      bySub.set(key, list);
    }
  }
  const syms = (stage: StageId) => byStage.get(stage) ?? [];
  const subSyms = (stage: StageId, sub: string) => bySub.get(`${stage}/${sub}`) ?? [];
  const listed = (stage: StageId, sub: string) => subSyms(stage, sub).length;

  // Stage counts: the backend's counter when present, else the reasons we hold.
  const p = pipeline;
  const unmeasuredListed = listed('pre-screen', 'trend-unmeasured');
  const unmeasuredCounter = finite(p?.failed_direction_unmeasured);
  const unmeasuredCount = unmeasuredCounter ?? unmeasuredListed;
  const dataCount = finite(p?.failed_data) ?? syms('data-filters').length;
  const preCount = (finite(p?.failed_pre_screen) ?? syms('pre-screen').length - unmeasuredListed) + unmeasuredCount;
  const chainCount = finite(p?.no_chain) ?? syms('chain-window').length;
  const scoreCount = finite(p?.failed_score) ?? listed('contract-rules', 'score-gate');
  const contractsCount = finite(p?.failed_contracts) ?? syms('contract-rules').length - listed('contract-rules', 'score-gate');
  const contractCount = scoreCount + contractsCount;
  // A result stored before `failed_direction_unmeasured` existed counted the
  // unmeasured drops inside `failed_direction`; they are moved to the
  // pre-screen stage above, so take them out here.
  const fd = finite(p?.failed_direction);
  const directionCount = fd !== undefined
    ? (unmeasuredCounter !== undefined ? fd : Math.max(0, fd - unmeasuredListed))
    : listed('direction-shortlist', 'direction');
  const shortlistCount = finite(p?.failed_shortlist) ?? listed('direction-shortlist', 'shortlist');
  const lateCount = directionCount + shortlistCount;
  const unclassifiedCount = finite(p?.other_rejected) ?? listed('errors', 'unclassified');

  const countedWithoutGap = dataCount + preCount + chainCount + contractCount + lateCount + unclassifiedCount;
  const gap = totalDropped - countedWithoutGap;
  const unattributedCount = Math.max(0, gap);
  const errorsCount = unclassifiedCount + unattributedCount;
  const reconciliationNote = gap < 0
    ? `The stage counts add up to ${countedWithoutGap}, more than the ${totalDropped} not ranked (scanned − survivors); this result's counters are inconsistent.`
    : undefined;

  function buildSubRules(
    stage: StageId,
    stageTotal: number,
    defs: SubRuleDef[],
    keepEmpty: boolean,
  ): { subRules: DiagnosticSubRule[]; note?: string } {
    const stageSyms = syms(stage);
    const haveReasons = stageSyms.length > 0;
    const subRules = defs
      .map((d): DiagnosticSubRule => {
        const s = subSyms(stage, d.id);
        return {
          id: d.id,
          label: d.label,
          symbols: s,
          count: haveReasons || stageTotal === 0 ? s.length : null,
          ruleExplanation: d.explanation,
        };
      })
      .filter((r) => keepEmpty || r.count === null || r.count > 0);
    let note: string | undefined;
    if (stageTotal > 0 && !haveReasons) {
      note = `Per-rule breakdown unavailable: this scan recorded ${stageTotal} drop${stageTotal === 1 ? '' : 's'} here but no per-symbol reasons.`;
    } else if (stageSyms.length < stageTotal) {
      note = `${stageSyms.length} of ${stageTotal} dropped symbols have a recorded reason; the rest are not attributed.`;
    } else if (stageSyms.length > stageTotal) {
      note = `${stageSyms.length} symbols carry this stage's reasons, but the scan counted ${stageTotal} here.`;
    }
    return { subRules, note };
  }

  // Pre-screen sub-rules: one per weighted component actually named weakest.
  const preDefs: SubRuleDef[] = [
    ...WEIGHTED_COMPONENTS.filter((k) => listed('pre-screen', `weak-${k}`) > 0).map((k) => ({
      id: `weak-${k}`,
      label: `Lowest Weighted Component: ${COMPONENT_LABELS[k]}`,
      explanation: `Status REJECT at the pre-screen, and ${COMPONENT_LABELS[k]} was the lowest of the weighted components — a pointer, not the rule that fired. ${STATUS_CAVEAT}`,
    })),
    { id: 'no-breakdown', label: 'Rejected (no component breakdown recorded)',
      explanation: 'Status REJECT at the pre-screen; the scan did not record a component breakdown for these symbols.' },
    { id: 'trend-unmeasured', label: 'Trend Unmeasured (direction gate, no data)',
      explanation: 'The trend could not be measured (missing bars or benchmark), so the direction-conviction gate removed the symbol as "no data" before the chain fetch.' },
  ];

  const dte = options.dteWindow;
  const dteText = dte ? `${dte.min_dte}–${dte.max_dte}d` : undefined;
  const minTrend = finite(p?.direction_min_trend);

  const stageDefs: Array<{
    id: StageId; title: string; count: number; summary: string; defs: SubRuleDef[]; keepEmpty: boolean;
  }> = [
    {
      id: 'errors', title: 'Errors & Unattributed (any step)', count: errorsCount, keepEmpty: false,
      summary: 'Per-symbol errors and reasons no stage recognises can happen at any step, so they are taken off the universe first rather than placed in the funnel order.',
      defs: [
        { id: 'unclassified', label: 'Errors / Unclassified Reasons',
          explanation: 'A per-symbol exception (often with an empty reason) or a reason no stage recognises — the backend\'s residual bucket.' },
        { id: 'unattributed', label: 'Not Attributed',
          explanation: 'Not ranked, but no stage counter covers it — usually a result stored before the direction/shortlist/other counters existed.' },
      ],
    },
    {
      id: 'data-filters', title: 'Data & Universe Filters', count: dataCount, keepEmpty: true,
      summary: 'Removes symbols outside the Step-2 price and market-cap bounds, and symbols with no market or regime data.',
      defs: [
        { id: 'price', label: 'Price Out of Range', explanation: 'Spot price outside the Step-2 min/max.' },
        { id: 'cap', label: 'Market Cap Out of Range', explanation: 'Market cap outside the Step-2 min/max.' },
        { id: 'missing-data', label: 'Missing Market / Regime Data',
          explanation: 'No quote or price history, or no regime bars, from the data provider — not a setting.' },
      ],
    },
    {
      id: 'pre-screen', title: 'Pre-Screen Setup Score', count: preCount, keepEmpty: false,
      summary: 'Scores the stock before the chain fetch (IV not yet known, so vol is a placeholder); status REJECT is dropped. Unmeasured trends are dropped here too.',
      defs: preDefs,
    },
    {
      id: 'chain-window', title: 'Option Chain Window', count: chainCount, keepEmpty: true,
      summary: dteText
        ? `Fetches the option chain around this scan's DTE window (${dteText}; the lower bound is widened by a small tolerance); symbols with nothing returned are dropped.`
        : 'Fetches the option chain around the scan\'s DTE window; symbols with nothing returned are dropped.',
      defs: [
        { id: 'no-chain', label: 'No Option Chain Returned',
          explanation: 'The fetch returned no contracts in the window — no listed expiry inside it, or no data from the provider.' },
      ],
    },
    {
      id: 'contract-rules', title: 'Score Gate & Contract Rules', count: contractCount, keepEmpty: false,
      summary: 'Re-scores with IV, then grades every contract against the hard rules. A symbol is dropped when no contract survives; it is listed under every rule its contracts failed.',
      defs: contractSubRuleDefs(options.contractRules),
    },
    {
      id: 'direction-shortlist', title: 'Direction Gate & Shortlist', count: lateCount, keepEmpty: false,
      summary: 'Drops measured trends below the direction-conviction floor, then trims to the shortlist cap by rank.',
      defs: [
        { id: 'direction', label: minTrend !== undefined ? `Direction Conviction (trend < ${fmtNum(minTrend)})` : 'Direction Conviction',
          explanation: 'Measured trend score below the conviction floor for this direction and horizon.' },
        { id: 'shortlist', label: 'Shortlist Cap',
          explanation: 'Passed every gate but ranked below the shortlist limit — trimmed, not rejected.' },
      ],
    },
  ];

  function errorsSubRules(): { subRules: DiagnosticSubRule[]; note?: string } {
    // `unattributed` is arithmetic, not a reason — it never has symbols.
    const unc = subSyms('errors', 'unclassified');
    const [uncDef, unattrDef] = stageDefs[0].defs;
    const subRules: DiagnosticSubRule[] = [
      { id: uncDef.id, label: uncDef.label, ruleExplanation: uncDef.explanation, symbols: unc,
        count: unc.length > 0 || unclassifiedCount === 0 ? unc.length : null },
      { id: unattrDef.id, label: unattrDef.label, ruleExplanation: unattrDef.explanation, symbols: [],
        count: unattributedCount },
    ].filter((r) => r.count === null || r.count > 0);
    const note = unclassifiedCount > 0 && unc.length !== unclassifiedCount
      ? `${unc.length} of ${unclassifiedCount} errors/unclassified drops have a recorded reason.`
      : undefined;
    return { subRules, note };
  }

  let remaining = scanned;
  const stages: DiagnosticStage[] = stageDefs
    .filter((d) => d.id !== 'errors' || d.count > 0)
    .map((d) => {
      remaining = Math.max(0, remaining - d.count);
      const built = d.id === 'errors' ? errorsSubRules() : buildSubRules(d.id, d.count, d.defs, d.keepEmpty);
      let note = built.note;
      if (d.id === 'contract-rules' && !note) {
        const listedTotal = built.subRules.reduce((n, r) => n + (r.count ?? 0), 0);
        if (listedTotal > syms('contract-rules').length) {
          note = 'Rule counts overlap: a symbol is listed under each rule its contracts failed.';
        }
      }
      return {
        id: d.id,
        title: d.title,
        droppedCount: d.count,
        remainingCount: remaining,
        pctOfTotal: pct(d.count, scanned),
        isBottleneck: false,
        ruleSummary: d.summary,
        subRules: built.subRules,
        allSymbols: syms(d.id),
        note,
      };
    });

  // Bottleneck: the stage that dropped most; none when nothing was dropped.
  let bottleneck: DiagnosticStage | undefined;
  for (const s of stages) {
    if (s.droppedCount > 0 && (!bottleneck || s.droppedCount > bottleneck.droppedCount)) bottleneck = s;
  }
  if (bottleneck) bottleneck.isBottleneck = true;

  function topSubRule(s: DiagnosticStage): DiagnosticSubRule | undefined {
    let best: DiagnosticSubRule | undefined;
    for (const r of s.subRules) if ((r.count ?? 0) > (best?.count ?? 0)) best = r;
    return best;
  }

  let primaryBottleneck: PrimaryBottleneck | null = null;
  if (bottleneck) {
    const b = bottleneck;
    const tiedWith = stages.filter((s) => s !== b && s.droppedCount === b.droppedCount);
    const top = topSubRule(b);
    const topText = top && top.count ? ` Largest recorded cause: ${top.label} (${top.count}).` : '';
    const tieText = tiedWith.length > 0 ? ` Tied with ${tiedWith.map((s) => s.title).join(', ')}.` : '';
    const insight = `${b.title} removed ${b.droppedCount} of ${scanned} scanned symbols (${b.pctOfTotal}%).${topText}${tieText}`;
    let suggestedAction: string;
    let adjustHref: string | null = '/screener/step-3-direction';
    let adjustLabel: string | null = 'Review in Step 3';
    switch (b.id) {
      case 'errors':
        suggestedAction = top?.id === 'unattributed'
          ? 'This stored result predates some pipeline counters, so part of the drop cannot be placed. Re-run the scan for a full breakdown.'
          : 'Per-symbol errors are usually the data provider or the network, not a setting — check the backend log for this scan.';
        adjustHref = null;
        adjustLabel = null;
        break;
      case 'data-filters':
        suggestedAction = 'Review the price and market-cap bounds in Step 2. Missing-data drops come from the data provider, not a setting.';
        adjustHref = '/screener/step-2-universe';
        adjustLabel = 'Review in Step 2';
        break;
      case 'pre-screen':
        suggestedAction = top?.id === 'trend-unmeasured'
          ? 'Unmeasured trends are missing bars or benchmark data, not a setting.'
          : 'Look up a few rejected symbols: a weak weighted component points at its Step-3 scoring parameters; a high score that was still rejected points at a gate cap (regime, fundamentals, confidence).';
        break;
      case 'chain-window':
        suggestedAction = `Review the horizon / hold window in Step 3${dteText ? ` (this scan's DTE window was ${dteText})` : ''}, and check the options data source.`;
        break;
      case 'contract-rules':
        suggestedAction = 'Review the contract rules in Step 3\'s Execution Parameters, starting with the largest cause above.';
        break;
      default:
        if (top?.id === 'shortlist') {
          suggestedAction = 'These passed every gate and lost on rank; the shortlist limit is in Settings.';
          adjustHref = '/settings';
          adjustLabel = 'Open Settings';
        } else {
          suggestedAction = 'Direction-conviction drops follow the trend floor for this direction and horizon.';
        }
        break;
    }
    primaryBottleneck = {
      stageId: b.id,
      stageTitle: b.title,
      droppedCount: b.droppedCount,
      pctOfTotal: b.pctOfTotal,
      insight,
      suggestedAction,
      adjustHref,
      adjustLabel,
    };
  }

  // ASCII tree — generated from the same stages the interactive tree renders.
  const lines: string[] = [`Universe (${scanned})`];
  for (const s of stages) {
    lines.push('│');
    lines.push(`├── [−${s.droppedCount}] ${s.title} (Left: ${s.remainingCount}) · ${s.pctOfTotal}%${s.isBottleneck ? '  <-- [PRIMARY BOTTLENECK]' : ''}`);
    s.subRules.forEach((r, i) => {
      const branch = i === s.subRules.length - 1 && !s.note ? '└──' : '├──';
      lines.push(`│   ${branch} ${r.label}: ${r.count === null ? '—' : r.count}`);
    });
    if (s.note) lines.push(`│   └── (${s.note})`);
  }
  if (reconciliationNote) {
    lines.push('│');
    lines.push(`├── (${reconciliationNote})`);
  }
  lines.push('│');
  lines.push(`└── Final Candidates: ${candidatesCount} Survivor${candidatesCount !== 1 ? 's' : ''}`);
  const asciiTree = lines.join('\n');

  // Symbol lookup
  const survivorSet = new Set(survivorSymbols.map((s) => s.toUpperCase()));
  const stageTitle = new Map<StageId, string>(stageDefs.map((s) => [s.id, s.title]));
  const subLabel = new Map<string, string>();
  for (const d of stageDefs) for (const r of d.defs) subLabel.set(`${d.id}/${r.id}`, r.label);

  function lookupSymbol(query: string): SymbolDiagnosticResult | null {
    const q = (query ?? '').trim().toUpperCase();
    if (!q) return null;
    if (survivorSet.has(q)) {
      return {
        symbol: q,
        status: 'SURVIVOR',
        stageName: 'Passed All Gates',
        primaryReason: 'Ranked candidate',
        detailedReason: 'Cleared every gate this scan applied and made the shortlist.',
      };
    }
    const item = symbolMap.get(q);
    if (!item) return null;
    const c = classifyReason(item);
    return {
      symbol: q,
      status: 'REJECTED',
      stageName: stageTitle.get(c.stage) ?? 'Unclassified',
      primaryReason: c.subRules.map((s) => subLabel.get(`${c.stage}/${s}`) ?? s).join(', '),
      detailedReason: item.reason || '(no reason recorded)',
      breakdown: item.breakdown,
      weakestComponent: weakestComponent(item.breakdown, c.stage === 'pre-screen'),
    };
  }

  return {
    scanned,
    candidatesCount,
    totalDropped,
    primaryBottleneck,
    stages,
    reconciliationNote,
    asciiTree,
    lookupSymbol,
  };
}
