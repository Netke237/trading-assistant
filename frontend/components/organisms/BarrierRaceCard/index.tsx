'use client';

import { Text, Data } from '@/components/primitives';
import {
  formatRaceRisk,
  formatRaceRR,
  formatRacePremiumRR,
  formatRaceEdge,
  premiumStopSourceNote,
  weightPercents,
  money,
} from '@/lib/barrierRace';
import type { BarrierRace, BarrierRaceOutcome } from '@/types/domain';
import styles from './BarrierRaceCard.module.css';

export interface BarrierRaceCardProps {
  /** `undefined` while nothing has been run, `null` when the simulation was
   *  refused (dte < 1). The two render differently and neither renders bars. */
  race: BarrierRace | null | undefined;
  /** True when the editable "Premium stop" field is what actually set the
   *  barrier — decided at REQUEST time, from the premium the request used, not
   *  re-derived here from the cent-rounded one. */
  premiumStopFromField: boolean;
  /** The card's editable "Premium stop" field, in DOLLARS, as it stands now.
   *  Only used to say whether that field actually set the barrier or the
   *  backend fell back to its own default — never to compute a level. The
   *  premium every chain subtracts comes from `race.premiumUsed`, so that the
   *  printed arithmetic is the backend's own and cannot drift from it. */
  premiumStopField: number | null;
  /** True only while the estimate on screen was fetched THIS mount. See the
   *  freshness note below. */
  isFresh: boolean;
  /** Set when a barrier moved after the race was computed. The race is CLEARED,
   *  not recomputed: its bars were measured against a stop the user has since
   *  moved, and re-running is a click, not something that happens on its own. */
  barriersChanged?: boolean;
  /** True when the STOCK stop specifically is the barrier that moved. The
   *  standalone invalidation probability below is a property of that stop, so
   *  it survives a moved PREMIUM stop and must not survive this one. */
  stockStopMoved?: boolean;
  /** The stock stop's STANDALONE measure — "did any path ever reach it",
   *  ignoring whether the premium stop fired first. It moved here from the
   *  Monte Carlo card because this is where the comparison is legible: shown
   *  next to the attribution, the gap between the two IS the thing this card
   *  exists to expose. */
  invalidation?: { probability: number; expectedDays: number | null } | null;
}

function pctLabel(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function daysLabel(v: number | null): string {
  return v == null ? '—' : `~${v.toFixed(0)}d`;
}

/**
 * The Barrier Race.
 *
 * A REFEREE, not a fourth profit-target method: it proposes no level of its
 * own. Every barrier it races is a level one of the three existing cards
 * already produced — the profit target, the structural stock stop, and the
 * card's own editable premium stop.
 *
 * What it adds is that the outcomes are an ATTRIBUTION. The Monte Carlo card
 * above measures "did the option ever cross the target" and "did the stock ever
 * cross the invalidation price" on the same paths, independently, so the two can
 * sum past 100% and a path that hit both is counted twice. Here every path is
 * assigned to whichever barrier it reached FIRST, so each row sums to exactly
 * 100% and the medians mean something.
 *
 * NO STATUS BADGE, DELIBERATELY. Spec section 3.2 lists StatusBadge among the
 * things this organism composes, and D8 specifies "two states, PASS/CAUTION,
 * never REJECT". Neither the spec nor any config says what would make a race
 * PASS rather than CAUTION — no threshold on edge, R:R or any share is defined
 * anywhere — and D8 itself says "the race adds no new gate". Inventing a
 * threshold to fill the badge would BE that gate. The caution-toned notes below
 * carry the warnings a badge would have summarised; the decision is recorded
 * here rather than left as a silent omission from the spec.
 *
 * The stacked bar's "stock stop" segment uses var(--reject) as a segment COLOUR
 * (it is the losing outcome in a four-way legend), which is not a status tint
 * and does not make the card red in D8's sense.
 */
export default function BarrierRaceCard({
  race,
  premiumStopFromField,
  premiumStopField,
  isFresh,
  barriersChanged = false,
  stockStopMoved = false,
  invalidation = null,
}: BarrierRaceCardProps) {
  if (race === null) {
    return (
      <section className={styles.card}>
        <Header />
        <Text size={12} tone="dim">
          Not simulated — contract expires today. A zero-length simulation has no paths to
          attribute, and four zeroes would read as a result rather than a refusal.
        </Text>
      </section>
    );
  }

  // A restored estimate can be arbitrarily old, and its two barrier inputs
  // (the shared stop, the editable premium stop) are live. Rendering it beside
  // current inputs is the same mixed-vintage hazard five audit rounds built
  // this freshness machinery to prevent.
  //
  // CHECKED BEFORE `barriersChanged`, deliberately. The other way round, the
  // frame after a contract switch — where `isFresh` is already false but
  // `barriersChanged` is computed from the previous contract's snapshot against
  // the new contract's stop — painted "Barriers changed — re-run the estimate"
  // plus the PREVIOUS contract's invalidation probability under the new
  // contract's header. Only the `race === null` refusal above outranks this,
  // because that copy depends on no live barrier at all.
  if (!race || !isFresh) return null;

  if (barriersChanged) {
    return (
      <section className={styles.card}>
        <Header />
        <Text size={12} tone="caution">
          Barriers changed — re-run the estimate. These bars were measured against a stop that has
          since moved, so they no longer describe this trade.
        </Text>
        {/* The standalone invalidation probability moved onto this card (spec
            section 3.4), and short-circuiting above it deleted it from the
            screen whenever a barrier moved — including when the PREMIUM stop
            moved, which cannot affect "did any path ever touch the stock
            stop". It survives here: it is a property of the stock stop and the
            simulation, not of the attribution the moved barrier invalidated. */}
        {/* Only when the STOCK stop is the barrier that stayed put. With one
             boolean for both, this rendered after a Check-structure or
             Arithmetic-Plan click too — quoting a probability measured against
             a level that is no longer shown anywhere on the card, under copy
             asserting it was unaffected. */}
        {invalidation && !stockStopMoved && (
          <Text size={10} tone="dim">
            The stock-stop probability is unaffected by the premium stop:{' '}
            {(invalidation.probability * 100).toFixed(0)}% of paths touch the stock stop at some
            point
            {invalidation.expectedDays != null
              ? ` (median ~${Math.round(invalidation.expectedDays)}d)`
              : ''}
            . The attribution above is what needs the re-run.
          </Text>
        )}
      </section>
    );
  }


  return (
    <section className={styles.card}>
      <Header />

      {/* 1. The three barriers ------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>The three barriers</Text>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col"><Text size={10} tone="dim">Barrier</Text></th>
              <th scope="col"><Text size={10} tone="dim">Level</Text></th>
              <th scope="col"><Text size={10} tone="dim">How it is set</Text></th>
              <th scope="col"><Text size={10} tone="dim">Armed</Text></th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><Text size={11}>Profit target</Text></td>
              <td><Data size={11}>per row below</Data></td>
              <td><Text size={11} tone="secondary">Your T1/T2/T3 % of premium</Text></td>
              <td><Text size={11} tone="dim">exit, not a stop</Text></td>
            </tr>
            <tr>
              <td><Text size={11}>Stock stop</Text></td>
              {/* Always with its unit. A bare number here would be ambiguous
                  against the option-value barrier on the next row. */}
              <td><Data size={11}>{money(race.stockStopPrice)} stock</Data></td>
              <td><Text size={11} tone="secondary">Structural level, or structural + ATR once an Arithmetic Plan has run</Text></td>
              {/* Both stops are live at once — Q6's armed stop is "whichever
                  fires first", which is exactly what the race measures. Neither
                  is a broker instruction (D10); both are in-app levels. */}
              <td><Text size={11} tone="secondary">yes — whichever fires first</Text></td>
            </tr>
            <tr>
              <td><Text size={11}>Premium stop</Text></td>
              <td><Data size={11}>{money(race.premiumStopPrice)} option</Data></td>
              <td>
                <Text size={11} tone="secondary">
                  {premiumStopSourceNote(
                    race.premiumStopPct, premiumStopFromField, premiumStopField, race.premiumUsed,
                  )}
                </Text>
              </td>
              <td><Text size={11} tone="secondary">yes — whichever fires first</Text></td>
            </tr>
          </tbody>
        </table>
        {invalidation && (
          <Text size={10} tone="dim">
            Measured on its own, {(invalidation.probability * 100).toFixed(0)}% of paths touch the
            stock stop at some point
            {invalidation.expectedDays != null
              ? ` (median ~${Math.round(invalidation.expectedDays)}d)`
              : ''}
            {' '}— ignoring whether the premium stop had already fired. The attribution below is the
            honest version: the gap between the two is how often you were stopped out on premium
            before the stock ever got there.
          </Text>
        )}
      </div>

      {/* 2. Race outcome -------------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>Which barrier is reached first</Text>
        <div className={styles.legend}>
          <LegendKey className={styles.swatchTarget} label="Target first" />
          <LegendKey className={styles.swatchStock} label="Stock stop first" />
          <LegendKey className={styles.swatchPremium} label="Premium stop first" />
          <LegendKey className={styles.swatchNeither} label="Neither, held to expiry" />
        </div>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col"><Text size={10} tone="dim">Target</Text></th>
              <th scope="col"><Text size={10} tone="dim">Split</Text></th>
              {/* "Target first", not "Target": the first column is the target
                  percentage, this one is its share of the attribution. */}
              <th scope="col"><Text size={10} tone="dim">Target first</Text></th>
              <th scope="col"><Text size={10} tone="dim">Stock stop</Text></th>
              <th scope="col"><Text size={10} tone="dim">Premium stop</Text></th>
              <th scope="col"><Text size={10} tone="dim">Neither</Text></th>
              {/* All three conditional medians. The stop ones were computed,
                  mapped onto the wire and typed, but never rendered — dead
                  payload on a card whose point is that the medians are
                  conditional on the outcome they belong to. */}
              <th scope="col"><Text size={10} tone="dim">Median to target</Text></th>
              <th scope="col"><Text size={10} tone="dim">to stock stop</Text></th>
              <th scope="col"><Text size={10} tone="dim">to premium stop</Text></th>
            </tr>
          </thead>
          <tbody>
            {race.outcomes.map((o) => {
              // Scaled from the weights the BACKEND allocated and weighted the
              // edge with, so these labels, the edge chain's multipliers and
              // the printed total are all the same four numbers. Rounding each
              // share here independently put a sizeable minority of real rows
              // at 99% or 101% (12% on one sweep, 22% on another);
              // allocating them here instead fixed the row sum but still left
              // the chain below printing a different rounding of the same
              // outcome on ~48% of rows.
              const [sTarget, sStock, sPrem, sNone] = weightPercents(o);
              return (
                <tr key={o.targetPct}>
                  <td>
                    <Text size={11} weight={500}>{pctLabel(o.targetPct)}</Text>
                    <Data size={10} tone="dim">{money(o.targetOptionPrice)}</Data>
                  </td>
                  <td><StackedBar o={o} /></td>
                  <td><Data size={11}>{sTarget}%</Data></td>
                  <td><Data size={11}>{sStock}%</Data></td>
                  <td><Data size={11}>{sPrem}%</Data></td>
                  <td><Data size={11}>{sNone}%</Data></td>
                  <td><Data size={11}>{daysLabel(o.daysTarget)}</Data></td>
                  <td><Data size={11}>{daysLabel(o.daysStockStop)}</Data></td>
                  <td><Data size={11}>{daysLabel(o.daysPremiumStop)}</Data></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Text size={10} tone="dim">
          Every row sums to 100% because each of the {race.nPaths.toLocaleString()} simulated paths
          is counted once, for whichever barrier it reached first. The Monte Carlo card above
          measures each barrier on its own, so its numbers can sum past 100%.
        </Text>
        <Text size={10} tone="dim">
          The medians are conditional: &quot;{daysLabel(race.outcomes[0]?.daysTarget ?? null)} to{' '}
          {pctLabel(race.outcomes[0]?.targetPct ?? 0)}&quot; is the median over the paths that got
          there first, not over all paths.
        </Text>
      </div>

      {/* 3. Risk / reward ------------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>Risk and reward, per target</Text>
        {race.outcomes.map((o) => (
          <div key={o.targetPct} className={styles.chainGroup}>
            <Text size={11} weight={500}>{pctLabel(o.targetPct)} target</Text>
            <div className={styles.chain}>
              <Text size={10} tone="dim">Risk</Text>
              <Data size={11}>{formatRaceRisk(o, race.premiumUsed)}</Data>
            </div>
            <div className={styles.chain}>
              <Text size={10} tone="dim">R:R vs stock stop</Text>
              <Data size={11} weight={500}>{formatRaceRR(o)}</Data>
            </div>
            <div className={`${styles.chain} ${styles.muted}`}>
              <Text size={10} tone="dim">R:R vs premium stop</Text>
              <Data size={11} tone="dim">{formatRacePremiumRR(o)}</Data>
            </div>
          </div>
        ))}
        {/* The WEIGHT, not the raw share: a share of 0.0045 rounds to 0 but is
             allocated 0.01, so reading the raw value let this claim the stock
             stop never wins while the table two blocks above printed 1%. */}
        {race.outcomes.every((o) => o.weightStockStopFirst === 0) && (
          <Text size={10} tone="caution">
            On this contract the stock stop wins under 1% of paths, so the bolded R:R above
            describes an outcome the simulation almost never reached, and its term contributes
            exactly nothing to the edge below. Largest-remainder allocation can round a genuinely
            non-zero share down to 0%, so &quot;never&quot; would be too strong; &quot;contributes nothing&quot;
            is exact, because the edge is weighted with that same allocated 0.
          </Text>
        )}
        {!race.ivSolved && (
          <Text size={10} tone="caution">
            The contract&apos;s own implied volatility could not be backed out of its quote, so this
            simulation ran on a generic fallback volatility. Treat every number on this card as
            describing a contract the market is not pricing this way — re-check the quote.
          </Text>
        )}
        <Text size={10} tone="dim">
          Only the first ratio is a measurement. Its risk leg is the premium minus what the
          contract would still be worth at the stock stop, which depends on strike, spot, time and
          IV independently — so it genuinely differs between contracts. The greyed one divides two
          numbers that are both a fixed fraction of premium, so premium cancels out of it
          entirely and nothing about this contract survives into the result. It is the same on
          every contract you could pick, which is why it is greyed. Deliberately not written as a
          division of the two percentages shown above: both are rounded for display while the stop
          fraction is an arbitrary number, so working it out from them disagrees with the printed
          ratio on roughly two rows in five.
        </Text>
      </div>

      {/* 4. Edge ---------------------------------------------------------- */}
      <div className={styles.block}>
        <Text size={12} weight={600}>Edge per contract</Text>
        {race.outcomes.map((o) => (
          <div key={o.targetPct} className={styles.chainGroup}>
            <Text size={11} weight={500}>{pctLabel(o.targetPct)} target</Text>
            <Data size={11}>{formatRaceEdge(o, race.premiumUsed)}</Data>
          </div>
        ))}
        <Text size={10} tone="dim">
          The &quot;Neither&quot; term is the mean value of those paths at expiry minus the premium
          paid. It is signed, not a loss — those paths can end above what you paid.
        </Text>
        <Text size={10} tone="dim">
          Assumes implied volatility is unchanged when a barrier is reached. On a long call that is
          pessimistic at the stop and optimistic at the target — a real fear bid would leave more
          premium than shown.
        </Text>
      </div>
    </section>
  );
}

function Header() {
  return (
    <>
      <Text size={14} weight={600}>Barrier Race</Text>
      <Text size={10} tone="dim">
        Same simulation as the Monte Carlo card above, read differently: every path is attributed to
        whichever barrier it reached first. It proposes no level of its own.
      </Text>
    </>
  );
}

function LegendKey({ className, label }: { className: string; label: string }) {
  return (
    <span className={styles.legendKey}>
      <span className={`${styles.swatch} ${className}`} aria-hidden="true" />
      <Text size={10} tone="dim">{label}</Text>
    </span>
  );
}

/** A 100%-stacked bar. Widths come straight from the returned shares, which sum
 *  to 1 by construction, so the segments always fill the track exactly. */
function StackedBar({ o }: { o: BarrierRaceOutcome }) {
  const segments: Array<[string, number, string]> = [
    [styles.swatchTarget, o.pTargetFirst, 'Target first'],
    [styles.swatchStock, o.pStockStopFirst, 'Stock stop first'],
    [styles.swatchPremium, o.pPremiumStopFirst, 'Premium stop first'],
    [styles.swatchNeither, o.pNeither, 'Neither'],
  ];
  // The spoken label carries the same allocated percentages as the visible
  // ones, so a screen-reader user hears a row that sums to 100% too. Rounding
  // each share independently here read out 101% on ~1 row in 6.
  const spoken = weightPercents(o);
  return (
    <div
      className={styles.bar}
      role="img"
      aria-label={
        `${(o.targetPct * 100).toFixed(0)}% target: `
        + segments.map(([, , label], i) => `${label} ${spoken[i]}%`).join(', ')
      }
    >
      {segments.map(([cls, v, label]) => (
        v > 0 ? (
          <span
            key={label}
            className={`${styles.segment} ${cls}`}
            // toFixed, not `v * 100`: 0.14 * 100 is 14.000000000000002 in
            // binary floating point, and that tail ends up in the rendered
            // style attribute verbatim.
            style={{ width: `${(v * 100).toFixed(4)}%` }}
            data-testid={`segment-${label}`}
          />
        ) : null
      ))}
    </div>
  );
}
