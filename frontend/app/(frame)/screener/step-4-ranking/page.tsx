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
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Title, Text, Data } from '@/components/primitives';
import { TableRow } from '@/components/molecules/TableRow';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { Pagination } from '@/components/molecules/Pagination';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
import { WatchStar } from '@/components/atoms/WatchStar';
import { api } from '@/lib/api';
import { exportToXlsx } from '@/lib/export';
import { useScanStore } from '@/lib/scanStore';
import { cardToRow } from './cardToRow';
import { trendDetailText, pullbackDetailText, triggerDetailText, eventDetailText, volDetailText } from '@/components/organisms/TradeCard';
import type { WatchlistRow, TradeCardData } from '@/types/domain';
import type { Candle } from '@/types/chart';
import styles from './page.module.css';

const PAGE_SIZE = 10;

const COLUMNS = '28px 1fr 56px 54px 50px 64px 68px 80px';

const HORIZON_WEIGHTS: Record<string, { trend: number; pullback: number; trigger: number; event: number; volatility: number }> = {
  Intraday: { trend: 35, pullback: 20, trigger: 30, event: 5,  volatility: 10 },
  Swing:    { trend: 30, pullback: 20, trigger: 25, event: 15, volatility: 10 },
  Position: { trend: 30, pullback: 20, trigger: 20, event: 20, volatility: 10 },
};

type ComponentKey = 'trend' | 'pullback' | 'trigger' | 'event' | 'volatility';


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
  const router = useRouter();
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [candles, setCandles]     = useState<Candle[]>([]);
  const [selectedSym, setSelectedSym] = useState<string>('');
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [currentPage, setCurrentPage] = useState(1);

  const candidates = useScanStore((s) => s.scanResult?.candidates);
  const previousRun = useScanStore((s) => s.previousRun);
  const context = useScanStore((s) => s.context);
  const setSelectedSymbol = useScanStore((s) => s.setSelectedSymbol);
  const scanOverrides = useScanStore((s) => s.scanOverrides);

  const maType   = (scanOverrides.ma_type  as string | undefined) ?? 'EMA';
  const fastMa   = (scanOverrides.fast_ema as number | undefined) ?? 50;
  const slowMa   = (scanOverrides.slow_ema as number | undefined) ?? 200;
  const trendDesc = `Medium-term direction — price vs ${slowMa} ${maType}, slope of ${fastMa} ${maType}, higher highs.`;

  const COMPONENTS: { key: ComponentKey; label: string; desc: string }[] = [
    { key: 'trend',      label: 'Trend',      desc: trendDesc },
    { key: 'pullback',   label: 'Pullback',   desc: 'Healthy retracement to a supportive level — not extended, not broken.' },
    { key: 'trigger',    label: 'Trigger',    desc: 'Short-term entry signal — engulfing, volume expansion, breakout close.' },
    { key: 'event',      label: 'Event',      desc: 'Calendar gate — earnings / FOMC proximity. High = clear of events.' },
    { key: 'volatility', label: 'Volatility', desc: 'IV rank sweet-spot — rich enough to earn premium, not blown-out.' },
  ];

  useEffect(() => {
    const list = candidates?.map((c, idx) => cardToRow(c, idx + 1, previousRun, context?.horizon)) ?? [];
    setWatchlist(list);
    setCurrentPage(1);
    if (list.length > 0) {
      const sym = list[0].symbol;
      setSelectedSym(sym);
      setSelectedSymbol(sym);
    }
  }, [candidates, previousRun, context, setSelectedSymbol]);

  const sorted = useMemo(
    () => sortRows(watchlist, sortKey, sortDir),
    [watchlist, sortKey, sortDir],
  );

  const paginated = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return sorted.slice(start, start + PAGE_SIZE);
  }, [sorted, currentPage]);

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
    setCurrentPage(1);
  }

  if (!selected) {
    const hasRun = candidates !== undefined;
    return (
      <div className={styles.main}>
        <div className={styles.stepHeader}>
          <Text size={11} tone="dim" weight={500}>STEP 4 OF 7</Text>
          <Title as="h1" size={24}>Stock Ranking</Title>
        </div>
        <Text size={13} tone="dim">
          {hasRun ? 'No candidates matched the current scan criteria.' : 'Run a scan to see ranked candidates.'}
        </Text>
      </div>
    );
  }

  const horizonKey = context?.horizon?.startsWith('Intraday') ? 'Intraday'
    : context?.horizon?.startsWith('Position') ? 'Position'
    : 'Swing';
  const WEIGHTS = HORIZON_WEIGHTS[horizonKey];

  const contributions = COMPONENTS.map((c) => {
    const raw    = selected.breakdown[c.key];
    const weight = WEIGHTS[c.key] ?? 0;
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
            <Link href="/validation" className={styles.exportBtn}>
              Validation
            </Link>
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
            <Text size={11} tone="dim">HORIZON</Text>
            <SortHeader label="Δ RNK"    sortKey="rankDelta"     currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <SortHeader label="Δ SCR"    sortKey="scoreDelta"    currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <SortHeader label="SCORE"    sortKey="score"         currentKey={sortKey} dir={sortDir} onSort={handleSort} />
            <Text size={11} tone="dim">CONF</Text>
            <SortHeader label="NEXT"     sortKey="nextEventDays" currentKey={sortKey} dir={sortDir} onSort={handleSort} />
          </div>
          <div className={styles.tableBody}>
            {paginated.map((row) => (
              <TableRow
                key={row.symbol}
                status={row.status}
                columns={COLUMNS}
                selected={row.symbol === selectedSym}
                onClick={() => {
                  setSelectedSym(row.symbol);
                  setSelectedSymbol(row.symbol);
                }}
              >
                <WatchStar symbol={row.symbol} size="sm" />
                <button
                  className={styles.chartBtn}
                  title="Open in Chart"
                  onClick={(e) => { e.stopPropagation(); router.push(`/chart?symbol=${row.symbol}`); }}
                >
                  📈
                </button>
                <div className={styles.symCell}>
                  <Data size={12} weight={500}>{row.symbol}</Data>
                  <Text size={11} tone="secondary">{row.company}</Text>
                </div>
                <Text size={11} tone="secondary">{row.horizon}</Text>
                <RankDelta value={row.rankDelta}          context="rank"     />
                <RankDelta value={row.scoreDelta ?? 0}    context="score pt" />
                <Data size={13} weight={500}>{row.score}</Data>
                <StatusBadge status={row.status} />
                {row.nextEventDays != null
                  ? <EventFlag days={row.nextEventDays} title={row.nextEventLabel ?? undefined} />
                  : <Text size={11} tone="dim">—</Text>}
              </TableRow>
            ))}
          </div>
          <Pagination
            totalItems={sorted.length}
            pageSize={PAGE_SIZE}
            currentPage={currentPage}
            onPageChange={setCurrentPage}
          />
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
            <CandlestickChart data={candles} height="auto" defaultIndicators={['volume', 'rsi']} />
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
            {(() => {
              const bd = selected.breakdown;
              const detailFns: Record<string, () => string | undefined> = {
                trend:      () => trendDetailText(bd?.trendDetail),
                pullback:   () => pullbackDetailText(bd?.pullbackDetail),
                trigger:    () => triggerDetailText(bd?.triggerDetail),
                event:      () => eventDetailText(bd?.eventDetail),
                volatility: () => volDetailText(bd?.volDetail),
              };
              const text = detailFns[c.key]?.();
              return text ? <Text size={11} tone="dim">{text}</Text> : null;
            })()}
          </article>
        ))}
      </div>
    </div>
  );
}
