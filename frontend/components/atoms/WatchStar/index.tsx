'use client';

/*
 * WatchStar — compact button that toggles a symbol in useWatchlistStore.
 * Reused across Watchlist, Step 4 Ranking, and Step 5 Vol+Events tables,
 * and the InlineChartPanel / SymbolHeader when we surface it there.
 *
 * Visual rules:
 *   - Default: hollow star, dim text.
 *   - Watched: filled star, caution-yellow.
 *   - Hover: bg shade + stronger color.
 */

import { useWatchlistStore } from '@/lib/watchlistStore';
import { api } from '@/lib/api';
import styles from './WatchStar.module.css';

interface WatchStarProps {
  symbol:   string;
  size?:    'sm' | 'md';
  className?: string;
}

export function WatchStar({ symbol, size = 'md', className }: WatchStarProps) {
  const isWatched    = useWatchlistStore((s) => s.isWatched);
  const addSymbol    = useWatchlistStore((s) => s.addSymbol);
  const removeSymbol = useWatchlistStore((s) => s.removeSymbol);
  // Subscribe to added so toggles re-render.
  useWatchlistStore((s) => s.added);

  const watched = isWatched(symbol);
  const px = size === 'sm' ? 12 : 14;

  return (
    <button
      type="button"
      className={[
        styles.star,
        watched ? styles.starOn : '',
        size === 'sm' ? styles.sm : '',
        className,
      ].filter(Boolean).join(' ')}
      onClick={(e) => {
        e.stopPropagation();
        if (watched) {
          removeSymbol(symbol);
          api.removeWatchlist(symbol).catch(() => { addSymbol(symbol); });
        } else {
          addSymbol(symbol);
          api.addWatchlist(symbol).catch(() => { removeSymbol(symbol); });
        }
      }}
      aria-label={watched ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`}
      aria-pressed={watched}
      title={watched ? 'In watchlist' : 'Add to watchlist'}
    >
      <svg width={px} height={px} viewBox="0 0 14 14" fill="none" aria-hidden>
        <path
          d="M7 1.5 L8.7 5.1 L12.5 5.6 L9.7 8.3 L10.4 12.1 L7 10.3 L3.6 12.1 L4.3 8.3 L1.5 5.6 L5.3 5.1 Z"
          fill={watched ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
