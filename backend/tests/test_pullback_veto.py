"""Tests that a REJECT pullback caps the overall score at CAUTION."""
import pytest
from unittest.mock import patch
from app.scoring.stock_scorer import score_stock, RuleResult


def _flat_bars(n=120, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1_000_000} for _ in range(n)]


def _force_rules(bars, *, pullback_status, trend_score=90):
    """Score a stock with the pullback rule mocked to a specific status."""
    with (
        patch("app.scoring.stock_scorer._rule_trend",
              return_value=RuleResult("trend", "PASS", trend_score, {})),
        patch("app.scoring.stock_scorer._rule_pullback",
              return_value=RuleResult("pullback", pullback_status, 10 if pullback_status == "REJECT" else 88, {})),
        patch("app.scoring.stock_scorer._rule_trigger",
              return_value=(RuleResult("trigger", "PASS", 80, {"candle": "none", "macd_pass": True,
                                                                "rsi_pass": True, "stoch_pass": True,
                                                                "momentum_count": 3, "volume_bonus": False}), False)),
        patch("app.scoring.stock_scorer._rule_event",
              return_value=RuleResult("event", "PASS", 90, {})),
        patch("app.scoring.stock_scorer._rule_vol",
              return_value=RuleResult("vol", "PASS", 80, {})),
    ):
        return score_stock("TEST", "Bullish", "Swing", bars)


def test_pullback_reject_caps_overall_at_caution():
    """Even with trend/trigger PASS, pullback REJECT must prevent overall PASS."""
    bars = _flat_bars()
    card = _force_rules(bars, pullback_status="REJECT")
    assert card.status != "PASS", (
        f"Expected CAUTION or REJECT when pullback is REJECT, got {card.status}"
    )
    assert card.status == "CAUTION", (
        f"Expected CAUTION cap for REJECT pullback, got {card.status}"
    )


def test_pullback_pass_allows_overall_pass():
    """Pullback PASS must not block an otherwise-passing trade."""
    bars = _flat_bars()
    card = _force_rules(bars, pullback_status="PASS")
    assert card.status == "PASS", (
        f"Expected PASS when all rules pass, got {card.status}"
    )


def test_pullback_caution_does_not_cap():
    """Pullback CAUTION (not REJECT) must not trigger the hard cap."""
    bars = _flat_bars()
    card = _force_rules(bars, pullback_status="CAUTION")
    assert card.status == "PASS", (
        f"Pullback CAUTION must not cap a high-scoring setup, got {card.status}"
    )


def test_pullback_reject_plus_confidence_reject_gives_reject():
    """Pullback REJECT (→ CAUTION cap) combined with REJECT confidence → REJECT."""
    bars = _flat_bars()
    gate = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
    with (
        patch("app.scoring.stock_scorer._rule_trend",
              return_value=RuleResult("trend", "PASS", 90, {})),
        patch("app.scoring.stock_scorer._rule_pullback",
              return_value=RuleResult("pullback", "REJECT", 10, {})),
        patch("app.scoring.stock_scorer._rule_trigger",
              return_value=(RuleResult("trigger", "PASS", 80, {"candle": "none", "macd_pass": True,
                                                                "rsi_pass": True, "stoch_pass": True,
                                                                "momentum_count": 3, "volume_bonus": False}), False)),
        patch("app.scoring.stock_scorer._rule_event",
              return_value=RuleResult("event", "PASS", 90, {})),
        patch("app.scoring.stock_scorer._rule_vol",
              return_value=RuleResult("vol", "PASS", 80, {})),
    ):
        card = score_stock("TEST", "Bullish", "Swing", bars,
                           confidence=20, confidence_gate=gate)
    assert card.status == "REJECT", (
        f"Pullback REJECT + confidence REJECT must give REJECT, got {card.status}"
    )
