"""Per-position premium stop resolution (piece 4).

Before this module there were three global premium-stop percentages and no
per-position field at all:

    risk_rules.yaml -> reward_risk.premium_stop_pct   (alerts, trade plan)
    risk_rules.yaml -> auto_trade.premium_stop_pct    (auto-trader sizing)
    settingsStore.premiumStopPct                      (frontend alert engine)

Every open position shared one number, so changing it silently re-armed every
position at once and a conviction trade could not be given more room than a
speculative one.

`PortfolioPositionModel.premium_stop_pct` is the per-position override, and
this module is the ONE place that decides what a position's effective
percentage is. Every read site calls `resolve_premium_stop_pct` — the alert
generator, the auto-trader, and (via its TypeScript twin in
`frontend/lib/premiumStop.ts`) the frontend alert engine and the portfolio
drawer's preview. A preview that disagrees with the alert that later fires is
worse than no preview, so they must not each roll their own resolution.
"""

from typing import Optional

# Last-resort value, used only when the caller could not load a global from
# risk_rules.yaml at all. Mirrors `reward_risk.premium_stop_pct` and
# `auto_trade.premium_stop_pct`, both of which ship as 0.60.
PREMIUM_STOP_PCT_FALLBACK = 0.60


def resolve_premium_stop_pct(
    position_pct: Optional[float],
    global_pct: Optional[float],
) -> float:
    """Return the premium-stop fraction that applies to one position.

    `position_pct` is `PortfolioPositionModel.premium_stop_pct`. **NULL means
    "inherit the global"**, and that is a distinct, load-bearing state — not a
    missing value to be backfilled. A position stamped with the global's value
    at creation would stop responding when the global changed, which is
    precisely the behaviour piece 4 removes. So a position keeps tracking the
    global until someone sets an explicit number on it.

    Deliberately strict: only `None` falls back. A stored value outside
    (0, 1) is rejected at the schema on every write path, so it cannot arrive
    here through a supported route — and silently substituting the global for
    an out-of-range value would hide the corruption rather than surface it,
    while quietly arming the position at a threshold nobody chose.
    """
    if position_pct is None:
        return float(global_pct) if global_pct is not None else PREMIUM_STOP_PCT_FALLBACK
    return float(position_pct)


def premium_stop_threshold_price(entry_price: float, pct: float) -> float:
    """The price at which the premium stop fires: `entry * (1 - pct)`.

    Shared so the alert's comparison, the threshold it reports, and the
    drawer's "fires at" preview cannot drift apart by rounding differently.
    """
    return entry_price * (1 - pct)
