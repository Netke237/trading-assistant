"""Structural (support/resistance/order-block) invalidation lookup.

Self-contained, on-demand companion to the premium-based invalidation in
trade_plan.py. Reuses the existing structure detectors in
app.services.market_structure — no FVG/BOS/OB logic is duplicated here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.market_structure import detect_bos_choch, detect_order_blocks, find_swings

StructuralSource = Literal["order_block", "swing_low", "swing_high"]

_SWING_FALLBACK_CONFIDENCE = 60


@dataclass
class StructuralStop:
    price: float
    source: StructuralSource
    confidence: int
    distance_pct: float


def find_structural_stop(
    candles: list[dict],
    direction: Literal["Bullish", "Bearish"],
    reference_price: float,
) -> StructuralStop | None:
    """Find the nearest structural invalidation level relative to reference_price.

    Bullish (call): nearest unmitigated bullish Order Block below reference_price
    (its price_low), falling back to the nearest swing low below it.
    Bearish (put): nearest unmitigated bearish Order Block above reference_price
    (its price_high), falling back to the nearest swing high above it.
    """
    if len(candles) < 10:
        return None

    is_bullish = direction == "Bullish"
    bos_signals = detect_bos_choch(candles)
    order_blocks = detect_order_blocks(candles, bos_signals)

    ob_direction = "bullish" if is_bullish else "bearish"
    candidates = [
        ob for ob in order_blocks
        if ob["direction"] == ob_direction and not ob["mitigated"]
    ]

    if is_bullish:
        below = [ob for ob in candidates if ob["price_low"] < reference_price]
        if below:
            best = max(below, key=lambda ob: ob["price_low"])
            price = best["price_low"]
            return StructuralStop(
                price=price,
                source="order_block",
                confidence=best["confidence"],
                distance_pct=abs(reference_price - price) / reference_price * 100,
            )
    else:
        above = [ob for ob in candidates if ob["price_high"] > reference_price]
        if above:
            best = min(above, key=lambda ob: ob["price_high"])
            price = best["price_high"]
            return StructuralStop(
                price=price,
                source="order_block",
                confidence=best["confidence"],
                distance_pct=abs(reference_price - price) / reference_price * 100,
            )

    swing_highs, swing_lows = find_swings(candles)
    if is_bullish:
        below_lows = [s["price"] for s in swing_lows if s["price"] < reference_price]
        if not below_lows:
            return None
        price = max(below_lows)
        source: StructuralSource = "swing_low"
    else:
        above_highs = [s["price"] for s in swing_highs if s["price"] > reference_price]
        if not above_highs:
            return None
        price = min(above_highs)
        source = "swing_high"

    return StructuralStop(
        price=price,
        source=source,
        confidence=_SWING_FALLBACK_CONFIDENCE,
        distance_pct=abs(reference_price - price) / reference_price * 100,
    )
