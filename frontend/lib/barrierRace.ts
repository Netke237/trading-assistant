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

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function days(v: number): string {
  // The reprice horizon can be a fractional day once the DTE clamp binds
  // (0.75 x a 3-day contract). Show a whole number when it is one.
  return Number.isInteger(v) ? `${v}d` : `${v.toFixed(1)}d`;
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
  return (
    `${money(premium)} premium - ${money(o.stopRepricedValue)} at the stop ` +
    `(repriced at ${days(o.repriceDaysStockStop)}) = ${money(o.riskStockStop)}`
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
  if (o.rrStockStop == null || o.riskStockStop == null || o.riskStockStop <= 0) {
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
export function formatRacePremiumRR(o: BarrierRaceOutcome, premiumStopPct: number): string {
  const legs = `${money(o.rewardDollar)} / ${money(o.riskPremiumStop)}`;
  if (o.rrPremiumStop == null) {
    return `${legs} - no premium-stop risk to divide by`;
  }
  // Deliberately NOT printed as "$1.04 / $3.12 = 0.33x". Once both legs are
  // quantized to cents their quotient no longer reproduces the constant on
  // small premiums ($0.21 / $0.62 is 0.34x, $0.21 / $0.64 is 0.33x), so
  // printing an equals sign there would assert an identity that is false on
  // exactly the contracts where this column matters least. The ratio comes
  // from the definition; the dollars are shown as its inputs, not as a sum.
  return (
    `${legs} - ${pct(o.targetPct)} / ${pct(premiumStopPct)} = `
    + `${o.rrPremiumStop.toFixed(2)}x on every contract`
  );
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
    ? ` + ${o.pStockStopFirst.toFixed(2)} x ${money(-o.riskStockStop)} (worth more at the stop than it cost)`
    : ` - ${o.pStockStopFirst.toFixed(2)} x ${money(o.riskStockStop)}`;
  return (
    `${o.pTargetFirst.toFixed(2)} x ${money(o.rewardDollar)}` +
    stopTerm +
    ` - ${o.pPremiumStopFirst.toFixed(2)} x ${money(o.riskPremiumStop)}` +
    ` + ${o.pNeither.toFixed(2)} x ${money(neither)}` +
    ` = ${money(perShare)}  ->  ${money(o.edgePerContract)} per contract`
  );
}

/**
 * What to print under "How it is set" for the premium-stop barrier.
 *
 * The card used to state unconditionally that the level came "from the editable
 * field above". It often does not. The field holds a DOLLAR amount derived at
 * SCAN time (`premium x premium_stop_pct`), while the conversion below divides
 * it by the premium quoted NOW — so a contract that has since fallen turns a
 * "60% stop" into a 94% one, and one that has fallen far enough makes the
 * fraction >= 1, at which point nothing is sent and the backend silently
 * applies risk_rules.yaml's own default. Saying so is the fix; the mismatch
 * itself is the field being stale, which is the user's to resolve.
 */
export function premiumStopSourceNote(
  appliedPct: number,
  dollarStop: number | null | undefined,
  premium: number,
): string {
  const applied = `${(appliedPct * 100).toFixed(0)}% of premium`;
  if (premiumStopPctFromDollars(dollarStop, premium) != null) {
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
