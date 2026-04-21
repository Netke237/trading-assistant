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

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { WatchStar } from '@/components/atoms/WatchStar';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { candlesFor } from '@/mocks/candles';
import styles from './page.module.css';

const COLUMNS = '28px 1fr 56px 70px 72px';

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

export default function Step4Page() {
  const [selectedSym, setSelectedSym] = useState(MOCK_WATCHLIST[0]!.symbol);
  const selected = MOCK_WATCHLIST.find((r) => r.symbol === selectedSym) ?? MOCK_WATCHLIST[0]!;

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
            <Text size={11} tone="secondary">{MOCK_WATCHLIST.length} ranked</Text>
          </header>
          <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
            <span aria-hidden />
            <Text size={11} tone="dim">SYMBOL</Text>
            <Text size={11} tone="dim">Δ</Text>
            <Text size={11} tone="dim">SCORE</Text>
            <Text size={11} tone="dim">NEXT</Text>
          </div>
          <div className={styles.tableBody}>
            {MOCK_WATCHLIST.map((row) => (
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
                <RankDelta value={row.rankDelta} />
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <WatchStar symbol={selected.symbol} />
            <div style={{ flex: 1, minWidth: 0 }}>
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
            <CandlestickChart data={candlesFor(selected.symbol)} height="auto" />
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
