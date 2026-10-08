"""Fix #3, part 2 (review): the earnings veto at auto-trade fire time.

The scan marks an options candidate REJECT when earnings fall inside the
horizon's reject window. An arm can sit for up to max_arm_age_minutes after its
scan, so `fire()` refuses on the horizon's YAML window (a Step-3 override is not
carried on the arm).

D4 AMENDED 2026-10-03 (Kenneth): for a SINGLE STOCK an UNKNOWN earnings date
(None, a failed lookup, or a date already past) also refuses -- the scan caps
that card at CAUTION. ETFs (app.data.etfs.is_etf) have no earnings and still
fire. A symbol missing from the curated ETF set is treated as a stock (the safe
direction).
"""
from dataclasses import replace
from datetime import date, timedelta

import pytest

import app.services.auto_trader as at
from app.services.auto_trader import ArmedStrategy, AutoTradeService


class _S:
    symbol = "AAPL"
    horizon = "Swing"
    direction = "Bullish"
    hold_max_days = None


def test_veto_inside_window(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=3))
    with pytest.raises(at.EventVetoError):
        at._apply_event_veto(_S())


def test_no_veto_outside_window(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=90))
    at._apply_event_veto(_S())


class _Etf(_S):
    symbol = "SPY"


def test_stock_with_unknown_earnings_is_refused(monkeypatch):
    """D4 amended: a single stock with no earnings date on file cannot auto-fire."""
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: None)
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_S())
    assert "unknown" in str(info.value)
    assert "inside" not in str(info.value), "an unknown date is not 'inside the window'"
    assert info.value.unknown is True


def test_etf_with_unknown_earnings_is_not_refused(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: None)
    at._apply_event_veto(_Etf())


def test_stock_with_failed_lookup_is_refused(monkeypatch):
    def _boom(symbol):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(at, "_fetch_earnings_date", _boom)
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_S())
    assert "unknown" in str(info.value) and "yfinance down" in str(info.value)


def test_etf_with_failed_lookup_is_not_refused(monkeypatch):
    def _boom(symbol):
        raise RuntimeError("yfinance down")
    monkeypatch.setattr(at, "_fetch_earnings_date", _boom)
    at._apply_event_veto(_Etf())


def test_stock_with_past_earnings_date_is_refused(monkeypatch):
    """A past date means the NEXT one is unknown."""
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() - timedelta(days=2))
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_S())
    assert "unknown" in str(info.value)


def test_etf_with_past_earnings_date_is_not_refused(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() - timedelta(days=2))
    at._apply_event_veto(_Etf())


def test_inside_window_refusal_is_not_flagged_unknown(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=3))
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_S())
    assert info.value.unknown is False


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


def test_missing_horizon_with_unknown_or_past_earnings(monkeypatch):
    """Unknown needs no window: an ETF passes, a stock is refused."""
    etf, stock = _Etf(), _S()
    etf.horizon = stock.horizon = None
    for value in (None, date.today() - timedelta(days=2)):
        monkeypatch.setattr(at, "_fetch_earnings_date", lambda sym, v=value: v)
        at._apply_event_veto(etf)
        with pytest.raises(at.EventVetoError):
            at._apply_event_veto(stock)


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
    before = len(svc.get_state().history)
    with pytest.raises(at.EventVetoError):
        svc.fire(attempt_id="attempt-EVT")

    assert sent == [], "a vetoed fire must not reach the broker"
    rows = svc.get_state().history
    assert len(rows) == before + 1, "exactly one row for the refused attempt"
    assert [r for r in rows if r.get("attempt_id") == "attempt-EVT"] == [rows[-1]]
    assert sum(float(r.get("premium_at_risk") or 0) for r in rows) == 0.0, (
        "no premium may be booked against the daily budget by a refusal"
    )
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


def test_a_failing_veto_check_still_leaves_a_risk_check_failed_row(mocker, monkeypatch):
    """The disarm has consumed the arm, so a crash INSIDE the veto must leave a row.

    `effective_event_window` raising KeyError (a renamed YAML key) escaped
    `fire()` after the disarm with no history row, so /auto-trade/status kept
    showing the previous order. It is filed as `risk_check_failed`, not as an
    event veto: the veto decided nothing.
    """
    import app.scoring.stock_scorer as ss
    sent: list = []
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(at, "execute_option_order", side_effect=lambda s: sent.append(s))
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=3))

    def _boom(horizon, overrides):
        raise KeyError("event")
    monkeypatch.setattr(ss, "effective_event_window", _boom)

    svc = AutoTradeService()
    svc.arm(_armed())
    before = len(svc.get_state().history)
    with pytest.raises(KeyError):
        svc.fire(attempt_id="attempt-BOOM")

    rows = svc.get_state().history
    assert len(rows) == before + 1
    row = rows[-1]
    assert row["status"] == at._STATUS_RISK_CHECK_FAILED, row
    assert row["attempt_id"] == "attempt-BOOM"
    assert row["premium_at_risk"] == 0.0
    assert row["order_id"] is None
    assert "earnings veto check failed" in row["error"]
    assert sent == []
    assert svc.get_state().armed is False


def test_consumed_attempt_router_sends_an_event_veto_row_to_its_own_alert(mocker, monkeypatch):
    """Direct test of the `_STATUS_EVENT_VETO_BLOCKED` branch of the router.

    Without that branch the row falls through to the unclassified alert, whose
    wording ("could not classify why ... verify at the broker") is wrong here.
    """
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(at, "execute_option_order")
    monkeypatch.setattr(at, "_fetch_earnings_date",
                        lambda s: date.today() + timedelta(days=3))
    svc = AutoTradeService()
    svc.arm(_armed())
    with pytest.raises(at.EventVetoError) as info:
        svc.fire(attempt_id="attempt-ROUTE")

    event_alert = mocker.patch.object(at, "_alert_event_veto_refusal")
    unclassified = mocker.patch.object(at, "_alert_unclassified_refusal")
    svc._alert_for_consumed_attempt("attempt-ROUTE", "AAPL", info.value)

    assert event_alert.call_count == 1
    assert event_alert.call_args.args[0] == "AAPL"
    assert unclassified.call_count == 0


def _fire_with(mocker, monkeypatch, symbol, earnings):
    from app.data.ibkr_paper import OrderResult
    sent: list = []
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    mocker.patch.object(
        at, "execute_option_order",
        side_effect=lambda s: sent.append(s) or OrderResult("x", "ok", "ibkr_paper"))
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: earnings)
    svc = AutoTradeService()
    svc.arm(_armed(symbol))
    return svc, sent


def test_fire_refuses_a_stock_with_unknown_earnings_and_sends_nothing(mocker, monkeypatch):
    svc, sent = _fire_with(mocker, monkeypatch, "AAPL", None)
    with pytest.raises(at.EventVetoError):
        svc.fire(attempt_id="attempt-UNK")
    assert sent == []
    last = svc.get_state().history[-1]
    assert last["status"] == "event_veto_blocked", last
    assert last["attempt_id"] == "attempt-UNK"
    assert last["premium_at_risk"] == 0.0 and last["order_id"] is None
    assert "unknown" in last["error"]
    assert svc.get_state().armed is False


def test_fire_still_fires_an_etf_with_unknown_earnings(mocker, monkeypatch):
    svc, sent = _fire_with(mocker, monkeypatch, "SPY", None)
    svc.fire()
    assert len(sent) == 1


def test_unknown_earnings_alert_says_unknown_not_inside_the_window(mocker, monkeypatch):
    """The page must name the real reason: no date on file, not a near print."""
    svc, _ = _fire_with(mocker, monkeypatch, "AAPL", None)
    alert = mocker.patch.object(at, "_alert_refusal")
    svc.maybe_fire_on_scan()
    assert alert.call_count == 1
    body = alert.call_args.args[2]
    assert "unknown" in body
    assert "fall inside" not in body


@pytest.mark.parametrize("horizon, hold, days, veto, reject, effective_hold", [
    ("Position", 105, 90, 105, 30, 105),
    ("Position", None, 40, 45, 30, 45),
    (None, None, 40, 45, 30, 45),
    (None, 105, 90, 105, 30, 105),
])
def test_p0b_auto_veto_covers_hold(monkeypatch, horizon, hold, days, veto, reject, effective_hold):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=days))
    strategy = replace(_armed(), horizon=horizon, hold_max_days=hold)
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(strategy)
    assert str(info.value) == (f"earnings in {days}d is inside the hold window "
                               f"(<{veto}d: max(reject {reject}d, hold {effective_hold}d))")
    assert info.value.unknown is False


@pytest.mark.parametrize("hold, days, blocked", [(60, 59, True), (60, 60, False),
                                                 (0, 29, True), (0, 30, False)])
def test_p0b_auto_hold_boundary_and_zero(monkeypatch, hold, days, blocked):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=days))
    strategy = replace(_armed(), horizon="Position", hold_max_days=hold)
    if blocked:
        with pytest.raises(at.EventVetoError):
            at._apply_event_veto(strategy)
    else:
        at._apply_event_veto(strategy)


def test_p0b_fire_long_hold_refuses_before_broker(mocker, monkeypatch):
    svc, sent = _fire_with(mocker, monkeypatch, "AAPL", date.today() + timedelta(days=90))
    strategy = replace(_armed(), horizon="Position", hold_max_days=105)
    svc.arm(strategy)
    with pytest.raises(at.EventVetoError):
        svc.fire(attempt_id="p0b-long-hold")
    assert sent == []
    row = svc.get_state().history[-1]
    assert row["status"] == "event_veto_blocked"
    assert row["premium_at_risk"] == 0.0
    assert row["order_id"] is None
    assert svc.get_state().armed is False
