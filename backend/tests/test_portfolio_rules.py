"""
Portfolio risk rule tests — FR-42.
Tests the actual check_position_risk() function from portfolio_risk.py.
"""
import pytest
from app.services.portfolio_risk import (
    check_position_risk,
    PortfolioPosition,
    RiskCheckResult,
)


def _make_portfolio_position(
    symbol: str = "AAPL",
    contract_id: str = "AAPL|190|2026-05-16|C",
    contracts: int = 1,
    entry_premium: float = 4.15,
    current_price: float = 5.02,
    capital_at_risk: float = 415.0,
) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol,
        contract_id=contract_id,
        contracts=contracts,
        entry_premium=entry_premium,
        current_price=current_price,
        capital_at_risk=capital_at_risk,
    )


def _make_request(
    symbol: str = "TSLA",
    contract_id: str = "TSLA|250|2026-05-16|C",
    proposed_contracts: int = 1,
    entry_premium: float = 3.50,
    current_price: float = 4.20,
    portfolio: list[PortfolioPosition] | None = None,
    portfolio_value: float = 50_000.0,
    daily_recommendation_count: int = 0,
) -> dict:
    return dict(
        symbol=symbol,
        contract_id=contract_id,
        proposed_contracts=proposed_contracts,
        entry_premium=entry_premium,
        current_price=current_price,
        portfolio=portfolio or [],
        portfolio_value=portfolio_value,
        daily_recommendation_count=daily_recommendation_count,
    )


class TestCheckPositionRisk:

    def test_clean_position_is_approved(self):
        """A position well within all limits should be approved."""
        result = check_position_risk(**_make_request())
        assert isinstance(result, RiskCheckResult)
        assert result.approved is True
        assert result.reasons == []

    def test_rejected_by_single_trade_exposure(self):
        """Entry premium × contracts > max_single_trade_exposure_pct × portfolio_value → rejected or size-adjusted."""
        # max_single_trade_exposure_pct = 0.05 (from risk_rules.yaml)
        # 50_000 * 0.05 = 2_500 max capital at risk
        # entry_premium=30, contracts=2 → capital_at_risk = 30*2*100 = 6_000 > 2_500
        result = check_position_risk(**_make_request(
            entry_premium=30.0,
            proposed_contracts=2,
            portfolio_value=50_000.0,
        ))
        # Either rejected outright or adjusted to a smaller size
        if result.approved:
            assert result.adjusted_size is not None
            assert result.adjusted_size < 2
        else:
            assert "single_trade_exposure_too_high" in result.reasons

    def test_reducible_single_trade_exposure_is_approved_at_adjusted_size(self):
        """A trade that exceeds single-trade exposure at the requested size,
        but fits at a smaller size, must be APPROVED with adjusted_size set —
        not rejected outright. (Regression: check_position_risk previously
        always returned approved=False whenever adjusted_size was set, even
        though "size_reduced_to_fit_exposure_limit" is an informational
        reason, not a hard block — the trade could always proceed at the
        smaller size, it just never actually could.)
        """
        # Option cap = min(max_single_position_pct 0.05, max_loss_per_trade_pct
        # 0.0375) = 0.0375 (review fix #4, D5); portfolio_value = 50_000
        # -> max_allowed_premium = 1_875
        # entry_premium=7, proposed_contracts=5 -> capital_at_risk = 3_500 (exceeds)
        # adjusted = int(1_875 / (7*100)) = 2 -> a valid, non-zero smaller size
        result = check_position_risk(**_make_request(
            entry_premium=7.0,
            proposed_contracts=5,
            portfolio_value=50_000.0,
        ))
        assert result.approved is True
        assert result.adjusted_size == 2
        assert result.reasons == ["size_reduced_to_fit_exposure_limit"]

    def test_rejected_by_max_concurrent_positions(self):
        """Portfolio already at max_concurrent_positions (10) → rejected."""
        full_portfolio = [
            _make_portfolio_position(symbol=f"SYM{i}", capital_at_risk=200.0)
            for i in range(10)  # max_concurrent_positions = 10
        ]
        result = check_position_risk(**_make_request(portfolio=full_portfolio))
        assert result.approved is False
        assert "max_concurrent_positions_reached" in result.reasons

    def test_rejected_by_daily_recommendation_limit(self):
        """daily_recommendation_count >= max_daily_recommendations (5) → rejected."""
        result = check_position_risk(**_make_request(daily_recommendation_count=5))
        assert result.approved is False
        assert "daily_recommendation_limit_reached" in result.reasons

    def test_rejected_by_duplicate_symbol(self):
        """Same symbol already open → rejected when max_same_symbol_positions=1."""
        existing = [_make_portfolio_position(symbol="TSLA")]
        result = check_position_risk(**_make_request(
            symbol="TSLA",
            portfolio=existing,
        ))
        assert result.approved is False
        assert "duplicate_symbol_already_open" in result.reasons
