/*
 * PORTFOLIO-HISTORY-INSIGHTS (#663): the trade statistics strip above the
 * History chart. Pure display of `computeTradeStats` output: the stats hold raw
 * numbers and every figure is formatted here (formulas: lib/tradeStats.ts).
 * A missing value is shown as an em dash, never as a zero.
 */

import { Text, Data } from '@/components/primitives';
import { formatMoney, moneyTone } from '@/lib/portfolioFormat';
import type { TradeStats } from '@/lib/tradeStats';
import styles from './page.module.css';

const DASH = '—';

export function stopTooltip(stopPct: number): string {
  return `Compared with today's global premium stop (${Math.round(stopPct * 100)}%), not the stop that applied at entry — the stop at entry is not stored yet.`;
}

function money(v: number | null): string {
  return v === null ? DASH : formatMoney(v, { plus: true });
}

function tone(v: number | null) {
  return v === null ? undefined : moneyTone(v);
}

export function TradeStatsStrip({ stats, stopPct }: { stats: TradeStats; stopPct: number }) {
  const winRate = stats.winRate === null ? DASH : `${Math.round(stats.winRate)}%`;
  const lossToWin = stats.lossToWin === null ? null : `${stats.lossToWin.toFixed(1)}× the average win`;
  const profitFactor = stats.profitFactor === null ? DASH : stats.profitFactor.toFixed(2);
  const h = stats.hold;
  let hold = h.avg === null ? DASH : `${h.avg} days (${h.min}–${h.max})`;
  if (h.avg !== null && h.n < stats.count) hold += ` · ${h.n} of ${stats.count} trades`;
  const ps = stats.pastStop;
  const pastStop = ps.of === 0 ? DASH : `${ps.n} of ${ps.of} losses`;
  const notChecked = stats.losses - ps.of;

  return (
    <section className={styles.tradeStats} aria-label="Trade statistics">
      <div className={styles.tradeStatsGrid}>
        <div className={styles.tradeStat}>
          <Text size={11} tone="dim">Win rate</Text>
          <span data-testid="stat-winrate"><Data size={16} weight={500}>{winRate}</Data></span>
          <Text size={11} tone="dim">{`${stats.wins} wins · ${stats.losses} losses · ${stats.flats} flat`}</Text>
        </div>
        <div className={styles.tradeStat}>
          <Text size={11} tone="dim">Average win</Text>
          <span data-testid="stat-avgwin"><Data size={16} weight={500} tone={tone(stats.avgWin)}>{money(stats.avgWin)}</Data></span>
        </div>
        <div className={styles.tradeStat}>
          <Text size={11} tone="dim">Average loss</Text>
          <span data-testid="stat-avgloss"><Data size={16} weight={500} tone={tone(stats.avgLoss)}>{money(stats.avgLoss)}</Data></span>
          {lossToWin !== null && <span data-testid="stat-losstowin"><Text size={11} tone="dim">{lossToWin}</Text></span>}
        </div>
        <div className={styles.tradeStat}>
          <Text size={11} tone="dim">Profit factor</Text>
          <span data-testid="stat-profitfactor"><Data size={16} weight={500}>{profitFactor}</Data></span>
        </div>
        <div className={styles.tradeStat}>
          <Text size={11} tone="dim">Expectancy per trade</Text>
          <span data-testid="stat-expectancy"><Data size={16} weight={500} tone={tone(stats.expectancy)}>{money(stats.expectancy)}</Data></span>
        </div>
        <div className={styles.tradeStat}>
          <Text size={11} tone="dim">Average hold</Text>
          <span data-testid="stat-hold"><Data size={16} weight={500}>{hold}</Data></span>
        </div>
        <div className={styles.tradeStat} data-testid="stat-paststop-cell" title={stopTooltip(stopPct)}>
          <Text size={11} tone="dim">{'Past premium stop: '}</Text>
          <span data-testid="stat-paststop"><Data size={16} weight={500}>{pastStop}</Data></span>
          {notChecked > 0 && (
            <Text size={11} tone="dim">{`(${notChecked} losses not checked: stock or no entry price)`}</Text>
          )}
        </div>
      </div>
      {stats.skipped > 0 && (
        <Text size={11} tone="caution">{`${stats.skipped} rows with invalid P&L ignored`}</Text>
      )}
    </section>
  );
}
