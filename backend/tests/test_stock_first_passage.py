"""Stock first-passage estimator — the option-free sibling of estimate_first_passage."""
from __future__ import annotations

import pytest

from app.scoring.first_passage import estimate_stock_first_passage


def _candles(price: float = 100.0, n: int = 60, atr_pct: float = 0.02) -> list[dict]:
    band = price * atr_pct
    return [{"open": price, "high": price + band, "low": price - band,
             "close": price, "volume": 1_000_000} for _ in range(n)]


def test_nearer_targets_are_more_likely_than_farther_ones():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[102.0, 110.0, 125.0], candles=_candles(), horizon_days=10, seed=1,
    )
    probs = [t.probability for t in res.targets]
    assert probs == sorted(probs, reverse=True)
    assert 0.0 <= probs[-1] <= probs[0] <= 1.0


def test_bearish_targets_are_below_and_the_comparison_flips():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bearish", trend_score=80.0, stop_price=105.0,
        targets=[98.0, 90.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.targets[0].probability >= res.targets[1].probability
    # trend_score is direction-ALIGNED: 80 on a Bearish scan means "strongly
    # bearish", so the drift must point down. (An earlier draft asserted this
    # with trend_score=20, which yields mu = -1 * -0.6 * 0.4 = +0.24 — an UPWARD
    # drift, and the assertion would have failed.)
    assert res.mu < 0


def test_an_unfavourable_trend_score_drifts_against_the_trade():
    """The mirror of the above, pinned so the sign convention can't silently flip."""
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bearish", trend_score=20.0, stop_price=105.0,
        targets=[90.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.mu > 0


def test_is_deterministic_for_a_given_seed():
    kwargs = dict(stock_price=100.0, direction="Bullish", trend_score=55.0,
                  stop_price=96.0, targets=[105.0], candles=_candles(), horizon_days=10)
    a = estimate_stock_first_passage(**kwargs, seed=42)
    b = estimate_stock_first_passage(**kwargs, seed=42)
    assert a.targets[0].probability == b.targets[0].probability
    assert a.targets[0].expected_days == b.targets[0].expected_days


def test_zero_horizon_returns_zero_probability_without_crashing():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[110.0], candles=_candles(), horizon_days=0, seed=1,
    )
    assert res.targets[0].probability == 0.0
    assert res.targets[0].expected_days is None
    assert res.invalidation.probability == 0.0


def test_non_positive_price_returns_zero_probability():
    res = estimate_stock_first_passage(
        stock_price=0.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[110.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.targets[0].probability == 0.0


def test_empty_candles_still_produce_a_floored_sigma():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=50.0, stop_price=95.0,
        targets=[110.0], candles=[], horizon_days=10, sigma_floor=0.10, seed=1,
    )
    assert res.sigma_stock == pytest.approx(0.10)


def test_bad_target_values_are_filtered_out():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[0.0, -5.0, float("nan"), 110.0], candles=_candles(),
        horizon_days=10, seed=1,
    )
    assert [t.price for t in res.targets] == [110.0]


def test_a_non_positive_stop_yields_no_invalidation_probability():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=0.0,
        targets=[110.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.invalidation.probability == 0.0
    assert res.invalidation.expected_days is None


def test_expected_days_never_exceeds_the_horizon_window():
    """expected_days is a 1-based TRADING-day index into a horizon_days-long
    simulation, so it can never exceed horizon_days — a regression here would
    mean the +1 offset or the argmax indexing drifted."""
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=90.0, stop_price=95.0,
        targets=[100.5], candles=_candles(), horizon_days=10, seed=7,
    )
    assert res.targets[0].expected_days is not None
    assert 1 <= res.targets[0].expected_days <= 10


def test_sigma_is_clamped_by_the_ceiling_on_a_wild_series():
    """A 40%-ATR series annualizes to ~6.3, far past any plausible vol — the
    ceiling must bind, or the GBM would simulate nonsense."""
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=50.0, stop_price=95.0,
        targets=[110.0], candles=_candles(atr_pct=0.40), horizon_days=10,
        sigma_ceiling=1.50, seed=1,
    )
    assert res.sigma_stock == pytest.approx(1.50)


# ── POST /api/stocks/first-passage ────────────────────────────────────────────

class TestStockFirstPassageEndpoint:
    """Route-level smoke tests. `fetch_candles_async` is patched out so the test
    never reaches a real market-data provider; everything downstream of it (the
    seed, the estimator, the caveat rule) is exercised for real."""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.stock_scan import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _post(self, **overrides):
        from unittest.mock import patch, AsyncMock
        payload = {
            "symbol": "AAPL", "direction": "Bullish", "horizon": "Swing",
            "strategy": "pullback_ema", "stock_price": 100.0, "stop_price": 95.0,
            "targets": [105.0, 110.0, 120.0], "trend_score": 70.0,
        }
        payload.update(overrides)
        with patch("app.routers.stock_scan.fetch_candles_async",
                   AsyncMock(return_value=_candles())):
            return self._client().post("/api/stocks/first-passage", json=payload)

    def test_returns_one_estimate_per_target(self):
        r = self._post()
        assert r.status_code == 200, r.text
        body = r.json()
        assert [t["price"] for t in body["targets"]] == [105.0, 110.0, 120.0]
        for t in body["targets"]:
            assert 0.0 <= t["probability"] <= 1.0
        assert 0.0 <= body["invalidation"]["probability"] <= 1.0

    def test_horizon_days_comes_from_scoring_rules(self):
        """Swing -> confidence_backtest.swing.n_days. Pinned so the Monte Carlo
        window can't silently decouple from the empirical confidence window."""
        from app.scoring.signal_confidence import load_backtest_cfg
        assert self._post(horizon="Swing").json()["horizonDays"] == \
            int(load_backtest_cfg("Swing")["n_days"])
        assert self._post(horizon="Position").json()["horizonDays"] == \
            int(load_backtest_cfg("Position")["n_days"])

    def test_mean_reversion_strategies_carry_the_gbm_caveat(self):
        from app.routers.stock_scan import _MEAN_REVERSION_CAVEAT
        assert self._post(strategy="mean_reversion_bb").json()["modelCaveat"] == \
            _MEAN_REVERSION_CAVEAT

    def test_trend_following_strategies_carry_no_caveat(self):
        assert self._post(strategy="breakout_base").json()["modelCaveat"] is None

    def test_identical_requests_return_identical_estimates(self):
        """The seed is derived from the request, so repeated presses of Estimate
        must not show the user drifting Monte Carlo noise."""
        assert self._post().json()["targets"] == self._post().json()["targets"]

    def test_a_non_positive_stop_is_rejected(self):
        assert self._post(stop_price=0.0).status_code == 422

    def test_an_empty_target_ladder_is_rejected(self):
        assert self._post(targets=[]).status_code == 422

    def test_an_out_of_range_trend_score_is_rejected(self):
        assert self._post(trend_score=150.0).status_code == 422
