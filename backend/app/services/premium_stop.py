"""Per-position premium stop resolution (piece 4).

Before this module there were three global premium-stop percentages and no
per-position field at all:

    risk_rules.yaml -> reward_risk.premium_stop_pct   (alerts, trade plan)
    risk_rules.yaml -> auto_trade.premium_stop_pct    (auto-trader daily-loss gate;
                                                       NOT READ since A6, which
                                                       counts the full premium)
    settingsStore.premiumStopPct                      (frontend alert engine)

Every open position shared one number, so changing it silently re-armed every
position at once and a conviction trade could not be given more room than a
speculative one.

`PortfolioPositionModel.premium_stop_pct` is the per-position override, and
this module is the ONE place that decides what a position's effective
percentage is. Every read site calls `resolve_premium_stop_pct` — the alert
generator and (via its TypeScript twin in
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


# ── STOP-SEMANTICS-2026-10-02 ────────────────────────────────────────────────
# Twins of `frontend/lib/premiumStop.ts`'s helpers of the same names. The short
# flag is a REQUIRED positional argument everywhere (no default), so no call
# site can apply the long rule to a short by omission.

STOP_SIDE_SHORT_STOCK = 'short-stock'
STOP_SIDE_LONG_STOCK = 'long-stock'
STOP_SIDE_OPTION = 'option'


def is_short_stock_position(contract: Optional[str], direction: Optional[str]) -> bool:
    """A Bearish `|STOCK` position is a short: every stock send path opens it
    with a SELL. A Bearish OPTION is a long put and is NOT a short.

    Case-sensitive, exactly what the engines test (`contract.endswith('|STOCK')`
    and `direction == 'Bearish'`)."""
    return bool(contract) and contract.endswith('|STOCK') and direction == 'Bearish'


def premium_stop_side(contract: Optional[str], direction: Optional[str]) -> str:
    """The rule a PREMIUM_STOP fires under, stamped on the alert at fire time."""
    if is_short_stock_position(contract, direction):
        return STOP_SIDE_SHORT_STOCK
    if contract and contract.endswith('|STOCK'):
        return STOP_SIDE_LONG_STOCK
    return STOP_SIDE_OPTION


def percent_stop_threshold_price(entry_price: float, pct: float, short_stock: bool) -> float:
    """Direction-aware percent-stop threshold: a short stock's stop is
    `entry * (1 + pct)` (it fires on a RISE), everything else keeps
    `entry * (1 - pct)` via `premium_stop_threshold_price`."""
    if short_stock:
        return entry_price * (1 + pct)
    return premium_stop_threshold_price(entry_price, pct)


def premium_stop_is_sub_cent(entry_price: float, pct: float, short_stock: bool) -> bool:
    """True when a long stop's threshold is below the lowest live quote, $0.01,
    so it can never fire. This IS the engines' own comparison at price $0.01
    (`0.01 <= entry * (1 - pct)`), with no epsilon. A short stop fires on a
    rise and is never sub-cent."""
    if short_stock:
        return False
    return entry_price > 0 and not (0.01 <= entry_price * (1 - pct))
