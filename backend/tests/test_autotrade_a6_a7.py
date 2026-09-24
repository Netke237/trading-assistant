"""AUTOTRADE-A6-A7-GATES-AND-RECORDS (2026-09-24).

Pins the pieces of this lane that the flipped tests in test_auto_trader.py and
test_premium_stop_per_position.py do not:

- oq 2: an unexpected exception from `_apply_vol_sizing` leaves a row.
- oq 5: `cap_blocked` and `daily_loss_blocked` rows carry `error`.
- A7a: the `not_submitted` row carries the gate's and the sizer's VALUES.
- A7b: POST /auto-trade/fire answers a SizingConfigError with a 500 whose
  detail prefix the frontend reads as "refused".
- A6 end to end: a fire that fits under a stop-scaled count but not under the
  full premium is refused before the broker.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import app.services.auto_trader as at
from app.data.ibkr_paper import OrderResult
from app.scoring.conviction_sizing import SizingConfigError
from app.services.auto_trader import (
    ArmedStrategy,
    AutoTradeService,
    OrderNotSubmittedError,
    RegimeGateConfigError,
)


def _armed(symbol="MSFT", premium=2.50, qty=1, pv=100_000.0, **kw):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=qty, order_type="LMT",
        limit_price=premium, conid=None,
        entry_premium=premium, portfolio_value=pv, **kw,
    )


def _service(mocker, strategy=None, sizing=lambda s: s):
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", sizing)
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 1.0}))
    svc = AutoTradeService()
    svc.arm(strategy or _armed())
    return svc


# ── oq 2: the catch-all row ──────────────────────────────────────────────────

def test_an_unexpected_sizing_exception_leaves_a_row(mocker):
    execute = mocker.patch.object(at, "execute_option_order")

    def _boom(s):
        raise KeyError("regime_sizing")

    svc = _service(mocker, sizing=_boom)
    with pytest.raises(KeyError):
        svc.fire(attempt_id="a-boom")

    execute.assert_not_called()
    state = svc.get_state()
    assert state.armed is False
    row = state.history[-1]
    assert row["attempt_id"] == "a-boom"
    assert row["status"] == "risk_check_failed"
    assert row["order_id"] is None
    assert row["premium_at_risk"] == 0.0
    assert "sizing/regime check failed" in row["error"]
    assert "regime_sizing" in row["error"]


def test_the_catch_all_does_not_swallow_the_named_refusals(mocker):
    """Ordered LAST: each named class keeps its own status."""
    for exc, status in (
        (SizingConfigError("bad block"), "sizing_config_blocked"),
        (ValueError("nan conviction"), "sizing_data_blocked"),
        (RegimeGateConfigError("no threshold"), "regime_gate_config_blocked"),
    ):
        def _raise(s, exc=exc):
            raise exc
        svc = _service(mocker, sizing=_raise)
        with pytest.raises(type(exc)):
            svc.fire()
        assert svc.get_state().history[-1]["status"] == status


def test_the_catch_all_row_routes_to_the_unclassified_alert(mocker):
    def _boom(s):
        raise KeyError("x")

    svc = _service(mocker, sizing=_boom)
    mocker.patch.object(at, "execute_option_order")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")
    sizing_alert = mocker.patch.object(at, "_alert_sizing_config_refusal")

    svc.maybe_fire_on_scan()

    assert unclassified.call_count == 1
    assert sizing_alert.call_count == 0


# ── oq 5: `error` on the risk-limit rows ─────────────────────────────────────

def test_cap_blocked_row_carries_the_reason(mocker):
    svc = _service(mocker)
    mocker.patch.object(AutoTradeService, "_check_exposure",
                        side_effect=RuntimeError("Exposure cap breach: ['too big']"))
    with pytest.raises(RuntimeError):
        svc.fire(portfolio_snapshot=[], portfolio_value=100_000.0)
    row = svc.get_state().history[-1]
    assert row["status"] == "cap_blocked"
    assert row["error"] == "Exposure cap breach: ['too big']"


def test_daily_loss_blocked_row_carries_the_reason(mocker):
    svc = _service(mocker)
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 0.0001}))
    with pytest.raises(RuntimeError, match="Daily loss limit reached"):
        svc.fire(portfolio_value=100_000.0)
    row = svc.get_state().history[-1]
    assert row["status"] == "daily_loss_blocked"
    assert row["error"].startswith("Daily loss limit reached")


# ── A6 end to end ─────────────────────────────────────────────────────────────

def test_a_declared_stop_no_longer_lets_a_trade_through(mocker):
    """limit = 0.002 x 100_000 = $200. Premium $2.50 x 1 x 100 = $250.
    Under the old rule a declared 0.30 stop counted $75 and fired; now it is
    refused before the broker, like the undeclared trade."""
    execute = mocker.patch.object(at, "execute_option_order",
                                  return_value=OrderResult("o", "filled", "ibkr_paper"))
    svc = _service(mocker, strategy=_armed(premium_stop_pct=0.30))
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 0.002,
                                              "premium_stop_pct": 0.60}))
    with pytest.raises(RuntimeError, match="Daily loss limit reached: 250 at risk"):
        svc.fire(portfolio_value=100_000.0)
    execute.assert_not_called()


def test_todays_full_premium_rows_spend_the_budget(mocker):
    """Two $250 fires against a $400 limit: the first books $250 on its row,
    so the second is refused -- the sum the gate reads is the full premium."""
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o", "filled", "ibkr_paper"))
    svc = _service(mocker)
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 0.004}))
    svc.fire(portfolio_value=100_000.0)
    assert svc.get_state().history[-1]["premium_at_risk"] == pytest.approx(250.0)
    svc.arm(_armed(premium_stop_pct=0.10))
    with pytest.raises(RuntimeError, match="Daily loss limit reached: 500 at risk"):
        svc.fire(portfolio_value=100_000.0)


# ── A7a: not_submitted carries the gate and the sizing VALUES ────────────────

def test_not_submitted_row_records_what_the_gate_and_sizer_decided(mocker):
    def _sized(s):
        return dataclasses.replace(s, regime_gate_outcome="caution",
                                   sizing_basis="floor:unmeasured")

    svc = _service(mocker, sizing=_sized)
    mocker.patch.object(at, "execute_option_order",
                        side_effect=OrderNotSubmittedError("credentials expired"))
    with pytest.raises(RuntimeError, match="Order not submitted"):
        svc.fire()
    row = svc.get_state().history[-1]
    assert row["status"] == "not_submitted"
    assert row["regime_gate"] == "caution"
    assert row["sizing"] == "floor:unmeasured"
    assert row["premium_at_risk"] == 0.0


# ── A7b: the sizing-config 500 on POST /auto-trade/fire ──────────────────────

class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDb:
    async def execute(self, *a, **k):
        return _FakeResult()


@pytest.mark.asyncio
async def test_fire_endpoint_maps_a_sizing_config_error_to_500(mocker):
    """Through the REAL fire(): the refusal lands after the disarm, before the
    broker, and the endpoint answers 500 with the prefix."""
    from app.routers import auto_trade as rt

    def _broken(s):
        raise SizingConfigError("regime_sizing.min_mult must be <= 1")

    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", _broken)
    execute = mocker.patch.object(at, "execute_option_order")
    book = mocker.patch.object(rt, "book_fired_order", AsyncMock())
    rt.auto_trader.arm(_armed())
    try:
        with pytest.raises(HTTPException) as ei:
            await rt.fire_now(db=_FakeDb())
    finally:
        rt.auto_trader.disarm()

    assert ei.value.status_code == 500
    assert ei.value.detail == (rt.SIZING_CONFIG_REFUSED_PREFIX
                               + "regime_sizing.min_mult must be <= 1")
    execute.assert_not_called()
    book.assert_not_called()
    assert rt.auto_trader.get_state().history[-1]["status"] == "sizing_config_blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    ValueError("the regime conviction is not a usable number"),
    RegimeGateConfigError("regime_gate missing a threshold"),
    RuntimeError("Exposure cap breach: []"),
])
async def test_other_refusals_stay_400(mocker, exc):
    """Only SizingConfigError moved. A sizing DATA fault (ValueError) and a
    regime_gate config fault were not part of decision A7b."""
    from app.routers import auto_trade as rt
    mocker.patch.object(rt.auto_trader, "fire", side_effect=exc)
    rt.auto_trader.arm(_armed())
    try:
        with pytest.raises(HTTPException) as ei:
            await rt.fire_now(db=_FakeDb())
    finally:
        rt.auto_trader.disarm()
    assert ei.value.status_code == 400
    assert not ei.value.detail.startswith(rt.SIZING_CONFIG_REFUSED_PREFIX)


def test_the_prefix_is_the_one_the_frontend_reads():
    """The string coupling across the wire, pinned from this side too: the
    frontend's classifier treats a 500 as 'refused' only when its detail
    starts with this exact prefix."""
    from app.routers.auto_trade import SIZING_CONFIG_REFUSED_PREFIX
    ts = (Path(__file__).resolve().parents[2]
          / "frontend" / "lib" / "armBookingFields.ts").read_text()
    m = re.search(r"export const SIZING_CONFIG_REFUSED_PREFIX = '([^']*)';", ts)
    assert m, "frontend SIZING_CONFIG_REFUSED_PREFIX not found"
    assert m.group(1) == SIZING_CONFIG_REFUSED_PREFIX
