'use client';

import { useEffect } from 'react';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';

export function InitStores() {
  const syncPortfolio = usePortfolioStore((s) => s.syncFromBackend);
  const syncWatchlist = useWatchlistStore((s) => s.syncFromBackend);

  useEffect(() => {
    // Rehydrate from localStorage immediately (skipHydration is true on both stores).
    usePortfolioStore.persist.rehydrate();
    useWatchlistStore.persist.rehydrate();
    // Then overlay with fresh backend data.
    syncPortfolio();
    syncWatchlist();
  }, [syncPortfolio, syncWatchlist]);

  return null;
}
