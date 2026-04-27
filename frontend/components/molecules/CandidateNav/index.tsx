'use client';

/*
 * CandidateNav — header strip above the Step 7 TradeCard.
 *
 *   [ ← Prev ]   AAPL (2 / 8)   [ Next → ]
 *                [ ★ Pin to basket ]   [ AAPL × ] [ NVDA × ] ...
 *
 * Callers own the basket state; this component is pure presentation.
 */

import { Text, Data } from '@/components/primitives';
import styles from './CandidateNav.module.css';

interface CandidateNavProps {
  symbols:       string[];        // ordered candidate list
  activeSymbol:  string;
  basket:        string[];        // symbols currently pinned
  onPrev:        () => void;
  onNext:        () => void;
  onSelect:      (symbol: string) => void;
  onTogglePin:   () => void;
  onRemovePin:   (symbol: string) => void;
}

export function CandidateNav({
  symbols,
  activeSymbol,
  basket,
  onPrev,
  onNext,
  onSelect,
  onTogglePin,
  onRemovePin,
}: CandidateNavProps) {
  const idx     = symbols.indexOf(activeSymbol);
  const atFirst = idx <= 0;
  const atLast  = idx < 0 || idx >= symbols.length - 1;
  const pinned  = basket.includes(activeSymbol);

  return (
    <div className={styles.wrap}>
      <div className={styles.navRow}>
        <button
          type="button"
          className={styles.navBtn}
          onClick={onPrev}
          disabled={atFirst}
          aria-label="Previous candidate"
        >
          ← Prev
        </button>

        <div className={styles.position}>
          <Data size={14} weight={500}>{activeSymbol}</Data>
          <Text size={11} tone="secondary">
            {idx < 0 ? '—' : `${idx + 1} / ${symbols.length}`}
          </Text>
        </div>

        <button
          type="button"
          className={styles.navBtn}
          onClick={onNext}
          disabled={atLast}
          aria-label="Next candidate"
        >
          Next →
        </button>

        <button
          type="button"
          className={`${styles.pinBtn} ${pinned ? styles.pinBtnOn : ''}`}
          onClick={onTogglePin}
          aria-pressed={pinned}
          title={pinned ? 'Remove from basket' : 'Pin to basket'}
        >
          {pinned ? '★ Pinned' : '☆ Pin to basket'}
        </button>
      </div>

      <div className={styles.basketRow} aria-label="Basket">
        <Text size={11} tone="dim">
          BASKET {basket.length > 0 ? `(${basket.length})` : '— empty'}
        </Text>
        <div className={styles.chips}>
          {basket.map((sym) => (
            <span
              key={sym}
              className={`${styles.chip} ${sym === activeSymbol ? styles.chipActive : ''}`}
            >
              <button
                type="button"
                className={styles.chipSelect}
                onClick={() => onSelect(sym)}
              >
                {sym}
              </button>
              <button
                type="button"
                className={styles.chipRemove}
                onClick={() => onRemovePin(sym)}
                aria-label={`Remove ${sym} from basket`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
