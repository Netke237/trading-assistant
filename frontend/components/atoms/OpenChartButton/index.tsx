'use client';

import styles from './OpenChartButton.module.css';

interface OpenChartButtonProps {
  symbol: string;
  className?: string;
}

/** Icon button that opens /chart?symbol=... in a new tab. Mirrors the pattern
 *  already used inline on Watchlist / step-4-ranking / step-6-contracts. */
export function OpenChartButton({ symbol, className }: OpenChartButtonProps) {
  return (
    <button
      type="button"
      className={[styles.chartBtn, className].filter(Boolean).join(' ')}
      title="Open in Chart"
      onClick={(e) => {
        e.stopPropagation();
        window.open(`/chart?symbol=${encodeURIComponent(symbol)}`, '_blank');
      }}
    >
      📈
    </button>
  );
}
