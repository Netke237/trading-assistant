/*
 * Portfolio right-rail. Spec §4: Aggregate Greeks / risk summary.
 */

'use client';

import { usePortfolioStore, useIsSymbolHeld } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { SymbolNotes } from '@/components/molecules/SymbolNotes';
import { Text, Data } from '@/components/primitives';
import { openTotals, unquotedNote } from '@/lib/portfolioTotals';
import styles from './page.module.css';

export default function PortfolioContextRail() {
  const positions = usePortfolioStore((s) => s.positions);
  const selectedSymbol = usePortfolioUiStore((s) => s.selectedSymbol);
  // `selectedSymbol` tracks whichever row's pencil icon was last clicked and
  // is only cleared by this page's own close/remove/unmount handlers — an
  // out-of-band close (another tab, a stop-triggered close reconciled by the
  // 30s portfolio poll) can leave it pointing at a symbol no longer held.
  // Computing `editable` for real (instead of assuming "selected means
  // held") is what actually re-gates the note box in that case, same as the
  // Chart sidebar and EditDrawer.
  const isHeld = useIsSymbolHeld(selectedSymbol ?? '');
  const isWatched = useWatchlistStore((s) => (selectedSymbol ? s.isWatched(selectedSymbol) : false));
  // Positions without a quote are left out of the totals (NO-LIVE-QUOTE NLQ-1).
  const { deployed, openPnL, unquoted } = openTotals(positions);
  const note = unquotedNote(unquoted);
  const hasGreeks = positions.some((p) => p.delta != null || p.theta != null);
  const aggDelta = hasGreeks
    ? positions.reduce((s, p) => s + (p.delta ?? 0) * (p.contract.endsWith('|STOCK') ? 1 : 100) * (p.contracts ?? 1), 0).toFixed(2)
    : null;
  const aggTheta = hasGreeks
    ? positions.reduce((s, p) => s + (p.theta ?? 0) * (p.contracts ?? 1), 0).toFixed(1)
    : null;

  return (
    <>
      <RailSection title="Totals">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>${Math.round(deployed).toLocaleString()}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
              {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </Row>
          <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{positions.length}</Data></Row>
          {note && <Text size={11} tone="caution">{note}</Text>}
        </div>
      </RailSection>

      <RailSection title="Aggregate Greeks">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Δ Delta</Text><Data size={12}>{aggDelta ?? '—'}</Data></Row>
          <Row><Text size={12} tone="secondary">Θ Theta / day</Text><Data size={12} tone={aggTheta != null ? (parseFloat(aggTheta) < 0 ? 'reject' : 'pass') : undefined}>{aggTheta ?? '—'}</Data></Row>
        </div>
      </RailSection>

      {selectedSymbol && (
        <RailSection title={`Notes · ${selectedSymbol}`}>
          <SymbolNotes symbol={selectedSymbol} editable={isHeld || isWatched} />
        </RailSection>
      )}

      {/* showPortfolio=false: the "Totals" section above already covers
          positions/deployed/open P&L — RailQuickLook's own "Portfolio"
          section would just repeat the same numbers a second time. */}
      <RailQuickLook showPortfolio={false} />
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
