"""Exit-plan pipeline orchestration.

Composes existing, already-verified building blocks — structural_stop.py's
order-block/swing detection, first_passage.py's Monte Carlo engine, and
reward_risk.py's option repricing chain — into one coherent stop/target
recommendation. See docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md
("The exit-plan algorithm") for the full spec this module implements.

Nothing here duplicates structure detection, GBM simulation, or option
pricing — this module only decides WHICH existing result to use and how to
combine them (final stop = wider of structural/ATR-floor; target = arithmetic
RR multiple, optionally snapped to a real structural level ahead of entry).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from app.scoring.structural_stop import StructuralStop, find_structural_stop, find_structural_target

BEARISH_MIN_TARGET_FRACTION = 0.10

StopSource = Literal["structural", "atr_widened"]
TpSource = Literal["arithmetic", "structural_snap"]


@dataclass
class FinalStopResult:
    price: float
    source: StopSource
    structural: Optional[StructuralStop]   # the raw structural lookup, whether or not it decided the price
    atr_floor_price: float                 # the ATR-floor price, whether or not it decided the final price


def compute_final_stop(
    candles: list[dict],
    direction: Literal["Bullish", "Bearish"],
    entry_price: float,
    atr: float,
    atr_multiplier: float,
) -> FinalStopResult:
    """Algorithm step 1: final stop = the wider of the structural stop and an
    ATR floor. "Wider" means further from entry_price in the invalidating
    direction. A structural level that already clears the floor unassisted
    is used as-is (source="structural" — a real technical level that also
    happens to have enough breathing room); a tighter one, or no structural
    level at all, is widened out to the floor (source="atr_widened").
    """
    is_bullish = direction == "Bullish"
    atr_floor_distance = max(atr_multiplier, 0.0) * max(atr, 0.0)
    atr_floor_price = entry_price - atr_floor_distance if is_bullish else entry_price + atr_floor_distance

    structural = find_structural_stop(candles, direction, entry_price)
    if structural is not None:
        structural_distance = abs(entry_price - structural.price)
        if structural_distance >= atr_floor_distance:
            return FinalStopResult(
                price=structural.price, source="structural", structural=structural,
                atr_floor_price=atr_floor_price,
            )

    return FinalStopResult(
        price=atr_floor_price, source="atr_widened", structural=structural,
        atr_floor_price=atr_floor_price,
    )


StockStopSource = Literal["final_stop", "flat_fallback"]


@dataclass
class StockStopResult:
    """The stock stop a trade card is built around (piece 3).

    `price` is the number that becomes `TradeExit.invalidation` — the level the
    Exit Plan's Invalidation field seeds from, the level `buildPaperPosition`
    stores as `PortfolioPosition.stop`, and the last-resort barrier the Monte
    Carlo card measures against. Before piece 3 it was a flat percentage move
    off the stock price (risk_rules.yaml's `bullish_invalidation_pct`), which
    measured the same distance on every symbol in the universe regardless of
    where its structure actually sits.
    """
    price: float                            # unrounded; round at the display boundary
    source: StockStopSource
    final_stop: Optional[FinalStopResult]   # None on the flat_fallback path only
    atr: float                              # the ATR(14) the floor was built on; 0.0 on the fallback path


def resolve_stock_stop(
    candles: list[dict],
    direction: Literal["Bullish", "Bearish"],
    entry_price: float,
    atr: float,
    atr_multiplier: float,
    flat_fallback_pct: float,
) -> StockStopResult:
    """Resolve the stock stop for one candidate: the structural+ATR final stop
    whenever the bar feed can form one, else a flat percentage move.

    THE FALLBACK IS THE DEGENERATE PATH, NOT A CO-EQUAL BRANCH. `atr <= 0` means
    `_atr` could not form even one true range — fewer than two bars, or a stale
    feed repeating one bar — and `compute_final_stop` on such a feed hands back
    an ATR floor sitting exactly ON `entry_price`, i.e. a zero-width stop that
    every downstream consumer would read as a real level. That is the same guard,
    for the same reason, as `/contracts/exit-plan`'s 422 and the scan-time gate's
    `if _scan_atr > 0`. Any candidate that scored at all has hundreds of bars, so
    in production this returns `final_stop` essentially always.

    `flat_fallback_pct` is Step 3's "Bullish stop %" / "Bearish stop %"
    execution parameter (risk_rules.yaml `reward_risk.bullish_invalidation_pct`
    / `bearish_invalidation_pct`, per-request overridable). Deciding WHICH stop
    applies lives here, with the candles, and deliberately NOT inside
    `build_trade_plan` — that module does contract arithmetic and has never had
    a bar feed to judge structure with.
    """
    is_bullish = direction == "Bullish"

    if atr > 0:
        final = compute_final_stop(candles, direction, entry_price, atr, atr_multiplier)
        # A bullish ATR floor can be driven negative by a wide multiplier on a
        # low-priced name (entry 3.00, ATR 2.00, multiplier 2.0 -> -1.00). Floor
        # it at a cent, matching what the flat branch below has always done —
        # a stop at or below zero is not a level, and `estimate_stock_first_passage`
        # treats `invalidation_price > 0` as the switch for pricing the stop leg
        # at all.
        return StockStopResult(
            price=max(final.price, 0.01) if is_bullish else final.price,
            source="final_stop", final_stop=final, atr=atr,
        )

    pct = max(float(flat_fallback_pct), 0.0)
    flat = (
        max(entry_price * (1 - pct), 0.01) if is_bullish
        else entry_price * (1 + pct)
    )
    return StockStopResult(price=flat, source="flat_fallback", final_stop=None, atr=0.0)


def final_stop_out(stock_stop: Optional[StockStopResult], computed_at: str):
    """Render a resolved stop as the wire block piece 3 puts on `TradeExit`.

    ONE builder, used by both the scan and /contracts/recompute-plan, because
    `mergePlan` on the client replaces `exit` wholesale: if the two endpoints
    emitted different shapes for the same stop, a Step 6 contract override
    would silently change what the "Bottom (final stop)" row reads.

    Returns None -- "not computed" -- for a stop the structural/ATR model did
    not actually choose. On the flat-percentage fallback there is no structural
    level and no ATR floor to report, and a block full of nulls would read on
    the card as "we looked and found nothing" rather than "we could not look at
    all". Same for a resolution that raised (`stock_stop is None`).
    """
    from app.schemas import FinalStopOut

    if stock_stop is None or stock_stop.final_stop is None:
        return None

    fs = stock_stop.final_stop
    structural_price = round(fs.structural.price, 2) if fs.structural else None
    atr_floor_price = round(fs.atr_floor_price, 2)
    return FinalStopOut(
        # Rounded to match `TradeExit.invalidation` exactly -- the provenance
        # row and the Invalidation field must print the same number.
        price=round(stock_stop.price, 2),
        source=stock_stop.source,
        stopSource=fs.source,
        structuralSource=fs.structural.source if fs.structural else None,
        structuralPrice=structural_price,
        atrFloorPrice=atr_floor_price,
        distanceDollar=(
            round(abs(structural_price - atr_floor_price), 2)
            if structural_price is not None else None
        ),
        atr=round(stock_stop.atr, 4),
        computedAt=computed_at,
    )


@dataclass
class TargetRowResult:
    rr_ratio: float
    arithmetic_price: float
    price: float                          # the price actually used — arithmetic, or snapped
    tp_source: TpSource
    structural: Optional[StructuralStop]  # nearest real level ahead of entry, if any (regardless of snap)
    distance_dollar: Optional[float]      # |structural.price - arithmetic_price|; None when no structural candidate
    tolerance_dollar: float               # snap_atr_multiplier * atr — the snap band, always computable
    quality_good: bool
    quality_reasons: list[str]


def compute_target_row(
    candles: list[dict],
    direction: Literal["Bullish", "Bearish"],
    entry_price: float,
    final_stop: FinalStopResult,
    atr: float,
    rr_ratio: float,
    snap_atr_multiplier: float,
) -> TargetRowResult:
    """Algorithm steps 2 and 4 (composite quality flag) for one R:R ratio.

    arithmetic_tp = entry +/- rr_ratio * final_stop_distance. If a real
    structural level ahead of entry falls within snap_atr_multiplier * ATR of
    that arithmetic price, the row snaps to it (tp_source="structural_snap");
    otherwise the arithmetic price stands (tp_source="arithmetic").

    Quality is good when final_stop didn't need ATR-widening AND the target
    sits at-or-before the next real structural level in the trade's
    direction (trivially true on a snap; vacuously true when no structural
    level exists ahead to overshoot).
    """
    is_bullish = direction == "Bullish"
    final_stop_distance = abs(entry_price - final_stop.price)
    arithmetic_price = (
        entry_price + rr_ratio * final_stop_distance if is_bullish
        else entry_price - rr_ratio * final_stop_distance
    )

    target_floor = entry_price * BEARISH_MIN_TARGET_FRACTION
    target_capped = not is_bullish and arithmetic_price < target_floor
    if target_capped:
        arithmetic_price = target_floor

    structural_target = find_structural_target(candles, direction, entry_price)
    tolerance_dollar = max(snap_atr_multiplier, 0.0) * max(atr, 0.0)
    distance_dollar = abs(structural_target.price - arithmetic_price) if structural_target is not None else None

    tp_source: TpSource = "arithmetic"
    price = arithmetic_price
    snap_eligible = distance_dollar is not None and distance_dollar <= tolerance_dollar
    snap_below_floor = snap_eligible and not is_bullish and structural_target.price < target_floor
    if snap_below_floor:
        target_capped = True
    if snap_eligible and not snap_below_floor:
        tp_source = "structural_snap"
        price = structural_target.price

    quality_reasons: list[str] = []
    if target_capped:
        quality_reasons.append("target_capped")
    if final_stop.source != "structural":
        quality_reasons.append("stop_widened")

    tp_at_or_before_structural = (
        tp_source == "structural_snap"
        or structural_target is None
        or (is_bullish and arithmetic_price <= structural_target.price)
        or (not is_bullish and arithmetic_price >= structural_target.price)
    )
    if not tp_at_or_before_structural:
        quality_reasons.append("target_beyond_structural")

    return TargetRowResult(
        rr_ratio=rr_ratio,
        arithmetic_price=arithmetic_price,
        price=price,
        tp_source=tp_source,
        structural=structural_target,
        distance_dollar=distance_dollar,
        tolerance_dollar=tolerance_dollar,
        quality_good=not quality_reasons,
        quality_reasons=quality_reasons,
    )


def resolve_t1_target(candles, direction, entry_price, stock_stop, stop_price,
                      r_multiple, snap_atr_multiplier):
    """Resolve the first stock target; trade_plan bounds its ladder extension."""
    if stock_stop is not None and stock_stop.source == "final_stop":
        row = compute_target_row(candles, direction, entry_price, stock_stop.final_stop,
                                 stock_stop.atr, r_multiple, snap_atr_multiplier)
        return row.price, row.tp_source
    sign = 1 if direction == "Bullish" else -1
    return entry_price + sign * r_multiple * abs(entry_price - stop_price), "flat_fallback"
