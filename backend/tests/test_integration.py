"""
Integration tests: real candles (Tiingo-sourced, pinned) + full scorer pipeline.
Network-free — fixtures are committed JSON files.
"""
import json
from pathlib import Path

import pytest

from app.scoring.stock_scorer import score_stock
from app.scoring.contract_validator import validate_contract
from app.scoring.entry_quality import assess_entry

FIXTURES = Path(__file__).parent / "fixtures"


def _load(symbol: str) -> list[dict]:
    path = FIXTURES / f"{symbol}_candles.json"
    if not path.exists():
        pytest.skip(f"Fixture not found: {path}. Run scripts/pin_fixtures.py first.")
    return json.loads(path.read_text())


# ── score_stock ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol,direction", [
    ("AAPL", "Bullish"),
    ("AAPL", "Bearish"),
    ("MSFT", "Bullish"),
    ("NVDA", "Bullish"),
    ("SPY",  "Bullish"),
])
def test_score_stock_returns_valid_card(symbol, direction):
    bars = _load(symbol)
    card = score_stock(symbol, direction, "Swing", bars)
    assert card.score >= 0
    assert card.status in ("PASS", "CAUTION", "REJECT")
    assert len(card.rules) > 0


def test_score_stock_uses_at_least_50_bars(symbol="AAPL"):
    bars = _load(symbol)
    assert len(bars) >= 50, "Fixture too short for scoring"


def test_score_stock_bearish_returns_valid_card():
    bars = _load("AAPL")
    bear = score_stock("AAPL", "Bearish", "Swing", bars)
    assert bear.score >= 0
    assert bear.status in ("PASS", "CAUTION", "REJECT")
    assert len(bear.rules) > 0


# ── validate_contract ─────────────────────────────────────────────────────────

def _sample_contract(stock_score: int = 70) -> dict:
    return {
        "id": "AAPL|185|2026-06-30|C",
        "symbol": "AAPL",
        "strike": 185,
        "expiry": "2026-06-30",
        "right": "C",
        "dte": 59,
        "dteTotal": 59,
        "price": 5.20,
        "bid": 5.10,
        "ask": 5.30,
        "delta": 0.52,
        "theta": -0.04,
        "ivRank": 42,
        "ivPercentile": 0,
        "spread": 0.20,
        "volume": 1500,
        "open_interest": 1500,
        "score": 0,
    }


def test_validate_contract_pass_on_good_contract():
    contract = _sample_contract()
    card = validate_contract(contract, stock_score=75)
    assert card.status in ("PASS", "CAUTION")


def test_validate_contract_reject_on_zero_volume():
    contract = _sample_contract()
    contract["volume"] = 0
    contract["open_interest"] = 0
    card = validate_contract(contract, stock_score=75)
    assert card.status == "REJECT"


# ── assess_entry ──────────────────────────────────────────────────────────────

def test_assess_entry_tight_spread_is_pass():
    result = assess_entry(bid=5.10, ask=5.30, mid=5.20)
    assert result.quality_status in ("PASS", "CAUTION")


def test_assess_entry_wide_spread_is_reject():
    result = assess_entry(bid=1.00, ask=4.00, mid=2.50)
    assert result.quality_status == "REJECT"


# ── horizon variants ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("horizon", ["Intraday", "Swing", "Position"])
def test_score_stock_all_horizons(horizon):
    bars = _load("AAPL")
    card = score_stock("AAPL", "Bullish", horizon, bars)
    assert card.status in ("PASS", "CAUTION", "REJECT")
