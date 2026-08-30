/*
 * RMultipleBadge — net P&L (+ R-multiple, when available) for a journal entry.
 *
 * NOT statusForScore-style coloring — that's a 0–100 percentage-threshold
 * function with no applicability to a P&L dollar amount or an R-multiple, and
 * no neutral/dash output. Tone-derivation priority:
 *   1. `net_pnl`'s sign, when net_pnl is set and non-zero — the realized
 *      outcome, and the one that matters once a trade is closed.
 *   2. `r_multiple`'s sign, only when net_pnl is null and r_multiple isn't.
 *      r_multiple's own null-guard requires net_pnl to be set (see the
 *      backend's computed_field), so this branch is unreachable in practice —
 *      kept only for defensive completeness, per the plan.
 *   3. Neutral/dash tone otherwise: both null (open trade, no P&L yet) or
 *      net_pnl === 0 (breakeven — neither a pass nor a reject).
 */

import { Data } from '@/components/primitives';
import styles from './RMultipleBadge.module.css';

interface RMultipleBadgeProps {
  netPnl: number | null;
  rMultiple: number | null;
  className?: string;
}

function signed(value: number, digits: number, suffix = ''): string {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

export function RMultipleBadge({ netPnl, rMultiple, className }: RMultipleBadgeProps) {
  let tone: 'pass' | 'reject' | 'dim' = 'dim';
  if (netPnl != null && netPnl !== 0) {
    tone = netPnl > 0 ? 'pass' : 'reject';
  } else if (netPnl == null && rMultiple != null && rMultiple !== 0) {
    tone = rMultiple > 0 ? 'pass' : 'reject';
  }

  const pnlText = netPnl != null ? signed(netPnl, 2) : '—';
  const rText = rMultiple != null ? signed(rMultiple, 2, 'R') : null;

  return (
    <span className={[styles.wrap, className].filter(Boolean).join(' ')}>
      <Data size={12} weight={500} tone={tone}>{pnlText}</Data>
      {rText && <Data size={11} tone="secondary" className={styles.r}>{rText}</Data>}
    </span>
  );
}
