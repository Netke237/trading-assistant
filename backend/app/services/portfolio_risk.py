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
    # P1a: the quantity the caps were judged at. Equal to the ordered quantity
    # for an option; for a |STOCK row it is the deferred clamp's value (see the
    # stock branch below). None only on the `portfolio_too_small` return, which
    # comes before anything is judged.
    judged_size: Optional[int] = None
    # P1a: the per-trade contract cap this check read, so a caller can word a
    # refusal without a config read of its own.
    max_contracts: Optional[int] = None


# Q18 / P1-CLAMP-AT-SOURCE-2026-09-25: an OPTION quantity above
# `sizing.max_contracts_per_trade` is REFUSED with this reason (a hard reason),
# for every caller -- card POST, drawer PATCH, auto-trade fire check.
EXCEEDS_MAX_CONTRACTS = "exceeds_max_contracts_per_trade"


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
    max_per_trade = sizing["max_contracts_per_trade"]

    if portfolio_value < rules["min_portfolio_value"]:
        return RiskCheckResult(
            approved=False,
            reasons=["portfolio_too_small"],
            portfolio_exposure_pct=0.0,
            max_contracts=max_per_trade,
        )

    # REFUSE, DON'T CLAMP (Q18 at the source). This line used to be an
    # unconditional `min(proposed_contracts, max_contracts_per_trade)`: a 10-lot
    # was judged as 5 and then booked as 10 (card POST), set to 10 (drawer
    # PATCH) or fired as 10 (auto-trader). An option quantity above the cap is
    # now a hard reason, and every cap below is judged at the REAL quantity.
    if contract_id.endswith("|STOCK"):
        # DEFERRED by P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25: the stock
        # send paths place the broker order BEFORE saving, so judging real share
        # counts now would refuse the books after a full-size order. Phase
        # STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES removes this clamp.
        proposed_contracts = min(proposed_contracts, max_per_trade)
    elif proposed_contracts > max_per_trade:
        reasons.append(EXCEEDS_MAX_CONTRACTS)
    judged_size = proposed_contracts

    if daily_recommendation_count >= rules["max_daily_recommendations"]:
        return RiskCheckResult(
            approved=False,
            reasons=["daily_recommendation_limit_reached"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
            judged_size=judged_size,
            max_contracts=max_per_trade,
        )

    if len(portfolio) >= rules["max_concurrent_positions"]:
        return RiskCheckResult(
            approved=False,
            reasons=["max_concurrent_positions_reached"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
            judged_size=judged_size,
            max_contracts=max_per_trade,
        )

    existing_symbols = [p.symbol for p in portfolio]
    if symbol in existing_symbols and rules["max_same_symbol_positions"] <= 1:
        return RiskCheckResult(
            approved=False,
            reasons=["duplicate_symbol_already_open"],
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
            judged_size=judged_size,
            max_contracts=max_per_trade,
        )

    is_stock = contract_id.endswith("|STOCK")
    multiplier = 1 if is_stock else 100
    capital_at_risk = entry_premium * proposed_contracts * multiplier
    single_exposure_pct = capital_at_risk / portfolio_value
    max_single = rules["max_single_position_pct"]

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
        # "size_reduced_to_fit_exposure_limit" is the one soft/informational
        # reason — the trade CAN proceed at adjusted_size. Every other reason
        # is a hard block. Without this split, a trade that fits fine at a
        # smaller size was rejected outright, identical to one with no valid
        # smaller size at all — adjusted_size was computed but never usable.
        hard_reasons = [r for r in reasons if r != "size_reduced_to_fit_exposure_limit"]
        return RiskCheckResult(
            approved=not hard_reasons,
            reasons=reasons,
            adjusted_size=adjusted_size,
            portfolio_exposure_pct=_current_exposure(portfolio, portfolio_value),
            judged_size=judged_size,
            max_contracts=max_per_trade,
        )

    return RiskCheckResult(
        approved=True,
        reasons=[],
        adjusted_size=adjusted_size,
        portfolio_exposure_pct=round(total_exposure_pct * 100, 2),
        judged_size=judged_size,
        max_contracts=max_per_trade,
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
