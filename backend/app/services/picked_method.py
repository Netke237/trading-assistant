"""Seeding `active_tp_method` / `resolved_tp_price` from a Phase G method pick.

Phase G (piece 5) records the method a trader EXPLICITLY picked for a trade, on
`PortfolioPositionModel.picked_method` and friends. That is the RECORD. This
module answers the separate question the same pick has to answer at creation:
which post-trade alert basis should the position START life on, so the TP_HIT
alert agrees with the card the trade was sent from instead of defaulting to the
ladder.

Two axes, and they can legitimately disagree:

    picked_method       the human decision. 'arithmetic' | 'monte_carlo'
                        | 'ladder' | 'barrier_race'. Displayed by the portfolio.
    active_tp_method    which computation drives TP_HIT. 'ladder' | 'monte_carlo'
                        | 'exit_plan_2r' | 'exit_plan_3r'. Never displayed as
                        the trader's choice.

THE INVARIANT THIS MODULE EXISTS TO HOLD (spec §2.7). `EditDrawer.tsx`'s
`tpMethodPatch` writes the method and its price TOGETHER, always:

    method === 'ladder' ? { activeTpMethod: 'ladder', resolvedTpPrice: null }
                        : { activeTpMethod: method,   resolvedTpPrice: price }

Both alert consumers depend on that pairing — `alertEngine.ts:171-178` and
`alert_generator.py:206-209` suppress the method label unless
`resolvedTpPrice > 0` and fall back to the ladder price. So a position carrying
a non-ladder `active_tp_method` with a NULL `resolved_tp_price` is a state the
drawer's own writer cannot produce, and it is not benign: the drawer renders
that method as selected with a null price while TP_HIT silently fires on the
ladder. A screen naming one basis while a different one fires is gate-level.
`seed_tp_from_pick` returns the PAIR, as one value, so there is no call site at
which half of it can be written.

WHY THE GATING PRECONDITION HAS NO DISCRETION IN IT. `resolved_tp_price` is
compared against the UNDERLYING quote (`alert_generator.py:181`'s
`target_stock_price`, `alertEngine.ts:152`). Only `picked_row_stock_price` is in
that space. `picked_row_option_price` is a PREMIUM and this module never reads
it — a $6.24 premium in a stock-price column makes `price >= 6.24` true on the
first tick and fires TP_HIT instantly on every bullish option position. The
parameter is not accepted here at all, which is the cheapest possible guarantee
that no future edit can route it through.
"""

from math import isclose
from typing import Any, Optional

# The pair this module returns: (active_tp_method, resolved_tp_price).
TpSeed = tuple[str, Optional[float]]

# The one safe pair. Every degraded path returns exactly this, and it is a pair
# all three consumers already agree on: the alert fires on the ladder, both
# consumers suppress the method label, and the drawer shows 'ladder'.
LADDER_SEED: TpSeed = ('ladder', None)

# `rr_ratios[i]` -> the TpMethod value for that row. POSITIONAL, because the
# ratios themselves are configurable (risk_rules.yaml -> exit_plan.target.
# rr_ratios) while these two enum values hardcode "2R" and "3R" in their names.
# A third configured ratio has no enum value and falls through to LADDER_SEED,
# which is correct: widening a persisted enum that four consumers read is a
# cascade, and Q6 says no cascade in G.
_RR_ROW_METHODS = ('exit_plan_2r', 'exit_plan_3r')

# Prices arrive as floats that have been through JSON and (for the arithmetic
# rows) a round-to-2. Match with a tolerance rather than `==`; a cent is far
# below the gap between any two R rows and far above float noise.
_PRICE_TOL = 0.005
_RATIO_TOL = 1e-9


def seed_tp_from_pick(
    picked_method: Optional[str],
    picked_row_stock_price: Optional[float],
    *,
    exit_plan: Optional[dict[str, Any]],
    rr_ratios: Optional[list[float]],
) -> TpSeed:
    """Return the `(active_tp_method, resolved_tp_price)` pair a new position
    should start life on, given the trader's pick.

    `exit_plan` is the position's persisted exit plan (`body.exitPlan`); its
    `targets` rows each carry their own `rrRatio`, which is how an arithmetic
    pick is mapped back to an R row without re-deriving it from entry and stop.
    `rr_ratios` is `risk_rules.yaml -> exit_plan.target.rr_ratios`, READ FROM
    CONFIG BY THE CALLER and never hardcoded here — change the configured list
    and the mapping moves with it.

    Every unmappable, absent or degraded input returns `LADDER_SEED`. That is a
    deliberate floor, not a swallowed error: the alert degrades to the ladder,
    which is where it fired before G, and `picked_method` still records what the
    trader actually chose. The RECORD never degrades; only the alert does.
    """
    # The gating precondition, applied BEFORE the method is looked at at all.
    # A row seeds a price only if it has one, in the right space, and positive.
    # `> 0` is re-checked here even though the schema bounds it with gt=0,
    # because this function is also reachable from paths that build the pick
    # server-side, and zero is the one value the far end cannot distinguish
    # from "unset" (`alertEngine.ts:164-169` re-checks it for the same reason).
    if not picked_method:
        return LADDER_SEED
    if picked_row_stock_price is None or picked_row_stock_price <= 0:
        # Includes EVERY barrier_race pick, by construction rather than by a
        # branch: `BarrierRaceOutcome` carries `targetOptionPrice` and no stock
        # level at all, so the race can never supply this argument. Seeding
        # 'monte_carlo' from the race's option price would have put a premium in
        # a stock-price column; seeding 'monte_carlo' with NULL would have
        # produced the forbidden state above. It is also the everyday Monte
        # Carlo case: `FirstPassageTarget.stockPrice` is documented "display-only
        # Stage-1 approximation; null if unreachable", so a NULL here is
        # reachable on any ordinary card and is not a defensive branch.
        return LADDER_SEED

    if picked_method == 'ladder':
        # The ladder tracks its target LIVE. A snapshot would go stale the
        # moment the user edits the targets in the drawer, so the ladder is the
        # one method that deliberately stores no price.
        return LADDER_SEED

    if picked_method == 'monte_carlo':
        return ('monte_carlo', picked_row_stock_price)

    if picked_method == 'arithmetic':
        rr = _rr_ratio_for_row(exit_plan, picked_row_stock_price)
        if rr is None:
            return LADDER_SEED
        return _seed_for_rr(rr, rr_ratios, picked_row_stock_price)

    # 'barrier_race' reaches here only if it somehow carried a stock price, and
    # an unknown string reaches here from a client ahead of this backend. Both
    # degrade rather than guess.
    return LADDER_SEED


def _rr_ratio_for_row(
    exit_plan: Optional[dict[str, Any]],
    picked_row_stock_price: float,
) -> Optional[float]:
    """Find the R multiple of the exit-plan row the trader picked.

    The pick carries a PRICE, not a row index, because a price survives an
    `rr_ratios` change and an index does not. The persisted exit plan's rows
    carry both (`ExitPlanTargetRowOut.rrRatio` / `.price`), so the price is
    matched back to its own row and that row's own ratio is returned — rather
    than re-deriving R from entry and stop, which is not available in the same
    space for an option position (whose `entry_price` is a PREMIUM).

    Returns None when there is no plan, no rows, or no row at that price — all
    of which are "unmappable" and degrade to the ladder upstream.
    """
    if not isinstance(exit_plan, dict):
        return None
    rows = exit_plan.get('targets')
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = row.get('price')
        ratio = row.get('rrRatio')
        if not isinstance(price, (int, float)) or not isinstance(ratio, (int, float)):
            continue
        if isinstance(price, bool) or isinstance(ratio, bool):
            continue
        if isclose(float(price), picked_row_stock_price, abs_tol=_PRICE_TOL):
            return float(ratio)
    return None


def _seed_for_rr(
    rr: float,
    rr_ratios: Optional[list[float]],
    picked_row_stock_price: float,
) -> TpSeed:
    """Map one R multiple onto its TpMethod value, POSITIONALLY, against the
    configured `rr_ratios`.

    Never hardcodes 2.0 / 3.0. With `rr_ratios: [1.5, 4.0]` a 1.5R pick is the
    FIRST configured row and maps to `exit_plan_2r`; a 2.0R pick is not a
    configured row at all and degrades to the ladder. Reading the enum names as
    literal multiples is the mistake this indirection exists to prevent —
    they are row ORDINALS whose names predate the ratios being configurable.
    """
    if not rr_ratios:
        return LADDER_SEED
    for index, configured in enumerate(rr_ratios[:len(_RR_ROW_METHODS)]):
        if not isinstance(configured, (int, float)) or isinstance(configured, bool):
            continue
        if isclose(float(configured), rr, rel_tol=_RATIO_TOL, abs_tol=_RATIO_TOL):
            return (_RR_ROW_METHODS[index], picked_row_stock_price)
    return LADDER_SEED
