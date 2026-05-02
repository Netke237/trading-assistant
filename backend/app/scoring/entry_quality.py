from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OrderType = Literal["Limit", "Market"]
Status = Literal["PASS", "CAUTION", "REJECT"]


@dataclass
class EntryConfig:
    spread_tolerance_pct: float = 0.10
    max_slippage_pct: float = 0.03
    min_premium: float = 0.10


@dataclass
class EntryAssessment:
    limit_price: float
    max_fill: float
    order_type: OrderType
    quality_status: Status
    quality_reasons: list[str] = field(default_factory=list)


def assess_entry(
    bid: float,
    ask: float,
    mid: float,
    config: EntryConfig | None = None,
) -> EntryAssessment:
    if config is None:
        config = EntryConfig()

    spread_pct = round((ask - bid) / mid, 10) if mid > 0 else 1.0

    limit_price = round(mid, 2)
    max_fill = round(mid * (1 + config.max_slippage_pct), 2)
    order_type: OrderType = "Limit"

    quality_reasons: list[str] = []
    worst_status: Status = "PASS"

    if mid < config.min_premium:
        quality_reasons.append("premium too low")
        worst_status = "REJECT"

    if spread_pct > config.spread_tolerance_pct * 3:
        quality_reasons.append("wide spread")
        worst_status = "REJECT"
    elif spread_pct > config.spread_tolerance_pct:
        quality_reasons.append("elevated spread")
        if worst_status != "REJECT":
            worst_status = "CAUTION"

    return EntryAssessment(
        limit_price=limit_price,
        max_fill=max_fill,
        order_type=order_type,
        quality_status=worst_status,
        quality_reasons=quality_reasons,
    )