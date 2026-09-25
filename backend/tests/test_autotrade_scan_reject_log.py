"""AUTOTRADE-SCAN-REJECT-LOG (2026-09-25) -- oq item 2, Kenneth: agree.

A broker-stated rejection makes `fire()` return normally, so the scan trigger
used to log "fired on scan completion trigger" for an order that never
happened. It now logs a REJECTED warning instead, judged by the same
`_is_rejected_status` set `fire()` books 0 on. `_clear_config_refusal_holds()`
still runs on a rejection: the order was built, so the config was applied.
"""
from __future__ import annotations

import logging

import pytest

import app.services.auto_trader as at
from app.data.ibkr_paper import OrderResult
from app.services.auto_trader import ArmedStrategy, AutoTradeService


def _armed(symbol="MSFT", premium=2.50, qty=1, pv=100_000.0):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=qty, order_type="LMT",
        limit_price=premium, conid=None,
        entry_premium=premium, portfolio_value=pv,
    )


def _service(mocker, status):
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(AutoTradeService, "_risk_config",
                        staticmethod(lambda: {"max_daily_loss_pct": 1.0}))
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o-9", status, "ibkr_paper"))
    svc = AutoTradeService()
    svc.arm(_armed())
    return svc


_LOGGER = "app.services.auto_trader"


@pytest.mark.parametrize("status", ["rejected", " Cancelled ", "EXPIRED"])
def test_a_rejected_order_logs_rejected_not_fired(mocker, caplog, status):
    svc = _service(mocker, status)
    clear = mocker.patch.object(at, "_clear_config_refusal_holds")

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        fired = svc.maybe_fire_on_scan()

    assert fired is not None
    assert "fired on scan completion trigger" not in caplog.text
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "REJECTED" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "MSFT" in msg and "ibkr_paper" in msg
    assert repr(status) in msg and repr("o-9") in msg
    # The config was read and applied, so the hold still clears.
    clear.assert_called_once_with()


@pytest.mark.parametrize("status", ["filled", "Submitted", "some_new_word"])
def test_a_non_rejected_order_still_logs_fired(mocker, caplog, status):
    svc = _service(mocker, status)
    clear = mocker.patch.object(at, "_clear_config_refusal_holds")

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        fired = svc.maybe_fire_on_scan()

    assert fired is not None
    assert "fired on scan completion trigger" in caplog.text
    assert "REJECTED" not in caplog.text
    clear.assert_called_once_with()
