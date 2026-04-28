/*
 * RailQuickLook — shared right-rail widget.
 * Surfaces the user's watchlist top picks + portfolio mini-totals so they are
 * visible from every screen (Dashboard, Watchlist, Portfolio, Screener steps).
 * Rail is narrow (~300px), so rows are dense — just the signal dot, symbol,
 * score, and a single number on the right.
 */

import { RailSection } from '@/components/organisms/ContextRail';
import { Text, Data } from '@/components/primitives';
import { QuickLookRow } from '@/components/molecules/QuickLookRow';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import styles from './QuickLook.module.css';

export function RailQuickLook() {
  const top = [...MOCK_WATCHLIST].sort((a, b) => b.score - a.score).slice(0, 5);

  const deployed = MOCK_PORTFOLIO.reduce(
    (s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1),
    0,
  );
  const openPnL = MOCK_PORTFOLIO.reduce((s, p) => s + p.pnlDollar, 0);
  const winners = MOCK_PORTFOLIO.filter((p) => p.pnlDollar > 0).length;

  return (
    <>
      <RailSection title="Watchlist · Top 5">
        <div className={styles.watchlistStack}>
          {top.map((r) => (
            <QuickLookRow
              key={r.symbol}
              symbol={r.symbol}
              score={r.score}
              status={r.status}
            />
          ))}
        </div>
      </RailSection>

      <RailSection title="Portfolio">
        <div className={styles.portfolioStack}>
          <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{MOCK_PORTFOLIO.length}</Data></Row>
          <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>${Math.round(deployed).toLocaleString()}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
              {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </Row>
          <Row>
            <Text size={12} tone="secondary">Winners</Text>
            <Data size={12} tone="pass">{winners} / {MOCK_PORTFOLIO.length}</Data>
          </Row>
        </div>
      </RailSection>
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
