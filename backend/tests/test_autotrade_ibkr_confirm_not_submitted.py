"""AUTOTRADE-IBKR-CONFIRM-NOT-SUBMITTED (2026-09-25) -- Kenneth chose option A:
item 3(b) with item 2 folded in.

IBKR's Client Portal can answer an order POST with an "order reply message": a
2xx carrying a reply id and a question to confirm, and no `order_id`. IBKR does
not take the order until that question is answered, and nothing here answers
it. The auto-trader used to book it as a live order at the full premium. It
now records `not_submitted` with 0 at risk, and alerts in words that do not
claim the broker was never contacted.

Also here: `fire()`'s own log line on a stated rejection (the scan trigger's
line changed in AUTOTRADE-SCAN-REJECT-LOG).
"""
from __future__ import annotations

import logging

import httpx
import pytest
import respx

import app.services.auto_trader as at
from app.data import ibkr_paper
from app.data.ibkr_paper import BrokerOrder, IbkrPaperAdapter, OrderResult
from app.services.auto_trader import (
    AutoTradeService,
    OrderAwaitingConfirmationError,
    OrderNotSubmittedError,
)
from tests.test_auto_trader import _capture_alerts, _scan_trigger_service

_BASE = "https://localhost:7499/v1/api"
_ORDERS = f"{_BASE}/iserver/account/DU123456/orders"
# The shape IBKR documents for an order reply message.
_QUESTION = [{
    "id": "07a13a5a-4a48-44a5-bb25-5ab37b79186c",
    "message": ["You are about to submit an order outside regular hours.",
                "Are you sure you want to submit this order?"],
    "isSuppressed": False,
    "messageIds": ["o163"],
}]


def _gateway_up():
    respx.get(f"{_BASE}/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True}))
    respx.post(f"{_BASE}/tickle").mock(return_value=httpx.Response(200, json={}))
    ibkr_paper._auth_cache = None  # avoid cross-test cache leakage


def _place(reply):
    respx.post(_ORDERS).mock(return_value=httpx.Response(200, json=reply))
    adapter = IbkrPaperAdapter(base_url=_BASE, account_id="DU123456")
    return adapter.place_order(BrokerOrder(
        symbol="MSFT", action="BUY", effect="OPEN", quantity=1,
        order_type="LMT", limit_price=2.5, sec_type="OPT", conid=123))


# --- the adapter ------------------------------------------------------------

@respx.mock
def test_the_adapter_flags_ibkrs_confirmation_question():
    _gateway_up()
    result = _place(_QUESTION)
    assert result.awaiting_confirmation is True
    assert result.order_id == ""
    # The question's text, readable, not a Python list repr.
    assert result.message.startswith("You are about to submit")
    assert "[" not in result.message


@pytest.mark.parametrize("reply", [
    [{"order_id": "987654", "order_status": "PreSubmitted"}],
    # No order id, but not the question shape either: stays as before, and
    # keeps booking the full premium (NO-ORDER-ID-BOOKS-FULL-PREMIUM-2026-09-25).
    [{"error": "something odd"}],
    [{"id": "abc"}],
    [{"message": ["a warning with no reply id"]}],
    # An acknowledged order that also carries a message is still an order.
    [{"order_id": "1", "order_status": "Submitted", "id": "x", "message": ["m"]}],
    # A null order id is still an order_id key: not flagged, the safe side.
    [{"order_id": None, "id": "x", "message": ["m"]}],
])
@respx.mock
def test_the_adapter_flags_nothing_else(reply):
    _gateway_up()
    assert _place(reply).awaiting_confirmation is False


@pytest.mark.parametrize("reply", [
    # A bare dict rather than a list, and a plain-string message.
    {"id": "abc", "message": "Are you sure?"},
    [{"id": "abc", "message": "Are you sure?"}],
])
@respx.mock
def test_the_adapter_flags_the_question_in_other_shapes(reply):
    _gateway_up()
    result = _place(reply)
    assert result.awaiting_confirmation is True
    assert result.message == "Are you sure?"


# --- the fire path, end to end through the real adapter ---------------------

def _route_to_real_ibkr_adapter(mocker):
    import app.services.broker_router as br
    mocker.patch.object(br, "build_router_from_credentials", lambda: br.BrokerRouter(
        adapters={"ibkr_paper": IbkrPaperAdapter(base_url=_BASE,
                                                 account_id="DU123456")}))


@respx.mock
def test_a_confirmation_question_is_not_submitted_and_books_nothing(mocker, caplog):
    at_, svc = _scan_trigger_service(mocker)
    _route_to_real_ibkr_adapter(mocker)
    _gateway_up()
    respx.post(_ORDERS).mock(return_value=httpx.Response(200, json=_QUESTION))

    fired = svc.maybe_fire_on_scan()

    assert fired is None, "nothing was placed, so nothing may be booked"
    row = svc.get_state().history[-1]
    assert row["status"] == "not_submitted"
    assert row["premium_at_risk"] == 0.0
    assert row["order_id"] is None
    assert row["broker_contacted"] is True
    assert "nothing reached the broker" not in caplog.text
    assert "the broker was contacted but did not take the order" in caplog.text
    assert "confirmation question" in row["error"]
    assert "outside regular hours" in row["error"]
    assert svc.get_state().armed is False


@respx.mock
def test_an_acknowledged_ibkr_order_still_fires(mocker):
    at_, svc = _scan_trigger_service(mocker)
    _route_to_real_ibkr_adapter(mocker)
    _gateway_up()
    respx.post(_ORDERS).mock(return_value=httpx.Response(
        200, json=[{"order_id": "987654", "order_status": "PreSubmitted"}]))

    fired = svc.maybe_fire_on_scan()

    assert fired is not None
    row = svc.get_state().history[-1]
    assert row["status"] == "PreSubmitted"
    assert row["premium_at_risk"] > 0


def test_the_manual_fire_answers_a_refusal_not_an_order_failure(mocker):
    """`/auto-trade/fire` maps a RuntimeError to 400; the frontend reads a 400
    without 'Order failed:' as refused (nothing live), which is correct here."""
    at_, svc = _scan_trigger_service(mocker)
    mocker.patch.object(at, "execute_option_order", side_effect=(
        OrderAwaitingConfirmationError("ibkr_paper did not accept the order")))

    with pytest.raises(RuntimeError) as info:
        svc.fire()

    assert str(info.value).startswith("Order not submitted:")
    assert isinstance(info.value.__cause__, OrderNotSubmittedError)


def test_a_pre_submission_failure_is_not_marked_contacted(mocker):
    at_, svc = _scan_trigger_service(mocker)
    mocker.patch.object(at, "execute_option_order",
                        side_effect=OrderNotSubmittedError("Unknown broker"))

    svc.maybe_fire_on_scan()

    row = svc.get_state().history[-1]
    assert row["status"] == "not_submitted"
    assert row["broker_contacted"] is False


# --- the alert --------------------------------------------------------------

@respx.mock
def test_the_alert_says_the_broker_was_contacted_and_took_nothing(mocker):
    at_, svc = _scan_trigger_service(mocker)
    _route_to_real_ibkr_adapter(mocker)
    _gateway_up()
    respx.post(_ORDERS).mock(return_value=httpx.Response(200, json=_QUESTION))
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    assert len(calls) == 1
    subject, body = calls[0]
    assert "MSFT" in subject
    assert "not contacted at all" not in body, body
    assert "MAY HAVE LANDED" not in body, body
    assert "did NOT accept the order" in body, body
    assert "NO position was opened" in body, body


def test_the_pre_submission_alert_wording_is_unchanged(mocker):
    at_, svc = _scan_trigger_service(mocker)
    mocker.patch.object(at, "execute_option_order",
                        side_effect=OrderNotSubmittedError("Unknown broker"))
    calls = _capture_alerts(mocker)

    svc.maybe_fire_on_scan()

    assert len(calls) == 1
    assert "the broker was not contacted at all" in calls[0][1]


# --- fire()'s own log line --------------------------------------------------

_LOGGER = "app.services.auto_trader"


@pytest.mark.parametrize("status", ["rejected", " Cancelled "])
def test_fire_logs_a_stated_rejection_as_rejected(mocker, caplog, status):
    at_, svc = _scan_trigger_service(mocker)
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o-9", status, "ibkr_paper"))

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        svc.fire()

    assert "AutoTrader fired" not in caplog.text
    hits = [r for r in caplog.records if r.levelno == logging.WARNING
            and "AutoTrader order REJECTED by the broker" in r.getMessage()]
    assert len(hits) == 1
    assert repr(status) in hits[0].getMessage()


def test_fire_still_logs_fired_for_a_live_order(mocker, caplog):
    at_, svc = _scan_trigger_service(mocker)
    mocker.patch.object(at, "execute_option_order",
                        return_value=OrderResult("o-9", "filled", "ibkr_paper"))

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        svc.fire()

    assert "AutoTrader fired: order o-9 status filled" in caplog.text
    assert "REJECTED" not in caplog.text
