'use client';

/*
 * ContractStar — compact button that toggles an option contract in
 * useWatchedContractsStore and syncs to the backend.
 * Visually identical to WatchStar; different store.
 *
 * `grading` (WATCHLIST-SCAN-CONTRACT-RULES): the inputs Step 6 graded this row
 * with, stored with the star so the Watchlist grades it the same way.
 */

import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import { api } from '@/lib/api';
import { statusOf } from '@/lib/apiError';
import type { ContractGrading } from '@/types/domain';
import styles from '@/components/atoms/WatchStar/WatchStar.module.css';

interface ContractStarProps {
  contractId: string;
  grading?:   ContractGrading;
  size?:      'sm' | 'md';
  className?: string;
}

export function ContractStar({ contractId, grading, size = 'md', className }: ContractStarProps) {
  const isWatched    = useWatchedContractsStore((s) => s.isWatched);
  const add          = useWatchedContractsStore((s) => s.add);
  const remove       = useWatchedContractsStore((s) => s.remove);
  const clearGrading = useWatchedContractsStore((s) => s.clearGrading);
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
        if (watched) {
          // Captured before remove, so a failed DELETE restores the grading too.
          const prev = useWatchedContractsStore.getState().grading[contractId];
          remove(contractId);
          api.removeWatchedContract(contractId).catch(() => { add(contractId, prev); });
        } else {
          add(contractId, grading);
          api.addWatchedContract(contractId, grading).catch((err) => {
            if (grading !== undefined && statusOf(err) === 422) {
              // The server refused the grading: keep the star, honestly
              // YAML-graded. Explicit null also clears any stale server grading.
              console.warn('ContractStar: grading refused, starring without it', err);
              clearGrading(contractId);
              api.addWatchedContract(contractId, null).catch(() => { remove(contractId); });
              return;
            }
            remove(contractId);
          });
        }
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
