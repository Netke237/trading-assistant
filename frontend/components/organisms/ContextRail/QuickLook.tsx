/*
 * RailQuickLook — shared right-rail widget.
 * Surfaces the user's watchlist top picks + portfolio mini-totals so they are
 * visible from every screen (Dashboard, Watchlist, Portfolio, Screener steps).
 * Rail is narrow (~300px), so rows are dense — just the signal dot, symbol,
 * score, and a single number on the right.
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
import { RailSection } from '@/components/organisms/ContextRail';
import { Text, Data } from '@/components/primitives';
import { QuickLookRow } from '@/components/molecules/QuickLookRow';
import { api } from '@/lib/api';
import type { DataSourceInfo } from '@/lib/api';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useScanStore } from '@/lib/scanStore';
import { openTotals, unquotedNote } from '@/lib/portfolioTotals';
import type { WatchlistRow } from '@/types/domain';
import styles from './QuickLook.module.css';

export function RailQuickLook({ showPortfolio = true }: { showPortfolio?: boolean } = {}) {
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [watchlistError, setWatchlistError] = useState(false);
  const portfolio       = usePortfolioStore((s) => s.positions);
  const syncFromBackend = usePortfolioStore((s) => s.syncFromBackend);
  const [dataSources, setDataSources] = useState<DataSourceInfo[] | null>(null);
  const scanState = useScanStore((s) => s.scanState);

  useEffect(() => {
    api.getWatchlist()
      .then(setWatchlist)
      .catch(() => setWatchlistError(true));
    syncFromBackend();
    api.getDataSources().then(setDataSources).catch(() => {});
  }, [syncFromBackend]);

  useEffect(() => {
    if (scanState === 'COMPLETED' || scanState === 'FAILED') {
      api.getDataSources().then(setDataSources).catch(() => {});
    }
  }, [scanState]);

  // /api/watchlist already returns only the user's starred symbols —
  // no need to cross-filter against the Zustand store here.
  const top = useMemo(
    () => [...watchlist].sort((a, b) => b.score - a.score).slice(0, 5),
    [watchlist],
  );

  // Positions without a quote are left out of the totals (NO-LIVE-QUOTE NLQ-1).
  const { deployed, openPnL, winners, quoted, unquoted } = openTotals(portfolio);
  const note = unquotedNote(unquoted);

  return (
    <>
      <RailSection title="Watchlist · Top 5">
        <div className={styles.watchlistStack}>
          {watchlistError && (
            <Text size={12} tone="dim">Could not load watchlist</Text>
          )}
          {top.map((r) => (
            <QuickLookRow
              key={r.symbol}
              symbol={r.symbol}
              score={r.score}
              status={r.status}
              onClick={() => window.open(`/chart?symbol=${r.symbol}`, '_blank')}
            />
          ))}
        </div>
      </RailSection>

      {showPortfolio && (
        <RailSection title="Portfolio">
          <div className={styles.portfolioStack}>
            <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{portfolio.length}</Data></Row>
            <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>${Math.round(deployed).toLocaleString()}</Data></Row>
            <Row>
              <Text size={12} tone="secondary">Open P&amp;L</Text>
              <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
                {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
              </Data>
            </Row>
            <Row>
              <Text size={12} tone="secondary">Winners</Text>
              <Data size={12} tone="pass">{winners} / {quoted}</Data>
            </Row>
            {note && <Text size={11} tone="caution">{note}</Text>}
          </div>
        </RailSection>
      )}

      {dataSources !== null && dataSources.length > 0 && (
        <RailSection title="Data Sources">
          <DataSourceGroups sources={dataSources} styles={styles} />
        </RailSection>
      )}
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}

const BROKER_FAMILIES = [
  { prefix: 'alpaca',     ids: ['alpaca', 'alpaca_paper'] },
  { prefix: 'ibkr',       ids: ['ibkr', 'ibkr_paper'] },
  { prefix: 'tradier',    ids: ['tradier', 'tradier_paper'] },
  { prefix: 'tastytrade', ids: ['tastytrade', 'tastytrade_paper'] },
];
const DATA_SOURCE_IDS = ['tiingo', 'yfinance'];

function DsRow({ src, styles: s }: { src: DataSourceInfo; styles: Record<string, string> }) {
  return (
    <div className={s.dataSourceRow} title={src.detail ?? src.provides.join(', ')}>
      <span className={s.statusDot} data-status={src.status} aria-label={src.status} />
      <Text size={12} tone="secondary">{src.label}</Text>
      <span className={s.dataSourceStatus}>
        <Text size={11} tone="dim">{src.status}</Text>
      </span>
    </div>
  );
}

function DataSourceGroups({ sources, styles: s }: { sources: DataSourceInfo[]; styles: Record<string, string> }) {
  const byId = new Map(sources.map((src) => [src.id, src]));

  const brokerGroups = BROKER_FAMILIES.map(({ ids }) =>
    ids.map((id) => byId.get(id)).filter(Boolean) as DataSourceInfo[]
  ).filter((g) => g.length > 0);

  const dataRows = DATA_SOURCE_IDS.map((id) => byId.get(id)).filter(Boolean) as DataSourceInfo[];

  const allGrouped = new Set([
    ...BROKER_FAMILIES.flatMap((f) => f.ids),
    ...DATA_SOURCE_IDS,
  ]);
  const other = sources.filter((src) => !allGrouped.has(src.id));

  return (
    <div className={s.dataSourceStack}>
      {brokerGroups.map((group, i) => (
        <div key={group[0]!.id} className={s.dataSourceGroup}>
          {i > 0 && <hr className={s.dataSourceDivider} />}
          {group.map((src) => <DsRow key={src.id} src={src} styles={s} />)}
        </div>
      ))}
      {dataRows.length > 0 && (
        <>
          <hr className={s.dataSourceDivider} />
          {dataRows.map((src) => <DsRow key={src.id} src={src} styles={s} />)}
        </>
      )}
      {other.map((src) => <DsRow key={src.id} src={src} styles={s} />)}
    </div>
  );
}
