import type { StockPipeline } from '@/types/stockDomain';
import type { DiagnosticStage, DiagnosticSubRule, PipelineDiagnosticReport, StageId } from './parsePipelineDiagnostics';
import { isPlaceholderScore } from './parsePipelineDiagnostics';
import { SHORTLIST_REASON_PREFIX } from './shortlistCap';

export interface StockRejectedEntry {
  symbol: string;
  reason: string;
  breakdown?: Record<string, number>;
}

type Bucket = 'history' | 'score' | 'direction' | 'direction-unmeasured' | 'regime' | 'signal' | 'backtest' | 'shortlist' | 'other';

// Exact first-match predicates from stock_scan.classify_stock_rejection.
function classify(reason: string): Bucket {
  if (reason.includes('insufficient history') || reason.includes('insufficient intraday history')
    || reason.includes('no price data') || reason.startsWith('price $')
    || reason.startsWith('regime data unavailable:') || reason.startsWith('Excluded (data):')) return 'history';
  if (reason.startsWith('REJECT score=')) return 'score';
  if (reason.startsWith('direction_conviction_unmeasured:')) return 'direction-unmeasured';
  if (reason.startsWith('direction_conviction:')) return 'direction';
  if (reason === 'regime headwind') return 'regime';
  if ((reason.startsWith('no ') && reason.includes('setup'))
    || reason.startsWith('no mean_reversion_multi:') || reason.startsWith('mean_reversion_multi:')) return 'signal';
  if (reason.startsWith('backtest gate:') || reason.startsWith('confidence gate ')) return 'backtest';
  if (reason.startsWith(SHORTLIST_REASON_PREFIX)) return 'shortlist';
  return 'other';
}

const finite = (n: number | null | undefined): number | undefined =>
  typeof n === 'number' && Number.isFinite(n) ? n : undefined;

/** Counters describe totals; raw reasons describe only the recorded symbols.
 * Survivor symbols must be the complete scan shortlist, not a visible page. */
export function parseStockPipelineDiagnostics(
  pipeline?: Partial<StockPipeline>,
  rejected: StockRejectedEntry[] = [],
  survivorSymbols: string[] = [],
): PipelineDiagnosticReport {
  const candidatesCount = survivorSymbols.length;
  const scanned = finite(pipeline?.scanned) ?? rejected.length + candidatesCount;
  const totalDropped = Math.max(0, scanned - candidatesCount);
  const listed = (bucket: Bucket) => rejected.filter(r => classify(r.reason || '') === bucket);
  let reconstructed = 0;
  const count = (bucket: Bucket, counter?: number) => {
    const recorded = finite(counter);
    if (recorded !== undefined) return recorded;
    const fallback = listed(bucket).length;
    if (bucket !== 'other') reconstructed += fallback;
    return fallback;
  };
  const direction = count('direction', pipeline?.failed_direction);
  // Unlike options, stock failed_direction counts only the measured prefix.
  // An absent unmeasured counter therefore does not reduce failed_direction.
  const unmeasured = count('direction-unmeasured', pipeline?.failed_direction_unmeasured);
  const defs: Array<{ key: Exclude<Bucket, 'direction-unmeasured'>; title: string; count: number; summary: string }> = [
    { key: 'history', title: 'History & Data', count: count('history', pipeline?.failed_history), summary: 'History, price bounds and unavailable price or regime data.' },
    { key: 'score', title: 'Score Gate', count: count('score', pipeline?.failed_score), summary: 'Recorded REJECT score outcomes, including the minimum stock score gate.' },
    { key: 'direction', title: 'Direction', count: direction + unmeasured, summary: 'Measured conviction below the scan floor, or no trend measurement.' },
    { key: 'regime', title: 'Regime', count: count('regime', pipeline?.failed_regime), summary: 'Recorded regime headwind.' },
    { key: 'signal', title: 'Signal', count: count('signal', pipeline?.failed_signal), summary: 'No strategy setup or no valid combined signal.' },
    { key: 'backtest', title: 'Backtest', count: count('backtest', pipeline?.failed_backtest), summary: 'Recorded backtest or confidence gate failure.' },
    { key: 'shortlist', title: 'Shortlist', count: count('shortlist', pipeline?.failed_shortlist), summary: 'Passed the gates, then trimmed by rank at the shortlist cap.' },
    { key: 'other', title: 'Other & Not Attributed', count: count('other', pipeline?.other_rejected), summary: 'Residual reasons and drops not covered by any recorded counter.' },
  ];
  // Legacy residuals included reasons whose dedicated counters were absent.
  // Explicit counters, including zero, remain authoritative.
  const other = defs[defs.length - 1];
  const recordedOther = finite(pipeline?.other_rejected);
  const migrated = recordedOther === undefined ? 0 : Math.min(recordedOther, reconstructed);
  other.count -= migrated;
  const accounted = defs.reduce((sum, d) => sum + d.count, 0);
  const gap = Math.max(0, totalDropped - accounted);
  other.count += gap;
  // Like ScanFunnel, exclude residuals before gates; qualify unknown placement.
  if (other.count > 0) defs.unshift(defs.pop()!);
  const reconciliationNote = accounted > totalDropped
    ? `The stage counts add up to ${accounted}, more than the ${totalDropped} not ranked (scanned - survivors); this result's counters are inconsistent.`
    : candidatesCount > scanned ? `The ${candidatesCount} survivor symbols exceed the ${scanned} scanned symbols; this result is inconsistent.` : undefined;
  let remaining = scanned;
  const stages: DiagnosticStage[] = defs.map(d => {
    const entries = d.key === 'direction' ? [...listed('direction'), ...listed('direction-unmeasured')] : listed(d.key);
    const groups = new Map<string, string[]>();
    for (const r of entries) {
      const reason = r.reason || '(no reason recorded)';
      groups.set(reason, [...(groups.get(reason) ?? []), r.symbol.toUpperCase()]);
    }
    const subRules: DiagnosticSubRule[] = [...groups].map(([reason, symbols], i) => ({
      id: `reason-${i}`, label: reason, count: symbols.length, symbols, ruleExplanation: d.summary,
    }));
    const reasonTotal = d.key === 'other' ? d.count - gap : d.count;
    if (!entries.length && reasonTotal > 0) subRules.push({
      id: 'missing-reasons', label: 'Per-rule breakdown unavailable', count: null, symbols: [],
      ruleExplanation: 'The counter was recorded without per-symbol reasons.',
    });
    if (d.key === 'other' && gap > 0) subRules.push({
      id: 'unattributed', label: 'Not Attributed', count: gap, symbols: [],
      ruleExplanation: 'Not ranked, but no recorded stage count covers these drops.',
    });
    const reasonNote = entries.length !== reasonTotal
      ? `${entries.length} recorded per-symbol reasons; the scan counted ${reasonTotal} drops here. ${entries.length < reasonTotal ? 'Missing reasons are not attributed to sub-rules.' : 'Listed reasons exceed the stage counter.'}`
      : undefined;
    const note = [reasonNote,
      d.key === 'other' && migrated > 0
        ? `${migrated} listed legacy drops moved from other_rejected to buckets with absent counters.` : undefined,
      d.key === 'other' && d.count > 0
        ? 'Residual failure positions are unknown. Gate Left counts exclude residual and unattributed drops; they do not establish that those symbols reached or passed each gate.' : undefined,
    ].filter(Boolean).join(' ') || undefined;
    remaining = Math.max(0, remaining - d.count);
    return { id: `stock-${d.key}` as StageId, title: d.title, droppedCount: d.count,
      remainingCount: remaining, pctOfTotal: scanned > 0 ? Math.round(d.count / scanned * 100) : 0,
      isBottleneck: false, ruleSummary: d.summary, subRules,
      allSymbols: entries.map(r => r.symbol.toUpperCase()), note };
  });
  const bottleneck = stages.reduce<DiagnosticStage | undefined>((best, s) =>
    s.droppedCount > (best?.droppedCount ?? 0) ? s : best, undefined);
  if (bottleneck) bottleneck.isBottleneck = true;
  const primaryBottleneck = bottleneck ? {
    stageId: bottleneck.id, stageTitle: bottleneck.title, droppedCount: bottleneck.droppedCount,
    pctOfTotal: bottleneck.pctOfTotal,
    insight: `${bottleneck.title} removed ${bottleneck.droppedCount} of ${scanned} scanned symbols (${bottleneck.pctOfTotal}%).`,
    suggestedAction: 'Inspect recorded symbol reasons and the parameters used by this scan.',
    adjustHref: null, adjustLabel: null,
  } : null;
  const lines = [`Universe (${scanned})`];
  for (const s of stages) {
    lines.push(`|- [-${s.droppedCount}] ${s.title} (Left: ${s.remainingCount}) - ${s.pctOfTotal}%${s.isBottleneck ? ' <-- [PRIMARY BOTTLENECK]' : ''}`);
    for (const r of s.subRules) lines.push(`|  |- ${r.label}: ${r.count === null ? '-' : r.count}`);
    if (s.note) lines.push(`|  |- (${s.note})`);
  }
  if (reconciliationNote) lines.push(`|- (${reconciliationNote})`);
  lines.push(`Final Candidates: ${candidatesCount} Survivors`);
  const survivorSet = new Set(survivorSymbols.map(s => s.toUpperCase()));
  const symbolMap = new Map(rejected.map(r => [r.symbol.toUpperCase(), r]));
  return { scanned, candidatesCount, totalDropped, stages, primaryBottleneck, reconciliationNote,
    asciiTree: lines.join('\n'), lookupSymbol(query) {
      const symbol = (query ?? '').trim().toUpperCase();
      if (survivorSet.has(symbol)) return { symbol, status: 'SURVIVOR', stageName: 'Passed All Gates',
        primaryReason: 'Ranked candidate', detailedReason: 'Cleared the scan gates and made the shortlist.' };
      const entry = symbolMap.get(symbol);
      if (!entry) return null;
      const bucket = classify(entry.reason || '');
      const key = bucket === 'direction-unmeasured' ? 'direction' : bucket;
      const components = entry.breakdown ? ['trend', 'pullback', 'trigger', 'event', 'vol']
        .filter(k => Number.isFinite(entry.breakdown![k])).map(k => ({ key: k,
          label: k[0].toUpperCase() + k.slice(1), score: entry.breakdown![k],
          placeholder: isPlaceholderScore(k, entry.breakdown![k]) })) : undefined;
      return { symbol, status: bucket === 'shortlist' ? 'TRIMMED' : 'REJECTED',
        stageName: defs.find(d => d.key === key)!.title,
        primaryReason: entry.reason || '(no reason recorded)', detailedReason: entry.reason || '(no reason recorded)', components };
    } };
}
