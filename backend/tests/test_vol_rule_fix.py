"""Verify _rule_vol behaviour after iv_rank_pass_max was set for Swing/Position.

Now that scoring_rules.yaml has iv_rank_pass_max: 34 (Swing) and 44 (Position),
passing iv_rank=None triggers the "no_iv_data" branch → CAUTION 50, NOT PASS 90.
Intraday remains null (gate disabled) → still PASS.
"""
from app.scoring.stock_scorer import score_stock, _load_config


def _flat_bars(n: int = 200, price: float = 100.0) -> list[dict]:
    return [
        {"open": price, "high": price + 1, "low": price - 1,
         "close": price, "volume": 1_000}
        for _ in range(n)
    ]


def test_swing_vol_rule_caution_when_no_iv():
    """score_stock on Swing without iv_rank returns CAUTION (no_iv_data) — gate is active."""
    _load_config.cache_clear()
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Swing", bars=bars)
    vol_rules = [r for r in card.rules if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "CAUTION", (
        f"Expected vol rule CAUTION (no_iv_data) when iv_rank=None on Swing, got {vol_rules[0].status}. "
        "iv_rank_pass_max=34 is set — no iv_rank means no_iv_data → CAUTION."
    )


def test_position_vol_rule_caution_when_no_iv():
    """score_stock on Position without iv_rank returns CAUTION (no_iv_data) — gate is active."""
    _load_config.cache_clear()
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Position", bars=bars)
    vol_rules = [r for r in card.rules if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "CAUTION", (
        f"Expected vol rule CAUTION (no_iv_data) when iv_rank=None on Position, got {vol_rules[0].status}. "
        "iv_rank_pass_max=44 is set — no iv_rank means no_iv_data → CAUTION."
    )


def test_intraday_vol_rule_still_pass():
    """Intraday iv_rank_pass_max stays null — gate disabled, vol rule stays PASS regardless."""
    _load_config.cache_clear()
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Intraday", bars=bars)
    vol_rules = [r for r in card.rules if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "PASS"
