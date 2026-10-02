"""Fix #1 (TRADING_REVIEW.md): lowercase 'bullish' ran the BEARISH branch."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.strategy_backtest import normalize_direction, run_strategy_backtest

FIX = Path(__file__).parent / "fixtures" / "SPY_candles.json"


def _spy():
    return json.loads(FIX.read_text())


@pytest.mark.parametrize("raw,expected", [
    ("bullish", "Bullish"), ("Bullish", "Bullish"), (" BULLISH ", "Bullish"),
    ("bearish", "Bearish"), ("Bearish", "Bearish"),
])
def test_normalize_direction(raw, expected):
    assert normalize_direction(raw) == expected


@pytest.mark.parametrize("raw", ["", "long", "neutral", None])
def test_normalize_direction_rejects_unknown(raw):
    with pytest.raises(ValueError):
        normalize_direction(raw)


def test_lowercase_bullish_backtest_equals_capitalised():
    bars = _spy()
    lower = run_strategy_backtest(bars, strategy="pullback_ema", direction="bullish")
    upper = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert lower.n_trades == upper.n_trades
    assert lower.expectancy == upper.expectancy
    assert lower.direction == "Bullish"


def test_get_direction_is_normalised(monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "_load", lambda: {"direction": "bullish"})
    assert store.get_direction() == "Bullish"


def test_build_proposal_carries_direction():
    from app.services.strategy_param_optimizer import build_proposal
    p = build_proposal(
        strategy="pullback_ema", direction="Bearish",
        fold_winners=[{"ema_period": 20}], fold_test_returns=[1.0],
        in_sample_return=2.0, walk_forward_return=1.0,
        oos_metrics={"sharpe": 1, "expectancy": 0.1, "win_rate": 0.5,
                     "total_return": 1.0, "max_drawdown": -1.0, "n_trades": 30},
        min_trades=20,
    )
    assert p["direction"] == "Bearish"


def test_adopt_requires_direction(monkeypatch):
    from app.services import strategy_param_store as store

    def _boom(*a, **k):  # must never be reached
        raise AssertionError("store.adopt called without a direction")

    monkeypatch.setattr(store, "adopt", _boom)
    client = TestClient(app)
    r = client.post("/api/strategy-tuning/adopt",
                    json={"strategy": "pullback_ema", "params": {"ema_period": 20}})
    assert r.status_code == 422


def test_adopt_normalises_direction(monkeypatch):
    from app.services import strategy_param_store as store
    calls = []
    monkeypatch.setattr(store, "adopt", lambda s, p, direction: calls.append((s, p, direction)))
    monkeypatch.setattr(store, "get_active", lambda s, d="Bullish": {"ema_period": 20})
    client = TestClient(app)
    r = client.post("/api/strategy-tuning/adopt",
                    json={"strategy": "pullback_ema", "params": {"ema_period": 20},
                          "direction": "bearish"})
    assert r.status_code == 200
    assert calls == [("pullback_ema", {"ema_period": 20}, "Bearish")]


def test_adopt_rejects_unknown_direction(monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "adopt", lambda *a, **k: pytest.fail("adopt called"))
    client = TestClient(app)
    r = client.post("/api/strategy-tuning/adopt",
                    json={"strategy": "pullback_ema", "params": {"ema_period": 20},
                          "direction": "long"})
    assert r.status_code == 422
