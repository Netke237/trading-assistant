/*
 * Portfolio right-rail. Spec §4: Aggregate Greeks / risk summary.
 * Greeks are summed per position as θ/Δ × multiplier × contracts (theta in dollars per day).
 */

'use client';

import { usePortfolioStore, useIsSymbolHeld } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { SymbolNotes } from '@/components/molecules/SymbolNotes';
import { Text, Data } from '@/components/primitives';
import { openTotals, unquotedNote, aggregateGreeks, deltaDollarsNote } from '@/lib/portfolioTotals';
import { formatMoney, moneyTone } from '@/lib/portfolioFormat';
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
  const { deltaShares, thetaDollars, deltaDollars, deltaDollarsExcluded } = aggregateGreeks(positions);
  const ddNote = deltaShares != null ? deltaDollarsNote(deltaDollarsExcluded) : null;

  return (
    <>
      <RailSection title="Totals">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>{formatMoney(deployed)}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
              {formatMoney(openPnL, { plus: true })}
            </Data>
          </Row>
          <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{positions.length}</Data></Row>
          {note && <Text size={11} tone="caution">{note}</Text>}
        </div>
      </RailSection>

      <RailSection title="Aggregate Greeks">
        <div className={styles.statStack}>
          <Row><Text size={12} tone="secondary">Δ Delta (share-equiv.)</Text><Data size={12}>{deltaShares != null ? deltaShares.toFixed(2) : '—'}</Data></Row>
          <Row><Text size={12} tone="secondary">Δ in dollars</Text><Data size={12}>{deltaDollars != null ? formatMoney(deltaDollars) : '—'}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Θ Theta / day</Text>
            <Data size={12} tone={thetaDollars != null ? moneyTone(thetaDollars, 2) : undefined}>
              {thetaDollars != null ? formatMoney(thetaDollars, { decimals: 2, plus: true }) : '—'}
            </Data>
          </Row>
          {ddNote && <Text size={11} tone="caution">{ddNote}</Text>}
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
