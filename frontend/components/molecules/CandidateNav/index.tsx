'use client';

/*
 * CandidateNav — header strip above the Step 7 TradeCard.
 *
 *   ‹ Previous · AAPL 2 / 8 · Next ›      [ ☆ Pin to basket ]  Basket (2) [ AAPL × ] [ NVDA × ]
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
  /** The active candidate may not be pinned (e.g. an earnings veto). An
   *  already-pinned candidate can still be un-pinned. */
  pinDisabled?:  boolean;
  pinDisabledReason?: string;
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
  pinDisabled = false,
  pinDisabledReason,
}: CandidateNavProps) {
  const idx     = symbols.indexOf(activeSymbol);
  const atFirst = idx <= 0;
  const atLast  = idx < 0 || idx >= symbols.length - 1;
  const pinned  = basket.includes(activeSymbol);

  return (
    // #610 G2 — a thin inline row, as in the frozen trade-card reference:
    // "‹ Previous · AAPL 1 / 2 · Next ›" on the left; Pin to basket and the
    // basket on the right. Every control, chip, title and handler is the same.
    <div className={styles.wrap} data-candidate-nav-row="">
      <div className={styles.navRow}>
        <button
          type="button"
          className={styles.navBtn}
          onClick={onPrev}
          disabled={atFirst}
          aria-label="Previous candidate"
        >
          ‹ Previous
        </button>

        <span className={styles.sep} aria-hidden="true">·</span>
        <div className={styles.position}>
          <Data size={13} weight={500}>{activeSymbol}</Data>
          <Text size={12} tone="secondary">
            {idx < 0 ? '—' : `${idx + 1} / ${symbols.length}`}
          </Text>
        </div>
        <span className={styles.sep} aria-hidden="true">·</span>

        <button
          type="button"
          className={styles.navBtn}
          onClick={onNext}
          disabled={atLast}
          aria-label="Next candidate"
        >
          Next ›
        </button>
      </div>

      <div className={styles.basketSide}>
        <button
          type="button"
          className={`${styles.pinBtn} ${pinned ? styles.pinBtnOn : ''}`}
          onClick={onTogglePin}
          aria-pressed={pinned}
          disabled={pinDisabled && !pinned}
          title={pinned ? 'Remove from basket' : pinDisabled && pinDisabledReason ? pinDisabledReason : 'Pin to basket'}
        >
          {pinned ? '★ Pinned' : '☆ Pin to basket'}
        </button>

        <div className={styles.basketRow} aria-label="Basket">
          <Text size={12} tone="secondary">
            {basket.length > 0 ? `Basket (${basket.length})` : 'Basket — empty'}
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
    </div>
  );
}
