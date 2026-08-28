/*
 * Chart page right-rail. The chart previously fell through to the shared
 * root default.tsx (plain RailQuickLook, no page-specific content) — this
 * segment keeps that behavior and appends a Notes section for the symbol
 * currently open in the chart workspace.
 *
 * Deliberately a page.tsx, not a default.tsx: this segment used to be a
 * default.tsx (the natural choice — Chart has no sub-routes needing a
 * distinct fallback), but Next's parallel-route router only reliably picks
 * up default.tsx on a hard/initial load. On a client-side soft navigation
 * from a route whose own rail slot resolves via page.tsx (Dashboard,
 * Portfolio, Watchlist all do), the router kept rendering the origin
 * page's rail content instead of swapping to this one — so Notes silently
 * never appeared when navigating to Chart from Dashboard specifically.
 * Matching the sibling pattern (a real page.tsx) fixes it.
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
