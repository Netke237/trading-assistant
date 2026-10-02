"""Fix #3, part 2 (review): the earnings veto at auto-trade fire time.

The scan marks an options candidate REJECT when earnings fall inside the
horizon's reject window. An arm can sit for up to max_arm_age_minutes after its
scan, so `fire()` applies the same rule again. An UNKNOWN earnings date never
vetoes (decision D4), exactly as in the scan.
"""
from datetime import date, timedelta

import pytest

import app.services.auto_trader as at
from app.services.auto_trader import ArmedStrategy, AutoTradeService


class _S:
    symbol = "AAPL"
    horizon = "Swing"
    direction = "Bullish"


def test_veto_inside_window(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=3))
    with pytest.raises(at.EventVetoError):
        at._apply_event_veto(_S())


def test_no_veto_outside_window(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=90))
    at._apply_event_veto(_S())


def test_unknown_earnings_does_not_veto(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: None)
    at._apply_event_veto(_S())


def test_failed_lookup_does_not_veto(monkeypatch):
    def _boom(symbol):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(at, "_fetch_earnings_date", _boom)
    at._apply_event_veto(_S())


def test_missing_horizon_with_earnings_inside_the_widest_window_vetoes(monkeypatch, caplog):
    """No horizon never loosens the veto: a known near date refuses, and says so."""
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=3))
    s = _S()
    s.horizon = None
    with caplog.at_level("WARNING"):
        with pytest.raises(at.EventVetoError):
            at._apply_event_veto(s)
    assert "no horizon" in caplog.text


def test_missing_horizon_with_earnings_beyond_the_widest_window_passes(monkeypatch):
    from typing import get_args
    from app.scoring.stock_scorer import Horizon, effective_event_window
    widest = max(effective_event_window(h, None)[0] for h in get_args(Horizon))
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=widest + 30))
    s = _S()
    s.horizon = None
    at._apply_event_veto(s)


def test_missing_horizon_with_unknown_or_past_earnings_passes(monkeypatch):
    s = _S()
    s.horizon = None
    for value in (None, date.today() - timedelta(days=2)):
        monkeypatch.setattr(at, "_fetch_earnings_date", lambda sym, v=value: v)
        at._apply_event_veto(s)


def test_window_boundary_is_exclusive(monkeypatch):
    """`days < reject_days`, the scan's own comparison: the reject day itself passes."""
    from app.scoring.stock_scorer import effective_event_window
    reject_days, _ = effective_event_window("Swing", None)
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=reject_days))
    at._apply_event_veto(_S())
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=reject_days - 1))
    with pytest.raises(at.EventVetoError):
        at._apply_event_veto(_S())


def _armed(symbol="AAPL"):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50, portfolio_value=100_000.0,
        horizon="Swing",
    )


def test_fire_refuses_inside_the_window_and_sends_nothing(mocker, monkeypatch):
    """The integration shape of the headwind refusal: a row, no order, disarmed."""
    from app.data.ibkr_paper import OrderResult
    sent: list = []
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(
        at, "execute_option_order",
        side_effect=lambda s: sent.append(s) or OrderResult("x", "ok", "ibkr_paper"))
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=3))

    svc = AutoTradeService()
    svc.arm(_armed())
    with pytest.raises(at.EventVetoError):
        svc.fire(attempt_id="attempt-EVT")

    assert sent == [], "a vetoed fire must not reach the broker"
    last = svc.get_state().history[-1]
    assert last["status"] == "event_veto_blocked", last
    assert last["premium_at_risk"] == 0.0
    assert last["order_id"] is None
    assert last["attempt_id"] == "attempt-EVT"
    assert svc.get_state().armed is False, "disarm happens before the refusal"


def test_fire_outside_the_window_still_fires(mocker, monkeypatch):
    from app.data.ibkr_paper import OrderResult
    sent: list = []
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(
        at, "execute_option_order",
        side_effect=lambda s: sent.append(s) or OrderResult("x", "ok", "ibkr_paper"))
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=90))

    svc = AutoTradeService()
    svc.arm(_armed())
    svc.fire()
    assert len(sent) == 1


def test_scan_trigger_alerts_an_event_veto_with_its_own_wording(mocker, monkeypatch):
    """The unattended path must page the veto, and not as an unclassified refusal."""
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(at, "execute_option_order")
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=3))
    event_alert = mocker.patch.object(at, "_alert_event_veto_refusal")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")

    svc = AutoTradeService()
    svc.arm(_armed())
    svc.maybe_fire_on_scan()

    assert event_alert.call_count == 1
    assert event_alert.call_args.args[0] == "AAPL"
    assert unclassified.call_count == 0
