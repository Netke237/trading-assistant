"""AUTOTRADE-A9 (2026-09-24) -- fire accounting for failed and rejected orders,
and the regime_gate config 500 on POST /auto-trade/fire.

- A9-ORDER-FAILED-BOOKS-FULL-PREMIUM: an `order_failed` row books the full
  premium (the order may be live), so it spends daily-loss budget.
- A9-REJECTED-BOOKS-ZERO: a broker-stated rejection books 0, by the SAME set
  the booking step refuses it with.
- A9-REGIME-GATE-CONFIG-500: RegimeGateConfigError answers a prefixed 500.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import app.services.auto_trade_booking as atb
import app.services.auto_trader as at
from app.data.ibkr_paper import OrderResult
from app.services.auto_trader import (
    ArmedStrategy,
    AutoTradeService,
    RegimeGateConfigError,
)


def _armed(symbol="MSFT", premium=2.50, qty=2, pv=100_000.0, **kw):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=qty, order_type="LMT",
        limit_price=premium, conid=None,
        entry_premium=premium, portfolio_value=pv, **kw,
    )


def _service(mocker, max_pct=1.0, sizing=lambda s: s):
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", sizing)
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": max_pct}))
    svc = AutoTradeService()
    svc.arm(_armed())
    return svc


# ── A9: order_failed books the full premium ─────────────────────────────────

def test_an_order_failed_row_books_the_full_premium(mocker):
    """$2.50 x 2 x 100 = $500. Also pins `regime_gate` and `sizing` on the
    row (open_questions[70]: no test failed if `sizing` was dropped)."""
    def _sized(s):
        return dataclasses.replace(s, regime_gate_outcome="passed",
                                   sizing_basis="measured")

    svc = _service(mocker, sizing=_sized)
    mocker.patch.object(at, "execute_option_order",
                        side_effect=RuntimeError("read timeout after submit"))
    with pytest.raises(RuntimeError, match="Order failed"):
        svc.fire(portfolio_value=100_000.0)
    row = svc.get_state().history[-1]
    assert row["status"] == "order_failed"
    assert row["premium_at_risk"] == pytest.approx(500.0)
    assert row["regime_gate"] == "passed"
    assert row["sizing"] == "measured"


def test_an_order_failed_row_spends_the_daily_budget(mocker):
    """Limit 0.008 x 100_000 = $800 fits one $500 trade, not two. The
    order_failed row's $500 must refuse the second fire before the broker."""
    svc = _service(mocker, max_pct=0.008)
    execute = mocker.patch.object(at, "execute_option_order",
                                  side_effect=RuntimeError("connection reset"))
    with pytest.raises(RuntimeError, match="Order failed"):
        svc.fire(portfolio_value=100_000.0)
    assert execute.call_count == 1

    svc.arm(_armed())
    with pytest.raises(RuntimeError, match="Daily loss limit reached: 1000 at risk"):
        svc.fire(portfolio_value=100_000.0)
    assert execute.call_count == 1
    assert svc.get_state().history[-1]["status"] == "daily_loss_blocked"


# ── A9: a stated rejection books 0 ──────────────────────────────────────────

@pytest.mark.parametrize("status", [
    "rejected", " Rejected ", "Inactive", "cancelled", "CANCELED", "expired", "error",
])
def test_a_rejected_status_books_zero_and_spends_nothing(mocker, status):
    svc = _service(mocker, max_pct=0.008)
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o-1", status, "ibkr_paper"))
    svc.fire(portfolio_value=100_000.0)
    row = svc.get_state().history[-1]
    assert row["status"] == status
    assert row["premium_at_risk"] == 0.0

    # A second $500 fire under the $800 limit fits ONLY because the rejected
    # row spent nothing: booked at the full premium it would be $1000.
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o-2", "filled", "ibkr_paper"))
    svc.arm(_armed())
    svc.fire(portfolio_value=100_000.0)
    assert svc.get_state().history[-1]["premium_at_risk"] == pytest.approx(500.0)


@pytest.mark.parametrize("status", ["filled", "Submitted", "PreSubmitted", "some_new_word", None])
def test_any_other_status_books_the_full_premium(mocker, status):
    """A rejection list, not an allowlist: an unknown word most likely means a
    live order, and a missing status is not a stated rejection."""
    svc = _service(mocker)
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o-1", status, "ibkr_paper"))
    svc.fire(portfolio_value=100_000.0)
    assert svc.get_state().history[-1]["premium_at_risk"] == pytest.approx(500.0)


def test_the_fire_path_and_the_booking_step_share_one_rejection_test():
    """ONE definition of "rejected" for the daily-loss budget and for the
    portfolio, so the two cannot drift."""
    assert atb._is_rejected_status is at._is_rejected_status
    assert not hasattr(atb, "_REJECTED_STATUSES")


# ── A9: the regime_gate config 500 on POST /auto-trade/fire ─────────────────

class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDb:
    async def execute(self, *a, **k):
        return _FakeResult()

    # P3c item 7: fire_now releases the snapshot read's transaction
    # before it waits on the fire executor.
    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_fire_endpoint_maps_a_regime_gate_config_error_to_500(mocker):
    """Through the REAL fire(): the refusal lands after the disarm, before the
    broker, and the endpoint answers 500 with the regime_gate prefix."""
    from app.routers import auto_trade as rt

    def _broken(s):
        raise RegimeGateConfigError("regime_gate.headwind_reject_pct is missing")

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
    assert ei.value.detail == (rt.REGIME_GATE_CONFIG_REFUSED_PREFIX
                               + "regime_gate.headwind_reject_pct is missing")
    execute.assert_not_called()
    book.assert_not_called()
    assert rt.auto_trader.get_state().history[-1]["status"] == "regime_gate_config_blocked"


def test_the_regime_gate_prefix_is_the_one_the_frontend_reads():
    from app.routers.auto_trade import (
        REGIME_GATE_CONFIG_REFUSED_PREFIX,
        SIZING_CONFIG_REFUSED_PREFIX,
    )
    ts = (Path(__file__).resolve().parents[2]
          / "frontend" / "lib" / "armBookingFields.ts").read_text()
    m = re.search(r"export const REGIME_GATE_CONFIG_REFUSED_PREFIX = '([^']*)';", ts)
    assert m, "frontend REGIME_GATE_CONFIG_REFUSED_PREFIX not found"
    assert m.group(1) == REGIME_GATE_CONFIG_REFUSED_PREFIX
    # Neither prefix may start with the other, or one 500 would read as both.
    assert not REGIME_GATE_CONFIG_REFUSED_PREFIX.startswith(SIZING_CONFIG_REFUSED_PREFIX)
    assert not SIZING_CONFIG_REFUSED_PREFIX.startswith(REGIME_GATE_CONFIG_REFUSED_PREFIX)
