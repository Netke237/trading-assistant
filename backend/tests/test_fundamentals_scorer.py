"""Tests for fundamentals_scorer.py"""
from decimal import Decimal
from datetime import date

from app.data.edgar import FundamentalsSnapshot
from app.scoring.fundamentals_scorer import score_fundamentals, FundamentalHealth


def _snap(**kwargs) -> FundamentalsSnapshot:
    defaults = dict(
        symbol="TEST", fiscal_period_end=date(2023, 9, 30), filed_date=None, cik="0000000001",
        revenue=Decimal("100"), net_income=Decimal("20"), eps_diluted=Decimal("2.0"),
        gross_profit=Decimal("45"), operating_income=Decimal("18"),
        op_cash_flow=Decimal("25"), capex=Decimal("5"),
        total_debt=Decimal("30"), stockholders_eq=Decimal("100"),
        current_assets=Decimal("60"), current_liab=Decimal("30"),
        shares_diluted=Decimal("1000"),
        revenue_growth_yoy=0.10, eps_growth_yoy=0.12,
        gross_margin=0.45, operating_margin=0.18,
        fcf=Decimal("20"), debt_to_equity=0.30, current_ratio=2.0,
        share_growth_yoy=0.01,
    )
    defaults.update(kwargs)
    return FundamentalsSnapshot(**defaults)


def test_strong_company_scores_high():
    h = score_fundamentals(_snap(), "Bullish")
    assert h.score >= 65
    assert h.quality_label == "Strong"
    assert not h.safety_flags


def test_negative_equity_flag():
    h = score_fundamentals(_snap(stockholders_eq=Decimal("-1")), "Bullish")
    assert "negative_equity" in h.safety_flags


def test_extreme_leverage_flag():
    h = score_fundamentals(_snap(debt_to_equity=4.0), "Bullish")
    assert "extreme_leverage" in h.safety_flags


def test_none_metrics_return_neutral():
    # All growth/margin/ratio fields None → score near 50
    h = score_fundamentals(_snap(
        revenue_growth_yoy=None, eps_growth_yoy=None,
        gross_margin=None, operating_margin=None,
        debt_to_equity=None, current_ratio=None, share_growth_yoy=None,
    ), "Bullish")
    assert 30 <= h.score <= 70


def test_weak_fundamentals_scores_low():
    h = score_fundamentals(_snap(
        revenue_growth_yoy=-0.20, eps_growth_yoy=-0.15,
        gross_margin=0.05, operating_margin=-0.05,
        debt_to_equity=3.5, current_ratio=0.5, share_growth_yoy=0.10,
    ), "Bullish")
    assert h.score < 40
    assert h.quality_label == "Weak"


def test_invert_metrics_score_correctly():
    low_debt = score_fundamentals(_snap(debt_to_equity=0.2, share_growth_yoy=0.0, current_ratio=2.0), "Bullish")
    high_debt = score_fundamentals(_snap(debt_to_equity=2.5, share_growth_yoy=0.05, current_ratio=2.0), "Bullish")
    assert low_debt.risk_score > high_debt.risk_score
