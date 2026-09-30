'use client';

import { useCallback, useMemo } from 'react';
import { Text, Data } from '@/components/primitives';
import type { MethodPick, PickedMethod, PickedStopBasis } from '@/types/domain';
import styles from './MethodPickSelector.module.css';

// Phase G (piece 5, D4/D5) build step 3 — THE CARD CONTROL.
//
// Spec: docs/superpowers/plans/2026-09-14-phase-g-per-trade-method-pick-spec.md
// §6.1 (the control), §7.4 (what an explicit pick means) and §9.2 (the copy).
//
// ONE COMPONENT, BOTH CARDS. TradeCard offers four methods and
// StockPositionCard offers three (§6.3 — no Barrier Race, because a stock has
// no premium barrier to race). They are otherwise the same decision, so they
// are the same control, and the difference is the `options` array the caller
// builds rather than a `mode` prop branching inside.
//
// DUMB AND CONTROLLED, DELIBERATELY. It holds no state and starts no effects:
// the pick lives in `scanStore`'s stamped slice, the card owns the round trip,
// and this renders whatever it is handed. That matters because the clear rules
// (§6.1: a pick whose numbers have gone stale is cleared) depend on knowing
// whether the CARD has finished re-syncing to a new contract, which is a fact
// only the card has. A clear effect in here would fire during the card's
// transition commit and wipe the incoming contract's legitimate restored pick.
// See TradeCard's note on its `pickedMethodGone` clear effect (the
// `prevContractRef.current` comparison) for that argument in full.
//
// THE MAPPING TABLE IS THE CALLER'S, AND THAT IS NOT LAZINESS. §6.1 fixes which
// field of the selected row lands in which of the two price slots, per method,
// and §4.1 says why: the four methods do not quote their rows in the same
// space, and only `rowStockPrice` may ever seed `resolved_tp_price`. Reading
// "the price on the row" and storing it once is the defect that split exists to
// prevent — a $6.24 Monte Carlo PREMIUM stamped as a stock target makes
// `price >= 6.24` true on the first tick and fires TP_HIT instantly on every
// bullish position. So each row arrives here with both slots already filled in
// by the code that owns the source object, and this component never derives one
// from the other, never falls back from one to the other, and never reads
// `displayPrice` into either.

/** One selectable target row of one method.
 *
 *  `displayPrice` is what the CARD shows for this row — the number the trader
 *  is actually looking at — and it is display only. For Monte Carlo that is the
 *  option premium while `rowStockPrice` is the underlying level beside it
 *  (§6.1 calls this row "the trap"), so the two are deliberately separate
 *  fields rather than one reused three ways. */
export interface MethodPickRow {
  key: string;
  label: string;
  displayPrice: number | null;
  /** Underlying space. The ONLY field that may ever seed `resolvedTpPrice`. */
  rowStockPrice: number | null;
  /** Premium space. Record only — never seeds, never alerts. */
  rowOptionPrice: number | null;
}

export interface MethodPickOption {
  method: PickedMethod;
  label: string;
  /** `null` when the method is selectable. A non-null string is the REASON it
   *  is not, and it is rendered: §6.1 requires a method whose numbers do not
   *  exist to be "disabled with a reason, not hidden", so that the absence of
   *  Monte Carlo reads as "Estimate hasn't been run" rather than as a method
   *  this card does not have. */
  unavailable: string | null;
  rows: MethodPickRow[];
}

interface MethodPickSelectorProps {
  options: MethodPickOption[];
  pick: MethodPick | null;
  onChange: (pick: MethodPick | null) => void;
  /** Injected so a test can pin `pickedAt` without freezing global time. */
  now?: () => string;
}

/** The two stop bases, with §9.2's copy.
 *
 *  "JUDGED ON", NEVER "ARMED", and §9.2 spends a paragraph on why: G records
 *  which stop the trade was judged against and changes NOTHING about which
 *  alerts fire. STOP_REACHED still fires on the position's `stop` and
 *  PREMIUM_STOP still fires on the premium stop, exactly as before. A control
 *  captioned "armed: premium" beside a STOP_REACHED that fires on the stock
 *  stop would be a screen naming one basis while a different one fires — the
 *  precise defect this spec refuses everywhere else. Full arming semantics is a
 *  Phase H question (§11 item 2).
 *
 *  THE WORD "ARMED" APPEARS NOWHERE IN THIS COMPONENT, including in the
 *  explanatory copy below the basis row, and a test pins that. The explanation
 *  could truthfully use it ("both stay armed") — it is banned anyway, because
 *  a blunt "this string is absent" is a property a mutation cannot slip past,
 *  and a nuanced one about which sentences may say it is not. */
const STOP_BASES: { value: PickedStopBasis; label: string }[] = [
  { value: 'stock',   label: 'Stock stop' },
  { value: 'premium', label: 'Premium stop' },
];

/** `'stock'` IS THE DEFAULT, and unlike the method radiogroup above it it is
 *  pre-selected. Three reasons, because §6.1's "no default is pre-selected"
 *  rule is stated about the METHOD and does not carry over unexamined:
 *
 *  1. `MethodPick.stopBasis` is not nullable — the type says every pick has
 *     one, so there is no "unset" to render.
 *  2. §9.2 makes this a RECORD, not a gate and not an arming. §7.4's gate is on
 *     the method alone, so a required third click would buy the send path
 *     nothing and cost a step on every trade.
 *  3. `'stock'` is not an arbitrary default. It is the basis the position's
 *     `stop` field carries and the one STOP_REACHED actually fires on, so a
 *     trade nobody re-basised really was judged on the stock stop. That is what
 *     separates this from "a default nobody looked at wearing a radio's
 *     clothes" — the phrase §6.1 uses about pre-selecting a method, where no
 *     such truthful default exists. */
const DEFAULT_STOP_BASIS: PickedStopBasis = 'stock';

/** Match a stored pick back to the row it names.
 *
 *  BY PRICE PAIR, because that is what `MethodPick` stores. §4.1 chose prices
 *  over a row index on purpose ("a price survives an `rr_ratios` change and
 *  `exit_plan_2r` does not"), and the cost of that choice is paid right here:
 *  the selected row has to be recovered by value. Both fields must agree, not
 *  just the one that happens to be non-null, or a Monte Carlo row with a null
 *  stock price would match every other row with a null stock price.
 *
 *  Returns null when nothing matches — a pick with no row (§7.4: picking a
 *  method alone is a complete, gate-passing decision) and a pick whose row has
 *  since been recomputed to a different price both land here, and both render
 *  as "method chosen, no row highlighted" rather than as a wrong row lit up. */
function rowOfPick(rows: MethodPickRow[], pick: MethodPick | null): string | null {
  if (!pick) return null;
  if (pick.rowStockPrice == null && pick.rowOptionPrice == null) return null;
  const hit = rows.find(
    (r) => Object.is(r.rowStockPrice, pick.rowStockPrice)
        && Object.is(r.rowOptionPrice, pick.rowOptionPrice),
  );
  return hit?.key ?? null;
}

function priceText(price: number | null): string {
  return price != null ? `$${price.toFixed(2)}` : '—';
}

export function MethodPickSelector({ options, pick, onChange, now }: MethodPickSelectorProps) {
  const stamp = now ?? (() => new Date().toISOString());
  /** The option whose rows are on offer — null unless a pick exists AND that
   *  method is currently selectable.
   *
   *  THE `unavailable` TERM IS NOT BELT-AND-BRACES. A pick survives its method
   *  going away for exactly as long as it takes the card's clear effect to
   *  fire, and `active` is chosen by the PICK's method rather than by what is
   *  enabled — so without this term the control would, on that commit, offer
   *  clickable rows belonging to a method it is simultaneously rendering as
   *  disabled-with-a-reason. Enforcing it here rather than in each caller's
   *  `rows:` expression is what lets the two cards build their rows
   *  unconditionally and still not contradict themselves. */
  const active = useMemo(() => {
    if (!pick) return null;
    const hit = options.find((o) => o.method === pick.method) ?? null;
    return hit && hit.unavailable == null ? hit : null;
  }, [options, pick]);
  const activeRowKey = rowOfPick(active?.rows ?? [], pick);

  const pickMethod = useCallback((method: PickedMethod) => {
    // Re-clicking the live method is a NO-OP, not a re-stamp. A radiogroup does
    // not deselect on a second click, and re-emitting here would clear the row
    // the user had already chosen (the reset below is keyed on the method
    // CHANGING) and move `pickedAt` without any decision having been made.
    if (pick?.method === method) return;
    // A method change drops the row, and it has to: the rows belong to the
    // method. Carrying the old row's prices across would leave an Arithmetic
    // row's stock price stamped on a Barrier Race pick, which is the one thing
    // §4.1's split exists to make impossible.
    onChange({
      method,
      rowStockPrice:  null,
      rowOptionPrice: null,
      stopBasis:      pick?.stopBasis ?? DEFAULT_STOP_BASIS,
      pickedAt:       stamp(),
    });
  }, [onChange, pick, stamp]);

  const pickRow = useCallback((row: MethodPickRow) => {
    if (!pick) return;
    onChange({
      ...pick,
      rowStockPrice:  row.rowStockPrice,
      rowOptionPrice: row.rowOptionPrice,
      // RE-STAMPED. `pickedAt` is "the vintage of the numbers the pick was made
      // against" (types/domain.ts), and choosing a different row is a fresh
      // decision against the numbers on screen now.
      pickedAt:       stamp(),
    });
  }, [onChange, pick, stamp]);

  const pickBasis = useCallback((basis: PickedStopBasis) => {
    // No pick, nothing to record a basis against. The buttons are disabled in
    // that state; this is the guard that makes that non-load-bearing.
    if (!pick || pick.stopBasis === basis) return;
    onChange({ ...pick, stopBasis: basis, pickedAt: stamp() });
  }, [onChange, pick, stamp]);

  return (
    <div className={styles.wrap}>
      <div className={styles.head}>
        <Text size={11} tone="secondary" weight={400}>Exit method for this trade</Text>
        {pick && (
          <button type="button" className={styles.clear} onClick={() => onChange(null)}>
            <Text size={10} tone="dim">Clear</Text>
          </button>
        )}
      </div>

      <div className={styles.row} role="radiogroup" aria-label="Exit method for this trade">
        {options.map((o) => (
          <button
            key={o.method}
            type="button"
            role="radio"
            aria-checked={pick?.method === o.method}
            aria-label={o.label}
            disabled={o.unavailable != null}
            title={o.unavailable ?? undefined}
            className={pick?.method === o.method ? styles.btnActive : styles.btn}
            onClick={() => pickMethod(o.method)}
          >
            <Text size={11} weight={500}>{o.label}</Text>
            <Text size={10} tone="dim">
              {o.unavailable ?? `${o.rows.length} target${o.rows.length === 1 ? '' : 's'}`}
            </Text>
          </button>
        ))}
      </div>

      {active && active.rows.length > 0 && (
        <>
          <Text size={10} tone="dim">Target row</Text>
          <div className={styles.row} role="radiogroup" aria-label="Target row">
            {active.rows.map((r) => (
              <button
                key={r.key}
                type="button"
                role="radio"
                aria-checked={activeRowKey === r.key}
                aria-label={r.label}
                className={activeRowKey === r.key ? styles.btnActive : styles.btn}
                onClick={() => pickRow(r)}
              >
                <Text size={11} weight={500}>{r.label}</Text>
                <Data size={11} weight={400} tone="dim">{priceText(r.displayPrice)}</Data>
              </button>
            ))}
          </div>
        </>
      )}

      <Text size={10} tone="dim">Judged on</Text>
      <div className={styles.row} role="radiogroup" aria-label="Judged on">
        {STOP_BASES.map((b) => (
          <button
            key={b.value}
            type="button"
            role="radio"
            aria-checked={pick != null && pick.stopBasis === b.value}
            aria-label={b.label}
            disabled={pick == null}
            className={pick?.stopBasis === b.value ? styles.btnActive : styles.btn}
            onClick={() => pickBasis(b.value)}
          >
            <Text size={11} weight={500}>{b.label}</Text>
          </button>
        ))}
      </div>
      <Text size={10} tone="dim">
        A record of which stop this trade was judged on. It does not change which alerts fire —
        the stock stop and the premium stop both keep firing exactly as they do today.
      </Text>
    </div>
  );
}

export default MethodPickSelector;
