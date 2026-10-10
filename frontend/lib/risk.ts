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
  StopCostOut,
  MethodPick,
  PickedMethod,
} from '@/types/domain';
import type { Status } from '@/lib/status';
import { worstStatus, STATUS_LABEL } from '@/lib/status';
import { exposureMark } from '@/lib/portfolioTotals';

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
 * stop. The point of the gate: on a cheap, low-delta contract a far-away
 * structural stop is often BEYOND the point of total premium loss, so the
 * "stop" is not a risk control at all — it is a marker for a position that
 * was already worthless before it got there.
 *
 * THIS MODULE NO LONGER COMPUTES THE GATE (B2, spec §3 of
 * docs/superpowers/plans/2026-09-02-gate-basis-spec.md). It renders what the
 * endpoint that produced the stop already priced.
 *
 * What was here before: `|stop − spot| × |delta|`, capped at the premium. Two
 * reasons it is gone rather than kept as a fallback.
 *
 *   * It could not discriminate. On the spec's reference chain (stock $201.86,
 *     stop $185.87, 45 DTE) the cap bound on four of eight strikes, pinning
 *     them at exactly 100% — the gate could not tell a 220 call from a 240
 *     call, and merely restated that a long option's maximum loss is its
 *     premium.
 *   * A fallback that quietly answers a DIFFERENT question is worse than no
 *     answer. The straight line runs 17-29 points pessimistic against
 *     Black-Scholes on the same contract, so the two bases need two sets of
 *     thresholds; keeping both meant two rulers on one screen, which is the
 *     defect Phase B round 1 found and `LINEAR_BASIS_FALLBACK` was the stopgap
 *     for. Both are deleted together. Where no `stopCost` came back the badge
 *     reads "not computed" — never a silent PASS.
 *
 * The arithmetic lives in backend/app/scoring/stop_cost.py, on the endpoints
 * that produce a stop (`/contracts/structural-stop`, `/contracts/exit-plan`),
 * because the gate is evaluated at a stop that MOVES — "Check structure" and
 * "Compute Arithmetic Plan" each change it — so no scan-time precompute can
 * serve it, and a Black-Scholes-plus-IV-solver in TypeScript would permanently
 * duplicate the Python one (spec §2: "show the arithmetic, don't relocate it").
 */

/** The presenter's output. Same NAME and same role as the shape this file used
 *  to compute, so `TradeCard` and its formatters keep their structure, but the
 *  delta-linear members are gone: there is no `stockMove`/`delta`/`rawLoss`
 *  because nothing multiplies any more, and no `capped` because Black-Scholes
 *  cannot exceed the premium for a long option — there is nothing to cap and
 *  nothing to disclose past the cap. */
export interface StopPremiumRisk {
  premium:         number;   // per share, as the gate priced it
  valueAtStop:     number;   // BS(stop, K, today's dte, r, iv), per share
  loss:            number;   // premium − valueAtStop, per share
  stopPrice:       number;   // the stop this was priced AT
  fraction:        number;   // loss / premium, and what `status` was decided on
  passMaxFraction: number;   // the threshold applied — echoed for auditability
  status:          Status;
  basis:           'bs_today';
}

/** Renders a returned gate block. `null` in → `null` out (spec test 1).
 *
 *  The guard is not a second opinion on the server's arithmetic — it is the
 *  same "there is no honest answer" rule `compute_stop_cost` applies, repeated
 *  at the only place a block can arrive from somewhere other than a live
 *  endpoint: a persisted `ExitPlan` restored from an older localStorage blob.
 *  A sub-cent premium has no printable card (every figure here is rendered to
 *  cents, so it would print a percentage beside "$0.00 of $0.00 premium"), and
 *  a non-finite member has no printable anything. Both take the same "not
 *  computed" path the card already has for an absent block. */
export function stopPremiumRisk(c: StopCostOut | null): StopPremiumRisk | null {
  if (!c) return null;
  const nums = [c.lossDollar, c.valueAtStop, c.fraction, c.passMaxFraction, c.premium, c.stopPrice];
  if (!nums.every(Number.isFinite)) return null;
  if (c.premium < 0.01) return null;
  return {
    premium:         c.premium,
    valueAtStop:     c.valueAtStop,
    loss:            c.lossDollar,
    stopPrice:       c.stopPrice,
    fraction:        c.fraction,
    passMaxFraction: c.passMaxFraction,
    status:          c.status,
    basis:           c.basis,
  };
}

/** The two figures every readout below scales from, in whole cents.
 *
 *  The server hands these over already quantized, so this is a unit change and
 *  not a rounding step — but it stays the single place the conversion happens,
 *  because the defect this file spent five audit rounds removing was two
 *  precisions deciding one printed line. Comparing and subtracting in integer
 *  cents also keeps `$0.16 of $0.20` from turning into 0.7999999999999999 the
 *  moment anything divides the two dollar doubles. */
function cents(r: StopPremiumRisk) {
  return { loss: Math.round(r.loss * 100), premium: Math.round(r.premium * 100) };
}

/** The gate's inputs on one line, so the verdict is auditable at a glance:
 *  "$5.20 premium − $1.49 at $185.87 = $3.71 of $5.20 premium".
 *
 *  A formatter rather than inline JSX because interpolating this many values
 *  into markup splits it across text nodes — unreadable in the DOM and
 *  untestable by `getByText`. Same reasoning as
 *  `formatRecommendedContractSizeRaw`.
 *
 *  The basis suffix is not decoration. This line and the Barrier Race card's
 *  repriced figures are both "what is this contract worth at the stop", and
 *  they legitimately disagree: the race reprices AT THE HORIZON (theta
 *  included) and drives sizing, this one prices at TODAY's remaining life and
 *  drives only the verdict (spec §5). Naming the basis is what stops the pair
 *  reading as a contradiction. */
/* ── The ranking table's gate (Phase B3) ───────────────────────────────────
 *
 * A DIFFERENT reading from the card badge above, deliberately, and the table
 * has to say so. This one was priced at SCAN time, against a structural/ATR
 * stop, for the contract the scan auto-picked. The card's is priced against
 * whatever stop the user has since refreshed, for whatever contract they may
 * have overridden in Step 6. The two can legitimately disagree; what they must
 * never do is disagree silently, which is why the tooltip names the contract
 * this figure describes rather than just quoting the number.
 *
 * The row carries a percentage and a verdict and nothing else (spec §2.3), so
 * there is no arithmetic to show and none is invented here.
 */
export interface RankingStopCost {
  /** Badge text. '—' when there is nothing honest to say. */
  label:   string;
  tooltip: string;
  /** null renders as plain dim text, never as a badge: a verdict-shaped thing
   *  with no verdict in it is how "not computed" comes to read as "fine". */
  status:  'PASS' | 'CAUTION' | null;
}

export function rankingStopCost(
  pct: number | null | undefined,
  status: 'PASS' | 'CAUTION' | null | undefined,
): RankingStopCost {
  // BOTH must be present. One without the other is a half-computed gate, and
  // rendering either half alone would put a number with no verdict, or a
  // verdict with no number, in front of a user.
  if (pct == null || status == null || !Number.isFinite(pct)) {
    return {
      label: '—',
      tooltip:
        'Stop cost not computed for this candidate — no structural stop could be '
        + 'formed, the contract had no workable volatility, or this row came from a '
        + 'scan run before the gate existed. Re-run the scan.',
      status: null,
    };
  }
  const rounded = Math.round(pct);
  return {
    label: `${rounded}%`,
    tooltip:
      `${rounded}% of the premium is gone by the time the underlying reaches its stop `
      + `(${status}). Black-Scholes at today's date, priced at the scan's structural/ATR `
      + `stop — for the contract the SCAN picked. Step 6 can pick a different contract, `
      + `and the trade card re-prices against the stop you refresh there, so the two `
      + `readings can differ. This gate sorts candidates; it never blocks a trade.`,
    status,
  };
}

export function formatStopPremiumRisk(r: StopPremiumRisk): string {
  return (
    `$${r.premium.toFixed(2)} premium − $${r.valueAtStop.toFixed(2)} ` +
    `at $${r.stopPrice.toFixed(2)} = ` +
    `$${r.loss.toFixed(2)} of $${r.premium.toFixed(2)} premium` +
    ` · Black-Scholes, priced today`
  );
}

/** Whether the stop is a TOTAL LOSS on the figures actually printed.
 *
 *  Exported so the badge's tooltip branches on the same figures as the words
 *  around it. It used to be possible for the tooltip to call a contract a
 *  total loss while the money beside it read "$1 left", because the two came
 *  from different precisions; both now come from `cents`. */
export function stopLossIsTotalOnPrintedFigures(r: StopPremiumRisk): boolean {
  const c = cents(r);
  return c.loss >= c.premium;
}

/** The badge label: the verdict, the percentage, AND what survives the stop,
 *  per share.
 *
 *  Decision BADGE-SPEC-2026-09-05 (Kenneth). The schematic's card 03 puts the
 *  dollars-left on the badge itself and per SHARE — "Caution · 71% of premium
 *  · $1.49 left". The reason it matters beyond this card: the badge is what
 *  the ranking view will reuse, and there it would travel with only a
 *  percentage, which is the half that does not tell you whether being wrong
 *  costs $8 or $800.
 *
 *  UNITS ARE NAMED ON BOTH LINES, deliberately. This card shows the same
 *  quantity twice a foot apart in two units — $1.49 per share here, $149 per
 *  contract on the headline. That is the schematic's layout, not an accident,
 *  so each string says which it is rather than leaving a reader to conclude
 *  the card contradicts itself by a factor of a hundred. "/share" rather than
 *  "a share" because StatusBadge uppercases its label and is
 *  `white-space: nowrap` — "$1.49/SHARE LEFT" sits in the space the badge has,
 *  "$1.49 A SHARE LEFT" does not.
 *
 *  THE VERDICT WORD LEADS, as the schematic has it. StatusBadge renders
 *  `label ?? STATUS_LABEL[status]`, so supplying a label REPLACES the word —
 *  and dropping it left colour as the only thing separating two badges that
 *  print the same percentage. The percentage is rounded to a whole point and
 *  the verdict is not, so a badge carrying only the percentage is genuinely
 *  ambiguous near the line; the word is what settles it. */
export function formatStopLossBadge(r: StopPremiumRisk): string {
  const c = cents(r);
  const left = c.premium - c.loss;
  return `${STATUS_LABEL[r.status]} · ${formatStopLossPct(r)} of premium · $${(left / 100).toFixed(2)}/share left`;
}

/** The badge's percentage.
 *
 *  Taken from `fraction`, which is the number the SERVER decided the verdict
 *  on, so the percentage and the colour beside it can never be read off two
 *  different quantities — the failure mode that put "100% OF PREMIUM" next to
 *  "of the $1,890 premium, $8 left" on this card before.
 *
 *  100% is reserved for an actual total loss on the printed cents. `fraction`
 *  is rounded to hundredths server-side, so a contract with one cent of a
 *  $5.20 premium left rounds to 1.00 and would otherwise assert a total loss
 *  the money beside it contradicts; anything with a cent left reads at most
 *  99%.
 *
 *  0% is NOT reserved in the same way, and the asymmetry is deliberate. The
 *  two ends are different kinds of claim: "100% of premium" beside "$1.49/share
 *  left" is IMPOSSIBLE, while "0% of premium" beside "$9.99/share left" is
 *  merely a percentage rounded to the nearest whole point, which is what every
 *  other figure on the badge is too. Forcing the bottom up to 1% would break
 *  the stronger property — that the printed percentage is within half a point
 *  of the true fraction. */
export function formatStopLossPct(r: StopPremiumRisk): string {
  const c = cents(r);
  if (c.premium <= 0) return '0%';
  if (c.loss >= c.premium) return '100%';
  return `${Math.min(99, Math.max(0, Math.round(r.fraction * 100)))}%`;
}

/** The headline the badge's percentage is a summary OF: what one contract
 *  actually loses at the stop, and what is left afterwards.
 *
 *  Dollars per CONTRACT, not per share, because that is the number being
 *  risked — the arithmetic line below it stays per-share so it reconciles with
 *  the premium printed there. `$824 of the $1,890 premium, $1,066 left`.
 *
 *  "of the $1,890 PREMIUM", never "you paid". Two figures on this very card
 *  disagree with "paid": the order strip's Limit is freely editable, and CaR
 *  three rows up is `mid × contracts × 100`, so at Contracts=3 it reads $5,670
 *  against this line's $1,890. Both halves of this sentence are per contract
 *  and at the premium the gate priced; saying so is the difference between a
 *  figure that reconciles with CaR by division and one that looks like a
 *  contradiction.
 *
 *  `left` is subtracted from the already-rounded pair rather than rounded on
 *  its own, so the three figures cannot fail to add up. Rounding all three
 *  independently is how this line once read "$401 per contract — of the $651
 *  you paid, $251 left". */
export function formatStopLossHeadline(r: StopPremiumRisk): string {
  const c = cents(r);
  const left = c.premium - c.loss;
  const usd = (n: number) => `$${n.toLocaleString('en-US')}`;
  return `${usd(c.loss)} per contract — of the ${usd(c.premium)} premium, ${usd(left)} left`;
}

export function checkInvalidation(invalidation: number | null | undefined): boolean {
  // `null` is piece 3's "not computed — re-run the scan" (see
  // TradeCardData.exit.invalidation): a card whose stored stop was a
  // pre-piece-3 flat percentage, stripped by the scanStore v15 migration.
  // It fails here exactly as `undefined` does, so `missing_invalidation`
  // blocks the send rather than an order going out against a stop the model
  // never chose.
  return invalidation != null && invalidation > 0;
}

export const hasInvalidation = checkInvalidation;

/* ── The missing-method-pick refusal (Phase G piece 5, build step 4) ───────
 *
 * Spec §7.4 — "an explicit pick" means a `MethodPick` exists for the key
 * being sent and its `method` is one of the four values. A pick made for a
 * different contract, or cleared by a staleness reset, is absent and blocks;
 * so is a pick from a previous scan, since §5's reader returns an empty
 * slice on a `scan_id` mismatch — a stale pick is not "old", it is GONE.
 *
 * The set-membership check (rather than a bare `pick != null`) is defensive
 * against a corrupted/pre-G localStorage blob reaching this far: `method` is
 * typed as `PickedMethod` and can never legitimately be anything else, but a
 * restored value is not "trust the type", it is "trust what was on disk".
 *
 * NEITHER PRICE FIELD BLOCKS. Not `rowStockPrice` — Barrier Race never has
 * one (§4.1) and blocking on it would make the race unpickable. Not
 * `rowOptionPrice` — Ladder and Arithmetic never have one. A missing price is
 * not a missing DECISION: it degrades the `active_tp_method` seed to
 * `('ladder', NULL)` per §4.3's precondition, a state all three consumers
 * already agree on. */
const VALID_PICKED_METHODS: ReadonlySet<PickedMethod> = new Set([
  'arithmetic', 'monte_carlo', 'ladder', 'barrier_race',
]);

export function checkMethodPick(pick: MethodPick | null | undefined): boolean {
  return pick != null && VALID_PICKED_METHODS.has(pick.method);
}

export const MISSING_METHOD_PICK_TITLE = 'Method pick required';
export const MISSING_METHOD_PICK_MESSAGE =
  'Method pick required — choose which method this trade is judged on before submitting.';

/* ── The missing-invalidation refusal, said once ───────────────────────────
 *
 * DIRECT-SEND-STOP-GATE-2026-09-09. Three surfaces refuse a card whose
 * resolved stop is null -- SendToBrokerDialog (the basket), and step 7's two
 * DIRECT buttons "Place Limit" and "Right Now — Market" -- plus AutoTradeArm,
 * which refuses to arm one. They are one refusal for one reason, so they read
 * from one string rather than four copies that drift the first time anyone
 * rewords it. The dialog's existing wording is what these are: this is an
 * extraction, not a rewrite, so the copy on screen is unchanged where it
 * already existed.
 *
 * "before submitting" covers all four: each is the gesture that submits an
 * order to a broker. */
export const MISSING_INVALIDATION_TITLE = 'Invalidation stop required';
export const MISSING_INVALIDATION_MESSAGE =
  'Invalidation stop required — define an invalidation level before submitting.';

export function positionMultiplier(p: PortfolioPosition): number {
  return p.contract.endsWith('|STOCK') ? 1 : 100;
}

/** Sum of notional. `kind` (STOCK-SENDS) limits it to option or stock rows:
 *  each kind's total counts only its own rows (decision
 *  STOCK-SENDS-STOCK-CAPS-2026-09-27). A row without a live quote is valued at
 *  its entry price, never 0 (`exposureMark`, NO-LIVE-QUOTE NLQ-1). */
export function totalNotional(positions: PortfolioPosition[], kind?: 'option' | 'stock'): number {
  return positions.reduce(
    (sum, p) => {
      if (kind && p.contract.endsWith('|STOCK') !== (kind === 'stock')) return sum;
      return sum + exposureMark(p) * positionMultiplier(p) * (p.contracts ?? 1);
    },
    0,
  );
}

/** NOT the dashboard's source: RiskPanel reads `riskStore.computeMetrics`,
 *  which judges options and stocks against their own caps (STOCK-SENDS). This
 *  older helper has no production caller; it still sums every row, and its
 *  stock fields are placeholders. Use `computeMetrics` for anything shown. */
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
    const posNotional = exposureMark(p) * positionMultiplier(p) * (p.contracts ?? 1);
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
    stockExposurePct: 0,
    largestStockConcentrationPct: 0,
    largestStockConcentrationSymbol: '—',
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
  /** PIECE 3. The stop the card is actually SHOWING, when the caller has
   *  resolved one — step 7's `invalidationFor`, i.e. the user's typed value
   *  when the Invalidation field is touched, else the card's own.
   *
   *  It matters only now that `card.exit.invalidation` can be null. Before
   *  piece 3 the scan always sent a number and `missing_invalidation` was
   *  effectively unreachable; the v15 migration makes it live, and reading the
   *  CARD alone would then refuse to send a restored candidate even after the
   *  user typed a stop into it — the one gesture that fixes the card. Pass
   *  `undefined` to fall back to the card, which is what every caller with no
   *  overlay to consult should do. */
  resolvedInvalidation?: number | null,
  /** Phase G piece 5, build step 4 (§7.1) — the trader's explicit method
   *  pick for this card, resolved by the caller exactly as `resolvedInvalidation`
   *  is: step 7's `methodPickFor`, keyed by contract through `editKeyFor`.
   *  `undefined`/`null` alike mean no pick, since `MethodPick` has no
   *  card-level fallback the way invalidation falls back to `card.exit.*` —
   *  a pick is a decision a human made, not a field the card seeds. */
  methodPick?: MethodPick | null,
): RiskCheckResult {
  const reasons: string[] = [];
  let approved = true;

  const mid = card.contractDetails?.mid ?? 0;
  const car = capitalAtRisk(mid, proposedContracts);
  const singleExposure = exposurePct(car, limits.portfolioValue);
  // Options only (this check runs on the options basket): stock rows count
  // against the stock total, not this one (STOCK-SENDS).
  const currentNotional = totalNotional(positions, 'option');
  const totalExposure = exposurePct(currentNotional + car, limits.portfolioValue);

  if (!checkInvalidation(resolvedInvalidation ?? card.exit.invalidation)) {
    reasons.push('missing_invalidation');
    approved = false;
  }

  if (!checkMethodPick(methodPick)) {
    reasons.push('missing_method_pick');
    approved = false;
  }

  // Review fix #4 (decision D5): this check runs on the options basket only,
  // and an option order carries no protective order, so its worst-case loss is
  // the whole premium. `maxLossPerTradePct` therefore caps premium as well, and
  // the effective cap is the smaller of the two. Both limits and
  // `singleExposure` are fractions of portfolio value (0.05 = 5%). Mirrors
  // backend `portfolio_risk.check_position_risk`; stocks never reach here.
  const maxSingleOption = Math.min(limits.maxSingleTradeExposurePct, limits.maxLossPerTradePct);
  if (singleExposure > maxSingleOption) {
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
