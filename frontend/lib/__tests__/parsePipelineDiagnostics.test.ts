import { parsePipelineDiagnostics, classifyReason, contractCodes, weakestComponent } from '../parsePipelineDiagnostics';
import type { OptionsPipeline, RejectedEntry } from '../scanStore';

// Every reason string below is copied from what the backend emits —
// backend/app/routers/scan.py (RejectedCandidate reasons and the `_is_*`
// bucket predicates) and backend/app/scoring/contract_validator.py (reject
// codes). If a producer is reworded, these must change with it.

const REJECTED: RejectedEntry[] = [
  { symbol: 'PENNY', reason: 'price filter ($2.10 < $15.00 min)' },
  { symbol: 'TINY', reason: 'cap filter ($1.2B < $5.0B min)' },
  { symbol: 'NODATA', reason: 'no market data' },
  { symbol: 'NOREG', reason: 'regime data unavailable: no 15-min bars' },
  { symbol: 'WTREND', reason: 'Pre-screen: score 28 rejected', breakdown: { trend: 20, pullback: 60, trigger: 70, event: 80, vol: 90 } },
  { symbol: 'WVOL', reason: 'Pre-screen: score 31 rejected', breakdown: { trend: 70, pullback: 60, trigger: 70, event: 80, vol: 10 } },
  { symbol: 'ALLHI', reason: 'Pre-screen: score 33 rejected', breakdown: { trend: 60, pullback: 58, trigger: 70, event: 80, vol: 90 } },
  { symbol: 'NOBD', reason: 'Pre-screen: score 20 rejected' },
  { symbol: 'UNMEAS', reason: 'direction_conviction_unmeasured: trend not measured (Bullish/Swing)' },
  { symbol: 'NOOPT', reason: 'no option chain' },
  { symbol: 'SG', reason: 'Score gate: score 30 rejected', breakdown: { trend: 40, pullback: 30, trigger: 50, event: 60, vol: 20 } },
  { symbol: 'NVDA', reason: 'contracts rejected: spread_too_wide(14), volume_too_low(8)' },
  { symbol: 'IVONLY', reason: 'contracts rejected: iv_too_high(9)' },
  { symbol: 'LOWSC', reason: 'contracts rejected: contract_score_below_caution(4); best contract score 30 < caution 40' },
  { symbol: 'BARE', reason: 'all contracts rejected' },
  { symbol: 'DIR1', reason: 'direction_conviction: trend 20 < 40 (Bearish/Position)' },
  { symbol: 'DIR2', reason: 'direction_conviction: trend 25 < 40 (Bearish/Position)' },
  { symbol: 'DIR3', reason: 'direction_conviction: trend 30 < 40 (Bearish/Position)' },
  { symbol: 'CAPPED', reason: 'Shortlist cap: PASS score 61 below the top 10' },
  { symbol: 'ERR', reason: '' },
];

const PIPELINE: OptionsPipeline = {
  scanned: 22,
  failed_data: 4,
  failed_pre_screen: 4,
  failed_direction_unmeasured: 1,
  no_chain: 1,
  failed_score: 1,
  failed_contracts: 4,
  failed_direction: 3,
  failed_shortlist: 1,
  other_rejected: 1,
  candidates: 2,
};

const SURVIVORS = ['AAPL', 'MSFT'];

function stage(report: ReturnType<typeof parsePipelineDiagnostics>, id: string) {
  const s = report.stages.find((x) => x.id === id);
  if (!s) throw new Error(`stage ${id} missing`);
  return s;
}

function sub(report: ReturnType<typeof parsePipelineDiagnostics>, stageId: string, subId: string) {
  return stage(report, stageId).subRules.find((r) => r.id === subId);
}

describe('classifyReason', () => {
  it('maps every backend reason to the stage its counter belongs to', () => {
    const byStage = Object.fromEntries(REJECTED.map((r) => [r.symbol, classifyReason(r).stage]));
    expect(byStage).toEqual({
      PENNY: 'data-filters', TINY: 'data-filters', NODATA: 'data-filters', NOREG: 'data-filters',
      WTREND: 'pre-screen', WVOL: 'pre-screen', ALLHI: 'pre-screen', NOBD: 'pre-screen', UNMEAS: 'pre-screen',
      NOOPT: 'chain-window',
      SG: 'contract-rules', NVDA: 'contract-rules', IVONLY: 'contract-rules', LOWSC: 'contract-rules', BARE: 'contract-rules',
      DIR1: 'direction-shortlist', DIR2: 'direction-shortlist', DIR3: 'direction-shortlist',
      CAPPED: 'direction-shortlist', ERR: 'direction-shortlist',
    });
  });

  it('does not count an IV-only or score-only contract reject as a spread reject', () => {
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'IVONLY')!).subRules).toEqual(['iv']);
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'LOWSC')!).subRules).toEqual(['low-score']);
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'BARE')!).subRules).toEqual(['other-contract']);
    expect(classifyReason({ symbol: 'X', reason: 'contracts rejected: dte_too_short(3), brand_new_code(1)' }).subRules)
      .toEqual(['dte', 'other-contract']);
  });

  it('separates an unmeasured trend from a measured one below the floor', () => {
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'UNMEAS')!).subRules).toEqual(['trend-unmeasured']);
    expect(classifyReason(REJECTED.find((r) => r.symbol === 'DIR1')!).subRules).toEqual(['direction']);
  });
});

describe('helpers', () => {
  it('contractCodes reads codes before the "; best contract score" suffix only', () => {
    expect(contractCodes('contracts rejected: spread_too_wide(14), volume_too_low(8)')).toEqual(['spread_too_wide', 'volume_too_low']);
    expect(contractCodes('contracts rejected: contract_score_below_caution(4); best contract score 30 < caution 40'))
      .toEqual(['contract_score_below_caution']);
    expect(contractCodes('all contracts rejected')).toEqual([]);
  });

  it('weakestComponent names the lowest key, including vol, with no threshold', () => {
    expect(weakestComponent({ trend: 70, vol: 10 })).toBe('vol');
    expect(weakestComponent({ trend: 60, pullback: 58 })).toBe('pullback');
    expect(weakestComponent({ trend: 30, pullback: 30 })).toBe('trend');
    expect(weakestComponent(undefined)).toBeUndefined();
  });
});

describe('parsePipelineDiagnostics', () => {
  const report = parsePipelineDiagnostics(PIPELINE, REJECTED, SURVIVORS);

  it('stage drops plus survivors account for the whole universe', () => {
    expect(report.scanned).toBe(22);
    expect(report.totalDropped).toBe(20);
    const dropped = report.stages.reduce((n, s) => n + s.droppedCount, 0);
    expect(dropped + report.candidatesCount).toBe(report.scanned);
    expect(report.stages[report.stages.length - 1].remainingCount).toBe(report.candidatesCount);
  });

  it('takes stage counts from the backend counters', () => {
    expect(stage(report, 'data-filters').droppedCount).toBe(4);
    expect(stage(report, 'pre-screen').droppedCount).toBe(5);         // 4 pre-screen + 1 unmeasured
    expect(stage(report, 'chain-window').droppedCount).toBe(1);
    expect(stage(report, 'contract-rules').droppedCount).toBe(5);     // 1 score gate + 4 contracts
    expect(stage(report, 'direction-shortlist').droppedCount).toBe(5); // 3 direction + 1 cap + 1 other
  });

  it('subtracts the unmeasured-trend drops before the chain stage', () => {
    expect(stage(report, 'pre-screen').remainingCount).toBe(22 - 4 - 5);
  });

  it('attributes pre-screen rejects to their weakest component, including vol, never defaulting to trend', () => {
    expect(sub(report, 'pre-screen', 'weak-trend')?.symbols).toEqual(['WTREND']);
    expect(sub(report, 'pre-screen', 'weak-vol')?.symbols).toEqual(['WVOL']);
    expect(sub(report, 'pre-screen', 'weak-pullback')?.symbols).toEqual(['ALLHI']);
    expect(sub(report, 'pre-screen', 'no-breakdown')?.symbols).toEqual(['NOBD']);
    expect(sub(report, 'pre-screen', 'trend-unmeasured')?.symbols).toEqual(['UNMEAS']);
    expect(sub(report, 'pre-screen', 'weak-regime')).toBeUndefined();
  });

  it('lists score-gate and every contract rule symbol where it belongs', () => {
    expect(sub(report, 'contract-rules', 'score-gate')?.symbols).toEqual(['SG']);
    expect(sub(report, 'contract-rules', 'spread')?.symbols).toEqual(['NVDA']);
    expect(sub(report, 'contract-rules', 'liquidity')?.symbols).toEqual(['NVDA']);
    expect(sub(report, 'contract-rules', 'iv')?.symbols).toEqual(['IVONLY']);
    expect(sub(report, 'contract-rules', 'low-score')?.symbols).toEqual(['LOWSC']);
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
        ...['A', 'B', 'C', 'D', 'E', 'F'].map((s) => ({ symbol: s, reason: 'direction_conviction: trend 20 < 40 (Bearish/Swing)' })),
      ],
      ['WIN'],
    );
    expect(r.primaryBottleneck?.stageId).toBe('direction-shortlist');
    expect(r.primaryBottleneck?.droppedCount).toBe(6);
    expect(r.primaryBottleneck?.insight).toContain('Direction Conviction (6)');
  });

  it('names no bottleneck when nothing was dropped', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 2, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0, candidates: 2 },
      [],
      ['A', 'B'],
    );
    expect(r.primaryBottleneck).toBeNull();
    expect(r.stages.every((s) => !s.isBottleneck)).toBe(true);
    expect(r.asciiTree).not.toContain('PRIMARY BOTTLENECK');
  });

  it('never invents sub-rule counts when per-symbol reasons are missing', () => {
    const r = parsePipelineDiagnostics(
      { scanned: 500, failed_data: 0, failed_pre_screen: 300, no_chain: 0, failed_score: 0, failed_contracts: 0, candidates: 200 },
      [],
      [],
    );
    const pre = stage(r, 'pre-screen');
    expect(pre.droppedCount).toBe(300);
    for (const s of pre.subRules) expect(s.count).toBeNull();
    expect(pre.note).toMatch(/breakdown unavailable/i);
    expect(r.asciiTree).toContain(': —');
  });

  it('does not double-count unmeasured trends on a result stored before that counter existed', () => {
    const r = parsePipelineDiagnostics(
      // failed_direction already includes the unmeasured one; no separate counter
      { scanned: 5, failed_data: 0, failed_pre_screen: 0, no_chain: 0, failed_score: 0, failed_contracts: 0,
        failed_direction: 2, candidates: 3 },
      [
        { symbol: 'U', reason: 'direction_conviction_unmeasured: trend not measured' },
        { symbol: 'D', reason: 'direction_conviction: trend 10 < 40' },
      ],
      ['A', 'B', 'C'],
    );
    expect(r.stages.reduce((n, s) => n + s.droppedCount, 0)).toBe(2);
  });

  it('shows a threshold in a label only when the scan recorded it', () => {
    expect(sub(report, 'contract-rules', 'spread')?.label).toBe('Spread Too Wide');
    expect(sub(report, 'contract-rules', 'spread')?.ruleExplanation).toContain('contract_rules.yaml');
    const withRules = parsePipelineDiagnostics(PIPELINE, [...REJECTED, { symbol: 'DLT', reason: 'contracts rejected: delta_too_low_far_otm(5)' }], SURVIVORS, {
      contractRules: { max_bid_ask_spread_pct: 0.2, min_open_interest: 200, min_delta: 0.2, max_delta: 0.85 },
      dteWindow: { min_dte: 30, max_dte: 60, multiplier: 1 },
    });
    expect(sub(withRules, 'contract-rules', 'spread')?.label).toBe('Spread Too Wide (> 20% of mid)');
    expect(sub(withRules, 'contract-rules', 'liquidity')?.label).toBe('Low Liquidity (OI < 200)');
    expect(sub(withRules, 'contract-rules', 'delta')?.label).toBe('Delta Outside Range (outside 0.2–0.85)');
    expect(sub(withRules, 'chain-window', 'no-chain')?.label).toBe('No Option Chain Returned (30–60d)');
    // the old literals that disagreed with contract_rules.yaml are gone
    expect(withRules.asciiTree).not.toMatch(/15%|OI < 500|0\.30/);
  });

  it('looks up survivors, every rejected stage, and unknown symbols', () => {
    expect(report.lookupSymbol('aapl')?.status).toBe('SURVIVOR');
    expect(report.lookupSymbol('SG')?.stageName).toBe('Score Gate & Contract Rules');
    expect(report.lookupSymbol('NOREG')?.stageName).toBe('Data & Universe Filters');
    expect(report.lookupSymbol('UNMEAS')?.primaryReason).toBe('Trend Unmeasured (direction gate, no data)');
    expect(report.lookupSymbol('NVDA')?.primaryReason).toBe('Spread Too Wide, Low Liquidity');
    expect(report.lookupSymbol('CAPPED')?.primaryReason).toBe('Shortlist Cap');
    expect(report.lookupSymbol('WVOL')?.weakestComponent).toBe('vol');
    expect(report.lookupSymbol('ERR')?.detailedReason).toBe('(no reason recorded)');
    expect(report.lookupSymbol('ZZZZ')).toBeNull();
    expect(report.lookupSymbol('   ')).toBeNull();
  });

  it('handles no data without NaN', () => {
    const r = parsePipelineDiagnostics(undefined, [], []);
    expect(r.scanned).toBe(0);
    expect(r.primaryBottleneck).toBeNull();
    for (const s of r.stages) {
      expect(Number.isNaN(s.pctOfTotal)).toBe(false);
      for (const x of s.subRules) {
        expect(Number.isNaN(x.pctOfStage ?? 0)).toBe(false);
        expect(Number.isNaN(x.pctOfTotal ?? 0)).toBe(false);
      }
    }
  });

  it('survives undefined counters on a partial pipeline object', () => {
    const r = parsePipelineDiagnostics({ scanned: 3 } as unknown as OptionsPipeline, [], ['A']);
    for (const s of r.stages) expect(Number.isFinite(s.droppedCount)).toBe(true);
  });
});
