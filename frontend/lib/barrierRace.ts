/*
 * Barrier-race presentation helpers.
 *
 * Spec: docs/superpowers/plans/2026-09-02-barrier-race-spec.md section 2.4.
 *
 * WHY FORMATTERS AND NOT INLINE JSX: the card prints the full arithmetic chain
 * behind every number ("show the arithmetic" — Kenneth, 2026-09-02).
 * Interpolating this many values straight into markup splits them across text
 * nodes, which is unreadable in the DOM and untestable by getByText. Same
 * reasoning as formatRecommendedContractSizeRaw and formatStopPremiumRisk in
 * lib/risk.ts.
 *
 * WHY NO MATHS HERE: every number below is computed backend-side and arrives
 * already quantized to cents, so these functions only lay values out — they
 * never recompute one. The frontend has no option-pricing maths at all (no
 * Black-Scholes, no normal CDF, not one Math.exp in lib/), and adding a pricer
 * here would permanently duplicate Python's against a number that cannot update
 * live anyway: moving a barrier invalidates the simulation, which has to be
 * re-run.
 */
import type { BarrierRaceOutcome } from '@/types/domain';

/** "$5.20", "-$1.20". A leading minus reads better outside the dollar sign. */
export function money(v: number): string {
  const s = `$${Math.abs(v).toFixed(2)}`;
  return v < 0 ? `-${s}` : s;
}

function days(v: number): string {
  // The reprice horizon can be fractional once a clamp binds (0.75 x a 3-day
  // contract, or the half-day-before-expiry cap). Show a whole number when it
  // is one, and otherwise enough precision to BE the value used: at 1dp,
  // 0.75 x 21 = 15.75 printed as "15.8d", and this card's contract is that
  // every printed input is the one the arithmetic used.
  if (Number.isInteger(v)) return `${v}d`;
  return `${Number(v.toFixed(2))}d`;
}

/**
 * The four allocated weights as whole percentages. They sum to exactly 100
 * because the backend allocated them to hundredths that sum to 1.00 — this only
 * scales them, it does not round anything.
 *
 * There used to be a largest-remainder allocation HERE, over the raw shares,
 * which fixed the labels but left the edge chain three blocks below printing a
 * separately-rounded multiplier for the same outcome — the table reading
 * "Neither 49%" beside a chain reading "+ 0.48 x". Any share whose allocated
 * hundredth differs from its own 2dp rounding disagrees, which on sampled
 * sweeps of real output ran from a few percent to a fifth of rows depending on
 * the parameter mix. One allocation, done once, upstream of both.
 */
export function weightPercents(o: BarrierRaceOutcome): number[] {
  return [
    o.weightTargetFirst, o.weightStockStopFirst, o.weightPremiumStopFirst, o.weightNeither,
  ].map((w) => Math.round(w * 100));
}

/**
 * The stock-stop risk leg, with its inputs.
 *
 *   "$5.20 premium - $1.09 at the stop (repriced at 7d) = $4.11"
 *
 * The chain adds up exactly, because the backend does this arithmetic in cents
 * for that reason.
 *
 * `premium` must be the backend's own `race.premiumUsed`, not a local copy:
 * Python's round() is banker's rounding and JavaScript's toFixed() is not, so
 * on an exact half-cent the two disagree and the printed chain stops adding up.
 *
 * "repriced at Nd" is DAYS ELAPSED until the stop is reached, and it is the
 * same on all three rows — the stop leg is a property of the stop, not of the
 * target being raced against it.
 */
export function formatRaceRisk(o: BarrierRaceOutcome, premium: number): string {
  if (o.stopRepricedValue == null || o.riskStockStop == null) {
    return `${money(premium)} premium - could not reprice at the stop`;
  }
  // The horizon is named, not just numbered. It is the UNCONDITIONAL median day
  // any path reaches the stop (shown in the barriers block above), while the
  // table's "to stock stop" column is the CONDITIONAL median over stop-first
  // paths — so the two legitimately differ, and on the reference contract the
  // column reads "—" while this chain says 26d. When no path reached the stop
  // at all, this is the preset fallback and no median exists anywhere on screen.
  const basis = (() => {
    if (o.daysAnyPathReachedStop == null) {
      return ' — the preset default; no path reached the stop';
    }
    // The median is capped half a day short of expiry, so on a short contract
    // the number printed here is NOT the median: at dte=10 with a median of
    // 10, this prints 9.5 while daysAnyPathReachedStop is 10. Calling that
    // "the median" was simply false whenever the cap bound.
    if (Math.abs(o.daysAnyPathReachedStop - o.repriceDaysStockStop) > 1e-9) {
      return ` — capped just short of expiry; the median is ${days(o.daysAnyPathReachedStop)}`;
    }
    return ' — the median day any path reaches the stop';
  })();
  return (
    `${money(premium)} premium - ${money(o.stopRepricedValue)} at the stop ` +
    `(repriced at ${days(o.repriceDaysStockStop)}${basis}) = ${money(o.riskStockStop)}`
  );
}

/**
 * The stock-stop R:R, with its inputs. THE measurement on this card.
 *
 *   "$1.04 / $4.11 = 0.25x"
 *
 * Returns the em-dash form when the risk leg is not positive — possible on a
 * deep-ITM contract with a tight stop, where the option is still worth more at
 * the stop than it cost. Never render a negative or infinite ratio.
 */
export function formatRaceRR(o: BarrierRaceOutcome): string {
  // Two different states, two different sentences. Folding them together
  // printed "worth more there than it cost" for a stop that could not be
  // repriced AT ALL — directly under formatRaceRisk's "could not reprice at
  // the stop", two adjacent lines explaining the same state incompatibly.
  if (o.riskStockStop == null || o.stopRepricedValue == null) {
    return `${money(o.rewardDollar)} / could not reprice at the stop = —`;
  }
  if (o.rrStockStop == null || o.riskStockStop <= 0) {
    return `${money(o.rewardDollar)} / no risk at the stop (worth more there than it cost) = —`;
  }
  return `${money(o.rewardDollar)} / ${money(o.riskStockStop)} = ${o.rrStockStop.toFixed(2)}x`;
}

/**
 * The premium-stop R:R, labelled as the constant it is.
 *
 *   "$1.04 / $3.12 = 0.33x - equals your 20% target / 60% stop, on every contract"
 *
 * Its risk leg IS proportional to premium, so premium cancels out of the ratio
 * and it reduces to the two percentages the user typed. Shown for completeness;
 * the card must say it is not a measurement.
 */
export function formatRacePremiumRR(o: BarrierRaceOutcome): string {
  // "legs A and B", never "A / B". A slash between two dollar amounts reads as
  // a division to the one audience this card is built for — someone checking
  // the arithmetic — and on a $1.03 premium the cent-quantized legs $0.21 and
  // $0.62 divide to 0.34x, not the 0.33x this column is BY DEFINITION. The
  // dollars are inputs, not a sum to be performed.
  const legs = `legs ${money(o.rewardDollar)} and ${money(o.riskPremiumStop)}`;
  if (o.rrPremiumStop == null) {
    return `${legs} - no premium-stop risk to divide by`;
  }
  // Deliberately NOT printed as "$1.04 / $3.12 = 0.33x". Once both legs are
  // quantized to cents their quotient no longer reproduces the constant on
  // small premiums ($0.21 / $0.62 is 0.34x, $0.21 / $0.64 is 0.33x), so
  // printing an equals sign there would assert an identity that is false on
  // exactly the contracts where this column matters least. The ratio comes
  // from the definition; the dollars are shown as its inputs, not as a sum.
  // NO PERCENTAGES HERE, and the stop percentage is no longer even a parameter.
  // Printing "20% / 60% = 0.33x" renders both at 0dp while premiumStopPct is an
  // arbitrary float — the field holds a scan-time dollar amount over the
  // premium quoted now — so on a third of realistic combinations the printed
  // division does not produce the printed ratio: a $0.20 stop on a $0.70
  // premium prints "10% / 29%", which is 0.34, beside a true 0.35. Replacing
  // one unverifiable chain with another is not a fix. The stop percentage is
  // shown once, in the barriers block above, where it is not part of a sum.
  // The ratio is STATED, and the reader is no longer told to derive it from the
  // two percentages on screen. Deleting the printed division was not enough:
  // "which is your target % over your stop %" instructs the same division, and
  // the operands are both rendered at 0dp while the stop fraction is an
  // arbitrary float — a 20% target against a 0.5455 stop prints "20%" and
  // "~55%", whose quotient is 0.36, beside a true 0.37x. The block-level prose
  // under this table explains WHY the number carries no information, which is
  // the part worth saying, without attaching the claim to a specific pair of
  // rounded digits.
  return `${legs} - ${o.rrPremiumStop.toFixed(2)}x, the same on every contract`;
}

/**
 * The edge, with all four signed contributions.
 *
 *   "0.27 x $1.04 - 0.00 x $5.02 - 0.69 x $3.12 + 0.05 x -$1.57 = -$1.93  ->  -$193"
 *
 * Term order matches the outcome columns above it on the card, so the chain
 * reads in the same order as the bars.
 *
 * The fourth term is SIGNED, not a loss: a path that reached no barrier can end
 * above the premium paid. Writing it as "- p x loss" would be wrong whenever
 * that happens.
 */
export function formatRaceEdge(o: BarrierRaceOutcome, premium: number): string {
  if (o.edgePerContract == null || o.riskStockStop == null) return '—';
  const neither = o.terminalMean == null ? 0 : o.terminalMean - premium;
  const perShare = o.edgePerContract / 100;
  // A NEGATIVE stock-stop risk leg is a real state, not an error: on a deep-ITM
  // contract with a tight stop the option can still be worth more at the stop
  // than it cost. Subtracting it then ADDS to the edge, which is correct signed
  // EV but reads as an unexplained "- 0.00 x -$70.90". Print it as the gain it
  // is, and say why — the R:R column shows an em dash in the same state, and
  // nothing else on the card connects the two.
  const stopTerm = o.riskStockStop < 0
    ? ` + ${o.weightStockStopFirst.toFixed(2)} x ${money(-o.riskStockStop)} (worth more at the stop than it cost)`
    : ` - ${o.weightStockStopFirst.toFixed(2)} x ${money(o.riskStockStop)}`;
  return (
    `${o.weightTargetFirst.toFixed(2)} x ${money(o.rewardDollar)}` +
    stopTerm +
    ` - ${o.weightPremiumStopFirst.toFixed(2)} x ${money(o.riskPremiumStop)}` +
    ` + ${o.weightNeither.toFixed(2)} x ${money(neither)}` +
    ` = ${money(perShare)}  ->  ${money(o.edgePerContract)} per contract`
  );
}

/**
 * What to print under "How it is set" for the premium-stop barrier.
 *
 * The card used to state unconditionally that the level came "from the editable
 * field above". It often does not. The field holds a DOLLAR amount derived at
 * SCAN time (`premium x premium_stop_pct`), while the conversion divides it by
 * the premium quoted NOW — so a contract that has since fallen turns a "60%
 * stop" into a 94% one, and one that has fallen far enough makes the fraction
 * >= 1, at which point nothing is sent and the backend silently applies
 * risk_rules.yaml's own default. Saying so is the fix; the mismatch itself is
 * the field being stale, which is the user's to resolve.
 *
 * `fromField` is decided AT REQUEST TIME by the caller, from the same premium
 * the request used — not re-derived here. Re-deriving it from the backend's
 * cent-rounded `premiumUsed` disagreed with the request in the band where the
 * two straddle 1.0: a quoted premium of 2.996 against a $2.998 field made the
 * request send nothing (1.0007) while the note credited the field (0.9993).
 */
export function premiumStopSourceNote(
  appliedPct: number,
  fromField: boolean,
  dollarStop: number | null | undefined,
  premium: number,
): string {
  // "stops out after losing ~55% of premium", NOT "~55% of premium". The
  // percentage is the LOSS that fires the stop; the cell immediately beside it
  // holds the resulting LEVEL, which is the complement — a $2.75 premium with a
  // 55% stop sits at $1.25, and 55% of $2.75 is $1.51. Two numbers in one table
  // row that cannot be reconciled without silently knowing to take the
  // complement, on a card whose premise is that every term can be checked by
  // hand. The `~` fixes the precision; this fixes the sense.
  const applied = `stops out after losing ~${(appliedPct * 100).toFixed(0)}% of premium`;
  if (fromField) {
    return `${applied}, from the editable field above`;
  }
  if (dollarStop != null && Number.isFinite(dollarStop) && dollarStop > 0
      && Number.isFinite(premium) && premium > 0) {
    return (
      `${applied} — the default. Your ${money(dollarStop)} stop is at or above the `
      + `${money(premium)} premium this estimate used, which is a total loss rather than a stop.`
    );
  }
  return `${applied} — the default, because no premium stop is set above`;
}

/**
 * The card's "Premium stop" field holds a DOLLAR amount (entry x the backend's
 * premium_stop_pct). The barrier race's third barrier is expressed as a
 * FRACTION of premium, because that is what defines the option-value level
 * `premium x (1 - pct)`. Convert, or return undefined to let the backend fall
 * back to risk_rules.yaml's own premium_stop_pct.
 *
 * A dollar stop at or above the whole premium is a total loss, which makes the
 * barrier unreachable-by-definition rather than a stop — the backend rejects
 * pct >= 1 outright, so refuse it here rather than sending a 422.
 */
export function premiumStopPctFromDollars(
  dollarStop: number | null | undefined,
  premium: number,
): number | undefined {
  if (dollarStop == null || !Number.isFinite(dollarStop) || dollarStop <= 0) return undefined;
  if (!Number.isFinite(premium) || premium <= 0) return undefined;
  const pctOfPremium = dollarStop / premium;
  if (pctOfPremium <= 0 || pctOfPremium >= 1) return undefined;
  return pctOfPremium;
}
