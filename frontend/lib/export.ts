// xlsx has 2 known high-severity CVEs (prototype pollution, ReDoS) with no
// upstream fix on npm — both trigger only via XLSX.read/readFile parsing
// attacker-controlled input. This file only writes (json_to_sheet/writeFile)
// from our own in-memory data, never parses external files, so neither is
// reachable here. Re-check this note if XLSX.read/readFile is ever added
// anywhere in this codebase.
import * as XLSX from 'xlsx';
import type { WatchlistRow, TradeCardData } from '@/types/domain';

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
    'Next Event': r.nextEventDays != null
      ? `${r.nextEventDays}d${r.nextEventLabel ? ` (${r.nextEventLabel})` : ''}`
      : '—',
  }));

  const ws = XLSX.utils.json_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Rankings');
  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
}

export function exportValidationToXlsx(candidates: TradeCardData[], filename: string): void {
  const data = candidates.map((c, i) => ({
    Rank:     i + 1,
    Symbol:   c.symbol,
    Company:  c.company,
    Direction: c.direction,
    Score:    c.stockScore,
    Status:   c.finalStatus,
    Trend:    c.stockBreakdown.trend,
    Pullback: c.stockBreakdown.pullback,
    Trigger:  c.stockBreakdown.trigger,
    Event:    c.stockBreakdown.event,
    Vol:      c.stockBreakdown.volatility,
  }));

  const ws = XLSX.utils.json_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Validation');
  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
}
