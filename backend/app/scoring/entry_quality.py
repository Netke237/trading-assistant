from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EntryConfig:
    pass


@dataclass
class EntryResult:
    limit_price: float
    max_fill: float
    order_type: str
    quality_status: str


def assess_entry(bid: float, ask: float, mid: float) -> EntryResult:
    """
    Assess entry quality for an option contract.
    Returns a suggested limit price, max fill, order type, and quality status.
    """
    spread = ask - bid
    limit = round(bid + spread * 0.2, 2)
    max_fill = round(ask + spread * 0.5, 2)
    return EntryResult(
        limit_price=limit,
        max_fill=max_fill,
        order_type="Limit",
        quality_status="PASS",
    )
