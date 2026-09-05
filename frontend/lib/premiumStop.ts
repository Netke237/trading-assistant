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
