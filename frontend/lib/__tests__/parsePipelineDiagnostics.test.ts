import { parsePipelineDiagnostics, classifyReason, contractCodes, weakestComponent } from '../parsePipelineDiagnostics';
import type { OptionsPipeline, RejectedEntry } from '../scanStore';

// Reason strings follow the backend's producers exactly:
//   backend/app/routers/scan.py — RejectedCandidate reasons (price/cap filter,
//     "no market data", "Pre-screen: score N rejected", "no option chain",
//     "Score gate: score N rejected", "contracts rejected: …",
//     "direction_conviction: trend T < F for <Direction> <Horizon>",
//     "Shortlist cap: <status> score S contract C ranked R of N (cap K)")
//   backend/app/routers/stock_scan.py — "direction_conviction_unmeasured: no
//     trend measurement for <Direction> <Horizon>"
//   backend/app/scoring/contract_validator.py — reject codes.
// Breakdowns are shaped like `{r.name: r.score for r in card.rules}`: the five
// weighted components plus the gate-cap entries the scorer appends (`regime`
// is always 0; `fundamentals` is a health score; at the pre-screen `vol` is
// the no-IV placeholder 50).

const PRE_BD = (o: Partial<Record<string, number>>) =>
  ({ trend: 70, pullback: 60, trigger: 70, event: 80, vol: 50, regime: 0, fundamentals: 40, ...o }) as Record<string, number>;

const REJECTED: RejectedEntry[] = [
  { symbol: 'PENNY', reason: 'price filter ($2.10 < $15.00 min)' },
  { symbol: 'TINY', reason: 'cap filter ($1.2B < $5.0B min)' },
  { symbol: 'NODATA', reason: 'no market data' },
  { symbol: 'NOREG', reason: 'regime data unavailable: no 15-min bars for NOREG' },
  { symbol: 'WTREND', reason: 'Pre-screen: score 28 rejected', breakdown: PRE_BD({ trend: 20 }) },
  { symbol: 'WEVENT', reason: 'Pre-screen: score 31 rejected', breakdown: PRE_BD({ event: 10 }) },
  { symbol: 'CAPPED62', reason: 'Pre-screen: score 62 rejected', breakdown: PRE_BD({ pullback: 55 }) },
  { symbol: 'NOBD', reason: 'Pre-screen: score 20 rejected' },
  { symbol: 'UNMEAS', reason: 'direction_conviction_unmeasured: no trend measurement for Bullish Swing' },
  { symbol: 'NOOPT', reason: 'no option chain' },
  { symbol: 'SG', reason: 'Score gate: score 30 rejected', breakdown: { trend: 40, pullback: 30, trigger: 50, event: 60, vol: 20, regime: 0 } },
  { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(14), volume_too_low(8)' },
  { symbol: 'IVONLY', reason: 'contracts rejected: iv_too_high(9)' },
  { symbol: 'LOWSC', reason: 'contracts rejected: contract_score_below_caution(4); best contract score 30 < caution 40' },
  { symbol: 'MINSS', reason: 'contracts rejected: stock_score_below_threshold(12)' },
  { symbol: 'BARE', reason: 'all contracts rejected' },
  { symbol: 'DIR1', reason: 'direction_conviction: trend 20 < 40 for Bearish Position' },
  { symbol: 'DIR2', reason: 'direction_conviction: trend 25 < 40 for Bearish Position' },
  { symbol: 'DIR3', reason: 'direction_conviction: trend 30 < 40 for Bearish Position' },
  { symbol: 'TRIMMED', reason: 'Shortlist cap: PASS score 61 contract 70 ranked 11 of 12 (cap 10)' },
  { symbol: 'ERR', reason: '' },
];

const PIPELINE: OptionsPipeline = {
  scanned: 23,
  failed_data: 4,
  failed_pre_screen: 4,
  failed_direction_unmeasured: 1,
  no_chain: 1,
  failed_score: 1,
  failed_contracts: 5,
  failed_direction: 3,
  failed_shortlist: 1,
  other_rejected: 1,
  direction_min_trend: 40,
  candidates: 2,
};

const SURVIVORS = ['AAPL', 'MSFT'];

type Report = ReturnType<typeof parsePipelineDiagnostics>;

function stage(report: Report, id: string) {
  const s = report.stages.find((x) => x.id === id);
  if (!s) throw new Error(`stage ${id} missing`);
  return s;
}

function sub(report: Report, stageId: string, subId: string) {
  return stage(report, stageId).subRules.find((r) => r.id === subId);
}

function sumDrops(report: Report) {
  return report.stages.reduce((n, s) => n + s.droppedCount, 0);
}

describe('classifyReason', () => {
  it('maps every backend reason to the stage its counter belongs to', () => {
    const byStage = Object.fromEntries(REJECTED.map((r) => [r.symbol, classifyReason(r).stage]));
    expect(byStage).toEqual({
      PENNY: 'data-filters', TINY: 'data-filters', NODATA: 'data-filters', NOREG: 'data-filters',
      WTREND: 'pre-screen', WEVENT: 'pre-screen', CAPPED62: 'pre-screen', NOBD: 'pre-screen', UNMEAS: 'pre-screen',
      NOOPT: 'chain-window',
      SG: 'contract-rules', NVDA: 'contract-rules', IVONLY: 'contract-rules', LOWSC: 'contract-rules',
      MINSS: 'contract-rules', BARE: 'contract-rules',
      DIR1: 'direction-shortlist', DIR2: 'direction-shortlist', DIR3: 'direction-shortlist', TRIMMED: 'direction-shortlist',
      ERR: 'errors',
    });
  });

  it('maps each contract code to its own threshold sub-rule', () => {
    const subs = (reason: string) => classifyReason({ symbol: 'X', reason }).subRules;
    expect(subs('contracts rejected: spread_too_wide(14), volume_too_low(8)')).toEqual(['spread', 'volume']);
    expect(subs('contracts rejected: open_interest_too_low(3)')).toEqual(['oi']);
    expect(subs('contracts rejected: iv_too_high(9)')).toEqual(['iv-abs']);
    expect(subs('contracts rejected: iv_rank_too_high(9)')).toEqual(['iv-rank']);
    expect(subs('contracts rejected: delta_too_low_far_otm(2), delta_too_high_deep_itm(1)')).toEqual(['delta-low', 'delta-high']);
    expect(subs('contracts rejected: stock_score_below_threshold(12)')).toEqual(['min-stock-score']);
    expect(subs('contracts rejected: contract_score_below_caution(4); best contract score 30 < caution 40')).toEqual(['low-score']);
    expect(subs('all contracts rejected')).toEqual(['other-contract']);
    expect(subs('contracts rejected: dte_too_short(3), brand_new_code(1)')).toEqual(['dte', 'other-contract']);
  });

  it('separates an unmeasured trend from a measured one below the floor', () => {
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'UNMEAS')!).subRules).toEqual(['trend-unmeasured']);
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'DIR1')!).subRules).toEqual(['direction']);
  });
});

describe('weakestComponent', () => {
  it('ignores the gate-cap entries the scorer appends (regime is always 0)', () => {
    expect(weakestComponent(PRE_BD({ trend: 20 }), true)).toBe('trend');
    expect(weakestComponent({ trend: 70, regime: 0, fundamentals: 5, confidence: 0 })).toBe('trend');
  });

  it('skips the pre-screen vol placeholder when asked', () => {
    expect(weakestComponent(PRE_BD({ pullback: 55 }), true)).toBe('pullback');
    expect(weakestComponent({ trend: 70, vol: 10 }, false)).toBe('vol');
    expect(weakestComponent({ trend: 70, vol: 10 }, true)).toBe('trend');
  });

  it('breaks ties toward the earlier component and handles no breakdown', () => {
    expect(weakestComponent({ trend: 30, pullback: 30 })).toBe('trend');
    expect(weakestComponent(undefined)).toBeUndefined();
    expect(weakestComponent({ regime: 0 })).toBeUndefined();
  });
});

describe('contractCodes', () => {
  it('reads codes before the "; best contract score" suffix only', () => {
    expect(contractCodes('contracts rejected: spread_too_wide(14), volume_too_low(8)')).toEqual(['spread_too_wide', 'volume_too_low']);
    expect(contractCodes('contracts rejected: contract_score_below_caution(4); best contract score 30 < caution 40'))
      .toEqual(['contract_score_below_caution']);
    expect(contractCodes('all contracts rejected')).toEqual([]);
  });
});

describe('parsePipelineDiagnostics — current results', () => {
  const report = parsePipelineDiagnostics(PIPELINE, REJECTED, SURVIVORS);

  it('stage drops plus survivors account for the whole universe', () => {
    expect(report.scanned).toBe(23);
    expect(report.totalDropped).toBe(21);
    expect(sumDrops(report) + report.candidatesCount).toBe(report.scanned);
    expect(report.stages[report.stages.length - 1].remainingCount).toBe(report.candidatesCount);
    expect(report.reconciliationNote).toBeUndefined();
  });

  it('takes errors off the universe first, then follows the backend gate order', () => {
    expect(report.stages.map((s) => s.id)).toEqual(
      ['errors', 'data-filters', 'pre-screen', 'chain-window', 'contract-rules', 'direction-shortlist']);
    expect(stage(report, 'errors').droppedCount).toBe(1);
    expect(stage(report, 'errors').remainingCount).toBe(22);
    expect(stage(report, 'data-filters').droppedCount).toBe(4);
    expect(stage(report, 'pre-screen').droppedCount).toBe(5);          // 4 pre-screen + 1 unmeasured
    expect(stage(report, 'pre-screen').remainingCount).toBe(22 - 4 - 5);
    expect(stage(report, 'chain-window').droppedCount).toBe(1);
    expect(stage(report, 'contract-rules').droppedCount).toBe(6);      // 1 score gate + 5 contracts
    expect(stage(report, 'direction-shortlist').droppedCount).toBe(4); // 3 direction + 1 trim
  });

  it('omits the errors stage when there are none', () => {
    const r = parsePipelineDiagnostics({ ...PIPELINE, scanned: 22, other_rejected: 0 },
      REJECTED.filter((x) => x.symbol !== 'ERR'), SURVIVORS);
    expect(r.stages.find((s) => s.id === 'errors')).toBeUndefined();
  });

  it('attributes pre-screen rejects to the lowest weighted component, never to regime or the vol placeholder', () => {
    expect(sub(report, 'pre-screen', 'weak-trend')?.symbols).toEqual(['WTREND']);
    expect(sub(report, 'pre-screen', 'weak-event')?.symbols).toEqual(['WEVENT']);
    expect(sub(report, 'pre-screen', 'weak-pullback')?.symbols).toEqual(['CAPPED62']);
    expect(sub(report, 'pre-screen', 'no-breakdown')?.symbols).toEqual(['NOBD']);
    expect(sub(report, 'pre-screen', 'trend-unmeasured')?.symbols).toEqual(['UNMEAS']);
    expect(stage(report, 'pre-screen').subRules.map((r) => r.id))
      .not.toEqual(expect.arrayContaining(['weak-regime', 'weak-vol', 'weak-fundamentals']));
  });

  it('does not claim a REJECT came from the score band', () => {
    const label = sub(report, 'pre-screen', 'weak-pullback')!;
    expect(label.label).toBe('Lowest Weighted Component: Pullback');
    expect(label.ruleExplanation).toMatch(/gate cap/);
    expect(label.ruleExplanation).not.toMatch(/fell in the REJECT band/);
    expect(sub(report, 'contract-rules', 'score-gate')?.ruleExplanation).toMatch(/gate cap/);
  });

  it('lists score-gate and every contract rule symbol where it belongs', () => {
    expect(sub(report, 'contract-rules', 'score-gate')?.symbols).toEqual(['SG']);
    expect(sub(report, 'contract-rules', 'spread')?.symbols).toEqual(['NVDA']);
    expect(sub(report, 'contract-rules', 'volume')?.symbols).toEqual(['NVDA']);
    expect(sub(report, 'contract-rules', 'iv-abs')?.symbols).toEqual(['IVONLY']);
    expect(sub(report, 'contract-rules', 'low-score')?.symbols).toEqual(['LOWSC']);
    expect(sub(report, 'contract-rules', 'min-stock-score')?.symbols).toEqual(['MINSS']);
    expect(sub(report, 'contract-rules', 'other-contract')?.symbols).toEqual(['BARE']);
    expect(stage(report, 'contract-rules').note).toMatch(/overlap/);
  });

  it('names the stage that dropped most as the bottleneck, including the direction stage', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 10, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 1, failed_contracts: 2,
        failed_direction: 6, failed_shortlist: 0, failed_direction_unmeasured: 0, other_rejected: 0, candidates: 1 },
      [
        { symbol: 'IVONLY', reason: 'contracts rejected: iv_too_high(9)' },
        { symbol: 'LOWSC', reason: 'contracts rejected: contract_score_below_caution(4)' },
        { symbol: 'SG', reason: 'Score gate: score 30 rejected' },
        ...['A', 'B', 'C', 'D', 'E', 'F'].map((s) => ({ symbol: s, reason: 'direction_conviction: trend 20 < 40 for Bearish Swing' })),
      ],
      ['WIN'],
    );
    expect(r.primaryBottleneck?.stageId).toBe('direction-shortlist');
    expect(r.primaryBottleneck?.droppedCount).toBe(6);
    expect(r.primaryBottleneck?.insight).toContain('Direction Conviction (6)');
    expect(r.primaryBottleneck?.suggestedAction).toMatch(/trend floor/);
  });

  it('points a shortlist-dominated bottleneck at Settings, not at the direction floor', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 13, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 0, failed_shortlist: 3, failed_direction_unmeasured: 0, other_rejected: 0, candidates: 10 },
      ['X', 'Y', 'Z'].map((s) => ({ symbol: s, reason: 'Shortlist cap: PASS score 60 contract 70 ranked 11 of 13 (cap 10)' })),
      Array.from({ length: 10 }, (_, i) => `S${i}`),
    );
    expect(r.primaryBottleneck?.adjustHref).toBe('/settings');
  });

  it('names a tie instead of silently picking one stage', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 5, failed_data: 2, failed_pre_screen: 2, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 0, failed_shortlist: 0, failed_direction_unmeasured: 0, other_rejected: 0, candidates: 1 },
      [], ['A'],
    );
    expect(r.primaryBottleneck?.insight).toContain('Tied with Pre-Screen Setup Score');
  });

  it('sends an error-dominated scan to the backend log, not to a setting', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 4, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 0, failed_shortlist: 0, failed_direction_unmeasured: 0, other_rejected: 4, candidates: 0 },
      ['A', 'B', 'C', 'D'].map((s) => ({ symbol: s, reason: '' })),
      [],
    );
    expect(r.primaryBottleneck?.stageId).toBe('errors');
    expect(r.primaryBottleneck?.suggestedAction).toMatch(/backend log/);
    expect(r.primaryBottleneck?.adjustHref).toBeNull();
    expect(stage(r, 'data-filters').remainingCount).toBe(0);
  });

  it('names no bottleneck when nothing was dropped', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 2, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0, candidates: 2 },
      [], ['A', 'B'],
    );
    expect(r.primaryBottleneck).toBeNull();
    expect(r.stages.every((s) => !s.isBottleneck)).toBe(true);
    expect(r.asciiTree).not.toContain('PRIMARY BOTTLENECK');
  });

  it('never invents sub-rule counts when per-symbol reasons are missing', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 500, failed_data: 0, failed_pre_screen: 300, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 0, failed_shortlist: 0, failed_direction_unmeasured: 0, other_rejected: 0, candidates: 200 },
      [], [],
    );
    const pre = stage(r, 'pre-screen');
    expect(pre.droppedCount).toBe(300);
    for (const s of pre.subRules) expect(s.count).toBeNull();
    expect(pre.note).toMatch(/breakdown unavailable/i);
    expect(r.asciiTree).toContain(': —');
  });

  it('shows a threshold in a label only for the rule the scan recorded it for', () => {
    expect(sub(report, 'contract-rules', 'spread')?.label).toBe('Spread Too Wide');
    expect(sub(report, 'contract-rules', 'spread')?.ruleExplanation).toMatch(/not recorded/);   // no contract_rules on this result
    const extra: RejectedEntry[] = [
      { symbol: 'DLT', reason: 'contracts rejected: delta_too_low_far_otm(5)' },
      { symbol: 'OI', reason: 'contracts rejected: open_interest_too_low(5)' },
    ];
    const withRules = parsePipelineDiagnostics(PIPELINE, [...REJECTED, ...extra], SURVIVORS, {
      // only OI overridden — a volume-only reject must not borrow the OI threshold
      contractRules: { max_bid_ask_spread_pct: 0.2, min_open_interest: 200, min_delta: 0.2, min_stock_score: 45 },
      dteWindow: { min_dte: 30, max_dte: 60, multiplier: 1 },
    });
    expect(sub(withRules, 'contract-rules', 'spread')?.label).toBe('Spread Too Wide (> 20% of mid)');
    expect(sub(withRules, 'contract-rules', 'oi')?.label).toBe('Open Interest Too Low (< 200)');
    expect(sub(withRules, 'contract-rules', 'volume')?.label).toBe('Volume Too Low');
    expect(sub(withRules, 'contract-rules', 'volume')?.ruleExplanation).toContain('min_volume');
    expect(sub(withRules, 'contract-rules', 'delta-low')?.label).toBe('Delta Too Low (far OTM) (< 0.2)');
    expect(sub(withRules, 'contract-rules', 'min-stock-score')?.label).toBe('Stock Score Below Contract Minimum (< 45)');
    expect(stage(withRules, 'chain-window').ruleSummary).toContain('30–60d');
    expect(withRules.asciiTree).not.toMatch(/15%|OI < 500|0\.30/);
  });

  it('looks up survivors, every rejected stage, and unknown symbols', () => {
    expect(report.lookupSymbol('aapl')?.status).toBe('SURVIVOR');
    expect(report.lookupSymbol('aapl')?.detailedReason).not.toMatch(/direction gate/);
    expect(report.lookupSymbol('SG')?.stageName).toBe('Score Gate & Contract Rules');
    expect(report.lookupSymbol('NOREG')?.stageName).toBe('Data & Universe Filters');
    expect(report.lookupSymbol('UNMEAS')?.primaryReason).toBe('Trend Unmeasured (direction gate, no data)');
    expect(report.lookupSymbol('NVDA')?.primaryReason).toBe('Spread Too Wide, Volume Too Low');
    expect(report.lookupSymbol('TRIMMED')?.primaryReason).toBe('Shortlist Cap');
    expect(report.lookupSymbol('WTREND')?.weakestComponent).toBe('trend');
    expect(report.lookupSymbol('SG')?.weakestComponent).toBe('vol');   // vol is measured at the score gate
    expect(report.lookupSymbol('ERR')?.stageName).toBe('Errors & Unattributed (any step)');
    expect(report.lookupSymbol('ERR')?.detailedReason).toBe('(no reason recorded)');
    expect(report.lookupSymbol('ZZZZ')).toBeNull();
    expect(report.lookupSymbol('   ')).toBeNull();
  });
});

describe('parsePipelineDiagnostics — stored legacy results', () => {
  it('moves unmeasured drops out of failed_direction when the separate counter is absent (2026-09-27..10-01)', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 5, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 2, failed_shortlist: 0, other_rejected: 0, candidates: 3 },
      [
        { symbol: 'U', reason: 'direction_conviction_unmeasured: no trend measurement for Bullish Swing' },
        { symbol: 'D', reason: 'direction_conviction: trend 10 < 40 for Bullish Swing' },
      ],
      ['A', 'B', 'C'],
    );
    expect(stage(r, 'pre-screen').droppedCount).toBe(1);
    expect(stage(r, 'pre-screen').remainingCount).toBe(4);
    expect(stage(r, 'direction-shortlist').droppedCount).toBe(1);
    expect(stage(r, 'direction-shortlist').note).toBeUndefined();
    expect(sumDrops(r)).toBe(2);
    for (const s of r.stages) {
      for (const x of s.subRules) {
        if ((x.count ?? 0) > 0) expect(s.droppedCount).toBeGreaterThan(0);
      }
    }
  });

  it('shows the gap as Not Attributed when pre-split counters are absent', () => {
    // A pre-split result: no direction/shortlist/other counters, and the 8
    // shortlist trims were never written to `rejected`.
    const r = parsePipelineDiagnostics(
      { scanned: 20, failed_data: 2, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0, candidates: 10 },
      [{ symbol: 'P1', reason: 'price filter ($2 < $5 min)' }, { symbol: 'P2', reason: 'price filter ($3 < $5 min)' }],
      Array.from({ length: 10 }, (_, i) => `S${i}`),
    );
    expect(sub(r, 'errors', 'unattributed')?.count).toBe(8);
    expect(sumDrops(r) + r.candidatesCount).toBe(r.scanned);
    expect(r.primaryBottleneck?.suggestedAction).toMatch(/predates/);
  });

  it('flags counters that add up to more than were dropped', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 3, failed_data: 5, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0, candidates: 1 },
      [], ['A'],
    );
    expect(r.reconciliationNote).toMatch(/inconsistent/);
  });

  it('falls back to listed reasons when contract counters are missing', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 3 } as unknown as OptionsPipeline,
      [{ symbol: 'C', reason: 'contracts rejected: spread_too_wide(3)' }, { symbol: 'G', reason: 'Score gate: score 20 rejected' }],
      ['A'],
    );
    expect(stage(r, 'contract-rules').droppedCount).toBe(2);
    for (const s of r.stages) expect(Number.isFinite(s.droppedCount)).toBe(true);
  });

  it('notes when more symbols carry a stage reason than the scan counted', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 3, failed_data: 1, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 0, failed_shortlist: 0, failed_direction_unmeasured: 0, other_rejected: 0, candidates: 1 },
      [{ symbol: 'X', reason: 'no market data' }, { symbol: 'Y', reason: 'no market data' }],
      ['A'],
    );
    expect(stage(r, 'data-filters').note).toMatch(/counted 1 here/);
  });

  it('handles no data without NaN', () => {
    const r = parsePipelineDiagnostics(undefined, [], []);
    expect(r.scanned).toBe(0);
    expect(r.primaryBottleneck).toBeNull();
    for (const s of r.stages) expect(Number.isNaN(s.pctOfTotal)).toBe(false);
  });
});

describe('parsePipelineDiagnostics — round-2 regressions', () => {
  const ZERO = { scanned: 0, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0,
    failed_direction: 0, failed_shortlist: 0, failed_direction_unmeasured: 0, other_rejected: 0, candidates: 0 };

  it('uses a row\'s own counter when its reasons were never listed (trims stored 2026-09-15..29)', () => {
    const r = parsePipelineDiagnostics(
      { ...ZERO, scanned: 52, failed_direction: 2, failed_shortlist: 40, candidates: 10 },
      ['D1', 'D2'].map((s) => ({ symbol: s, reason: 'direction_conviction: trend 20 < 40 for Bullish Swing' })),
      Array.from({ length: 10 }, (_, i) => `S${i}`),
    );
    expect(sub(r, 'direction-shortlist', 'shortlist')?.count).toBe(40);
    expect(sub(r, 'direction-shortlist', 'direction')?.count).toBe(2);
    expect(stage(r, 'direction-shortlist').note).toBeUndefined();   // the counters account for all 42
    expect(r.primaryBottleneck?.insight).toContain('Shortlist Cap (40)');
    expect(r.primaryBottleneck?.adjustHref).toBe('/settings');
  });

  it('does not blame the direction floor when the scan recorded zero direction drops', () => {
    const r = parsePipelineDiagnostics(
      { ...ZERO, scanned: 50, failed_shortlist: 40, candidates: 10 }, [],
      Array.from({ length: 10 }, (_, i) => `S${i}`),
    );
    expect(sub(r, 'direction-shortlist', 'direction')).toBeUndefined();
    expect(r.primaryBottleneck?.suggestedAction).not.toMatch(/trend floor/);
  });

  it('counts unmeasured trends from their counter even when none are listed', () => {
    const r = parsePipelineDiagnostics({ ...ZERO, scanned: 10, failed_direction_unmeasured: 8, candidates: 2 }, [], ['A', 'B']);
    expect(sub(r, 'pre-screen', 'trend-unmeasured')?.count).toBe(8);
    expect(r.primaryBottleneck?.suggestedAction).toMatch(/too few bars/);
  });

  it('does not call a 0 trend a measured weakness — it is also the insufficient-data value', () => {
    const entry = { symbol: 'NEWIPO', reason: 'Pre-screen: score 15 rejected', breakdown: PRE_BD({ trend: 0 }) };
    expect(classifyReason(entry).subRules).toEqual(['ambiguous-trend']);
    const r = parsePipelineDiagnostics({ ...ZERO, scanned: 2, failed_pre_screen: 1, candidates: 1 }, [entry], ['A']);
    expect(sub(r, 'pre-screen', 'ambiguous-trend')?.label).toBe('Trend at a Placeholder Score (failing or unmeasured)');
    expect(r.primaryBottleneck?.suggestedAction).toMatch(/history against the Step-3 lookback/);
  });

  it('treats the relative-strength trend placeholder (50, no benchmark) as ambiguous too', () => {
    const entry = { symbol: 'NOBENCH', reason: 'Pre-screen: score 60 rejected',
      breakdown: PRE_BD({ trend: 50, pullback: 70, trigger: 80, event: 90 }) };
    expect(classifyReason(entry).subRules).toEqual(['ambiguous-trend']);
  });

  it('does not highlight a vol placeholder as the weakest reading in a score-gate lookup', () => {
    const r = parsePipelineDiagnostics(undefined,
      [{ symbol: 'NOIV', reason: 'Score gate: score 30 rejected', breakdown: { trend: 60, pullback: 55, trigger: 70, event: 80, vol: 50 } }], []);
    expect(r.lookupSymbol('NOIV')?.weakestComponent).toBeUndefined();
  });

  it('says a threshold is unknown when the scan did not record its rules, and YAML only when it recorded none', () => {
    const e = [{ symbol: 'X', reason: 'contracts rejected: spread_too_wide(3)' }];
    const unknown = parsePipelineDiagnostics(undefined, e, [], { contractRules: null });
    expect(sub(unknown, 'contract-rules', 'spread')?.ruleExplanation).toMatch(/not recorded/);
    const yaml = parsePipelineDiagnostics(undefined, e, [], { contractRules: {} });
    expect(sub(yaml, 'contract-rules', 'spread')?.ruleExplanation).toMatch(/contract_rules\.yaml/);
  });

  it('does not call an unmeasured trend "not a setting" — a Step-3 lookback can cause it', () => {
    const r = parsePipelineDiagnostics({ ...ZERO, scanned: 10, failed_direction_unmeasured: 8, candidates: 2 }, [], ['A', 'B']);
    expect(r.primaryBottleneck?.suggestedAction).not.toMatch(/not a setting/);
    expect(r.primaryBottleneck?.suggestedAction).toMatch(/period/);
  });

  it('does not blame a missing benchmark for a 0 pullback', () => {
    const entry = { symbol: 'P', reason: 'Pre-screen: score 15 rejected', breakdown: PRE_BD({ pullback: 0 }) };
    const r = parsePipelineDiagnostics(undefined, [entry], []);
    expect(sub(r, 'pre-screen', 'ambiguous-pullback')?.ruleExplanation).not.toMatch(/benchmark/);
  });

  it('marks a shortlist trim TRIMMED, not REJECTED, and shows only weighted components', () => {
    const r = parsePipelineDiagnostics(PIPELINE, REJECTED, SURVIVORS);
    expect(r.lookupSymbol('TRIMMED')?.status).toBe('TRIMMED');
    const comps = r.lookupSymbol('WTREND')?.components ?? [];
    expect(comps.map((c) => c.key)).toEqual(['trend', 'pullback', 'trigger', 'event', 'vol']);
    expect(comps.find((c) => c.key === 'vol')?.placeholder).toBe(true);    // no IV at the pre-screen
    expect(comps.find((c) => c.key === 'trend')?.placeholder).toBe(false);
  });

  it('says confidence can cap the score gate but not the pre-screen', () => {
    const r = parsePipelineDiagnostics(PIPELINE, REJECTED, SURVIVORS);
    expect(sub(r, 'pre-screen', 'weak-trend')?.ruleExplanation).not.toMatch(/confidence/);
    expect(sub(r, 'contract-rules', 'score-gate')?.ruleExplanation).toMatch(/confidence/);
  });

  it('reports the top contract row as a frequency, never as the binding cause', () => {
    // Every symbol fails spread at the money AND delta on the wings: delta is
    // the most frequent row, but nothing says it removed them.
    const r = parsePipelineDiagnostics({ ...ZERO, scanned: 4, failed_contracts: 3, candidates: 1 },
      ['X', 'Y', 'Z'].map((s) => ({ symbol: s, reason: 'contracts rejected: delta_too_low_far_otm(20), spread_too_wide(4)' })), ['A']);
    expect(r.primaryBottleneck?.insight).toMatch(/Most frequent contract-level failure/);
    expect(r.primaryBottleneck?.insight).toMatch(/not the rule that removed them/);
    expect(r.primaryBottleneck?.suggestedAction).not.toMatch(/largest cause is/i);
    expect(r.primaryBottleneck?.adjustHref).toBe('/screener/step-3-direction');
  });

  it('explains an overcount even when some drops are also unattributed', () => {
    const r = parsePipelineDiagnostics({ ...ZERO, scanned: 6, failed_contracts: 5, candidates: 1 },
      ['X', 'Y', 'Z'].map((s) => ({ symbol: s, reason: 'contracts rejected: spread_too_wide(2), volume_too_low(1)' })), ['A']);
    const note = stage(r, 'contract-rules').note ?? '';
    expect(note).toMatch(/3 of 5/);
    expect(note).toMatch(/overlap/);
  });

  it('does not mention a hold-window widening in the chain summary as a narrowing tolerance only', () => {
    const r = parsePipelineDiagnostics(PIPELINE, REJECTED, SURVIVORS, { dteWindow: { min_dte: 10, max_dte: 40, multiplier: 1 } });
    expect(stage(r, 'chain-window').ruleSummary).toMatch(/kept above the hold period/);
  });
});

