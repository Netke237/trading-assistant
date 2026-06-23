"""Tests for event rule thresholds (options and stock modes)."""
import pytest
from datetime import date, timedelta
from app.scoring.stock_scorer import _rule_event


def test_options_earnings_within_21_days_is_reject():
    """Options: reject within 21 days — 7-day threshold was too tight."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=15),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="options",
    )
    assert result.status == "REJECT"


def test_options_earnings_22_days_away_is_caution():
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=22),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="options",
    )
    assert result.status == "CAUTION"


def test_options_earnings_beyond_45_days_is_pass():
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=50),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="options",
    )
    assert result.status == "PASS"


def test_stock_mode_earnings_close_is_caution_not_pass():
    """Stock mode must no longer auto-return PASS — event proximity is shown."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=5),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="stock",
    )
    # Status should NOT be PASS when earnings are imminent
    assert result.status != "PASS"
    assert result.detail.get("note") is not None


def test_stock_mode_no_event_is_pass():
    """Stock mode with no upcoming events should still PASS."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=None,
        dividend_date=None,
        cfg=cfg,
        scoring_mode="stock",
    )
    assert result.status == "PASS"


def test_stock_mode_note_in_detail():
    """The detail dict must include the 'note' key in stock mode."""
    cfg = {
        "event": {"reject_days": 21, "caution_days": 45}
    }
    result = _rule_event(
        earnings_date=date.today() + timedelta(days=30),
        dividend_date=None,
        cfg=cfg,
        scoring_mode="stock",
    )
    assert "note" in result.detail
    assert "weight" in result.detail["note"].lower() or "score" in result.detail["note"].lower()
