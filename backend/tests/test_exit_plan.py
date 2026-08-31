import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.exit_plan import FinalStopResult, TargetRowResult, compute_final_stop, compute_target_row
from app.scoring.structural_stop import StructuralStop, find_structural_target

FIXTURES = Path(__file__).parent / "fixtures"

_DUMMY_CANDLES = [{"time": str(i), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(20)]


# ── find_structural_target ────────────────────────────────────────────────────

class TestFindStructuralTarget:
    def test_bullish_delegates_to_bearish_stop_search(self):
        """A bullish trade's target is the next resistance above entry — exactly
        find_structural_stop's own Bearish search."""
        with patch("app.scoring.structural_stop.find_structural_stop") as mock_stop:
            mock_stop.return_value = StructuralStop(
                price=110, source="order_block", confidence=80, distance_pct=10.0,
            )
            result = find_structural_target(_DUMMY_CANDLES, "Bullish", entry_price=100)
        mock_stop.assert_called_once_with(_DUMMY_CANDLES, "Bearish", 100)
        assert result.price == 110

    def test_bearish_delegates_to_bullish_stop_search(self):
        """A bearish trade's target is the next support below entry — exactly
        find_structural_stop's own Bullish search."""
        with patch("app.scoring.structural_stop.find_structural_stop") as mock_stop:
            mock_stop.return_value = StructuralStop(
                price=90, source="swing_low", confidence=60, distance_pct=10.0,
            )
            result = find_structural_target(_DUMMY_CANDLES, "Bearish", entry_price=100)
        mock_stop.assert_called_once_with(_DUMMY_CANDLES, "Bullish", 100)
        assert result.price == 90

    def test_returns_none_when_nothing_qualifies(self):
        with patch("app.scoring.structural_stop.find_structural_stop", return_value=None):
            result = find_structural_target(_DUMMY_CANDLES, "Bullish", entry_price=100)
        assert result is None


# ── compute_final_stop ────────────────────────────────────────────────────────

class TestComputeFinalStop:
    def test_structural_used_as_is_when_it_clears_the_atr_floor(self):
        """Structural stop (distance 10) is wider than the ATR floor
        (2.0 * 4 = 8) -> used as-is, tagged 'structural'."""
        with patch(
            "app.scoring.exit_plan.find_structural_stop",
            return_value=StructuralStop(price=90, source="order_block", confidence=80, distance_pct=10.0),
        ):
            result = compute_final_stop(_DUMMY_CANDLES, "Bullish", entry_price=100, atr=4.0, atr_multiplier=2.0)
        assert result.source == "structural"
        assert result.price == 90
        # atr_floor_price survives even though it lost the comparison (100 - 2*4 = 92).
        assert result.atr_floor_price == pytest.approx(92.0)

    def test_widened_to_atr_floor_when_structural_is_tighter(self):
        """Structural stop (distance 3) is tighter than the ATR floor
        (2.0 * 4 = 8) -> widened out to the floor, tagged 'atr_widened'."""
        with patch(
            "app.scoring.exit_plan.find_structural_stop",
            return_value=StructuralStop(price=97, source="swing_low", confidence=60, distance_pct=3.0),
        ):
            result = compute_final_stop(_DUMMY_CANDLES, "Bullish", entry_price=100, atr=4.0, atr_multiplier=2.0)
        assert result.source == "atr_widened"
        assert result.price == pytest.approx(92.0)   # 100 - 2*4
        assert result.atr_floor_price == pytest.approx(92.0)

    def test_widened_to_atr_floor_when_no_structural_level_found(self):
        """No structural candidate at all — a distinct path from 'structural
        existed but lost' above, since `structural` is None on the result too."""
        with patch("app.scoring.exit_plan.find_structural_stop", return_value=None):
            result = compute_final_stop(_DUMMY_CANDLES, "Bullish", entry_price=100, atr=4.0, atr_multiplier=2.0)
        assert result.source == "atr_widened"
        assert result.price == pytest.approx(92.0)
        assert result.atr_floor_price == pytest.approx(92.0)
        assert result.structural is None

    def test_bearish_floor_widens_upward(self):
        with patch("app.scoring.exit_plan.find_structural_stop", return_value=None):
            result = compute_final_stop(_DUMMY_CANDLES, "Bearish", entry_price=100, atr=4.0, atr_multiplier=2.0)
        assert result.source == "atr_widened"
        assert result.price == pytest.approx(108.0)   # 100 + 2*4
        assert result.atr_floor_price == pytest.approx(108.0)


# ── compute_target_row ────────────────────────────────────────────────────────

class TestComputeTargetRow:
    def _good_stop(self, price: float = 90.0):
        from app.scoring.exit_plan import FinalStopResult
        return FinalStopResult(
            price=price, source="structural",
            structural=StructuralStop(price=price, source="order_block", confidence=80, distance_pct=10.0),
            atr_floor_price=80.0,
        )

    def test_arithmetic_target_when_no_structural_level_ahead(self):
        stop = self._good_stop(90.0)  # stop distance = 10
        with patch("app.scoring.exit_plan.find_structural_target", return_value=None):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bullish", entry_price=100, final_stop=stop,
                atr=4.0, rr_ratio=2.0, snap_atr_multiplier=0.3,
            )
        assert row.tp_source == "arithmetic"
        assert row.price == pytest.approx(120.0)   # 100 + 2*10
        assert row.quality_good is True   # stop structural + no structural to overshoot
        # No structural candidate ahead -> distance_dollar is None, but
        # tolerance_dollar (the snap band) is always computable.
        assert row.distance_dollar is None
        assert row.tolerance_dollar == pytest.approx(1.2)   # 0.3 * 4

    def test_snaps_to_structural_level_within_atr_distance(self):
        stop = self._good_stop(90.0)   # arithmetic TP = 100 + 2*10 = 120
        with patch(
            "app.scoring.exit_plan.find_structural_target",
            return_value=StructuralStop(price=121.0, source="order_block", confidence=70, distance_pct=21.0),
        ):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bullish", entry_price=100, final_stop=stop,
                atr=4.0, rr_ratio=2.0, snap_atr_multiplier=0.3,  # snap distance = 1.2, |121-120|=1 <= 1.2
            )
        assert row.tp_source == "structural_snap"
        assert row.price == 121.0
        assert row.quality_good is True
        assert row.distance_dollar == pytest.approx(1.0)    # |121 - 120|
        assert row.tolerance_dollar == pytest.approx(1.2)   # 0.3 * 4
        assert row.distance_dollar <= row.tolerance_dollar

    def test_does_not_snap_when_structural_level_is_too_far(self):
        stop = self._good_stop(90.0)   # arithmetic TP = 120
        with patch(
            "app.scoring.exit_plan.find_structural_target",
            return_value=StructuralStop(price=130.0, source="order_block", confidence=70, distance_pct=30.0),
        ):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bullish", entry_price=100, final_stop=stop,
                atr=4.0, rr_ratio=2.0, snap_atr_multiplier=0.3,   # snap distance = 1.2, |130-120|=10 > 1.2
            )
        assert row.tp_source == "arithmetic"
        assert row.price == pytest.approx(120.0)
        # Arithmetic TP (120) sits before the real structural level (130) -> still good.
        assert row.quality_good is True
        assert row.distance_dollar == pytest.approx(10.0)   # |130 - 120|
        assert row.tolerance_dollar == pytest.approx(1.2)   # 0.3 * 4
        assert row.distance_dollar > row.tolerance_dollar

    def test_quality_fails_when_target_overshoots_structural_level(self):
        stop = self._good_stop(90.0)   # arithmetic TP = 120
        with patch(
            "app.scoring.exit_plan.find_structural_target",
            return_value=StructuralStop(price=105.0, source="order_block", confidence=70, distance_pct=5.0),
        ):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bullish", entry_price=100, final_stop=stop,
                atr=4.0, rr_ratio=2.0, snap_atr_multiplier=0.3,   # too far to snap, and arithmetic (120) > structural (105)
            )
        assert row.tp_source == "arithmetic"
        assert row.quality_good is False
        assert "target_beyond_structural" in row.quality_reasons

    def test_quality_fails_when_stop_was_atr_widened(self):
        from app.scoring.exit_plan import FinalStopResult
        widened_stop = FinalStopResult(price=92.0, source="atr_widened", structural=None, atr_floor_price=92.0)
        with patch("app.scoring.exit_plan.find_structural_target", return_value=None):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bullish", entry_price=100, final_stop=widened_stop,
                atr=4.0, rr_ratio=2.0, snap_atr_multiplier=0.3,
            )
        assert row.quality_good is False
        assert "stop_widened" in row.quality_reasons

    def test_bearish_target_direction(self):
        from app.scoring.exit_plan import FinalStopResult
        stop = FinalStopResult(price=110.0, source="structural", structural=None, atr_floor_price=110.0)  # stop distance = 10
        with patch("app.scoring.exit_plan.find_structural_target", return_value=None):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bearish", entry_price=100, final_stop=stop,
                atr=4.0, rr_ratio=3.0, snap_atr_multiplier=0.3,
            )
        assert row.price == pytest.approx(70.0)   # 100 - 3*10


# ── POST /api/contracts/exit-plan ─────────────────────────────────────────────

class TestEndpoint:
    def _client(self) -> TestClient:
        from app.routers.contracts import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_returns_stop_and_both_target_rows(self):
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["stop"]["source"] in ("structural", "atr_widened")
        assert body["stop"]["price"] < entry_price
        assert body["stop"]["contractPrice"] > 0
        assert body["stop"]["rrModel"] in ("Heston repriced", "BS repriced (IV-derived)", "Delta approximation")

        assert len(body["targets"]) == 2
        assert [t["rrRatio"] for t in body["targets"]] == [2.0, 3.0]
        for t in body["targets"]:
            assert t["price"] > entry_price
            assert t["tpSource"] in ("arithmetic", "structural_snap")
            assert 0.0 <= t["probability"] <= 1.0
            assert isinstance(t["qualityGood"], bool)
        # A larger R:R ratio must produce a farther (or equal, if both snap to
        # the same structural level) target than a smaller one.
        assert body["targets"][1]["price"] >= body["targets"][0]["price"]

        assert body["atr"] >= 0

    def test_bearish_targets_are_below_entry(self):
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bearish", "entry_price": entry_price,
                "strike": round(entry_price * 0.95), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stop"]["price"] > entry_price
        for t in body["targets"]:
            assert t["price"] < entry_price

    def test_rejects_nonpositive_entry_price(self):
        r = self._client().post("/api/contracts/exit-plan", json={
            "symbol": "AAPL", "direction": "Bullish", "entry_price": 0,
            "strike": 105, "dte": 30, "premium": 2.50, "trend_score": 65,
        })
        assert r.status_code == 422

    def test_rejects_out_of_range_trend_score(self):
        r = self._client().post("/api/contracts/exit-plan", json={
            "symbol": "AAPL", "direction": "Bullish", "entry_price": 100,
            "strike": 105, "dte": 30, "premium": 2.50, "trend_score": 150,
        })
        assert r.status_code == 422

    def test_rejects_when_no_candle_history_is_available(self):
        """Empty candles would otherwise silently collapse the ATR floor to 0
        (entry_price exactly) and produce a zero-width stop/every target
        landing on entry_price — reject explicitly instead of returning a
        plan built on no data at all."""
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=[])):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": 100,
                "strike": 105, "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 422
        assert "insufficient" in r.json()["detail"].lower()

    def test_rejects_when_candle_history_is_a_single_bar(self):
        with patch(
            "app.routers.contracts.fetch_candles_async",
            AsyncMock(return_value=[{"time": "1", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}]),
        ):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": 100,
                "strike": 105, "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 422

    def test_rejects_when_candle_history_is_flat_with_zero_atr(self):
        """20 flat/duplicated OHLC candles pass the len(candles) < 2 guard but
        still collapse ATR(14) to exactly 0 — the same zero-width-stop
        outcome the candle-count guard exists to prevent, reached a
        different way (e.g. a stale or duplicated upstream data-feed
        response). Reject explicitly rather than return a "computed" plan
        with every target landing on entry_price."""
        flat_candles = [
            {"time": str(i), "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000}
            for i in range(20)
        ]
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=flat_candles)):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": 100,
                "strike": 105, "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 422
        assert "insufficient" in r.json()["detail"].lower()

    def test_target_row_below_current_premium_is_not_scored_as_high_probability(self, monkeypatch):
        """A target whose repriced contract value doesn't exceed the current
        premium (net loss from time decay outweighing the favorable move) must
        not be run through first_passage — that simulation would trivially
        report ~100% probability at ~day 1 since the "target" is already at or
        below where day 1's repriced value typically sits, which would
        misrepresent a loss as a near-certain profit target."""
        import app.routers.contracts as contracts_module
        from app.scoring.reward_risk import RrResult

        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]

        # Force every repricing call to return a value at/below current premium.
        monkeypatch.setattr(
            contracts_module, "estimate_rr",
            lambda **kwargs: RrResult(rr_ratio=0.0, model_used="BS repriced (IV-derived)", estimated_exit_premium=2.50),
        )
        fp_spy_calls = []
        real_fp = contracts_module.estimate_first_passage
        def _spy(**kwargs):
            fp_spy_calls.append(kwargs)
            return real_fp(**kwargs)
        monkeypatch.setattr(contracts_module, "estimate_first_passage", _spy)

        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        body = r.json()
        for t in body["targets"]:
            assert t["probability"] == 0.0
            assert t["expectedDays"] is None
        assert fp_spy_calls == []

    # ── new exit-plan-restructure fields (atrFloorPrice / structuralPrice /
    #    distanceDollar on the stop; distanceDollar / toleranceDollar on each
    #    target row) — compute_final_stop/compute_target_row are mocked so
    #    each branch is exercised deterministically rather than depending on
    #    whatever the AAPL fixture happens to produce. ──────────────────────

    def test_stop_structural_branch_exposes_new_fields(self):
        """structural wins: atrFloorPrice must still be populated with the
        value that LOST the comparison, and distanceDollar is the gap between
        the two candidate stop prices."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]

        fake_final_stop = FinalStopResult(
            price=entry_price - 10.0, source="structural",
            structural=StructuralStop(price=entry_price - 10.0, source="order_block", confidence=80, distance_pct=10.0),
            atr_floor_price=entry_price - 6.0,
        )
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.compute_final_stop", return_value=fake_final_stop):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        stop = r.json()["stop"]
        assert stop["source"] == "structural"
        assert stop["structuralPrice"] == pytest.approx(round(entry_price - 10.0, 2))
        assert stop["atrFloorPrice"] == pytest.approx(round(entry_price - 6.0, 2))
        assert stop["distanceDollar"] == pytest.approx(4.0)

    def test_stop_atr_widened_branch_when_structural_candidate_exists_but_loses(self):
        """atr_widened with a structural candidate that lost the comparison:
        structuralPrice must still surface the losing candidate's price (not
        None — it's a real level, it just didn't clear the ATR floor), and
        atrFloorPrice equals the final stop price."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]

        fake_final_stop = FinalStopResult(
            price=entry_price - 6.0, source="atr_widened",
            structural=StructuralStop(price=entry_price - 2.0, source="swing_low", confidence=50, distance_pct=2.0),
            atr_floor_price=entry_price - 6.0,
        )
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.compute_final_stop", return_value=fake_final_stop):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        stop = r.json()["stop"]
        assert stop["source"] == "atr_widened"
        assert stop["structuralPrice"] == pytest.approx(round(entry_price - 2.0, 2))
        assert stop["atrFloorPrice"] == pytest.approx(round(entry_price - 6.0, 2))
        assert stop["distanceDollar"] == pytest.approx(4.0)

    def test_stop_atr_widened_branch_when_no_structural_candidate(self):
        """atr_widened with no structural candidate at all (find_structural_stop
        returned None) — a genuinely separate case from 'structural existed but
        lost' above: structuralPrice and distanceDollar must both be None,
        while atrFloorPrice is still populated."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]

        fake_final_stop = FinalStopResult(
            price=entry_price - 6.0, source="atr_widened", structural=None,
            atr_floor_price=entry_price - 6.0,
        )
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.compute_final_stop", return_value=fake_final_stop):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        stop = r.json()["stop"]
        assert stop["source"] == "atr_widened"
        assert stop["structuralPrice"] is None
        assert stop["distanceDollar"] is None
        assert stop["atrFloorPrice"] == pytest.approx(round(entry_price - 6.0, 2))

    def test_target_row_snapped_exposes_distance_and_tolerance(self):
        """A target row that snapped to a structural level: distanceDollar is
        the gap that was within the tolerance band, both fields threaded
        through verbatim from compute_target_row."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]

        fake_row = TargetRowResult(
            rr_ratio=2.0, arithmetic_price=entry_price + 20.0, price=entry_price + 21.0,
            tp_source="structural_snap",
            structural=StructuralStop(price=entry_price + 21.0, source="order_block", confidence=70, distance_pct=21.0),
            distance_dollar=1.0, tolerance_dollar=1.2,
            quality_good=True, quality_reasons=[],
        )
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.compute_target_row", return_value=fake_row):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        for t in r.json()["targets"]:
            assert t["tpSource"] == "structural_snap"
            assert t["distanceDollar"] == pytest.approx(1.0)
            assert t["toleranceDollar"] == pytest.approx(1.2)
            assert t["distanceDollar"] <= t["toleranceDollar"]

    def test_target_row_not_snapped_exposes_distance_and_tolerance(self):
        """A target row that did NOT snap (structural candidate existed but was
        outside the tolerance band): distanceDollar is still populated, and is
        greater than toleranceDollar."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]

        fake_row = TargetRowResult(
            rr_ratio=2.0, arithmetic_price=entry_price + 20.0, price=entry_price + 20.0,
            tp_source="arithmetic",
            structural=StructuralStop(price=entry_price + 30.0, source="order_block", confidence=70, distance_pct=30.0),
            distance_dollar=10.0, tolerance_dollar=1.2,
            quality_good=False, quality_reasons=["target_beyond_structural"],
        )
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.compute_target_row", return_value=fake_row):
            r = self._client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "strike": round(entry_price * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65,
            })
        assert r.status_code == 200, r.text
        for t in r.json()["targets"]:
            assert t["tpSource"] == "arithmetic"
            assert t["distanceDollar"] == pytest.approx(10.0)
            assert t["toleranceDollar"] == pytest.approx(1.2)
            assert t["distanceDollar"] > t["toleranceDollar"]
