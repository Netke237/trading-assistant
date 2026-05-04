import * as XLSX from 'xlsx';
import type { WatchlistRow } from '@/types/domain';

export function exportToXlsx(rows: WatchlistRow[], filename: string): void {
  const data = rows.map((r, i) => ({
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

  const ws = XLSX.utils.json_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Rankings');
  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
}
