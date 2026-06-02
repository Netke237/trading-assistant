/*
 * RailQuickLook — shared right-rail widget.
 * Surfaces the user's watchlist top picks + portfolio mini-totals so they are
 * visible from every screen (Dashboard, Watchlist, Portfolio, Screener steps).
 * Rail is narrow (~300px), so rows are dense — just the signal dot, symbol,
 * score, and a single number on the right.
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { RailSection } from '@/components/organisms/ContextRail';
import { Text, Data } from '@/components/primitives';
import { QuickLookRow } from '@/components/molecules/QuickLookRow';
import { api } from '@/lib/api';
import type { DataSourceInfo } from '@/lib/api';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useScanStore } from '@/lib/scanStore';
import type { WatchlistRow } from '@/types/domain';
import styles from './QuickLook.module.css';

export function RailQuickLook() {
  const router = useRouter();
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

  const deployed = portfolio.reduce(
    (s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1),
    0,
  );
  const openPnL = portfolio.reduce((s, p) => s + p.pnlDollar, 0);
  const winners = portfolio.filter((p) => p.pnlDollar > 0).length;

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
              onClick={() => router.push(`/chart?symbol=${r.symbol}`)}
            />
          ))}
        </div>
      </RailSection>

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
            <Data size={12} tone="pass">{winners} / {portfolio.length}</Data>
          </Row>
        </div>
      </RailSection>

      {dataSources !== null && dataSources.length > 0 && (
        <RailSection title="Data Sources">
          <div className={styles.dataSourceStack}>
            {dataSources.map((src) => (
              <div
                key={src.id}
                className={styles.dataSourceRow}
                title={src.detail ?? src.provides.join(', ')}
              >
                <span
                  className={styles.statusDot}
                  data-status={src.status}
                  aria-label={src.status}
                />
                <Text size={12} tone="secondary">{src.label}</Text>
                <span className={styles.dataSourceStatus}>
                  <Text size={11} tone="dim">
                    {src.status === 'ok' ? 'connected' : src.status}
                  </Text>
                </span>
              </div>
            ))}
          </div>
        </RailSection>
      )}
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
