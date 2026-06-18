from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class SpreadLeg:
    right: Literal["C", "P"]
    strike: float
    expiry: str
    action: Literal["BUY", "SELL"]
    qty: int
    bid: float
    ask: float


@dataclass
class Spread:
    spread_type: Literal["bear_put", "bear_call"]
    legs: list[SpreadLeg]
    net_debit_credit: float   # >0 debit (paid), <0 credit (collected)
    max_profit: float
    max_loss: float
    breakeven: float


def _nearest_by_delta(chain: list[dict], target_abs_delta: float) -> dict:
    return min(chain, key=lambda c: abs(abs(c.get("delta", 0)) - target_abs_delta))


def build_bear_put(puts: list[dict], *, expiry: str, width: float, short_delta: float) -> Spread:
    """Buy a higher-strike put, sell a put `width` lower. Debit spread."""
    short = _nearest_by_delta(puts, short_delta)
    long_strike = short["strike"] + width
    long = min(puts, key=lambda c: abs(c["strike"] - long_strike))
    debit = round(long["ask"] - short["bid"], 2)
    w = long["strike"] - short["strike"]
    return Spread(
        spread_type="bear_put",
        legs=[
            SpreadLeg("P", long["strike"], expiry, "BUY", 1, long["bid"], long["ask"]),
            SpreadLeg("P", short["strike"], expiry, "SELL", 1, short["bid"], short["ask"]),
        ],
        net_debit_credit=debit,
        max_profit=round(w - debit, 2),
        max_loss=round(debit, 2),
        breakeven=round(long["strike"] - debit, 2),
    )


def build_bear_call(calls: list[dict], *, expiry: str, width: float, short_delta: float) -> Spread:
    """Sell a lower-strike call, buy a call `width` higher. Credit spread."""
    # Bear call: sell the lower-strike call (short), buy the higher-strike call (long).
    # Find the candidate short whose delta is nearest to short_delta, requiring that a
    # higher-strike entry exists in the chain so legs are correctly ordered.
    sorted_calls = sorted(calls, key=lambda c: c["strike"])
    best_short, best_long = None, None
    best_dist = float("inf")
    for candidate_short in sorted_calls:
        long_strike = candidate_short["strike"] + width
        # Only consider calls with a strictly higher strike for the long leg
        higher_calls = [c for c in sorted_calls if c["strike"] > candidate_short["strike"]]
        if not higher_calls:
            continue
        candidate_long = min(higher_calls, key=lambda c: abs(c["strike"] - long_strike))
        dist = abs(abs(candidate_short.get("delta", 0)) - short_delta)
        if dist < best_dist:
            best_dist = dist
            best_short = candidate_short
            best_long = candidate_long
    if best_short is None or best_long is None:
        raise ValueError("Not enough strikes in chain to build a bear call spread")
    short, long = best_short, best_long
    credit = round(short["bid"] - long["ask"], 2)
    w = long["strike"] - short["strike"]
    return Spread(
        spread_type="bear_call",
        legs=[
            SpreadLeg("C", short["strike"], expiry, "SELL", 1, short["bid"], short["ask"]),
            SpreadLeg("C", long["strike"], expiry, "BUY", 1, long["bid"], long["ask"]),
        ],
        net_debit_credit=round(-credit, 2),
        max_profit=round(credit, 2),
        max_loss=round(w - credit, 2),
        breakeven=round(short["strike"] + credit, 2),
    )


def choose_primary(*, iv_rank: float, threshold: float) -> Literal["bear_call", "bear_put"]:
    """High IV -> sell premium (credit / bear call). Low IV -> buy premium (debit / bear put)."""
    return "bear_call" if iv_rank >= threshold else "bear_put"
