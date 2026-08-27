import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.exit_plan import compute_final_stop, compute_target_row
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

    def test_widened_to_atr_floor_when_no_structural_level_found(self):
        with patch("app.scoring.exit_plan.find_structural_stop", return_value=None):
            result = compute_final_stop(_DUMMY_CANDLES, "Bullish", entry_price=100, atr=4.0, atr_multiplier=2.0)
        assert result.source == "atr_widened"
        assert result.price == pytest.approx(92.0)

    def test_bearish_floor_widens_upward(self):
        with patch("app.scoring.exit_plan.find_structural_stop", return_value=None):
            result = compute_final_stop(_DUMMY_CANDLES, "Bearish", entry_price=100, atr=4.0, atr_multiplier=2.0)
        assert result.source == "atr_widened"
        assert result.price == pytest.approx(108.0)   # 100 + 2*4


# ── compute_target_row ────────────────────────────────────────────────────────

class TestComputeTargetRow:
    def _good_stop(self, price: float = 90.0):
        from app.scoring.exit_plan import FinalStopResult
        return FinalStopResult(
            price=price, source="structural",
            structural=StructuralStop(price=price, source="order_block", confidence=80, distance_pct=10.0),
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
        widened_stop = FinalStopResult(price=92.0, source="atr_widened", structural=None)
        with patch("app.scoring.exit_plan.find_structural_target", return_value=None):
            row = compute_target_row(
                _DUMMY_CANDLES, "Bullish", entry_price=100, final_stop=widened_stop,
                atr=4.0, rr_ratio=2.0, snap_atr_multiplier=0.3,
            )
        assert row.quality_good is False
        assert "stop_widened" in row.quality_reasons

    def test_bearish_target_direction(self):
        from app.scoring.exit_plan import FinalStopResult
        stop = FinalStopResult(price=110.0, source="structural", structural=None)  # stop distance = 10
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
