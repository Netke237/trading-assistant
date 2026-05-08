from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

OrderType = Literal["Limit", "Market"]
Status = Literal["PASS", "CAUTION", "REJECT"]

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _entry_cfg() -> dict:
    return _load_config()["entry_quality"]


@dataclass
class EntryConfig:
    spread_tolerance_pct: float | None = None
    max_slippage_pct: float | None = None
    min_premium: float | None = None

    def __post_init__(self) -> None:
        cfg = _entry_cfg()
        if self.spread_tolerance_pct is None:
            self.spread_tolerance_pct = cfg["spread_tolerance_pct"]
        if self.max_slippage_pct is None:
            self.max_slippage_pct = cfg["max_slippage_pct"]
        if self.min_premium is None:
            self.min_premium = cfg["min_premium"]


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

    if spread_pct > config.spread_tolerance_pct:
        if worst_status == "PASS":
            worst_status = "CAUTION"
        quality_reasons.append("elevated spread")

    return EntryAssessment(
        limit_price=limit_price,
        max_fill=max_fill,
        order_type=order_type,
        quality_status=worst_status,
        quality_reasons=quality_reasons,
    )
