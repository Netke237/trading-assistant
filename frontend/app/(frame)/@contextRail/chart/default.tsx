/*
 * Chart page right-rail. The chart previously fell through to the shared
 * root default.tsx (plain RailQuickLook, no page-specific content) — this
 * segment keeps that behavior and appends a Notes section for the symbol
 * currently open in the chart workspace.
 */

'use client';

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { SymbolNotes } from '@/components/molecules/SymbolNotes';
import { useChartStore } from '@/lib/chartStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useIsSymbolHeld } from '@/lib/portfolioStore';

export default function ChartContextRail() {
  const symbol = useChartStore((s) => s.symbol);
  const isWatched = useWatchlistStore((s) => s.isWatched(symbol));
  const isHeld = useIsSymbolHeld(symbol);

  return (
    <>
      <RailQuickLook />
      {symbol && (
        <RailSection title="Notes">
          <SymbolNotes symbol={symbol} editable={isWatched || isHeld} />
        </RailSection>
      )}
    </>
  );
}
