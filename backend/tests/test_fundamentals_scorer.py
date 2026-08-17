"""Tests for fundamentals_scorer.py"""
from decimal import Decimal
from datetime import date
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Regression: cfg=None must load from YAML, not _DEFAULT_CFG
# ---------------------------------------------------------------------------

def test_score_fundamentals_cfg_none_returns_valid_score():
    """Passing cfg=None must not raise and must return a score in 0-100."""
    result = score_fundamentals(_snap(), direction="Bullish", cfg=None)
    assert 0 <= result.score <= 100


def test_score_fundamentals_cfg_none_uses_yaml_loader():
    """cfg=None must call _load_yaml_cfg, not use a hardcoded fallback.
    We inject non-default weights and verify the score reflects them."""
    snap = _snap()

    # Get baseline score with default cfg (all weights ~equal)
    baseline = score_fundamentals(snap, direction="Bullish", cfg=None)

    # Inject a cfg that puts ALL weight on risk (score will be dominated by risk_score)
    injected_cfg = {
        "weights": {"growth": 0.0, "quality": 0.0, "risk": 1.0},
        "safety": {"reject_on_negative_equity": True, "debt_to_equity_reject": 3.0},
    }
    with patch(
        "app.scoring.fundamentals_scorer._load_yaml_cfg",
        return_value={"fundamentals_gate": injected_cfg},
    ):
        risk_only = score_fundamentals(snap, direction="Bullish", cfg=None)

    assert risk_only.score != baseline.score, (
        f"Injected risk-only weights should change the score "
        f"(baseline={baseline.score}, risk_only={risk_only.score}). "
        "cfg=None is not reading from _load_yaml_cfg."
    )


# ── H3: quality_label must reflect quality_score, not blended score ─────────

def test_quality_label_reflects_quality_score_not_blended_score():
    """A stock with strong margins (high quality_score) but weak growth/risk (low blended
    score) must still get quality_label='Strong' — the label describes the Quality bucket,
    not the overall blended score."""
    h = score_fundamentals(_snap(
        gross_margin=0.55, operating_margin=0.30,
        revenue_growth_yoy=-0.30, eps_growth_yoy=-0.25,
        debt_to_equity=2.8, current_ratio=0.6, share_growth_yoy=0.08,
    ), "Bullish")
    assert h.quality_score >= 65, f"expected strong quality bucket, got {h.quality_score}"
    assert h.score < 40, f"expected blended score to be dragged down, got {h.score}"
    assert h.quality_label == "Strong", (
        f"quality_label={h.quality_label!r} must reflect quality_score={h.quality_score}, "
        f"not blended score={h.score}"
    )


def test_quality_label_weak_quality_bucket_labeled_weak_even_if_blended_score_high():
    """Inverse case: weak margins but strong growth/risk should NOT be labeled 'Strong'
    quality just because the blended score is high."""
    h = score_fundamentals(_snap(
        gross_margin=0.10, operating_margin=-0.10,
        revenue_growth_yoy=0.40, eps_growth_yoy=0.35,
        debt_to_equity=0.2, current_ratio=3.0, share_growth_yoy=-0.02,
    ), "Bullish")
    assert h.quality_score < 40, f"expected weak quality bucket, got {h.quality_score}"
    assert h.quality_label == "Weak", (
        f"quality_label={h.quality_label!r} should be Weak given quality_score={h.quality_score}"
    )


# ── M1: quality_label_thresholds must be sourced from cfg, not hardcoded ────

def test_quality_label_thresholds_configurable():
    """quality_label boundaries must be read from cfg['quality_label_thresholds'], not
    hardcoded 65/40. Uses a mid-range quality_score (not maxed at 100) so a raised
    'strong' threshold can actually demote the label."""
    snap = _snap(gross_margin=0.34, operating_margin=0.12)
    baseline = score_fundamentals(snap, "Bullish")
    assert baseline.quality_label == "Strong"
    assert baseline.quality_score < 100, "test needs headroom below 100 to prove demotion"

    tight_cfg = {
        "weights": {"growth": 0.35, "quality": 0.35, "risk": 0.30},
        "safety": {"reject_on_negative_equity": True, "debt_to_equity_reject": 3.0},
        "quality_label_thresholds": {"strong": 90, "neutral": 50},
    }
    tightened = score_fundamentals(snap, "Bullish", cfg=tight_cfg)
    assert tightened.quality_label != "Strong", (
        "raising quality_label_thresholds.strong to 90 should demote this snapshot's label"
    )


# ── T1: metric strong/weak pairs must be read from cfg['thresholds'] ─────────

def test_metric_thresholds_configurable_via_cfg():
    """Metric strong/weak pairs must come from cfg['thresholds'] — raising the
    revenue/EPS-growth 'strong' threshold must change the growth bucket score
    (0.12 growth = 80/100 under default 0.15, but 30/100 under 0.40)."""
    snap = _snap(revenue_growth_yoy=0.12, eps_growth_yoy=0.12)
    baseline = score_fundamentals(snap, "Bullish")
    assert baseline.growth_score == 80, "test needs the default 0.15 strong threshold"

    custom = {
        "weights": {"growth": 0.35, "quality": 0.35, "risk": 0.30},
        "safety": {"reject_on_negative_equity": True, "debt_to_equity_reject": 3.0},
        "quality_label_thresholds": {"strong": 65, "neutral": 40},
        "thresholds": {
            "revenue_growth_yoy": {"strong": 0.40, "weak": 0.0},
            "eps_growth_yoy": {"strong": 0.40, "weak": 0.0},
        },
    }
    tightened = score_fundamentals(snap, "Bullish", cfg=custom)
    assert tightened.growth_score == 30, (
        f"raised strong threshold should cut growth_score to 30, got {tightened.growth_score}"
    )
    assert tightened.growth_score < baseline.growth_score


def test_yaml_thresholds_take_effect():
    """The cfg=None path must read thresholds from the YAML loader — injecting
    modified thresholds via the module-level `_load_yaml_cfg` alias must move a
    bucket score (patch the alias itself, not signal_confidence._cfg)."""
    snap = _snap(revenue_growth_yoy=0.12, eps_growth_yoy=0.12)
    baseline = score_fundamentals(snap, "Bullish")

    injected_cfg = {
        "weights": {"growth": 0.35, "quality": 0.35, "risk": 0.30},
        "safety": {"reject_on_negative_equity": True, "debt_to_equity_reject": 3.0},
        "quality_label_thresholds": {"strong": 65, "neutral": 40},
        "thresholds": {
            "revenue_growth_yoy": {"strong": 0.40, "weak": 0.0},
            "eps_growth_yoy": {"strong": 0.40, "weak": 0.0},
        },
    }
    with patch(
        "app.scoring.fundamentals_scorer._load_yaml_cfg",
        return_value={"fundamentals_gate": injected_cfg},
    ):
        tightened = score_fundamentals(snap, direction="Bullish", cfg=None)

    assert tightened.growth_score == 30, (
        f"YAML-injected thresholds should change growth_score, got {tightened.growth_score}"
    )
    assert tightened.growth_score < baseline.growth_score


# ── T2: risk_label boundaries must match the score's inclusive thresholds ────

def test_risk_label_boundaries_follow_thresholds():
    """risk_label uses the same inclusive boundaries as _metric_score's invert
    branch: None → Low (historical), de == strong → Low, de == weak → High."""
    none_de = score_fundamentals(_snap(debt_to_equity=None), "Bullish")
    assert none_de.risk_label == "Low"

    at_strong = score_fundamentals(_snap(debt_to_equity=0.5), "Bullish")
    assert at_strong.risk_label == "Low", "de == strong (0.5) scores 100 and must label Low"

    at_weak = score_fundamentals(_snap(debt_to_equity=2.0), "Bullish")
    assert at_weak.risk_label == "High", "de == weak (2.0) scores 0 and must label High"


def test_custom_debt_thresholds_drive_risk_label():
    baseline = score_fundamentals(_snap(debt_to_equity=0.30), "Bullish")
    custom = score_fundamentals(
        _snap(debt_to_equity=0.30),
        "Bullish",
        cfg={"thresholds": {"debt_to_equity": {"strong": 0.25, "weak": 1.0}}},
    )
    assert baseline.risk_label == "Low"
    assert custom.risk_label == "Medium"


def test_malformed_threshold_pairs_fall_back_to_known_defaults():
    snap = _snap(revenue_growth_yoy=0.12, eps_growth_yoy=0.12, debt_to_equity=0.30)
    baseline = score_fundamentals(snap, "Bullish")
    malformed = score_fundamentals(
        snap,
        "Bullish",
        cfg={
            "thresholds": {
                "revenue_growth_yoy": {"strong": "not-a-number", "weak": 0.0},
                "gross_margin": {"strong": 0.20, "weak": 0.40},
                "debt_to_equity": {"strong": float("nan"), "weak": 2.0},
            },
        },
    )
    assert malformed.growth_score == baseline.growth_score
    assert malformed.quality_score == baseline.quality_score
    assert malformed.risk_score == baseline.risk_score
