from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional


@dataclass
class PortfolioPosition:
    symbol: str
    contract_id: str
    contracts: int
    entry_premium: float
    current_price: float
    capital_at_risk: float


@dataclass
class RiskCheckResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    adjusted_size: Optional[int] = None
    portfolio_exposure_pct: float = 0.0


CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def check_position_risk(
    symbol: str,
    contract_id: str,
    proposed_contracts: int,
    entry_premium: float,
    current_price: float,
    portfolio: list[PortfolioPosition],
    portfolio_value: float,
    daily_recommendation_count: int = 0,
) -> RiskCheckResult:
    cfg = _load_config()
    rules = cfg["portfolio"]
    sizing = cfg["sizing"]
    reasons = []
    adjusted_size: Optional[int] = None

    if portfolio_value < rules["min_portfolio_value"]:
        return RiskCheckResult(
            approved=False,
            reasons=["portfolio_too_small"],
            portfolio_exposure_pct=0.0,
        )

    proposed_contracts = min(proposed_contracts, sizing["max_contracts_per_trade"])

    if daily_recommendation_count >= rules["max_daily_recommendations"]:
        return RiskCheckResult(
            approved=False,
            reasons=["daily_recommendation_limit_reached"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    if len(portfolio) >= rules["max_concurrent_positions"]:
        return RiskCheckResult(
            approved=False,
            reasons=["max_concurrent_positions_reached"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    existing_symbols = [p.symbol for p in portfolio]
    if symbol in existing_symbols and rules["max_same_symbol_positions"] <= 1:
        return RiskCheckResult(
            approved=False,
            reasons=["duplicate_symbol_already_open"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    is_stock = contract_id.endswith("|STOCK")
    multiplier = 1 if is_stock else 100
    capital_at_risk = entry_premium * proposed_contracts * multiplier
    single_exposure_pct = capital_at_risk / portfolio_value
    max_single = rules["max_single_trade_exposure_pct"]

    if single_exposure_pct > max_single:
        max_allowed_premium = portfolio_value * max_single
        adjusted = int(max_allowed_premium / (entry_premium * multiplier))
        if adjusted >= 1:
            adjusted_size = adjusted
            capital_at_risk = entry_premium * adjusted_size * multiplier
            single_exposure_pct = capital_at_risk / portfolio_value
            reasons.append("size_reduced_to_fit_exposure_limit")
        else:
            reasons.append("single_trade_exposure_too_high")

    current_exposure = _current_exposure_abs(portfolio)
    total_exposure_pct = (current_exposure + capital_at_risk) / portfolio_value
    max_total = rules["max_total_exposure_pct"]

    if total_exposure_pct > max_total:
        reasons.append("total_exposure_limit_reached")

    if reasons:
        return RiskCheckResult(
            approved=False,
            reasons=reasons,
            adjusted_size=adjusted_size,
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
        )

    return RiskCheckResult(
        approved=True,
        reasons=[],
        adjusted_size=adjusted_size,
        portfolio_exposure_pct=round(total_exposure_pct * 100, 2),
    )


def _current_exposure_abs(portfolio: list[PortfolioPosition]) -> float:
    return sum(p.capital_at_risk for p in portfolio)


def _current_exposure(portfolio: list[PortfolioPosition], portfolio_value: float) -> float:
    if portfolio_value <= 0:
        return 0.0
    return round(_current_exposure_abs(portfolio) / portfolio_value * 100, 2)


def orm_positions_to_risk(orm_positions) -> list[PortfolioPosition]:
    """Convert ORM portfolio rows to PortfolioPosition dataclasses for risk checks."""
    result = []
    for p in orm_positions:
        qty = int(getattr(p, "qty", 0) or 0)
        if qty <= 0:
            continue
        is_stock = str(getattr(p, "contract", "")).endswith("|STOCK")
        multiplier = 1 if is_stock else 100
        entry = float(getattr(p, "entry_price", 0) or 0)
        car = entry * qty * multiplier
        result.append(PortfolioPosition(
            symbol=str(getattr(p, "symbol", "")),
            contract_id=str(getattr(p, "contract", "")),
            contracts=qty,
            entry_premium=entry,
            current_price=entry,
            capital_at_risk=car,
        ))
    return result
