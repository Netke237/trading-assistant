'use client';

/*
 * ContractStar — compact button that toggles an option contract in
 * useWatchedContractsStore. Visually identical to WatchStar; different store.
 */

import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import styles from '@/components/atoms/WatchStar/WatchStar.module.css';

interface ContractStarProps {
  contractId: string;
  size?:      'sm' | 'md';
  className?: string;
}

export function ContractStar({ contractId, size = 'md', className }: ContractStarProps) {
  const isWatched = useWatchedContractsStore((s) => s.isWatched);
  const toggle    = useWatchedContractsStore((s) => s.toggle);
  // Subscribe so toggles re-render.
  useWatchedContractsStore((s) => s.ids);

  const watched = isWatched(contractId);
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
        toggle(contractId);
      }}
      aria-label={watched ? 'Remove contract from watchlist' : 'Add contract to watchlist'}
      aria-pressed={watched}
      title={watched ? 'Watching contract' : 'Watch contract'}
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
