import * as XLSX from 'xlsx';
import type { WatchlistRow } from '@/types/domain';

function buildSheetData(rows: WatchlistRow[]): Record<string, unknown>[] {
  return rows.map((r, i) => ({
    Rank:         i + 1,
    Symbol:       r.symbol,
    Company:      r.company,
    Direction:    r.direction,
    Score:        r.score,
    'Score Δ':    r.scoreDelta ?? 0,
    'Rank Δ':     r.rankDelta,
    Status:       r.status,
    Trend:        r.breakdown.trend,
    Pullback:     r.breakdown.pullback,
    Trigger:      r.breakdown.trigger,
    Event:        r.breakdown.event,
    Vol:          r.breakdown.volatility,
    'Next Event': r.nextEventDays !== undefined
      ? `${r.nextEventDays}d${r.nextEventLabel ? ` (${r.nextEventLabel})` : ''}`
      : '—',
  }));
}

export function exportToXlsx(
  ranked: WatchlistRow[],
  rejected: WatchlistRow[],
  filename: string
): void {
  const wb = XLSX.utils.book_new();

  if (ranked.length > 0) {
    const wsRanked = XLSX.utils.json_to_sheet(buildSheetData(ranked));
    XLSX.utils.book_append_sheet(wb, wsRanked, 'Rankings');
  }

  if (rejected.length > 0) {
    const wsRejected = XLSX.utils.json_to_sheet(buildSheetData(rejected));
    XLSX.utils.book_append_sheet(wb, wsRejected, 'Rejected');
  }

  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
}
