import type { OptionsPipeline, RejectedEntry } from './scanStore';
import type { DteWindow } from '@/types/domain';

// Turns the options scan's pipeline counters and rejected list into the
// staged drop-off model the PipelineInspector renders.
//
// Everything here is DERIVED from what the backend recorded — nothing is
// estimated. Where the backend gave a count but no per-symbol reasons for a
// stage (an older stored result, a truncated list), a sub-rule's count is
// `null` and renders as "—"; it is never apportioned by a fixed ratio. Rule
// thresholds appear in a label only when the scan echoed them in
// `contract_rules` (the Step-3 overrides); otherwise the label names the rule
// and the YAML it lives in, never a literal that can drift from it.
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
  pctOfStage: number | null;
  pctOfTotal: number | null;
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
   *  missing reasons, or one symbol counted under several rules. */
  note?: string;
}

export interface SymbolDiagnosticResult {
  symbol: string;
  status: 'SURVIVOR' | 'REJECTED';
  stageName: string;
  primaryReason: string;
  detailedReason: string;
  breakdown?: Record<string, number>;
  /** The breakdown key with the lowest score, for a pre-screen/score-gate reject. */
  weakestComponent?: string;
}

export interface PrimaryBottleneck {
  stageId: StageId;
  stageTitle: string;
  droppedCount: number;
  pctOfTotal: number;
  insight: string;
  suggestedAction: string;
  adjustHref: string;
  adjustLabel: string;
}

export interface PipelineDiagnosticReport {
  scanned: number;
  candidatesCount: number;
  totalDropped: number;
  /** null when nothing was dropped — there is no bottleneck to name. */
  primaryBottleneck: PrimaryBottleneck | null;
  stages: DiagnosticStage[];
  asciiTree: string;
  /** null = the symbol was not part of this scan. */
  lookupSymbol: (ticker: string) => SymbolDiagnosticResult | null;
}

export interface PipelineDiagnosticOptions {
  /** `ScanResult.contract_rules` — the Step-3 contract-rule overrides the scan applied. */
  contractRules?: Record<string, number> | null;
  /** `ScanResult.dte_window` — the expiry window the chain fetch used. */
  dteWindow?: DteWindow;
}

// ── Classification ──────────────────────────────────────────────────────────

const COMPONENT_ORDER = ['trend', 'pullback', 'trigger', 'event', 'vol'];
const COMPONENT_LABELS: Record<string, string> = {
  trend: 'Trend', pullback: 'Pullback', trigger: 'Trigger', event: 'Event', vol: 'Vol',
};

function componentLabel(key: string): string {
  return COMPONENT_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

/** The lowest-scoring breakdown key; ties go to the earlier component. */
export function weakestComponent(bd?: Record<string, number>): string | undefined {
  if (!bd) return undefined;
  const keys = Object.keys(bd).filter((k) => Number.isFinite(bd[k]));
  if (keys.length === 0) return undefined;
  const rank = (k: string) => {
    const i = COMPONENT_ORDER.indexOf(k);
    return i === -1 ? COMPONENT_ORDER.length : i;
  };
  keys.sort((a, b) => bd[a] - bd[b] || rank(a) - rank(b));
  return keys[0];
}

/** Contract-validator reject code → sub-rule id. */
const CONTRACT_CODE_RULE: Record<string, string> = {
  spread_too_wide: 'spread',
  volume_too_low: 'liquidity',
  open_interest_too_low: 'liquidity',
  delta_too_low_far_otm: 'delta',
  delta_too_high_deep_itm: 'delta',
  iv_too_high: 'iv',
  iv_rank_too_high: 'iv',
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
  if (['no market data', 'price filter', 'cap filter'].some((k) => reason.includes(k))) {
    if (reason.includes('price filter')) return { stage: 'data-filters', subRules: ['price'] };
    if (reason.includes('cap filter')) return { stage: 'data-filters', subRules: ['cap'] };
    return { stage: 'data-filters', subRules: ['missing-data'] };
  }
  if (reason.startsWith('regime data unavailable:')) return { stage: 'data-filters', subRules: ['missing-data'] };
  if (reason.startsWith('Pre-screen:')) {
    const weak = weakestComponent(entry.breakdown);
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
  // The backend's residual bucket (`other_rejected`): exceptions — often an
  // empty reason — and any reason no predicate matches.
  return { stage: 'direction-shortlist', subRules: ['unclassified'] };
}

// ── Labels ──────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(4)));
}

function ruleValue(rules: Record<string, number> | null | undefined, key: string): number | undefined {
  const v = rules?.[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

const YAML_NOTE = 'Threshold: contract_rules.yaml hard_reject (no Step-3 override recorded for this scan).';

interface SubRuleDef { id: string; label: string; explanation: string }

function contractSubRuleDefs(rules: Record<string, number> | null | undefined): SubRuleDef[] {
  const spread = ruleValue(rules, 'max_bid_ask_spread_pct');
  const minVol = ruleValue(rules, 'min_volume');
  const minOi = ruleValue(rules, 'min_open_interest');
  const minDelta = ruleValue(rules, 'min_delta');
  const maxDelta = ruleValue(rules, 'max_delta');
  const ivAbs = ruleValue(rules, 'max_iv_abs');
  const ivRank = ruleValue(rules, 'max_iv_rank');
  const liq = [minVol !== undefined ? `volume < ${fmtNum(minVol)}` : null,
    minOi !== undefined ? `OI < ${fmtNum(minOi)}` : null].filter(Boolean).join(' or ');
  const delta = minDelta !== undefined || maxDelta !== undefined
    ? `outside ${minDelta !== undefined ? fmtNum(minDelta) : '…'}–${maxDelta !== undefined ? fmtNum(maxDelta) : '…'}`
    : '';
  const iv = [ivAbs !== undefined ? `abs IV > ${fmtNum(ivAbs)}` : null,
    ivRank !== undefined ? `IV rank > ${fmtNum(ivRank)}` : null].filter(Boolean).join(' / ');
  const withOverride = (base: string, detail: string) => (detail ? `${base} (${detail})` : base);
  const overrideNote = (present: boolean) => (present ? 'Threshold: the Step-3 override this scan recorded.' : YAML_NOTE);
  return [
    { id: 'score-gate', label: 'Score Gate (setup score with IV)',
      explanation: 'Re-scored once the chain supplied IV; the setup score fell in the REJECT band.' },
    { id: 'spread', label: withOverride('Spread Too Wide', spread !== undefined ? `> ${fmtNum(spread * 100)}% of mid` : ''),
      explanation: `A contract's bid-ask spread as a share of mid exceeded the maximum. ${overrideNote(spread !== undefined)}` },
    { id: 'liquidity', label: withOverride('Low Liquidity', liq),
      explanation: `Daily volume or open interest below the floor. ${overrideNote(liq !== '')}` },
    { id: 'delta', label: withOverride('Delta Outside Range', delta),
      explanation: `Strike too far OTM (delta below the floor) or too deep ITM (above the cap). ${overrideNote(delta !== '')}` },
    { id: 'iv', label: withOverride('IV Above Ceiling', iv),
      explanation: `Implied volatility (absolute, or rank when a true percentile is available) above the ceiling. ${overrideNote(iv !== '')}` },
    { id: 'dte', label: 'Expiry Outside DTE Limits',
      explanation: 'Contract expiry shorter or longer than the validator\'s DTE limits.' },
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
  const byStage = new Map<string, string[]>();
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

  // Stage counts: the backend's counters when present, else the reasons we hold.
  const p = pipeline;
  const listCount = (stage: StageId, sub: string) => subSyms(stage, sub).length;
  const dataCount = finite(p?.failed_data) ?? syms('data-filters').length;
  const unmeasuredListed = listCount('pre-screen', 'trend-unmeasured');
  // With a pipeline but no `failed_direction_unmeasured` (a result stored
  // before the counter existed), the backend counted these in
  // `failed_direction`; counting the listed ones here too would double them.
  const unmeasuredCount = p ? (finite(p.failed_direction_unmeasured) ?? 0) : unmeasuredListed;
  const preCount = (finite(p?.failed_pre_screen) ?? syms('pre-screen').length - unmeasuredListed) + unmeasuredCount;
  const chainCount = finite(p?.no_chain) ?? syms('chain-window').length;
  const contractCount = p
    ? (finite(p.failed_score) ?? 0) + (finite(p.failed_contracts) ?? 0)
    : syms('contract-rules').length;
  const directionCount = finite(p?.failed_direction) ?? listCount('direction-shortlist', 'direction');
  const shortlistCount = finite(p?.failed_shortlist) ?? listCount('direction-shortlist', 'shortlist');
  const unclassifiedCount = finite(p?.other_rejected) ?? listCount('direction-shortlist', 'unclassified');
  const lateCount = directionCount + shortlistCount + unclassifiedCount;

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
        const count = haveReasons || stageTotal === 0 ? s.length : null;
        return {
          id: d.id,
          label: d.label,
          symbols: s,
          count,
          pctOfStage: count === null ? null : pct(count, stageTotal),
          pctOfTotal: count === null ? null : pct(count, scanned),
          ruleExplanation: d.explanation,
        };
      })
      .filter((r) => keepEmpty || r.count === null || r.count > 0);
    let note: string | undefined;
    if (stageTotal > 0 && !haveReasons) {
      note = `Per-rule breakdown unavailable: this scan recorded ${stageTotal} drop${stageTotal === 1 ? '' : 's'} here but no per-symbol reasons.`;
    } else if (stageSyms.length < stageTotal) {
      note = `${stageSyms.length} of ${stageTotal} dropped symbols have a recorded reason; the rest are not attributed.`;
    }
    return { subRules, note };
  }

  // Pre-screen sub-rules: one per breakdown component actually seen.
  const seenComponents = new Set<string>();
  for (const key of bySub.keys()) {
    if (key.startsWith('pre-screen/weak-')) seenComponents.add(key.slice('pre-screen/weak-'.length));
  }
  const componentKeys = [
    ...COMPONENT_ORDER.filter((k) => seenComponents.has(k)),
    ...Array.from(seenComponents).filter((k) => !COMPONENT_ORDER.includes(k)).sort(),
  ];
  const preDefs: SubRuleDef[] = [
    ...componentKeys.map((k) => ({
      id: `weak-${k}`,
      label: `Weakest Component: ${componentLabel(k)}`,
      explanation: `Setup score in the REJECT band, with ${componentLabel(k)} its lowest-scoring component. This names the weakest input, not a single failed rule.`,
    })),
    { id: 'no-breakdown', label: 'Rejected (no component breakdown recorded)',
      explanation: 'Setup score in the REJECT band; the scan did not record a component breakdown for these symbols.' },
    { id: 'trend-unmeasured', label: 'Trend Unmeasured (direction gate, no data)',
      explanation: 'The trend could not be measured (missing bars or benchmark), so the direction-conviction gate removed the symbol as "no data" before the chain fetch.' },
  ];

  const dte = options.dteWindow;
  const dteText = dte ? `${dte.min_dte}–${dte.max_dte}d` : undefined;

  const stageDefs: Array<{
    id: StageId; title: string; count: number; summary: string; defs: SubRuleDef[]; keepEmpty: boolean;
  }> = [
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
      summary: 'Scores trend, pullback, trigger, event and vol before the chain fetch (IV unknown yet); a score in the REJECT band is dropped. Unmeasured trends are dropped here too.',
      defs: preDefs,
    },
    {
      id: 'chain-window', title: 'Option Chain Window', count: chainCount, keepEmpty: true,
      summary: dteText
        ? `Fetches the option chain within this scan's expiry window (${dteText}); symbols with nothing returned are dropped.`
        : 'Fetches the option chain within the scan\'s expiry window; symbols with nothing returned are dropped.',
      defs: [
        { id: 'no-chain', label: dteText ? `No Option Chain Returned (${dteText})` : 'No Option Chain Returned',
          explanation: 'The fetch returned no contracts in the window — no listed expiry inside it, or no data from the provider.' },
      ],
    },
    {
      id: 'contract-rules', title: 'Score Gate & Contract Rules', count: contractCount, keepEmpty: false,
      summary: 'Re-scores with IV, then grades every contract against the hard rules. A symbol is dropped when no contract survives; it is listed under every rule its contracts failed.',
      defs: contractSubRuleDefs(options.contractRules),
    },
    {
      id: 'direction-shortlist', title: 'Direction Gate, Shortlist & Unclassified', count: lateCount, keepEmpty: false,
      summary: 'Drops measured trends below the direction-conviction floor, trims to the shortlist cap by rank, and counts anything the backend could not classify.',
      defs: [
        { id: 'direction', label: p?.direction_min_trend != null
            ? `Direction Conviction (trend < ${fmtNum(p.direction_min_trend)})` : 'Direction Conviction',
          explanation: 'Measured trend score below the conviction floor for this direction and horizon.' },
        { id: 'shortlist', label: 'Shortlist Cap',
          explanation: 'Passed every gate but ranked below the shortlist limit — trimmed, not rejected.' },
        { id: 'unclassified', label: 'Unclassified / Errors',
          explanation: 'A per-symbol error or a reason no stage recognises (the backend\'s residual bucket).' },
      ],
    },
  ];

  let remaining = scanned;
  const stages: DiagnosticStage[] = stageDefs.map((d) => {
    remaining = Math.max(0, remaining - d.count);
    const { subRules, note: baseNote } = buildSubRules(d.id, d.count, d.defs, d.keepEmpty);
    let note = baseNote;
    if (d.id === 'contract-rules' && !note) {
      const listed = subRules.reduce((n, r) => n + (r.count ?? 0), 0);
      if (listed > syms('contract-rules').length) {
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
      subRules,
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
    const top = topSubRule(bottleneck);
    const topText = top && top.count ? ` Largest recorded cause: ${top.label} (${top.count}).` : '';
    const insight = `${bottleneck.title} removed ${bottleneck.droppedCount} of ${scanned} scanned symbols (${bottleneck.pctOfTotal}%).${topText}`;
    let suggestedAction: string;
    let adjustHref = '/screener/step-3-direction';
    let adjustLabel = 'Review in Step 3';
    switch (bottleneck.id) {
      case 'data-filters':
        suggestedAction = 'Review the price and market-cap bounds in Step 2. Missing-data drops come from the data provider, not a setting.';
        adjustHref = '/screener/step-2-universe';
        adjustLabel = 'Review in Step 2';
        break;
      case 'pre-screen':
        suggestedAction = 'Review Min Stock Score and the scoring parameters for the weakest component in Step 3\'s Execution Parameters.';
        break;
      case 'chain-window':
        suggestedAction = `Review the horizon / hold window in Step 3${dteText ? ` (this scan fetched ${dteText})` : ''}, and check the options data source.`;
        break;
      case 'contract-rules':
        suggestedAction = 'Review the contract rules (spread, liquidity, delta, IV) in Step 3\'s Execution Parameters, starting with the largest cause above.';
        break;
      default:
        suggestedAction = 'Direction-conviction drops follow the trend floor for this direction and horizon; shortlist trims passed every gate and lost on rank (the shortlist limit is in Settings).';
        break;
    }
    primaryBottleneck = {
      stageId: bottleneck.id,
      stageTitle: bottleneck.title,
      droppedCount: bottleneck.droppedCount,
      pctOfTotal: bottleneck.pctOfTotal,
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
  lines.push('│');
  lines.push(`└── Final Candidates: ${candidatesCount} Survivor${candidatesCount !== 1 ? 's' : ''}`);
  const asciiTree = lines.join('\n');

  // Symbol lookup
  const survivorSet = new Set(survivorSymbols.map((s) => s.toUpperCase()));
  const stageTitle = new Map(stages.map((s) => [s.id, s.title] as const));
  const subLabel = new Map<string, string>();
  for (const s of stages) for (const r of s.subRules) subLabel.set(`${s.id}/${r.id}`, r.label);
  for (const d of stageDefs) for (const r of d.defs) if (!subLabel.has(`${d.id}/${r.id}`)) subLabel.set(`${d.id}/${r.id}`, r.label);

  function lookupSymbol(query: string): SymbolDiagnosticResult | null {
    const q = (query ?? '').trim().toUpperCase();
    if (!q) return null;
    if (survivorSet.has(q)) {
      return {
        symbol: q,
        status: 'SURVIVOR',
        stageName: 'Passed All Gates',
        primaryReason: 'Ranked candidate',
        detailedReason: 'Passed the data filters, pre-screen, chain fetch, score gate, contract rules, direction gate and shortlist cap.',
      };
    }
    const item = symbolMap.get(q);
    if (!item) return null;
    const c = classifyReason(item);
    const stage = c.stage;
    const primaryReason = c.subRules
      .map((s) => subLabel.get(`${stage}/${s}`) ?? s)
      .join(', ');
    return {
      symbol: q,
      status: 'REJECTED',
      stageName: stageTitle.get(stage) ?? 'Unclassified',
      primaryReason,
      detailedReason: item.reason || '(no reason recorded)',
      breakdown: item.breakdown,
      weakestComponent: weakestComponent(item.breakdown),
    };
  }

  return {
    scanned,
    candidatesCount,
    totalDropped,
    primaryBottleneck,
    stages,
    asciiTree,
    lookupSymbol,
  };
}
