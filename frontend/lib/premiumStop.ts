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
 *  `cachedDollar` is what the card's overlay last reported for this CONTRACT;
 *  `seededDollar` is that card's own `exit.premiumStop`, the value the overlay
 *  was seeded with.
 *
 *  THE SEEDED VALUE MUST NOT BE SENT, and this is the whole reason the
 *  function exists. `exit.premiumStop` is not a dollar amount anybody chose --
 *  the backend computes it as `round(premium * premium_stop_pct, 2)`, i.e. the
 *  GLOBAL PERCENTAGE rendered in dollars against the card's mid. The card
 *  reports its overlay on every `patch()`, so editing Contracts or a target
 *  cached that untouched default, and the server then divided it by the
 *  entry price it had just replaced with the live fill. A $5.20 mid showing a
 *  $3.12 stop, filled at $4.00, was stored as 78% -- a threshold nobody chose,
 *  reached only by editing an unrelated field. Sending null instead means
 *  "inherit the global", which is exactly what an untouched default means, and
 *  keeps the position tracking the Settings value the way the model docstring
 *  promises.
 *
 *  Non-positive and non-finite values are null for the same reason the schema
 *  rejects them (`gt=0`): `round(premium * 0.60, 2)` is `0.00` for a premium
 *  under about $0.0084, and a `?? null` would post that 0 and 422 the whole
 *  create rather than falling back. */
export function premiumStopDollarToSend(
  cachedDollar: number | null | undefined,
  seededDollar: number | null | undefined,
): number | null {
  if (cachedDollar == null || !Number.isFinite(cachedDollar) || cachedDollar <= 0) return null;
  if (seededDollar != null && cachedDollar === seededDollar) return null;
  return cachedDollar;
}

/** How the resolved percentage reads in the UI: `"45%"` when the position sets
 *  its own, `"60% (global)"` when it inherits. */
export function formatPremiumStopPct(
  positionPct: number | null | undefined,
  globalPct: number | null | undefined,
): string {
  const resolved = resolvePremiumStopPct(positionPct, globalPct);
  const label = `${Math.round(resolved * 100)}%`;
  return hasOwnPremiumStopPct(positionPct) ? label : `${label} (global)`;
}
