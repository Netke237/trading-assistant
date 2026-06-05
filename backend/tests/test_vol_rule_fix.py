"""Verify _rule_vol returns PASS 90 (not CAUTION 50) when iv_rank=None on Swing/Position."""
import pytest
from app.scoring.stock_scorer import score_stock
from app.services.strategy_engine import pullback_ema_signal


def _flat_bars(n: int = 200, price: float = 100.0) -> list[dict]:
    return [
        {"open": price, "high": price + 1, "low": price - 1,
         "close": price, "volume": 1_000}
        for _ in range(n)
    ]


def test_swing_vol_rule_pass_when_no_iv():
    """score_stock on Swing without iv_rank should not produce CAUTION from vol rule."""
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Swing", bars=bars)
    vol_rules = [r for r in card.rules if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "PASS", (
        f"Expected vol rule PASS when iv_rank=None on Swing, got {vol_rules[0].status}"
    )


def test_position_vol_rule_pass_when_no_iv():
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Position", bars=bars)
    vol_rules = [r for r in card.rules if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "PASS", (
        f"Expected vol rule PASS when iv_rank=None on Position, got {vol_rules[0].status}"
    )


def test_intraday_vol_rule_already_pass():
    """Intraday was already null — verify it stays PASS (regression guard)."""
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Intraday", bars=bars)
    vol_rules = [r for r in card.rules if r.name == "vol"]
    assert not vol_rules or vol_rules[0].status == "PASS"
