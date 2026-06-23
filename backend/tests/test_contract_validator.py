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
