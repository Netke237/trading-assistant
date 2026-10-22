from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from app.services.config_health import config_health

OrderType = Literal["Limit", "Market"]
Status = Literal["PASS", "CAUTION", "REJECT"]

# NO-LIVE-QUOTE (plan 3e): the entry reason when the quote is not live.
NO_LIVE_QUOTE_REASON = "no live quote — entry priced off the last close"

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="scoring_rules.yaml",
    loader="entry_quality._load_config",
    fn=_load_config,
    project=lambda doc: doc,
)


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
    quote_live: bool | None = None,
) -> EntryAssessment:
    """Grade the entry off bid/ask/mid.

    quote_live (NO-LIVE-QUOTE plan 3e): False means bid/ask/mid are not a live
    quote (Step 7's live quote failed or came back not live), so the entry is
    at best CAUTION with the reason NO_LIVE_QUOTE_REASON. None (every caller
    that does not say) and True leave the grade as before.
    """
    if config is None:
        config = EntryConfig()

    limit_price = round(mid, 2)
    max_fill = round(mid * (1 + config.max_slippage_pct), 2)
    order_type: OrderType = "Limit"

    quality_reasons: list[str] = []
    worst_status: Status = "PASS"

    if bid > ask:
        quality_reasons.append("crossed quote")
        worst_status = "REJECT"

    spread_pct = round((ask - bid) / mid, 10) if mid > 0 else 1.0

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

    if quote_live is False:
        if worst_status == "PASS":
            worst_status = "CAUTION"
        quality_reasons.append(NO_LIVE_QUOTE_REASON)

    return EntryAssessment(
        limit_price=limit_price,
        max_fill=max_fill,
        order_type=order_type,
        quality_status=worst_status,
        quality_reasons=quality_reasons,
    )
