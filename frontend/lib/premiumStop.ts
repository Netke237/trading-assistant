/** Per-position premium stop resolution (piece 4) — the TypeScript twin of
 *  `backend/app/services/premium_stop.py`.
 *
 *  Before piece 4 there were three global premium-stop percentages and no
 *  per-position field at all, so every open position shared one number:
 *  changing it silently re-armed all of them, and a conviction trade could not
 *  be given more room than a speculative one.
 *
 *  Three call sites on this side must agree with each other AND with the
 *  backend's alert generator: `alertEngine.scanPortfolio` (which fires the
 *  in-app alert), the Portfolio drawer's "fires at" preview, and the drawer's
 *  own inherited-vs-set display. A preview that disagrees with the alert that
 *  later fires is worse than no preview, so all of them resolve through here.
 *
 *  Keep in step with the Python module above — the two implement one rule. */

/** Last-resort value, used only when no global was supplied. Mirrors
 *  `risk_rules.yaml -> reward_risk.premium_stop_pct` and
 *  `settingsStore.premiumStopPct`, both of which ship as 0.60. */
export const PREMIUM_STOP_PCT_FALLBACK = 0.60;

/** THE BAND BOTH EDITORS OF A PER-POSITION PREMIUM STOP ACCEPT.
 *
 *  ROUND 12 finding 13 — one quantity had two editors and they disagreed on
 *  what counts as a stop at all. TradeCard bounded the DOLLAR field at
 *  10%–99% of the mid (round 5, after a typed 0 clamped to $0.01 and armed a
 *  0.19% stop that alerts on the first cent of adverse move and shrinks the
 *  auto-trader's daily-loss denominator ~3000x). The Portfolio drawer, editing
 *  the same `premiumStopPct` on the same position, went on accepting anything
 *  the backend schema does — `gt=0, lt=1`, advertised in its own hint as
 *  0.01–99.99 — so the number the card refuses to create could still be typed
 *  onto the position ten seconds later.
 *
 *  10% because that is the floor the app already applies to the GLOBAL premium
 *  stop (`routers/risk_settings.py`, `ge=0.10, le=1.0`); 99% because the
 *  backend rejects a per-position ratio at or above 1 and 100% is not a stop
 *  but a total loss. Deriving both editors from these two numbers is what
 *  keeps them from drifting again.
 *
 *  THE BAND GOVERNS EDITORS, NOT STORED VALUES, and the distinction is not a
 *  hedge — round 1 of the follow-up audit established two live routes to a
 *  stored fraction outside it, so a reader that treated the band as an
 *  invariant would be wrong:
 *
 *    - the backend derives the stored ratio as `premiumStopDollar /
 *      entry_price` against the FILL, not the mid the card bounded the dollar
 *      against (`routers/portfolio.py:285-296` then `:361-364`), so $0.60
 *      typed on a $5.20 mid (11.5%, legal here) stores 7.5% on an $8.00 fill;
 *    - rows created before this band existed.
 *
 *  So the backend's own `(0, 1)` stays as it is: it is the outer bound, and
 *  both kinds of row still have to load and be editable upward. For the same
 *  reason `barrierRace.premiumStopPctFromDollars` deliberately keeps `(0, 1)`
 *  too — it reads a stored/derived fraction rather than accepting a typed one.
 *
 *  Fractions, matching `premiumStopPct` itself — multiply by 100 for the
 *  percent an editor shows. */
export const PREMIUM_STOP_MIN_PCT = 0.10;
export const PREMIUM_STOP_MAX_PCT = 0.99;

/** The DOLLAR bounds for a per-position premium stop quoted against `mid`.
 *
 *  TradeCard edits the stop in dollars and the drawer edits it as a percent,
 *  so the card has to convert — and it did that with `Math.round(n * 100) / 100`
 *  on both ends, which shaves up to half a cent in EITHER direction. That put
 *  the card's own boundary values OUTSIDE the band the drawer enforces: a
 *  $5.24 mid gave a minimum of $0.52 = 9.92%, and a $1.01 mid gave a maximum
 *  of $1.00 = 99.01%. A stop created at the card's own minimum was then one
 *  the drawer refused — the exact disagreement the shared band exists to end,
 *  surviving at the boundary for most mids.
 *
 *  So the rounding goes OUTWARD-TO-INWARD: ceil the floor, floor the ceiling.
 *  Both ends land inside the band at 2dp, which is the precision the card's
 *  editor commits at. The two `Math.max` calls handle the degenerate end of
 *  the scale, where 2dp cannot express the band at all: at a $0.01 mid the
 *  floor and the ceiling collapse onto the same penny, and one legal value is
 *  the honest answer for a contract quoted at a cent. */
export function premiumStopDollarBounds(mid: number): { min: number; max: number } {
  const min = Math.max(0.01, Math.ceil(mid * PREMIUM_STOP_MIN_PCT * 100) / 100);
  const max = Math.max(min, Math.floor(mid * PREMIUM_STOP_MAX_PCT * 100) / 100);
  return { min, max };
}

/** The premium-stop fraction that applies to one position.
 *
 *  `positionPct` is `PortfolioPosition.premiumStopPct`. **Null or undefined
 *  means "inherit the global"** — a distinct, load-bearing state rather than a
 *  missing value. A position stamped with the global at creation would stop
 *  responding when the global changed, which is exactly the behaviour piece 4
 *  removes, so a position keeps tracking the global until someone sets an
 *  explicit number on it.
 *
 *  Deliberately strict: only null/undefined falls back. A value outside (0, 1)
 *  is rejected by the backend schema on every write path, so it cannot arrive
 *  here through a supported route — and silently substituting the global would
 *  hide that rather than surface it, while arming the position at a threshold
 *  nobody chose. */
export function resolvePremiumStopPct(
  positionPct: number | null | undefined,
  globalPct: number | null | undefined,
): number {
  if (positionPct == null) {
    return globalPct ?? PREMIUM_STOP_PCT_FALLBACK;
  }
  return positionPct;
}

/** True when this position carries its own premium stop rather than inheriting
 *  the global. Drives the drawer's "60% (global)" vs "45%" distinction — an
 *  inherited value that looks set is how a user comes to believe they have
 *  per-position control they do not have. */
export function hasOwnPremiumStopPct(
  positionPct: number | null | undefined,
): boolean {
  return positionPct != null;
}

/** The price at which the premium stop fires: `entry * (1 - pct)`. Shared so
 *  the drawer's preview and the backend's threshold cannot drift apart. */
export function premiumStopThresholdPrice(entryPrice: number, pct: number): number {
  return entryPrice * (1 - pct);
}

/** The largest 2-decimal price that ACTUALLY FIRES this position's premium
 *  stop -- i.e. the greatest `x` with 2dp such that `x <= entry * (1 - pct)`,
 *  which is the comparison both alert engines make at full precision.
 *
 *  Naively flooring to cents is not enough, and that is the whole reason this
 *  function exists rather than the expression it replaces. `Math.floor(t * 100)
 *  / 100` performs a SECOND floating-point operation on `t`, and `t * 100`
 *  routinely rounds UP onto the exact integer even when `t` is a hair below
 *  that cent. When it does, the floored result is strictly GREATER than `t` and
 *  fires nothing:
 *
 *      entry $4.00 at 7%  ->  t = 3.7199999999999998
 *                             t * 100 = 372 exactly, floor 372
 *                             printed "$3.72", and 3.72 <= t is FALSE
 *                             the alert actually arms at $3.71
 *
 *  Measured across every (entry, whole-cent dollar stop) pair from $1 to $14,
 *  about 3% of positions land on that case -- and a server-derived stop is
 *  `premiumStopDollar / entry_price`, so the threshold almost never lands on a
 *  whole cent to begin with. The failure is in the dangerous direction: it
 *  tells the user the stop arms one cent EARLIER than it does.
 *
 *  Preview-only, so it has no counterpart in `premium_stop.py` -- the backend
 *  renders nothing. It exists here, beside the resolver, so every preview
 *  inherits one rule: a preview that disagrees with the alert that later fires
 *  is worse than no preview. */
export function premiumStopFiringPrice(entryPrice: number, pct: number): number {
  const threshold = premiumStopThresholdPrice(entryPrice, pct);
  // ROUND to the nearest cent first, then step back only if that cent is
  // genuinely above the threshold. Flooring is wrong in BOTH directions,
  // which the sweep in premiumStop.test.ts found the moment it stopped
  // pinning single pairs: `t * 100` lands above its integer for some inputs
  // (entry $4.00 at 7% -> 372 exactly, printing $3.72 where the alert arms at
  // $3.71) and BELOW it for others (a threshold of exactly $0.57 whose
  // product is 56.99999999999999, flooring to $0.56 and naming a stop a cent
  // tighter than the real one). Rounding cannot be off by more than half a
  // cent, so one conditional step-down is always enough.
  let cents = Math.round(threshold * 100);
  if (cents / 100 > threshold) cents -= 1;
  return cents / 100;
}

/** What a send path should post as `premiumStopDollar` for one card.
 *
 *  Both send paths (`buildPaperPosition` and `positionFromOrder` in
 *  step-7-trade-card/page.tsx) call THIS, so the premium stop a position is
 *  armed at cannot depend on which button was pressed.
 *
 *  `touchedDollar` is the page-level cache for this CONTRACT, which holds a
 *  number only when the user actually edited the premium-stop field and `null`
 *  while it is untouched. TOUCHED-NESS IS TRACKED, NOT INFERRED, and that is
 *  the whole point of this signature.
 *
 *  It used to take the card's seed as a second argument and treat
 *  `cached === seed` as "untouched". `exit.premiumStop` is not a dollar amount
 *  anybody chose -- the backend computes it as
 *  `round(premium * premium_stop_pct, 2)`, i.e. the GLOBAL PERCENTAGE rendered
 *  in dollars against the card's mid -- so posting it would have the server
 *  divide it by the entry price it had just replaced with the live fill, and a
 *  $5.20 mid showing a $3.12 stop, filled at $4.00, was stored as 78%: a
 *  threshold nobody chose. Comparing values caught that, but only by
 *  coincidence, and it was wrong in BOTH directions:
 *
 *    - Untouched read as touched. The card reports its whole overlay on every
 *      `patch()`, so bumping Contracts cached the seed; a later `mergePlan`
 *      moved the seed under the untouched field, and the stale cache no longer
 *      equalled the new seed, so the old default was posted as deliberate --
 *      the card displaying $0.80 while $1.50 went to the server.
 *    - Touched read as untouched. A user who typed $2.00, changed their mind
 *      and typed the seed's own $3.12 back had their explicit choice discarded
 *      and the position handed to the global.
 *
 *  Both vanish once the caller passes the tracked flag instead of a value to
 *  compare. Sending null means "inherit the global", which is exactly what an
 *  untouched default means, and keeps the position tracking the Settings value
 *  the way the model docstring promises.
 *
 *  Non-positive and non-finite values are null for the same reason the schema
 *  rejects them (`gt=0`): `round(premium * 0.60, 2)` is `0.00` for a premium
 *  under about $0.0084, and a `?? null` would post that 0 and 422 the whole
 *  create rather than falling back. */
export function premiumStopDollarToSend(
  touchedDollar: number | null | undefined,
): number | null {
  if (touchedDollar == null || !Number.isFinite(touchedDollar) || touchedDollar <= 0) return null;
  return touchedDollar;
}

/** How the resolved percentage reads in the UI: `"45%"` when the position sets
 *  its own, `"60% (global)"` when it inherits.
 *
 *  Two decimals, trimmed, rather than `Math.round`. A server-derived stop is
 *  almost never a whole percent (`premiumStopDollar / entry_price`, e.g.
 *  `2.00 / 4.13 = 0.4843`), and rounding the LABEL while the store holds the
 *  true value is how a readout comes to disagree with the number it names:
 *  0.0019 printed a flat `0%` and 0.997 printed `100%` -- the label for a total
 *  loss -- for stops that are neither. Trimming via `Number()` keeps the common
 *  whole-percent case reading `60%`, not `60.00%`. */
export function formatPremiumStopPct(
  positionPct: number | null | undefined,
  globalPct: number | null | undefined,
): string {
  const resolved = resolvePremiumStopPct(positionPct, globalPct);
  const label = premiumStopPctLabel(resolved);
  return hasOwnPremiumStopPct(positionPct) ? label : `${label} (global)`;
}

/** The bare trimmed percentage, for callers that need it inside their own
 *  sentence rather than with the `(global)` suffix -- the Alerts page prints
 *  it as `Premium stop (-45%)`.
 *
 *  Exported so that the two-decimal rule above has ONE implementation. It was
 *  learned here and then not applied at the other render site of the same
 *  number: the Alerts page rendered the resolved stop through
 *  `Math.round(pct * 100)`, so a position pinned at 0.19% printed
 *  "Premium stop (-0%)" and one at 99.7% printed "Premium stop (-100%)", the
 *  label for a total loss, for stops that are neither -- the exact lossiness
 *  this function's own comment documents as fixed. */
export function premiumStopPctLabel(resolved: number): string {
  return `${Number((resolved * 100).toFixed(2))}%`;
}
