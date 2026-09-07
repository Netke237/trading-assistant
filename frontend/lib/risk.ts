/*
 * Risk — pure helpers for capital-at-risk, exposure %, and portfolio metrics.
 */

import type {
  PortfolioPosition,
  RiskLimits,
  PortfolioRiskMetrics,
  TradeCardData,
  RiskCheckResult,
  MaxLossOverride,
} from '@/types/domain';
import type { Status } from '@/lib/status';
import { worstStatus, STATUS_LABEL } from '@/lib/status';

export function capitalAtRisk(mid: number, contracts: number): number {
  return mid * contracts * 100;
}

export function exposurePct(notional: number, portfolioValue: number): number {
  if (portfolioValue <= 0) return 0;
  return notional / portfolioValue;
}

/* ── Stop-vs-premium gate ──────────────────────────────────────────────────
 *
 * How much of the premium a long option loses if the underlying reaches its
 * structural stop. The point of the gate: on a cheap, low-delta contract a
 * far-away structural stop is often BEYOND the point of total premium loss,
 * so the "stop" is not a risk control at all — it is a marker for a position
 * that was already worthless before it got there.
 *
 * This is deliberately the cheap delta-linear estimate (same basis as
 * TradeCard's `structuralRR`), not a Black-Scholes reprice: it must be
 * computable from the scan payload alone, with no "Check structure" /
 * "Estimate" / "Compute Arithmetic Plan" round-trip, or it cannot fire early
 * enough to be a gate. It answers "is this stop roughly a full-premium loss?",
 * a question a 5% error does not change — not "what exactly will I lose",
 * which is what the exit-plan pipeline's repriced `stop.contractPrice` is for.
 */

/** Last-resort threshold, used only when no caller supplies one. The live value
 *  is per-horizon and comes from scoring_rules.yaml via
 *  `stopPremiumThresholdsStore` (which can also carry a per-run override) — this
 *  mirrors the Swing default so a caller that forgets to pass one degrades to a
 *  sane gate rather than to no gate.
 *
 *  ONE threshold, not two, and the verdict is PASS or CAUTION — never REJECT.
 *  The gate exists to sort candidates into "the stop is survivable on this
 *  contract" and "it isn't", so a screener can surface the cheaper-to-be-wrong
 *  trades up front; it is not a verdict on the trade and it blocks nothing.
 *  REJECT is the red badge in this design system, and a red badge on a
 *  contract the user may perfectly well want to trade reads as a refusal. */
export const STOP_PREMIUM_PASS_MAX_FRACTION = 0.7;

export interface StopPremiumRisk {
  stockMove: number;   // $ from the underlying's price to the stop
  delta:     number;   // |delta| actually used (floored, see below)
  rawLoss:   number;   // stockMove x delta, per share — UNCAPPED, may exceed premium
  loss:      number;   // min(rawLoss, premium) — the real per-share max loss
  premium:   number;   // per share
  fraction:  number;   // loss / premium, 0..1
  capped:    boolean;  // rawLoss >= premium — the stop is at/beyond total loss
  status:    Status;
}

/** Returns null when there is no meaningful answer: a non-positive premium, a
 *  stop sitting exactly at the current price (the card already renders that as
 *  "N/A (stop = price)"), or any non-finite input. */
export function stopPremiumRisk(
  stopPrice: number,
  stockPrice: number,
  delta: number,
  premium: number,
  thresholds?: { pass_max_fraction: number } | null,
): StopPremiumRisk | null {
  if (![stopPrice, stockPrice, delta, premium].every(Number.isFinite)) return null;
  if (premium <= 0) return null;
  // A premium that does not round to a whole cent has no printable card. Every
  // figure in this gate is rendered from the pair rounded to cents, so a
  // premium of $0.004 printed a badge of "0%" beside a tooltip calling the
  // contract a total loss, above "$0 per contract — of the $0 premium, $0
  // left" and "$10.00 away × Δ0.500 = $0.00 of $0.00 premium (uncapped
  // $5.00)". Returning null puts it through the same "N/A" path the card
  // already has for a stop sitting at the price, instead of printing four
  // mutually contradictory zeroes. Guarding here rather than in each formatter
  // keeps one definition of "there is no meaningful answer".
  //
  // BELOW ONE CENT, not below half a cent. `Number(premium.toFixed(2)) <= 0`
  // only caught premiums under $0.005, so a $0.005 premium still rendered:
  // "$1 per contract -- of the $1 premium, $0 left" for a contract that cost
  // 50c, contradicting the CaR row three lines above it (mid x contracts x
  // 100 = $0.50) by a factor of two -- the very reconciliation
  // formatStopLossHeadline's doc comment promises.
  // Tested on the RAW premium, not the rounded one: (0.005).toFixed(2) rounds
  // UP to "0.01", so a guard on the rounded value never rejected the very case
  // it was written for.
  if (premium < 0.01) return null;

  // A caller passing a non-finite or out-of-range threshold gets the default
  // rather than a gate that silently passes everything. The per-run override in
  // Step 3 is user-editable, so this is a reachable input, not a defensive
  // nicety. Above 1.0 is meaningless (the loss caps at the premium, so nothing
  // could ever exceed it) and would make CAUTION unreachable.
  const passMax =
    thresholds && Number.isFinite(thresholds.pass_max_fraction)
      && thresholds.pass_max_fraction > 0 && thresholds.pass_max_fraction <= 1
      ? thresholds.pass_max_fraction : STOP_PREMIUM_PASS_MAX_FRACTION;

  const stockMove = Math.abs(stopPrice - stockPrice);
  if (stockMove === 0) return null;

  // Floored at 0.05 exactly as TradeCard's `structuralRR` does — a delta at or
  // near zero would otherwise report a rounding artifact as "no risk at the
  // stop", which is the most dangerous direction to be wrong in.
  const usedDelta = Math.max(Math.abs(delta), 0.05);
  const rawLoss = stockMove * usedDelta;
  // A long option cannot lose more than it cost, however far the stop sits.
  const loss = Math.min(rawLoss, premium);
  const fraction = loss / premium;
  // `capped` is a fact about the instrument, not a policy: the uncapped estimate
  // has run past what the contract cost. Kept separate from the threshold (which
  // moved to a single configurable pass line) because `fraction` is pinned at
  // 1.0 for every capped case and so can never distinguish "exactly a total
  // loss" from "twice a total loss" — the formatter surfaces that difference.
  const capped = rawLoss >= premium;

  // Two states by design — see STOP_PREMIUM_PASS_MAX_FRACTION. A contract whose
  // stop costs 85% of premium and one whose stop is twice the premium both read
  // CAUTION; the percentage in the badge and the "(uncapped $X)" tail carry the
  // magnitude, so nothing is hidden by collapsing the verdict.
  // THE VERDICT IS DECIDED ON THE PRINTED PAIR, for the same reason the
  // percentage beside it is (see formatStopLossPct). Deciding the colour at
  // full precision and the number at printed precision let them straddle the
  // threshold in opposite directions: $1.77 away × Δ0.789 on a $2.00 premium
  // is 0.69827 at full precision — PASS — while the printed pair is exactly
  // $1.40 of $2.00, so the badge read "70% OF PREMIUM" in PASS green, under
  // the PASS tooltip ("still holds meaningful value"), directly above an
  // equation a reader resolves by hand to the CAUTION line. ~0.18% of ordinary
  // inputs at the Swing 0.70 line, and more at 0.80.
  //
  // What this does and does NOT buy: the verdict now agrees with the EQUATION
  // printed beneath it, always -- both are the printed pair. It does not make
  // the badge's whole-percent figure unambiguous, because that figure is
  // rounded and the verdict is not: $1.39 and $1.40 of a $2.00 premium both
  // print "70%" at a 0.70 line and are legitimately PASS and CAUTION. That is
  // why the badge leads with the VERDICT WORD (formatStopLossBadge) rather
  // than the percentage alone -- the word, not the number, is what separates
  // those two cards.
  //
  // `fraction` on the object stays full precision: it is the underlying
  // quantity, and nothing on screen is scaled from it.
  const printed = printedFrom(stockMove, usedDelta, premium);
  // COMPARED IN INTEGER CENTS, not by dividing the two dollar doubles.
  // `printed.loss / printed.premium` is a float quotient, and at the exact
  // threshold it lands a hair BELOW it: 0.16 / 0.20 is 0.7999999999999999,
  // while 16 / 20 is 0.8. So a card whose own printed equation reads
  // "$0.16 of $0.20 premium" -- exactly the 0.80 pass line, i.e. CAUTION --
  // was rendering PASS green under the PASS tooltip ("still holds meaningful
  // value if this stop is hit"). 412 exact-boundary cent pairs do this at the
  // 0.80 line, 161 at 0.75, 21 at 0.85, 3 at 0.70, and they include entirely
  // ordinary premiums ($0.05, $0.10, $0.20, $0.40, $0.50).
  //
  // This is round 5's own finding surviving at the boundary: that round moved
  // the verdict onto the printed pair, which was right, and then compared the
  // pair with the one operation that reintroduces float error. Cross-multiply
  // instead -- the same integer discipline `roundCentsOfProduct` two functions
  // down already uses, and the reason it exists.
  //
  // Both operands are exact to the cent by construction (printedFrom rounds
  // them), and `passMax` is a config fraction, so scaling by 1e6 keeps every
  // product an exact integer far inside Number.MAX_SAFE_INTEGER.
  const lossCents = Math.round(printed.loss * 100);
  const premiumCents = Math.round(printed.premium * 100);
  const passMaxScaled = Math.round(passMax * 1e6);
  const status: Status =
    lossCents * 1e6 < passMaxScaled * premiumCents ? 'PASS' : 'CAUTION';

  return { stockMove, delta: usedDelta, rawLoss, loss, premium, fraction, capped, status };
}

/** Half-up to cents on the EXACT product of the two printed factors.
 *
 *  `toFixed(2)` breaks a mathematical `x.xx5` according to the BINARY value,
 *  so the direction is effectively arbitrary — and the case this rework's own
 *  doc comment uses as its worked example is one of the losers: 8.01 x 0.500
 *  is exactly 4.005, whose double is 4.00499999..., so `toFixed(2)` gives
 *  "4.00" where a reader multiplying the two printed factors by hand gets
 *  $4.01.
 *
 *  Half-up matches what a person does on paper — but it has to be half-up on
 *  the value Kenneth's calculator shows, not on the double. The previous
 *  version was `Math.round(move * delta * 100 + Number.EPSILON) / 100`, and
 *  the EPSILON nudge in it was arithmetically inert wherever it mattered:
 *  EPSILON is 2.22e-16, while one ULP at a product of 994.5 (`$11.70 away x
 *  0.850` in cents) is 1.14e-13 — five hundred times larger. Adding EPSILON
 *  cannot move a double that is one ULP below the .5 split. Swept against a
 *  decimal-exact half-up over 4,995,000 ordinary pairs (move <= $50.00 by 1c,
 *  delta 0.001-0.999), that version disagreed on 2999 of them (0.060%) —
 *  three times the 0.02% error rate the rework was written to remove, and it
 *  moves the VERDICT too, since `status` is computed from
 *  `printed.loss / printed.premium`.
 *
 *  So do the multiplication in integers, where there is no binary split to
 *  lose. `move` is already rounded to 2dp and `delta` to 3dp by the caller, so
 *  `move x 100` and `delta x 1000` are exact integers, and their product is an
 *  exact integer count of 1e-5 dollars. Half-up on that is a comparison of
 *  integers: no double ever holds a value near the split.
 *
 *  Rounds half AWAY FROM ZERO rather than half-up-toward-positive, so a
 *  negative delta (a put quoted signed) would round by magnitude the way the
 *  hand check does. DEFENSIVE, not reachable from the one caller today:
 *  `stopPremiumRisk` passes `usedDelta = Math.max(Math.abs(delta), 0.05)`, so
 *  every delta arriving here is positive. Kept rather than asserted because
 *  the alternative on an unexpected sign is a silently wrong cent.
 *
 *  PRECONDITION, and it belongs to the caller rather than to this function:
 *  the integer scaling is exact only because `printedFrom` has already rounded
 *  `move` to 2dp and `delta` to 3dp. A future second caller passing raw
 *  full-precision values gets a DIFFERENT rule (its factors are silently
 *  re-rounded by the `Math.round` scaling), not a wrong one — but not the same
 *  one either. Hence the name: it rounds the product of two PRINTED factors,
 *  and there is exactly one place those exist. */
function roundCentsOfProduct(move: number, delta: number): number {
  // Exact: both factors arrive pre-rounded to 2dp / 3dp respectively, so
  // scaling them to integers cannot lose anything.
  const moveCents = Math.round(move * 100);
  const deltaMilli = Math.round(delta * 1000);
  // Units of 1e-5 dollars. Well inside Number.MAX_SAFE_INTEGER for any real
  // stop distance: $50,000 away at delta 1.000 is 5e6 x 1e3 = 5e9.
  const scaled = moveCents * deltaMilli;
  const sign = scaled < 0 ? -1 : 1;
  const cents = Math.floor((Math.abs(scaled) + 500) / 1000);
  return (sign * cents) / 100;
}

function printedShare(r: StopPremiumRisk) {
  return printedFrom(r.stockMove, r.delta, r.premium);
}

/** The figures EXACTLY as the card prints them, so every consumer scales from
 *  one rounded set instead of rounding full precision independently.
 *
 *  THE PRODUCT IS COMPUTED FROM THE PRINTED FACTORS, deliberately. Kenneth
 *  checks this line by multiplying the two numbers he can see, so the only
 *  version that survives a hand-check is the one those two numbers actually
 *  produce. Rounding the move to cents, the delta to 3dp and the loss to cents
 *  independently stacks three errors of up to half a unit each: over an
 *  ordinary sweep of stops and deltas about 6% of inputs printed a product a
 *  cent away from its own factors (e.g. `$0.58 away × Δ0.457 = $0.26`, where
 *  0.58 × 0.457 is 0.2651 and reads as $0.27). Moving from 2dp to 3dp on the
 *  delta narrowed that and could never close it: the move and the loss are
 *  rounded too, so no amount of delta precision makes the three agree.
 *
 *  THE VERDICT COMES FROM HERE TOO. This block used to end by claiming
 *  "`status` is unaffected — it still comes from full precision on the object",
 *  which had been false since the printed pair was introduced:
 *  `stopPremiumRisk` computes `status` from `printed.loss / printed.premium`,
 *  under a comment of its own shouting the opposite. The stale sentence
 *  survived because this block was ORPHANED — it sat above
 *  `roundCentsOfProduct`'s own doc rather than above the function it describes,
 *  so it documented nothing and nothing pointed at it. Both are fixed here:
 *  the block is attached to `printedFrom`, and the claim now matches the code.
 *  `fraction` on the object is the one thing that does stay full precision.
 *
 *  The single implementation of "what the card prints", shared by
 *  `printedShare` (which reads it off a finished object) and `stopPremiumRisk`
 *  (which needs it BEFORE the object exists, to decide the verdict on the same
 *  figures the badge will show). Two copies of this rounding is exactly the
 *  kind of drift the printed set was introduced to remove, so there is one. */
function printedFrom(rawMove: number, rawDelta: number, rawPremium: number) {
  const move = Number(rawMove.toFixed(2));
  const delta = Number(rawDelta.toFixed(3));
  const premium = Number(rawPremium.toFixed(2));
  const product = roundCentsOfProduct(move, delta);
  // WHETHER THE CAP BINDS IS DECIDED ON THE PRINTED PRODUCT, not on
  // `r.capped`. `r.capped` is `rawLoss >= premium` at full precision, and
  // rounding the delta to 3dp moves the product to the other side of the
  // premium in both directions:
  //
  //   `r.capped` true, product below premium — $70.10 away × Δ0.5505 on a
  //   $38.59 premium printed "= $38.59 of $38.59 premium (uncapped $38.55)",
  //   an "uncapped" figure BELOW the capped one, which cannot happen by
  //   construction (loss = min(rawLoss, premium)) and answers nothing.
  //
  //   `r.capped` false, product above premium — $70.02 away × Δ0.7495 on a
  //   $52.48 premium printed "= $52.48 of $52.48 premium" with no tail, while
  //   the printed factors give $52.52. The hand-check fails by 4c with nothing
  //   on screen to explain it, and the headline above it reads "$0 left" for a
  //   stop the code itself classifies as not a total loss.
  //
  // Both are the same defect: two different precisions deciding one printed
  // line. Deciding it on `product` makes the line self-consistent either way —
  // it multiplies out exactly when the cap does not bind, and carries the
  // "(uncapped …)" tail that explains the difference when it does. Rare
  // (~0.005% of inputs overall) but ~0.4% of the near-total-loss cards this
  // gate exists to surface.
  // Strictly greater: at product === premium the equation multiplies out to
  // the printed loss exactly, so a "(uncapped $6.51)" tail repeating "$6.51 of
  // $6.51 premium" would answer a question nobody asked. The tail exists only
  // where the two figures genuinely differ.
  const printedCapped = product > premium;
  const loss = Math.min(product, premium);
  return { move, delta, premium, product, loss, printedCapped };
}

/** The gate's inputs on one line, so the verdict is auditable at a glance:
 *  "$11.50 away × Δ0.450 = $2.50 of $2.50 premium (uncapped $5.18)".
 *
 *  A formatter rather than inline JSX because interpolating this many values
 *  into markup splits it across text nodes — unreadable in the DOM and
 *  untestable by `getByText`. Same reasoning as
 *  `formatRecommendedContractSizeRaw`. The uncapped tail appears only when the
 *  cap actually bound, where it answers "how far past a total loss is this?" —
 *  a question `loss` alone cannot, since it is pinned to `premium`. */
export function formatStopPremiumRisk(r: StopPremiumRisk): string {
  const p = printedShare(r);
  const base =
    `$${p.move.toFixed(2)} away × Δ${p.delta.toFixed(3)} = ` +
    `$${p.loss.toFixed(2)} of $${p.premium.toFixed(2)} premium`;
  const basis = ' · delta-linear, priced today';
  return p.printedCapped
    ? `${base} (uncapped $${p.product.toFixed(2)})${basis}`
    : `${base}${basis}`;
}

/** Whether the stop is a TOTAL LOSS on the figures actually printed.
 *
 *  The badge's tooltip used `r.capped`, which is `rawLoss >= premium` at full
 *  precision, while the badge label and the headline beside it both come from
 *  `printedShare`. Two precisions deciding one readout is the exact defect
 *  `printedShare` was introduced to remove, and it was reachable with ordinary
 *  4dp deltas: $55.92 away x 0.1622 on a $9.07 premium reads "99% OF PREMIUM"
 *  and "$906 per contract — of the $907 premium, $1 left" under a tooltip
 *  saying the contract is a total loss. Exported so the tooltip can branch on
 *  the same figures as the words around it. */
export function stopLossIsTotalOnPrintedFigures(r: StopPremiumRisk): boolean {
  const p = printedShare(r);
  return p.loss >= p.premium;
}

/** The badge label: the percentage AND what survives the stop, per share.
 *
 *  Decision BADGE-SPEC-2026-09-05 (Kenneth). The schematic's card 03 puts the
 *  dollars-left on the badge itself and per SHARE — "Caution · 71% of premium
 *  · $1.49 left" — and what shipped through rounds 1-4 kept the badge
 *  percent-only with per-contract dollars on the headline below. Put to
 *  Kenneth as a spec deviation; he chose the schematic. The reason it matters
 *  beyond this card: the badge is what the ranking view will reuse, and there
 *  it would travel with only a percentage, which is the half that does not
 *  tell you whether being wrong costs $8 or $800.
 *
 *  UNITS ARE NAMED ON BOTH LINES, deliberately. This card now shows the same
 *  quantity twice a foot apart in two units — $1.49 per share here, $149 per
 *  contract on the headline. That is the schematic's layout, not an accident,
 *  so each string says which it is ("a share" / "per contract") rather than
 *  leaving a reader to conclude the card contradicts itself by a factor of a
 *  hundred. "/share" rather than "a share" because StatusBadge uppercases its
 *  label and is `white-space: nowrap` -- "$1.49/SHARE LEFT" sits in the space
 *  the badge has, "$1.49 A SHARE LEFT" does not. The schematic renders the
 *  badge in mixed case; the uppercase is StatusBadge's house style applied to
 *  every badge in the app, so the CONTENT follows the schematic and the
 *  casing follows the design system.
 *
 *  Scaled from the SAME rounded cents pair as `formatStopLossPct` and
 *  `formatStopLossHeadline`, and the dollars-left is subtracted in whole cents
 *  rather than computed in floats, so the badge cannot round to "$0.00 left"
 *  while the percentage beside it still reads 99%, and cannot read "$0.01
 *  left" under a 100%. */
export function formatStopLossBadge(r: StopPremiumRisk): string {
  const p = printedShare(r);
  const lossCents = Math.round(p.loss * 100);
  const premiumCents = Math.round(p.premium * 100);
  const leftCents = premiumCents - lossCents;
  // The VERDICT WORD leads, as the schematic has it. StatusBadge renders
  // `label ?? STATUS_LABEL[status]`, so supplying a label REPLACES the word --
  // and dropping it left colour as the only thing separating two badges that
  // print the same percentage: at a 0.70 pass line, $2.78 away x 0.500 on a
  // $2.00 premium ($1.39, PASS) and $2.80 away x 0.500 on the same premium
  // ($1.40, CAUTION) both read "70% of premium". The percentage is rounded to
  // a whole point and the verdict is not, so a badge that carries only the
  // percentage is genuinely ambiguous near the line; the word is what settles
  // it, which is presumably why the schematic put it there.
  const verdict = STATUS_LABEL[r.status];
  const pct = formatStopLossPct(r);
  return `${verdict} · ${pct} of premium · $${(leftCents / 100).toFixed(2)}/share left`;
}

/** The badge's percentage, from the SAME rounded pair the headline prints.
 *
 *  MOVED HERE IN ROUND 8. This block described `formatStopLossPct` while
 *  sitting several functions above it, stacked on top of another doc comment —
 *  so it documented nothing, and a false sentence in it survived unnoticed for
 *  that reason (the same orphaning defect as `printedFrom`'s block, and the
 *  same one PROJECT_STATE records round 2 as having fixed elsewhere).
 *
 *  It used to be `(r.fraction * 100).toFixed(0)` in the badge's own JSX —
 *  full precision, while the headline two rows down was scaled from the
 *  printed pair. On ~1.4% of ordinary inputs the two disagreed by a point,
 *  and at the top of the range the disagreement was a flat contradiction:
 *  $35.24 away × Δ0.5342 on an $18.90 premium put "100% OF PREMIUM" beside
 *  "of the $1,890 premium, $8 left".
 *
 *  100% is therefore reserved for an actual total loss on the printed
 *  figures. Anything with a dollar left over reads at most 99%, so the badge
 *  cannot assert something the money beside it contradicts. (0% is NOT
 *  reserved in the same way — see the note on the return below for why the two
 *  ends are different.)
 *
 *  THE VERDICT COMES FROM THE PRINTED PAIR TOO. This block used to end
 *  "The PASS/CAUTION verdict is untouched: it is `status`, computed from full
 *  precision." False since the printed pair was introduced: `stopPremiumRisk`
 *  computes `status` from `printed.loss / printed.premium`. What stays at full
 *  precision is `fraction` on the object, which nothing on screen scales
 *  from. */
export function formatStopLossPct(r: StopPremiumRisk): string {
  const p = printedShare(r);
  const perContract = Math.round(p.loss * 100);
  const premiumTotal = Math.round(p.premium * 100);
  if (premiumTotal <= 0) return '0%';
  if (perContract >= premiumTotal) return '100%';
  // THE TOP IS RESERVED, THE BOTTOM IS NOT, and the asymmetry is deliberate.
  //
  // Round 8 read the missing bottom clamp as the mirror of the top one and
  // asked for `Math.max(1, ...)`. Building it showed why it is not: it breaks
  // the stronger property this file's sweep test pins, that the printed
  // percentage is within half a point of the true fraction (a 0.38% loss
  // forced up to "1%" is off by 0.62). The two ends are different kinds of
  // claim. "100% of premium" beside "$1.49/share left" is IMPOSSIBLE -- 100%
  // means nothing is left -- so the top has to be reserved for a real total
  // loss. "0% of premium" beside "$9.99/share left" is merely a percentage
  // rounded to the nearest whole point, which is what every other figure on
  // the badge is too, and it does not assert anything false.
  return `${Math.min(99, Math.round((perContract / premiumTotal) * 100))}%`;
}

/** The headline the badge's percentage is a summary OF: what one contract
 *  actually loses at the stop, and what is left afterwards.
 *
 *  Dollars per CONTRACT, not per share, because that is the number being
 *  risked -- the arithmetic line below it stays per-share so it reconciles
 *  with the premium and delta printed there. `$824 of the $1,890 premium,
 *  $1,066 left`. The dollars-left half is deliberate: the schematic argues it
 *  is more actionable than a percentage when deciding whether to overrule the
 *  verdict.
 *
 *  "of the $1,890 PREMIUM", never "you paid". `r.premium` is
 *  `contractDetails.mid`, the scan-time snapshot, and two figures on this very
 *  card disagree with "paid": the order strip's Limit is freely editable (set
 *  it to $22.00 on an $18.90 mid and nothing here moves), and CaR three rows
 *  up is `mid × contracts × 100`, so at Contracts=3 it reads $5,670 against
 *  this line's $1,890. Both halves of this sentence are per contract and at
 *  the mid; saying so is the difference between a figure that reconciles with
 *  CaR by division and one that looks like a contradiction. */
export function formatStopLossHeadline(r: StopPremiumRisk): string {
  // Scaled from the SAME rounded per-share figures the line beneath prints, and
  // `left` is subtracted from the already-rounded pair rather than rounded on
  // its own. Rounding all three independently from full precision let the
  // headline contradict itself and the line below it, two lines apart, on a
  // card whose entire premise is arithmetic a non-coder can check by hand: at
  // $8.01 away × Δ0.500 on a $6.51 premium it read "$401 per contract — of the
  // $651 you paid, $251 left" (401 + 251 = 652) directly above "= $4.00", whose
  // hundred is $400. This is the class of bug the notation rework was written
  // to remove, so re-introducing it here was worse than leaving it alone.
  const p = printedShare(r);
  const perContract = Math.round(p.loss * 100);
  const premiumTotal = Math.round(p.premium * 100);
  const left = premiumTotal - perContract;
  const usd = (n: number) => `$${n.toLocaleString('en-US')}`;
  return `${usd(perContract)} per contract — of the ${usd(premiumTotal)} premium, ${usd(left)} left`;
}

export function checkInvalidation(invalidation: number | undefined): boolean {
  return invalidation !== undefined && invalidation > 0;
}

export const hasInvalidation = checkInvalidation;

export function positionMultiplier(p: PortfolioPosition): number {
  return p.contract.endsWith('|STOCK') ? 1 : 100;
}

export function totalNotional(positions: PortfolioPosition[]): number {
  return positions.reduce(
    (sum, p) => sum + p.currentPrice * positionMultiplier(p) * (p.contracts ?? 1),
    0,
  );
}

export function computePortfolioRiskMetrics(
  positions: PortfolioPosition[],
  limits: RiskLimits,
  dailyRecommendations: number,
): PortfolioRiskMetrics {
  const portfolioValue = limits.portfolioValue || 1;
  const notional = totalNotional(positions);
  const totalExposurePct = notional / portfolioValue;
  const concurrentPositions = positions.length;

  let largestConcentrationPct = 0;
  let largestConcentrationSymbol = '—';
  for (const p of positions) {
    const posNotional = p.currentPrice * positionMultiplier(p) * (p.contracts ?? 1);
    const posPct = posNotional / portfolioValue;
    if (posPct > largestConcentrationPct) {
      largestConcentrationPct = posPct;
      largestConcentrationSymbol = p.symbol;
    }
  }

  const statuses: Status[] = [];

  if (totalExposurePct > limits.maxTotalExposurePct) {
    statuses.push('REJECT');
  } else if (totalExposurePct > limits.maxTotalExposurePct * 0.8) {
    statuses.push('CAUTION');
  } else {
    statuses.push('PASS');
  }

  if (concurrentPositions >= limits.maxConcurrentPositions) {
    statuses.push('REJECT');
  } else if (concurrentPositions >= Math.floor(limits.maxConcurrentPositions * 0.8)) {
    statuses.push('CAUTION');
  }

  if (dailyRecommendations >= limits.maxDailyRecommendations) {
    statuses.push('REJECT');
  } else if (dailyRecommendations >= limits.maxDailyRecommendations * 0.8) {
    statuses.push('CAUTION');
  }

  const status = worstStatus(...statuses);

  return {
    totalExposurePct,
    concurrentPositions,
    dailyRecommendations,
    largestConcentrationPct,
    largestConcentrationSymbol,
    status,
  };
}

/** Feature C (exit-plan pipeline plan) — $ loss projected if the position is
 *  stopped out at the exit-plan pipeline's final stop: entry premium minus
 *  the stop-repriced contract price (floored at 0 — a repriced value at or
 *  above entry means the "stop" isn't actually a loss for this leg), times
 *  contracts. Options-only, mirroring the exit-plan pipeline itself. */
export function maxLossAtStop(
  entryPremium: number,
  stopContractPrice: number,
  contracts: number,
): number {
  return Math.max(0, entryPremium - stopContractPrice) * contracts * 100;
}

/** Resolves the $ threshold `maxLossAtStop` is checked against — a per-trade
 *  override (fixed dollar or percent of portfolioValue) if one is set,
 *  otherwise the global `maxLossPerTradePct` default. */
export function resolveMaxLossLimitDollar(
  portfolioValue: number,
  globalPct: number,
  override?: MaxLossOverride | null,
): number {
  if (override) {
    return override.mode === 'dollar' ? override.value : portfolioValue * override.value;
  }
  return portfolioValue * globalPct;
}

/** Risk-derived contract size: how many whole contracts the given risk
 *  budget affords at the given per-contract risk (typically the exit-plan
 *  pipeline's `maxLossAtStop(entryPremium, stop.contractPrice, 1)`), rounded
 *  down. Returns both the floored recommendation and the raw decimal so the
 *  UI can show "3 contracts (3.71 exact)" rather than just the rounded
 *  number. Returns null when there's no meaningful answer — a non-positive
 *  budget, or a non-positive per-contract risk (the stop reprices at or
 *  above entry premium, i.e. not actually a loss on this leg).
 *
 *  `recommended` floors `raw + FLOOR_EPSILON` rather than `raw` directly —
 *  `riskPerContract` is a subtraction of two dollar floats (entry premium
 *  minus a repriced stop price, see `maxLossAtStop`), which routinely lands
 *  a few ULPs off the exact cent value (e.g. 1.00 - 0.41 === 0.5900000000000001
 *  in IEEE754). At an exact-multiple budget that noise pushes `raw` to
 *  0.9999999999999999 instead of 1.0, silently under-recommending by a
 *  whole contract. The epsilon is far too small to change any real,
 *  intentionally-fractional recommendation. */
const FLOOR_EPSILON = 1e-9;

export interface RecommendedContractSize {
  raw: number;
  recommended: number;
}

export function recommendedContractSize(
  riskBudget: number,
  riskPerContract: number,
): RecommendedContractSize | null {
  if (riskBudget <= 0 || riskPerContract <= 0) return null;
  const raw = riskBudget / riskPerContract;
  return { raw, recommended: Math.floor(raw + FLOOR_EPSILON) };
}

/** Formats a `recommendedContractSize` result for display as "N.dd" — always
 *  showing `size.recommended` as the whole part, by construction. Two
 *  earlier versions independently re-derived a floored/truncated decimal
 *  from `raw` (once via bare `toFixed`, once via a second, separately-
 *  epsilon-adjusted floor) — each fixed a real IEEE754 boundary disagreement
 *  with `recommended`, and each was later shown to have its own, narrower
 *  boundary where the two could still disagree, since two independent
 *  floating-point computations over the same input can be tuned to agree at
 *  every practically-reachable boundary but never proven to agree at every
 *  boundary. Deriving the decimal from `size.recommended` (already the
 *  authoritative, epsilon-corrected integer) instead of re-flooring `raw`
 *  a third time eliminates that whole bug class rather than patching the
 *  next boundary: the whole part can never disagree with `recommended`
 *  because it never comes from anywhere else. `Math.max(0, ...)` guards the
 *  fractional remainder against the same sub-epsilon negative noise
 *  `FLOOR_EPSILON` exists to absorb (e.g. raw fractionally *below*
 *  `recommended` by a few ULPs). */
export function formatRecommendedContractSizeRaw(size: RecommendedContractSize): string {
  const fractionCents = Math.min(99, Math.floor(Math.max(0, size.raw - size.recommended) * 100));
  return `${size.recommended}.${String(fractionCents).padStart(2, '0')}`;
}

export function checkTradeRisk(
  card: TradeCardData,
  proposedContracts: number,
  limits: RiskLimits,
  positions: PortfolioPosition[],
  dailyRecommendations: number,
  /** Feature 5 (Arithmetic Profit Target card) — the active PRE-trade
   *  max-loss override for this symbol, if the user has set one via the
   *  Arithmetic card. `undefined`/`null` inherits the global
   *  `maxLossPerTradePct` default, same as no override at all. */
  maxLossOverride?: MaxLossOverride | null,
): RiskCheckResult {
  const reasons: string[] = [];
  let approved = true;

  const mid = card.contractDetails?.mid ?? 0;
  const car = capitalAtRisk(mid, proposedContracts);
  const singleExposure = exposurePct(car, limits.portfolioValue);
  const currentNotional = totalNotional(positions);
  const totalExposure = exposurePct(currentNotional + car, limits.portfolioValue);

  if (!checkInvalidation(card.exit.invalidation)) {
    reasons.push('missing_invalidation');
    approved = false;
  }

  if (singleExposure > limits.maxSingleTradeExposurePct) {
    reasons.push('single_trade_exposure_too_high');
    approved = false;
  }

  if (totalExposure > limits.maxTotalExposurePct) {
    reasons.push('total_exposure_limit_reached');
    approved = false;
  }

  if (positions.length >= limits.maxConcurrentPositions) {
    reasons.push('max_concurrent_positions_reached');
    approved = false;
  }

  if (positions.some((p) => p.symbol === card.symbol)) {
    reasons.push('duplicate_symbol');
    approved = false;
  }

  if (dailyRecommendations >= limits.maxDailyRecommendations) {
    reasons.push('max_daily_recommendations_reached');
    approved = false;
  }

  // Feature 5 — a per-trade PRE-trade override now can exist (set on the
  // Arithmetic card, passed in via `maxLossOverride` above), resolved through
  // the same shared `resolveMaxLossLimitDollar` the post-trade override
  // (PortfolioPosition.maxLossOverride, via the Portfolio EditDrawer) already
  // uses — one resolution function, not two subtly different ones. Absent an
  // override, this still falls back to the global default. Skipped entirely
  // when no exit plan has been computed yet (nothing to reprice against).
  let lossAtStop: number | undefined;
  let lossLimitDollar: number | undefined;
  const exitPlan = card.exit.exitPlan;
  if (exitPlan) {
    // `cd.mid` is the scan-time snapshot, while `exitPlan.stop.contractPrice`
    // came from a fresh quote fetched when "Compute Exit Plan" ran (see the
    // comment on TradeCard's computeExitPlan) — the two don't share a
    // baseline if premium moved between scan and click. Same limitation as
    // `capitalAtRisk(mid, ...)` above, which this mirrors deliberately
    // rather than inventing a second, inconsistent convention; `ExitPlan`
    // doesn't currently carry the fresh premium it was computed against, so
    // fixing this for real means threading that value through as a new
    // field, which is out of scope here.
    const entryPremium = card.contractDetails?.mid ?? 0;
    lossAtStop = maxLossAtStop(entryPremium, exitPlan.stop.contractPrice, proposedContracts);
    lossLimitDollar = resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct, maxLossOverride);
    if (lossAtStop > lossLimitDollar) {
      reasons.push('max_loss_per_trade_exceeded');
      approved = false;
    }
  }

  return {
    approved,
    reasons,
    singleExposurePct: singleExposure,
    totalExposurePct: totalExposure,
    capitalAtRisk: car,
    maxLossAtStop: lossAtStop,
    maxLossLimitDollar: lossLimitDollar,
  };
}
