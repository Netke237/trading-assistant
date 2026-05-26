import pytest
from app.scoring.reward_risk import estimate_targets
from app.schemas import PricingMethod


def test_three_targets_returned():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30 / 365,
        current_premium=2.50,
        is_call=True,
    )
    assert len(targets) == 3


def test_t2_price_is_1_5x_move():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,  # T1 move = 8
        strike=105.0,
        expiry_years=30 / 365,
        current_premium=2.50,
        is_call=True,
    )
    t1, t2, t3 = targets
    assert abs(t2.targetPrice - 112.0) < 0.1  # 100 + 8*1.5 = 112
    assert abs(t3.targetPrice - 116.0) < 0.1  # 100 + 8*2.0 = 116


def test_pricing_method_not_empty():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30 / 365,
        current_premium=2.50,
        is_call=True,
    )
    for t in targets:
        assert t.pricingMethod in (PricingMethod.HESTON, PricingMethod.DELTA_APPROX, PricingMethod.UNAVAILABLE)
        assert t.pricingMethod != ""


def test_rr_contribution_positive():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30 / 365,
        current_premium=2.50,
        is_call=True,
    )
    for t in targets:
        assert t.rrContribution >= 0


def test_stock_price_equals_target_price():
    """stockPrice must equal targetPrice for backward compat with alertEngine."""
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30 / 365,
        current_premium=2.50,
        is_call=True,
    )
    for t in targets:
        assert t.stockPrice == t.targetPrice
