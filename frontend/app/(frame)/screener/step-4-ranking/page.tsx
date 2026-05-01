'use client';

/*
 * Screener Step 4 — Stock Ranking.
 *
 * Split-panel layout:
 *   - Left: ranked candidate table with status tint + score + rank delta
 *   - Right: SymbolHeader + candlestick preview + compact total-score card
 * Below: full-width per-component detail cards (Trend / Pullback / Trigger /
 * Event / Volatility) with raw, weight, weighted points and signal.
 */

import { useEffect, useState, useMemo } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { WatchStar } from '@/components/atoms/WatchStar';
import { api } from '@/lib/api';
import { exportToXlsx } from '@/lib/export';
import type { WatchlistRow } from '@/types/domain';
import type { Candle } from '@/types/chart';
import styles from './page.module.css';

const COLUMNS = '28px 1fr 46px 54px 64px 68px';

// Mirrors the Settings → Score weights defaults. Will read from store later.
const DEFAULT_WEIGHTS = {
  trend:      25,
  pullback:   20,
  trigger:    20,
  event:      15,
  volatility: 20,
} as const;

type ComponentKey = keyof typeof DEFAULT_WEIGHTS;

const COMPONENTS: { key: ComponentKey; label: string; desc: string }[] = [
  { key: 'trend',      label: 'Trend',      desc: 'Medium-term direction — price vs 200 EMA, slope of 50 EMA, higher highs.' },
  { key: 'pullback',   label: 'Pullback',   desc: 'Healthy retracement to a supportive level — not extended, not broken.' },
  { key: 'trigger',    label: 'Trigger',    desc: 'Short-term entry signal — engulfing, volume expansion, breakout close.' },
  { key: 'event',      label: 'Event',      desc: 'Calendar gate — earnings / FOMC proximity. High = clear of events.' },
  { key: 'volatility', label: 'Volatility', desc: 'IV rank sweet-spot — rich enough to earn premium, not blown-out.' },
];

type Signal = 'pos' | 'neu' | 'neg';

function signalFor(value: number): Signal {
  if (value >= 65) return 'pos';
  if (value >= 45) return 'neu';
  return 'neg';
}

function signalLabel(s: Signal): string {
  return s === 'pos' ? 'Positive' : s === 'neg' ? 'Negative' : 'Neutral';
}

type SortKey = 'symbol' | 'rankDelta' | 'scoreDelta' | 'score' | 'nextEventDays';
type SortDir = 'asc' | 'desc';

const DEFAULT_SORT: Record<SortKey, SortDir> = {
  symbol:       'asc',
  rankDelta:    'desc',
  scoreDelta:   'desc',
  score:        'desc',
  nextEventDays: 'asc',
};

function sortRows(rows: WatchlistRow[], key: SortKey, dir: SortDir): WatchlistRow[] {
  return [...rows].sort((a, b) => {
    let av: number | string;
    let bv: number | string;
    switch (key) {
      case 'symbol':        av = a.symbol;              bv = b.symbol;              break;
      case 'rankDelta':     av = a.rankDelta;           bv = b.rankDelta;           break;
      case 'scoreDelta':    av = a.scoreDelta ?? 0;     bv = b.scoreDelta ?? 0;     break;
      case 'score':         av = a.score;               bv = b.score;               break;
      case 'nextEventDays': av = a.nextEventDays ?? 9999; bv = b.nextEventDays ?? 9999; break;
    }
    if (av < bv) return dir === 'asc' ? -1 : 1;
    if (av > bv) return dir === 'asc' ? 1 : -1;
    return 0;
  });
}

interface SortHeaderProps {
  label: string;
  sortKey: SortKey;
  currentKey: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
}

function SortHeader({ label, sortKey, currentKey, dir, onSort }: SortHeaderProps) {
  const active = currentKey === sortKey;
  return (
    <button className={styles.sortBtn} onClick={() => onSort(sortKey)}>
      <span>{label}</span>
      <span className={active ? styles.sortIndActive : styles.sortInd}>
        {active ? (dir === 'asc' ? '▲' : '▼') : '⇅'}
      </span>
    </button>
  );
}

export default function Step4Page() {
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [candles, setCandles]     = useState<Candle[]>([]);
  const [selectedSym, setSelectedSym] = useState<string>('AAPL');
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  useEffect(() => { api.getWatchlist().then(setWatchlist).catch(() => {}); }, []);

  const sorted = useMemo(
    () => sortRows(watchlist, sortKey, sortDir),
    [watchlist, sortKey, sortDir],
  );

  const selected = sorted.find((r) => r.symbol === selectedSym) ?? sorted[0];

  useEffect(() => {
    if (!selected) return;
    api.getCandles(selected.symbol).then(setCandles).catch(() => {});
  }, [selected?.symbol]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(DEFAULT_SORT[key]);
    }
  }

  if (!selected) {
    return (
      <div className={styles.main}>
        <div className={styles.stepHeader}>
          <Text size={11} tone="dim" weight={500}>STEP 4 OF 7</Text>
          <Title as="h1" size={24}>Stock Ranking</Title>
        </div>
        <Text size={13} tone="dim">Loading candidates…</Text>
      </div>
    );
  }

  const contributions = COMPONENTS.map((c) => {
    const raw    = selected.breakdown[c.key];
    const weight = DEFAULT_WEIGHTS[c.key];
    const points = (raw * weight) / 100;
    return { ...c, raw, weight, points, signal: signalFor(raw) };
  });

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 4 OF 7</Text>
        <Title as="h1" size={24}>Stock Ranking</Title>
      </div>

      <div className={styles.split}>
        {/* LEFT — ranked table */}
        <section className={styles.leftPanel}>
          <header className={styles.panelHeader}>
            <Text size={13} weight={600}>Candidates</Text>
            <Text size={11} tone="secondary">{watchlist.length} ranked</Text>
            <button
              className={styles.exportBtn}
              onClick={() => exportToXlsx(sorted, 'bamendjou-rankings')}
              disabled={sorted.length === 0}
            >
              Export .xlsx
            </button>
          </header>
          <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
            <span aria-hidden />
            <SortHeader label="SYMBOL"   sortKey="symbol"        currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <SortHeader label="Δ RNK"    sortKey="rankDelta"     currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <SortHeader label="Δ SCR"    sortKey="scoreDelta"    currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <SortHeader label="SCORE"    sortKey="score"         currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <SortHeader label="NEXT"     sortKey="nextEventDays" currentKey={sortKey} dir={sortDir} onSort={handleSort} />
          </div>
          <div className={styles.tableBody}>
            {sorted.map((row) => (
              <TableRow
                key={row.symbol}
                status={row.status}
                columns={COLUMNS}
                selected={row.symbol === selectedSym}
                onClick={() => setSelectedSym(row.symbol)}
              >
                <WatchStar symbol={row.symbol} size="sm" />
                <div className={styles.symCell}>
                  <Data size={12} weight={500}>{row.symbol}</Data>
                  <Text size={11} tone="secondary">{row.company}</Text>
                </div>
                <RankDelta value={row.rankDelta}          context="rank"     />
                <RankDelta value={row.scoreDelta ?? 0}    context="score pt" />
                <Data size={13} weight={500}>{row.score}</Data>
                {row.nextEventDays !== undefined
                  ? <EventFlag days={row.nextEventDays} title={row.nextEventLabel} />
                  : <Text size={11} tone="dim">—</Text>}
              </TableRow>
            ))}
          </div>
        </section>

        {/* RIGHT — selected symbol detail */}
        <section className={styles.rightPanel}>
          <div className={styles.rightPanelHeader}>
            <WatchStar symbol={selected.symbol} />
            <div>
              <SymbolHeader
                ticker={selected.symbol}
                company={selected.company}
                price={selected.price}
                direction={selected.direction}
                status={selected.status}
                size={18}
              />
            </div>
          </div>
          <div className={styles.chartBox}>
            <CandlestickChart data={candles} height="auto" />
          </div>

          {/* Compact total-score card */}
          <div className={styles.totalCard}>
            <div className={styles.totalCardLeft}>
              <Text size={11} tone="secondary">Total score</Text>
              <Data size={24} weight={500}>{selected.score}<Text size={12} tone="dim"> / 100</Text></Data>
            </div>
            <StatusBadge status={selected.status} />
          </div>
        </section>
      </div>

      {/* ---------- Per-component detail cards ---------- */}

      <div className={styles.detailsHeader}>
        <Text size={13} weight={600}>{selected.symbol} · Score details</Text>
        <Text size={12} tone="secondary">
          Weights from Settings (default) · points = raw × weight / 100
        </Text>
      </div>

      <div className={styles.components}>
        {contributions.map((c) => (
          <article
            key={c.key}
            className={`${styles.compCard} ${styles[`compCard_${c.signal}`]}`}
          >
            <header className={styles.compHeader}>
              <Text size={13} weight={600}>{c.label}</Text>
              <Text
                size={11}
                weight={500}
                tone={c.signal === 'pos' ? 'pass' : c.signal === 'neg' ? 'reject' : 'caution'}
              >
                {signalLabel(c.signal)}
              </Text>
            </header>

            <Text size={11} tone="secondary">{c.desc}</Text>

            <div className={styles.meter} aria-hidden>
              <div
                className={`${styles.meterFill} ${styles[`meterFill_${c.signal}`]}`}
                style={{ width: `${c.raw}%` }}
              />
            </div>

            <div className={styles.compMeta}>
              <div className={styles.compMetaCell}>
                <Text size={10} tone="dim">RAW</Text>
                <Data size={13} weight={500}>{c.raw}/100</Data>
              </div>
              <div className={styles.compMetaCell}>
                <Text size={10} tone="dim">WEIGHT</Text>
                <Data size={13} weight={500}>{c.weight}%</Data>
              </div>
              <div className={styles.compMetaCell}>
                <Text size={10} tone="dim">POINTS</Text>
                <Data
                  size={13}
                  weight={500}
                  tone={c.signal === 'pos' ? 'pass' : c.signal === 'neg' ? 'reject' : undefined}
                >
                  {c.points.toFixed(1)}
                </Data>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
