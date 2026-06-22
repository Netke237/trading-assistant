"""Tests for vol scoring rule — iv_rank_pass_max gate.

These tests verify that scoring_rules.yaml has real values (not null) for
iv_rank_pass_max in the Swing and Position horizon vol sections.

Before the YAML fix:  iv_rank_pass_max: null → scorer always returns PASS 90
After the YAML fix:   iv_rank_pass_max: 34 (Swing) / 44 (Position) → gate enforced
"""
import pytest
from app.scoring.stock_scorer import score_stock, _load_config
from app.fixtures.candles import candles_for


def _bars(symbol: str = "AAPL") -> list[dict]:
    """Load fixture candles as plain dicts (same pattern as conftest.py:229-230)."""
    return [c.model_dump(by_alias=False) for c in candles_for(symbol)]


def _vol_status(result) -> str:
    """Extract the vol rule status from a StockScoreCard."""
    for rule in result.rules:
        if rule.name == "vol":
            return rule.status
    return "NOT_FOUND"


# ---------------------------------------------------------------------------
# Swing horizon — iv_rank_pass_max: 34
# ---------------------------------------------------------------------------

def test_swing_iv_rank_above_pass_max_returns_caution_after_yaml_update():
    """With iv_rank_pass_max=34 in YAML (Swing), iv_rank=40 must return CAUTION on vol rule."""
    _load_config.cache_clear()   # ensure fresh YAML read
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Swing",
        bars=_bars(),
        iv_rank=40.0,            # above pass_max=34, below caution_max=55 -> CAUTION
    )
    status = _vol_status(result)
    assert status == "CAUTION", (
        f"Expected vol=CAUTION for iv_rank=40 (above pass_max=34), got {status!r}. "
        "Did you add iv_rank_pass_max: 34 to scoring_rules.yaml Swing vol section?"
    )


def test_swing_iv_rank_below_pass_max_returns_pass_after_yaml_update():
    """With iv_rank_pass_max=34 in YAML (Swing), iv_rank=20 must return PASS on vol rule."""
    _load_config.cache_clear()
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Swing",
        bars=_bars(),
        iv_rank=20.0,            # below pass_max=34 -> PASS
    )
    status = _vol_status(result)
    assert status == "PASS", (
        f"Expected vol=PASS for iv_rank=20 (below pass_max=34), got {status!r}."
    )


def test_swing_iv_rank_above_caution_max_returns_reject():
    """iv_rank=60 exceeds caution_max=55 (Swing) -> REJECT."""
    _load_config.cache_clear()
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Swing",
        bars=_bars(),
        iv_rank=60.0,
    )
    status = _vol_status(result)
    assert status == "REJECT", (
        f"Expected vol=REJECT for iv_rank=60 (above caution_max=55), got {status!r}."
    )


# ---------------------------------------------------------------------------
# Position horizon — iv_rank_pass_max: 44
# ---------------------------------------------------------------------------

def test_position_iv_rank_above_pass_max_returns_caution_after_yaml_update():
    """With iv_rank_pass_max=44 in YAML (Position), iv_rank=50 must return CAUTION on vol rule."""
    _load_config.cache_clear()
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Position",
        bars=_bars(),
        iv_rank=50.0,            # above pass_max=44, below caution_max=65 -> CAUTION
    )
    status = _vol_status(result)
    assert status == "CAUTION", (
        f"Expected vol=CAUTION for iv_rank=50 (above pass_max=44), got {status!r}. "
        "Did you add iv_rank_pass_max: 44 to scoring_rules.yaml Position vol section?"
    )


def test_position_iv_rank_below_pass_max_returns_pass_after_yaml_update():
    """With iv_rank_pass_max=44 in YAML (Position), iv_rank=30 must return PASS on vol rule."""
    _load_config.cache_clear()
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Position",
        bars=_bars(),
        iv_rank=30.0,            # below pass_max=44 -> PASS
    )
    status = _vol_status(result)
    assert status == "PASS", (
        f"Expected vol=PASS for iv_rank=30 (below pass_max=44), got {status!r}."
    )


# ---------------------------------------------------------------------------
# Intraday horizon — iv_rank_pass_max stays null (gate disabled)
# ---------------------------------------------------------------------------

def test_intraday_vol_gate_remains_disabled():
    """Intraday iv_rank_pass_max stays null — vol rule always returns PASS regardless of iv_rank."""
    _load_config.cache_clear()
    result = score_stock(
        symbol="TEST",
        direction="Bullish",
        horizon="Intraday",
        bars=_bars(),
        iv_rank=90.0,            # very high — gate is null so still PASS
    )
    status = _vol_status(result)
    assert status == "PASS", (
        f"Expected vol=PASS for Intraday (gate disabled), got {status!r}. "
        "Intraday iv_rank_pass_max must stay null in scoring_rules.yaml."
    )
