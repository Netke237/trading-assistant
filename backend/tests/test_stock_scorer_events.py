"""Tests for event rule thresholds (options and stock modes)."""
import pytest
from datetime import date, timedelta
from app.scoring.stock_scorer import _rule_event, score_stock


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


def _bars_up(n=120):
    bars, price = [], 100.0
    for _ in range(n):
        price += 0.4
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 2_000_000})
    return bars


def test_event_weight_zero_in_stock_mode():
    """
    A candidate with upcoming earnings (5 days) should score differently in
    options vs stock mode because stock mode zeroes the event weight.
    The event rule result should be in the rules list but contribute 0.
    """
    bars = _bars_up()
    earnings = date.today() + timedelta(days=5)

    card_options = score_stock(
        "X", "Bullish", "Swing", bars,
        earnings_date=earnings,
        scoring_mode="options",
    )
    card_stock = score_stock(
        "X", "Bullish", "Swing", bars,
        earnings_date=earnings,
        scoring_mode="stock",
    )

    # Event rule exists in both
    ev_stock = next((r for r in card_stock.rules if r.name == "event"), None)
    assert ev_stock is not None

    # In stock mode, the event REJECT should not pull the final score down
    # because its weight is 0. Stock score must be >= options score when event
    # would otherwise trigger a REJECT in options mode.
    assert card_stock.score >= card_options.score


def test_stock_mode_score_in_range():
    """Renormalized weights must keep final score in [0, 100]."""
    bars = _bars_up()
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    assert 0 <= card.score <= 100
