/*
 * Analysis page right-rail. Mirrors @contextRail/chart/page.tsx: the shared
 * watchlist/portfolio quick-look plus a Notes section for the symbol
 * currently loaded on the Analysis page.
 *
 * Deliberately a page.tsx, not a default.tsx — see @contextRail/chart/page.tsx's
 * header comment for the parallel-route soft-nav staleness bug this avoids.
 *
 * Reads useAnalysisStore's `symbol` field, not `result?.symbol` — `symbol` is
 * a plain string (default ''), set synchronously the moment analyze() is
 * called, so it never needs an `?? ''` fallback and never drops the current
 * symbol just because a lookup is still in flight or failed.
 */

'use client';

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { SymbolNotes } from '@/components/molecules/SymbolNotes';
import { useAnalysisStore } from '@/lib/analysisStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useIsSymbolHeld } from '@/lib/portfolioStore';

export default function AnalysisContextRail() {
  const symbol = useAnalysisStore((s) => s.symbol);
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
