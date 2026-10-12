import { parseStockPipelineDiagnostics as parse } from '../parseStockPipelineDiagnostics';
import { SHORTLIST_REASON_PREFIX } from '../shortlistCap';

const zero = { scanned: 0, failed_history: 0, failed_score: 0, failed_direction: 0,
  failed_direction_unmeasured: 0, failed_regime: 0, failed_signal: 0,
  failed_backtest: 0, failed_shortlist: 0, other_rejected: 0, candidates: 0 };

describe('stock pipeline diagnostics', () => {
  it('reproduces the 518-symbol screenshot and exports the same stage numbers', () => {
    const report = parse({ ...zero, scanned: 518, failed_history: 16, failed_score: 195,
      failed_direction: 26, failed_signal: 280, failed_backtest: 1 });
    expect(report.stages.map(s => s.droppedCount)).toEqual([16, 195, 26, 0, 280, 1, 0, 0]);
    expect(report.stages.map(s => s.remainingCount)).toEqual([502, 307, 281, 281, 1, 0, 0, 0]);
    expect(report.primaryBottleneck).toMatchObject({ stageId: 'stock-signal', droppedCount: 280, pctOfTotal: 54 });
    expect(report.candidatesCount).toBe(0);
    expect(report.reconciliationNote).toBeUndefined();
    for (const stage of report.stages) {
      expect(report.asciiTree).toContain(`[-${stage.droppedCount}] ${stage.title} (Left: ${stage.remainingCount})`);
      if (stage.droppedCount) {
        expect(stage.subRules[0].count).toBeNull();
        expect(stage.note).toContain('Missing reasons');
      }
    }
  });

  it.each([
    ['insufficient history', 'history'], ['insufficient intraday history', 'history'],
    ['no price data', 'history'], ['price $3.00 < min', 'history'], ['price $900.00 > max', 'history'],
    ['regime data unavailable: no completed 15-min bars for XYZ', 'history'],
    ['Excluded (data): acquired; stored bars are not this company', 'history'],
    ['Excluded (data): no strategy setup in excluded history', 'history'],
    ['Excluded (data): backtest gate: price source unavailable', 'history'],
    ['REJECT score=42', 'score'], ['REJECT score=42 < min 50', 'score'],
    ['direction_conviction: trend 20 < 40 for Bearish Position', 'direction'],
    ['direction_conviction_unmeasured: no trend measurement for Bullish Swing', 'direction'],
    ['regime headwind', 'regime'], ['no pullback_ema setup', 'signal'],
    ['no mean_reversion_multi: 0/3 signals fired', 'signal'],
    ['mean_reversion_multi: variants produced no valid combined levels', 'signal'],
    ['backtest gate: insufficient trades', 'backtest'], ['confidence gate REJECT: 10% < 50%', 'backtest'],
    [`${SHORTLIST_REASON_PREFIX} ranked below cap 2`, 'shortlist'],
    ['', 'other'], ['provider timeout', 'other'], ['Regime headwind', 'other'],
    ['no test setup: insufficient history', 'history'],
    ['backtest gate: no price data', 'history'],
  ])('matches authoritative first-match producer reason %s', (reason, key) => {
    const report = parse(undefined, [{ symbol: 'xyz', reason }]);
    expect(report.stages.find(s => s.droppedCount === 1)?.id).toBe(`stock-${key}`);
    expect(report.lookupSymbol(' XYZ ')?.detailedReason).toBe(reason || '(no reason recorded)');
    const rule = report.stages.find(s => s.droppedCount === 1)!.subRules[0];
    expect(rule.ruleExplanation).not.toBe(rule.label);
  });

  it('uses listed optional counters and keeps stock measured direction intact', () => {
    const report = parse({ scanned: 3, failed_direction: 2 }, [
      { symbol: 'AAA', reason: 'direction_conviction_unmeasured: no trend measurement' },
    ]);
    expect(report.stages.find(s => s.id === 'stock-direction')?.droppedCount).toBe(3);
    expect(report.reconciliationNote).toBeUndefined();
  });

  it.each([
    ['failed_history', 'insufficient history', 'history'],
    ['failed_score', 'REJECT score=20', 'score'],
    ['failed_direction', 'direction_conviction: low trend', 'direction'],
    ['failed_direction_unmeasured', 'direction_conviction_unmeasured: no trend', 'direction'],
    ['failed_regime', 'regime headwind', 'regime'],
    ['failed_signal', 'no pullback_ema setup', 'signal'],
    ['failed_backtest', 'backtest gate: insufficient trades', 'backtest'],
    ['failed_shortlist', `${SHORTLIST_REASON_PREFIX} rank > 1`, 'shortlist'],
  ])('migrates absent %s but preserves explicit zero', (counter, reason, key) => {
    const entries = [{ symbol: 'DROP', reason }];
    const absent = parse({ scanned: 2, other_rejected: 1 }, entries, ['KEPT']);
    expect(absent.stages.find(s => s.id === `stock-${key}`)?.droppedCount).toBe(1);
    expect(absent.stages.find(s => s.id === 'stock-other')?.droppedCount).toBe(0);
    expect(absent.stages.find(s => s.id === 'stock-other')?.note).toContain('legacy drops moved');
    expect(absent.reconciliationNote).toBeUndefined();
    expect(absent.stages.reduce((n, s) => n + s.droppedCount, 0)).toBe(1);
    const explicit = parse({ scanned: 2, other_rejected: 1, [counter]: 0 }, entries, ['KEPT']);
    expect(explicit.stages.find(s => s.id === `stock-${key}`)?.droppedCount).toBe(0);
    expect(explicit.stages.find(s => s.id === `stock-${key}`)?.note).toContain('exceed');
    expect(explicit.stages.find(s => s.id === 'stock-other')?.droppedCount).toBe(1);
  });

  it('excludes provider residuals before history and exports qualified Left counts', () => {
    const report = parse({ scanned: 3, failed_history: 1, other_rejected: 1 }, [
      { symbol: 'HISTORY', reason: 'insufficient history' },
      { symbol: 'ERROR', reason: 'provider exception' },
    ], ['KEPT']);
    expect(report.stages[0]).toMatchObject({ id: 'stock-other', droppedCount: 1, remainingCount: 2 });
    expect(report.stages.find(s => s.id === 'stock-history')?.remainingCount).toBe(1);
    expect(report.stages.at(-1)?.remainingCount).toBe(1);
    expect(report.asciiTree).toContain('History & Data (Left: 1)');
    expect(report.stages[0].note).toContain('failure positions are unknown');
    expect(report.reconciliationNote).toBeUndefined();
  });

  it('bounds migration with mixed authoritative and fallback buckets and keeps gaps explicit', () => {
    const report = parse({ scanned: 5, failed_direction: 1, other_rejected: 2 }, [
      { symbol: 'D', reason: 'direction_conviction: low trend' },
      { symbol: 'U', reason: 'direction_conviction_unmeasured: no trend' },
      { symbol: 'S', reason: `${SHORTLIST_REASON_PREFIX} rank > 1` },
      { symbol: 'R', reason: 'regime headwind' },
    ], ['KEPT']);
    expect(report.stages.find(s => s.id === 'stock-direction')?.droppedCount).toBe(2);
    expect(report.stages.find(s => s.id === 'stock-other')?.droppedCount).toBe(0);
    expect(report.reconciliationNote).toBeUndefined();
    const gap = parse({ scanned: 4, other_rejected: 1 }, [
      { symbol: 'D', reason: 'direction_conviction: low trend' },
    ], ['KEPT']);
    expect(gap.stages[0].subRules).toContainEqual(expect.objectContaining({ label: 'Not Attributed', count: 2, symbols: [] }));
    expect(gap.stages[0].note).toContain('failure positions are unknown');
  });

  it('shows legacy gaps separately from residual reasons', () => {
    const report = parse({ scanned: 5, failed_history: 1 }, [{ symbol: 'AAA', reason: 'provider error' }], ['KEPT']);
    const other = report.stages.find(s => s.id === 'stock-other')!;
    expect(other.droppedCount).toBe(3);
    expect(other.subRules.map(r => r.count)).toEqual([1, 2]);
    expect(other.subRules[1].label).toBe('Not Attributed');
    expect(report.stages.at(-1)?.remainingCount).toBe(1);
  });

  it('keeps counters authoritative with truncated and contradictory reason lists', () => {
    const report = parse({ ...zero, scanned: 4, failed_signal: 3 }, [{ symbol: 'AAA', reason: 'no breakout_base setup' }], ['KEPT']);
    const stage = report.stages.find(s => s.id === 'stock-signal')!;
    expect(stage.droppedCount).toBe(3);
    expect(stage.subRules[0].count).toBe(1);
    expect(stage.note).toContain('Missing reasons');
    const contradiction = parse({ ...zero, scanned: 1 }, [{ symbol: 'AAA', reason: 'no breakout_base setup' }]);
    expect(contradiction.stages.find(s => s.id === 'stock-signal')?.droppedCount).toBe(0);
    expect(contradiction.stages.find(s => s.id === 'stock-signal')?.note).toContain('exceed');
  });

  it('notes over-counted stages without fabricating a gap', () => {
    const report = parse({ ...zero, scanned: 2, failed_score: 4 });
    expect(report.reconciliationNote).toContain('add up to 4');
    expect(report.stages.find(s => s.id === 'stock-other')?.droppedCount).toBe(0);
    expect(report.asciiTree).toContain(report.reconciliationNote);
  });

  it('groups raw reasons and finds trims and complete survivors despite stale pipeline candidates', () => {
    const reason = `${SHORTLIST_REASON_PREFIX} rank > 2`;
    const report = parse({ scanned: 4, candidates: 999 }, [
      { symbol: 'aaa', reason }, { symbol: 'BBB', reason },
      { symbol: 'kept', reason: 'old error' },
    ], ['KEPT', 'LAST']);
    expect(report.candidatesCount).toBe(2);
    expect(report.lookupSymbol('last')?.status).toBe('SURVIVOR');
    expect(report.lookupSymbol('kept')?.status).toBe('SURVIVOR');
    expect(report.lookupSymbol('aaa')?.status).toBe('TRIMMED');
    expect(report.lookupSymbol('unknown')).toBeNull();
    expect(report.lookupSymbol(' ')).toBeNull();
    expect(report.stages.find(s => s.id === 'stock-shortlist')?.subRules[0]).toMatchObject({ count: 2, symbols: ['AAA', 'BBB'] });
  });

  it('returns only recorded weighted components and never invents a weakest component', () => {
    const report = parse(undefined, [{ symbol: 'AAA', reason: 'REJECT score=40',
      breakdown: { trend: 0, trigger: 63, regime: 0, confidence: 10, vol: NaN } }]);
    expect(report.lookupSymbol('AAA')?.components).toEqual([
      { key: 'trend', label: 'Trend', score: 0, placeholder: true },
      { key: 'trigger', label: 'Trigger', score: 63, placeholder: false },
    ]);
    expect(report.lookupSymbol('AAA')?.weakestComponent).toBeUndefined();
    expect(parse(undefined, [{ symbol: 'BBB', reason: 'REJECT score=30' }]).lookupSymbol('BBB')?.components).toBeUndefined();
    expect(parse(zero).primaryBottleneck).toBeNull();
  });
});
