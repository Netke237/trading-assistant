"""The scan card's sizing when the symbol's own regime cannot be measured.

`_process_stock` sized an unmeasured symbol (15-min fetch failed, fewer than
min_obs bars, compute_omm returned nothing) at FULL size:
`mult = conviction_mult(...) if regime_signal else 1.0`. The auto-trader floors
the same case at min_mult (decision SIZING-4-UNMEASURED-FLOOR-2026-09-24), and
the card's `shares` is what StockSendDialog sends to the broker. These pin the
card to the same floor.

Harness: tests/test_confidence_gate_stocks.py's `_process_stock` patches.
Signal entry 152 / stop 148 -> 4.00 risk per share; account 50_000 at 1% ->
500 risk budget -> 125 shares at full size.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.routers.stock_scan as _router_mod
from app.schemas.stock_scan import PositionCardOut, StockScanRequest
from app.scoring.conviction_sizing import conviction_mult
from tests.test_confidence_gate_stocks import (
    _make_fake_bars, _make_fake_bt, _make_fake_card, _make_fake_signal,
)

_ON = {"enabled": True, "min_mult": 0.3, "full_conviction_pct": 40}
_FULL_SHARES = 125  # 50_000 * 0.01 / (152 - 148)


def _omm(conviction_pct: int):
    return SimpleNamespace(
        state="Bull", p_stay=0.9, stability="Stable", regime_age_days=5,
        avg_regime_duration=10.0, conviction_pct=conviction_pct,
        conviction_label="Moderate", interpretation="test",
    )


def _run(sizing, omm_result, **req_kw):
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        **req_kw,
    )
    cfg = dict(_router_mod._load_full_scoring_cfg())
    cfg["regime_sizing"] = sizing
    fake_signal = _make_fake_signal()

    async def run():
        with patch("app.routers.stock_scan.get_daily_regime_bars",
                   new=AsyncMock(return_value=_make_fake_bars())), \
             patch("app.routers.stock_scan.get_historical_bars",
                   new=AsyncMock(return_value=_make_fake_bars())), \
             patch("app.routers.stock_scan.fetch_company_name_async",
                   new=AsyncMock(return_value="Apple Inc")), \
             patch("app.routers.stock_scan.fetch_price_async", new=AsyncMock(return_value=152.0)), \
             patch("app.routers.stock_scan.score_stock", return_value=_make_fake_card()), \
             patch("app.routers.stock_scan.compute_omm", return_value=omm_result), \
             patch("app.routers.stock_scan.compute_directional_hmm", side_effect=RuntimeError), \
             patch("app.routers.stock_scan._get_fundamentals", new=AsyncMock(return_value=None)), \
             patch.object(_router_mod, "_SIGNAL_FNS", {"pullback_ema": lambda *a, **kw: fake_signal}), \
             patch("app.routers.stock_scan._get_backtest_cached", return_value=_make_fake_bt()), \
             patch("app.routers.stock_scan.get_cached",
                   return_value={"confidence": 60, "sample_size": 50}), \
             patch("app.routers.stock_scan._load_full_scoring_cfg", return_value=cfg):
            return await _router_mod._process_stock("AAPL", req, "scan-1", {}, [])

    result = asyncio.run(run())
    assert isinstance(result, PositionCardOut), result
    return result


def test_an_unmeasured_symbol_is_sized_at_the_floor_not_full():
    card = _run(_ON, omm_result=None)
    assert card.sentiment is None  # really unmeasured
    assert card.sizing_basis == "floor:unmeasured"
    assert card.dollar_risk == pytest.approx(150.0)  # 500 * 0.3
    assert card.shares == int(150.0 / 4.0)
    assert card.shares < _FULL_SHARES


def test_a_measured_symbol_still_rides_the_ramp():
    card = _run(_ON, omm_result=_omm(20))
    assert card.sizing_basis == "measured"
    mult = conviction_mult(20, _ON)
    assert card.dollar_risk == pytest.approx(round(500 * mult, 2))
    assert card.shares == int(500 * mult / 4.0)


@pytest.mark.parametrize("sizing", [None, {"enabled": False}])
def test_sizing_off_is_still_full_size_when_unmeasured(sizing):
    card = _run(sizing, omm_result=None)
    assert card.sizing_basis == "off"
    assert card.shares == _FULL_SHARES
    assert card.dollar_risk == pytest.approx(500.0)
