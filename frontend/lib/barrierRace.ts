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
  const ratio = `${money(o.rewardDollar)} / ${money(o.riskPremiumStop)} = ${o.rrPremiumStop.toFixed(2)}x`;
  return `${ratio} - equals your ${pct(o.targetPct)} target / ${pct(premiumStopPct)} stop, on every contract`;
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
  return (
    `${o.pTargetFirst.toFixed(2)} x ${money(o.rewardDollar)}` +
    ` - ${o.pStockStopFirst.toFixed(2)} x ${money(o.riskStockStop)}` +
    ` - ${o.pPremiumStopFirst.toFixed(2)} x ${money(o.riskPremiumStop)}` +
    ` + ${o.pNeither.toFixed(2)} x ${money(neither)}` +
    ` = ${money(perShare)}  ->  ${money(o.edgePerContract)} per contract`
  );
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
