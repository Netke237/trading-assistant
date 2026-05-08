'use client';

import { useEffect } from 'react';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';

export function InitStores() {
  const syncPortfolio = usePortfolioStore((s) => s.syncFromBackend);
  const syncWatchlist = useWatchlistStore((s) => s.syncFromBackend);

  useEffect(() => {
    syncPortfolio();
    syncWatchlist();
  }, [syncPortfolio, syncWatchlist]);

  return null;
}
