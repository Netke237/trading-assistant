import json
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.black_scholes import bs_price
from app.scoring.first_passage import (
    _vectorized_bs_price,
    _solve_target_stock_price,
    estimate_first_passage,
)

FIXTURES = Path(__file__).parent / "fixtures"

_FLAT_CANDLES = [
    {"time": str(i), "open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0, "volume": 1_000_000}
    for i in range(30)
]


class TestVectorizedBsPriceAgreesWithScalar:
    """The audit-fix test: this would have caught the vectorization bug had
    it shipped (bs_price's math.log/math.sqrt calls raise on an ndarray)."""

    @pytest.mark.parametrize("K,T,r,sigma,is_call", [
        (100.0, 30 / 365, 0.05, 0.25, True),
        (100.0, 30 / 365, 0.05, 0.25, False),
        (150.0, 90 / 365, 0.05, 0.60, True),
        (50.0, 5 / 365, 0.05, 0.15, False),
        (100.0, 1.0, 0.05, 1.2, True),
    ])
    def test_agrees_across_price_grid(self, K, T, r, sigma, is_call):
        S_grid = np.array([50.0, 75.0, 90.0, 100.0, 110.0, 125.0, 150.0, 200.0])
        vectorized = _vectorized_bs_price(S_grid, K, T, r, sigma, is_call)
        for i, S in enumerate(S_grid):
            scalar = bs_price(float(S), K, T, r, sigma, is_call)
            assert vectorized[i] == pytest.approx(scalar, abs=1e-8)

    def test_zero_time_returns_zeros(self):
        S_grid = np.array([90.0, 100.0, 110.0])
        result = _vectorized_bs_price(S_grid, 100.0, 0.0, 0.05, 0.25, True)
        assert (result == 0.0).all()


class TestSolveTargetStockPrice:
    def test_call_solves_to_higher_stock_price_for_higher_profit(self):
        s20 = _solve_target_stock_price(100.0, 105.0, 30 / 365, 0.05, 0.30, True, 2.50 * 1.20)
        s50 = _solve_target_stock_price(100.0, 105.0, 30 / 365, 0.05, 0.30, True, 2.50 * 1.50)
        assert s20 is not None and s50 is not None
        assert s50 > s20

    def test_put_solves_to_lower_stock_price_for_higher_profit(self):
        s20 = _solve_target_stock_price(100.0, 95.0, 30 / 365, 0.05, 0.30, False, 2.50 * 1.20)
        s50 = _solve_target_stock_price(100.0, 95.0, 30 / 365, 0.05, 0.30, False, 2.50 * 1.50)
        assert s20 is not None and s50 is not None
        assert s50 < s20

    def test_returns_none_when_target_unreachable_in_bracket(self):
        # A target option price far above what bs_price can reach anywhere in
        # [stock_price*0.01, stock_price*5] at this short a horizon.
        result = _solve_target_stock_price(100.0, 100.0, 1 / 365, 0.05, 0.20, True, 10_000.0)
        assert result is None

    def test_solution_actually_reprices_to_target(self):
        target = 2.50 * 1.35
        s = _solve_target_stock_price(100.0, 105.0, 30 / 365, 0.05, 0.30, True, target)
        assert s is not None
        assert bs_price(s, 105.0, 30 / 365, 0.05, 0.30, True) == pytest.approx(target, abs=1e-3)


class TestEstimateFirstPassage:
    def _run(self, **overrides):
        base = dict(
            stock_price=100.0, strike=105.0, dte=45, premium=2.50, delta=0.35,
            is_call=True, trend_score=75, invalidation_price=95.0, candles=_FLAT_CANDLES,
            t1_pct=0.20, t2_pct=0.35, t3_pct=0.50, seed=42,
        )
        base.update(overrides)
        return estimate_first_passage(**base)

    def test_returns_three_targets(self):
        result = self._run()
        assert len(result.targets) == 3
        assert [t.pct for t in result.targets] == [0.20, 0.35, 0.50]

    def test_higher_profit_pct_has_lower_probability(self):
        result = self._run()
        probs = [t.probability for t in result.targets]
        assert probs[0] >= probs[1] >= probs[2]

    def test_higher_profit_pct_takes_longer_when_both_hit(self):
        result = self._run()
        days = [t.expected_days for t in result.targets]
        assert all(d is not None for d in days)
        assert days[0] <= days[1] <= days[2]

    def test_same_seed_is_deterministic(self):
        a = self._run(seed=7)
        b = self._run(seed=7)
        assert a.targets == b.targets
        assert a.invalidation == b.invalidation

    def test_different_seed_can_differ(self):
        a = self._run(seed=1)
        b = self._run(seed=2)
        # Not a strict guarantee for any RNG, but true with overwhelming
        # probability for 2000 paths — a regression to "always identical
        # regardless of seed" would be a real bug (e.g. seed silently ignored).
        assert a.targets != b.targets or a.invalidation != b.invalidation

    def test_zero_dte_guard_returns_zero_probability_no_crash(self):
        result = self._run(dte=0)
        assert all(t.probability == 0.0 and t.expected_days is None for t in result.targets)
        assert result.invalidation.probability == 0.0
        assert result.invalidation.expected_days is None

    def test_mu_zero_at_neutral_trend_score(self):
        result = self._run(trend_score=50)
        assert result.mu == pytest.approx(0.0)

    def test_mu_positive_for_bullish_strong_trend(self):
        result = self._run(is_call=True, trend_score=100, max_drift_pct=0.40)
        assert result.mu == pytest.approx(0.40)

    def test_mu_sign_flips_for_bearish(self):
        result = self._run(is_call=False, trend_score=100, max_drift_pct=0.40)
        assert result.mu == pytest.approx(-0.40)

    def test_sigma_stock_respects_floor_and_ceiling(self):
        flat = [
            {"time": str(i), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1}
            for i in range(20)
        ]
        result = self._run(candles=flat, sigma_floor=0.10, sigma_ceiling=1.50)
        assert result.sigma_stock == pytest.approx(0.10)   # zero ATR -> floors

    def test_put_invalidation_is_above_price(self):
        result = self._run(is_call=False, invalidation_price=105.0, strike=95.0)
        assert result.invalidation.probability >= 0.0   # just must not crash / be nonsensical

    def test_performance_is_well_under_a_couple_seconds(self):
        start = time.time()
        self._run(dte=90)
        elapsed = time.time() - start
        assert elapsed < 2.0


class TestEndpoint:
    def _client(self) -> TestClient:
        from app.routers.contracts import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_returns_targets_and_invalidation(self):
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=_FLAT_CANDLES)):
            r = self._client().post("/api/contracts/first-passage", json={
                "symbol": "AAPL", "direction": "Bullish", "stock_price": 100.0,
                "strike": 105.0, "dte": 45, "premium": 2.50, "delta": 0.35,
                "trend_score": 75, "invalidation_price": 95.0,
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["targets"]) == 3
        assert body["targets"][0]["pct"] == pytest.approx(0.20)   # YAML default
        assert body["targets"][1]["pct"] == pytest.approx(0.35)
        assert body["targets"][2]["pct"] == pytest.approx(0.50)
        assert "probability" in body["invalidation"]
        assert "expectedDays" in body["invalidation"]

    def test_custom_pcts_override_yaml_defaults(self):
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=_FLAT_CANDLES)):
            r = self._client().post("/api/contracts/first-passage", json={
                "symbol": "AAPL", "direction": "Bullish", "stock_price": 100.0,
                "strike": 105.0, "dte": 45, "premium": 2.50, "delta": 0.35,
                "trend_score": 75, "invalidation_price": 95.0,
                "t1_pct": 0.10, "t2_pct": 0.25, "t3_pct": 0.40,
            })
        assert r.status_code == 200, r.text
        pcts = [t["pct"] for t in r.json()["targets"]]
        assert pcts == [pytest.approx(0.10), pytest.approx(0.25), pytest.approx(0.40)]

    def test_same_request_is_deterministic(self):
        payload = {
            "symbol": "AAPL", "direction": "Bullish", "stock_price": 100.0,
            "strike": 105.0, "dte": 45, "premium": 2.50, "delta": 0.35,
            "trend_score": 75, "invalidation_price": 95.0,
        }
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=_FLAT_CANDLES)):
            client = self._client()
            r1 = client.post("/api/contracts/first-passage", json=payload)
            r2 = client.post("/api/contracts/first-passage", json=payload)
        assert r1.json() == r2.json()

    def test_seed_is_a_fixed_sha256_derivation_not_pythons_salted_hash(self):
        """Regression guard for the hash()->hashlib.sha256() fix: two requests
        agreeing within one test process (test_same_request_is_deterministic,
        above) can NEVER distinguish a per-process-salted hash() from a truly
        stable one -- hash()'s salt is fixed for the process's whole lifetime,
        so it looks deterministic to any single-process test regardless of
        which formula is used. The only way to prove the seed doesn't depend
        on process-local salt is to pin it against an independently-computed,
        salt-free value. If contracts.py ever reverts to hash(), this fails:
        hash()'s output has no relationship to sha256's, so it would take
        the same 1-in-2^32 luck as the pre-fix bug ever matching by accident."""
        import hashlib
        from app.scoring import first_passage as fp_module

        payload = {
            "symbol": "AAPL", "direction": "Bullish", "stock_price": 100.0,
            "strike": 105.0, "dte": 45, "premium": 2.50, "delta": 0.35,
            "trend_score": 75, "invalidation_price": 95.0,
        }
        # Mirrors contracts.py's own seed_key construction exactly (including
        # falling back to the YAML target_t1/t2/t3_pct defaults, since this
        # payload doesn't override them).
        #
        # premium_stop_pct is deliberately ABSENT — see the long note at the
        # seed_key construction. It is a post-hoc barrier over already-simulated
        # paths, so moving it changes the answer at a fixed seed anyway, while
        # including it re-rolled the whole simulation every time the live quote
        # moved a cent and shifted unrelated Monte Carlo probabilities with it.
        expected_seed_key = "AAPL|105.0|45|100.0|0.2|0.35|0.5"
        expected_seed = int(hashlib.sha256(expected_seed_key.encode()).hexdigest(), 16) % (2 ** 32)

        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=_FLAT_CANDLES)), \
             patch("app.routers.contracts.estimate_first_passage", wraps=fp_module.estimate_first_passage) as spy:
            r = self._client().post("/api/contracts/first-passage", json=payload)
        assert r.status_code == 200, r.text
        assert spy.call_args.kwargs["seed"] == expected_seed

    def test_rejects_nonpositive_stock_price(self):
        r = self._client().post("/api/contracts/first-passage", json={
            "symbol": "AAPL", "direction": "Bullish", "stock_price": 0,
            "strike": 105.0, "dte": 45, "premium": 2.50, "delta": 0.35,
            "trend_score": 75, "invalidation_price": 95.0,
        })
        assert r.status_code == 422

    def test_rejects_out_of_range_trend_score(self):
        r = self._client().post("/api/contracts/first-passage", json={
            "symbol": "AAPL", "direction": "Bullish", "stock_price": 100.0,
            "strike": 105.0, "dte": 45, "premium": 2.50, "delta": 0.35,
            "trend_score": 150, "invalidation_price": 95.0,
        })
        assert r.status_code == 422
