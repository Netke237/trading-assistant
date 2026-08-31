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

    structural_target = find_structural_target(candles, direction, entry_price)
    tolerance_dollar = max(snap_atr_multiplier, 0.0) * max(atr, 0.0)
    distance_dollar = abs(structural_target.price - arithmetic_price) if structural_target is not None else None

    tp_source: TpSource = "arithmetic"
    price = arithmetic_price
    if distance_dollar is not None and distance_dollar <= tolerance_dollar:
        tp_source = "structural_snap"
        price = structural_target.price

    quality_reasons: list[str] = []
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
