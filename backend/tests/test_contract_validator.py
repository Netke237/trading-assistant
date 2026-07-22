"""Tests for contract_validator — hard reject and soft rank."""
import pytest
from app.scoring.contract_validator import validate_contract


def _base_contract(**overrides):
    c = {
        "symbol": "AAPL",
        "strike": 185.0,
        "expiry": "2026-09-19",
        "is_call": True,
        "bid": 2.00,
        "ask": 2.10,
        "volume": 500,
        "open_interest": 2000,
        "delta": 0.45,
        "iv_rank": 30.0,
    }
    c.update(overrides)
    return c


def test_low_iv_rank_passes():
    card = validate_contract(_base_contract(iv_rank=30), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_iv_rank_at_threshold_passes():
    """IV rank exactly at the limit (70) should still pass."""
    card = validate_contract(_base_contract(iv_rank=70), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_iv_rank_above_threshold_hard_rejects():
    """IV rank > 70 must hard-reject — buying expensive premium is the worst options mistake."""
    card = validate_contract(_base_contract(iv_rank=71), stock_score=70)
    assert card.status == "REJECT"
    assert "iv_rank_too_high" in card.reject_reasons


def test_iv_rank_very_high_hard_rejects():
    card = validate_contract(_base_contract(iv_rank=90), stock_score=70)
    assert card.status == "REJECT"
    assert "iv_rank_too_high" in card.reject_reasons


def test_iv_rank_none_is_not_rejected():
    """Missing IV rank data must not hard-reject (data gap != bad contract)."""
    card = validate_contract(_base_contract(iv_rank=None), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_override_raises_max_iv_rank():
    """Caller can override the threshold to 80 via overrides dict."""
    card = validate_contract(
        _base_contract(iv_rank=75),
        stock_score=70,
        overrides={"max_iv_rank": 80},
    )
    assert "iv_rank_too_high" not in card.reject_reasons


from datetime import date, timedelta


def _contract_with_expiry(days_out: int, **overrides):
    c = _base_contract(expiry=(date.today() + timedelta(days=days_out)).isoformat())
    c.update(overrides)
    return c


def test_dte_small_miss_below_window_scores_between_zero_and_old_flat_value():
    """Default preferred window is 21-60 (contract_rules.yaml). 20 DTE is 1 day
    short of d_min=21 -- half_range = (60-21)/2 = 19.5, so a 1-day miss should
    score just under the old flat 25, not exactly 25."""
    card = validate_contract(_contract_with_expiry(20), stock_score=70)
    assert 0 < card.breakdown.dte_score < 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_large_miss_below_window_floors_at_zero():
    """A miss at least half_range (19.5 -> 20 rounds via int()) days below d_min
    must floor at 0, not stay at the old flat 25."""
    card = validate_contract(_contract_with_expiry(1), stock_score=70)  # 20 days short of d_min=21
    assert card.breakdown.dte_score == 0
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_small_miss_above_window_scores_between_zero_and_old_flat_value():
    """61 DTE is 1 day past d_max=60."""
    card = validate_contract(_contract_with_expiry(61), stock_score=70)
    assert 0 < card.breakdown.dte_score < 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_large_miss_above_window_floors_at_zero():
    card = validate_contract(_contract_with_expiry(200), stock_score=70)  # 140 days past d_max=60
    assert card.breakdown.dte_score == 0
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_near_miss_scores_higher_than_far_miss():
    """The core complaint being fixed: a 1-day miss must no longer score
    identically to a 100+ day miss."""
    near = validate_contract(_contract_with_expiry(61), stock_score=70)
    far = validate_contract(_contract_with_expiry(200), stock_score=70)
    assert near.breakdown.dte_score > far.breakdown.dte_score


def test_dte_in_window_scoring_is_unchanged():
    """Centre of the default 21-60 window is 40.5 -> round to nearest int DTE;
    use 40 and 60 to lock in the existing in-window formula is untouched."""
    centre_ish = validate_contract(_contract_with_expiry(40), stock_score=70)
    edge = validate_contract(_contract_with_expiry(60), stock_score=70)
    assert centre_ish.breakdown.dte_score > edge.breakdown.dte_score
    assert edge.breakdown.dte_score == 0  # exact edge already scored 0 before this fix


def test_dte_collapsed_window_out_of_range_does_not_divide_by_zero():
    """A hold-derived override can collapse preferred_dte_min == preferred_dte_max
    (half_range == 0). The existing in-window guard only covers dte == that exact
    point; this covers the NEW out-of-window decay_span guard by picking a dte one
    day off the collapsed point, which must score cleanly instead of raising."""
    card = validate_contract(
        _contract_with_expiry(31),
        stock_score=70,
        overrides={"preferred_dte_min": 30, "preferred_dte_max": 30},
    )
    assert 0 <= card.breakdown.dte_score <= 25
    assert "dte_outside_preferred" in card.soft_flags
