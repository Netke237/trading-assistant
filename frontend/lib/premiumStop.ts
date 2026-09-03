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
