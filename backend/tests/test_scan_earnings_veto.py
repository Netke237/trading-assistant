from app.routers.scan import _earnings_unknown_caps, _earnings_veto, _final_status
import pytest

from app.scoring.stock_scorer import RuleResult


class _Card:
    def __init__(self, rules):
        self.rules = rules


def _ev(status, earnings_days, reject_days=21, event="earnings"):
    return RuleResult("event", status, 5, {"event": event, "earnings_days": earnings_days,
                                           "reject_days": reject_days})


def test_veto_when_earnings_inside_reject_window():
    assert _earnings_veto(_Card([_ev("REJECT", 3)]), 21) is True


def test_veto_when_dividend_labelled_but_earnings_inside():
    assert _earnings_veto(_Card([_ev("REJECT", 5, event="dividend")]), 21) is True


def test_no_veto_outside_window_or_unknown():
    assert _earnings_veto(_Card([_ev("CAUTION", 30)]), 21) is False
    assert _earnings_veto(_Card([_ev("PASS", None)]), 21) is False
    assert _earnings_veto(_Card([]), 21) is False


def test_no_veto_for_dividend_only_inside_window():
    # D3: a dividend stays a score penalty. Earnings unknown -> no veto.
    assert _earnings_veto(_Card([_ev("REJECT", None, event="dividend")]), 21) is False


def test_unknown_earnings_caps_a_single_stock_only():
    """D4 amended 2026-10-03 (Kenneth): unknown earnings on a NON-ETF caps the
    card at CAUTION. ETFs have no earnings. Not in the ETF set == a stock."""
    unknown = _Card([_ev("PASS", None)])
    known = _Card([_ev("PASS", 60)])
    assert _earnings_unknown_caps(unknown, "MSFT") is True
    assert _earnings_unknown_caps(unknown, "SPY") is False
    assert _earnings_unknown_caps(known, "MSFT") is False
    # No event rule at all: nothing says when earnings are -- unknown.
    assert _earnings_unknown_caps(_Card([]), "MSFT") is True
    assert _earnings_unknown_caps(_Card([]), "SPY") is False


def test_final_status_variadic_takes_worst():
    assert _final_status("PASS", "PASS", "PASS", "REJECT") == "REJECT"
    assert _final_status("PASS", "CAUTION", "PASS") == "CAUTION"


# ── End to end through POST /api/scan ────────────────────────────────────────
from contextlib import ExitStack  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from tests.test_scan_stop_cost import _OVERRIDES, _candles, _contract  # noqa: E402


def _scan_with_calendar(client, earnings, dividend=None, symbol="MSFT", *,
                        horizon="Swing", hold_max_days=None, return_result=False, overrides=None):
    # MSFT's bars for every symbol: the fixture setup is what passes; `symbol`
    # only decides stock vs ETF.
    candles = _candles("MSFT")
    price = candles[-1]["close"]
    chain = [_contract(price, strike_mult=1.0, dte=90 if hold_max_days is not None else 45)]
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
        stack.enter_context(patch("app.data.confidence_cache.get_cached",
                                  return_value={"confidence": 70, "sample_size": 40}))
        stack.enter_context(patch("app.data.confidence_cache.set_cached", AsyncMock()))
        stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
        stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles)))
        stack.enter_context(patch("app.routers.scan.get_daily_regime_bars", AsyncMock(return_value=candles)))
        stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)))
        stack.enter_context(patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Test Co")))
        stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)))
        stack.enter_context(patch("app.routers.scan.fetch_calendar_dates_async",
                                  AsyncMock(return_value=(earnings, dividend))))
        # Lower the status bands so the weak fixture setup scores PASS despite
        # the penalised event rule -- the exact shape of the bug (a near
        # earnings date that only lowered the score and left the card PASS).
        stack.enter_context(patch("app.scoring.stock_scorer._thresholds",
                                  return_value={"pass": 25, "caution": 10}))
        r = client.post("/api/scan", json={
            "universe": [symbol], "direction": "Bullish", "horizon": horizon,
            "overrides": {**_OVERRIDES, "min_stock_score": 20, **(overrides or {})},
            **({"hold_min_days": 0, "hold_max_days": hold_max_days}
               if hold_max_days is not None else {}),
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert cands, "fixture produced no surviving candidate; every assertion below would be vacuous"
    return r.json() if return_result else cands


def test_scan_card_earnings_inside_window_is_vetoed(client):
    for c in _scan_with_calendar(client, date.today() + timedelta(days=3)):
        assert c["status"] == "PASS"          # the score alone still passes ...
        assert c["earningsVeto"] is True
        assert c["earningsUnknown"] is False
        assert c["finalStatus"] == "REJECT"   # ... the veto does not let it through


def test_scan_card_unknown_earnings_on_a_stock_is_capped_at_caution(client):
    """D4 amended: not a veto (no REJECT), but a single stock with no earnings
    date on file cannot be PASS -- and so cannot auto-fire on the scan."""
    for c in _scan_with_calendar(client, None):
        assert c["status"] == "PASS"          # the score is unchanged ...
        assert c["earningsVeto"] is False
        assert c["earningsUnknown"] is True
        assert c["isEtf"] is False
        assert c["finalStatus"] == "CAUTION"  # ... the card is capped


def test_scan_card_past_earnings_on_a_stock_is_unknown_and_capped(client):
    """A past date means the next one is unknown (deferred T3 minor, folded in)."""
    for c in _scan_with_calendar(client, date.today() - timedelta(days=5)):
        assert c["earningsUnknown"] is True
        assert c["earningsDays"] is None
        assert c["finalStatus"] == "CAUTION"


def test_scan_card_unknown_earnings_on_an_etf_is_not_capped(client):
    for c in _scan_with_calendar(client, None, symbol="SPY"):
        assert c["earningsUnknown"] is True
        assert c["isEtf"] is True
        assert c["finalStatus"] == "PASS"     # same fixture: the cap is the only difference


def test_scan_card_dividend_inside_window_is_not_a_veto(client):
    # D3: only EARNINGS vetoes. Earnings far out, dividend 2 days away.
    for c in _scan_with_calendar(client, date.today() + timedelta(days=90),
                                 date.today() + timedelta(days=2)):
        assert c["earningsVeto"] is False


def test_scan_card_carries_earnings_days_not_the_nearer_dividend(client):
    # Final review: nextEventDays is the NEARER of earnings/dividend, so the
    # Step-7 rail cannot grade an "Earnings" gate on it. earningsDays is the
    # earnings distance alone (30d here, with a dividend 2d out).
    for c in _scan_with_calendar(client, date.today() + timedelta(days=30),
                                 date.today() + timedelta(days=2)):
        assert c["nextEventDays"] == 2
        assert c["earningsDays"] == 30


def test_scan_card_earningsdays_null_when_earnings_unknown(client):
    for c in _scan_with_calendar(client, None, date.today() + timedelta(days=2)):
        assert c["earningsDays"] is None


def test_p0b_veto_uses_hold_window_without_changing_event_rule():
    card = _Card([_ev("CAUTION", 40, reject_days=30)])
    assert _earnings_veto(card, 60) is True
    assert _earnings_veto(card, 30) is False
    assert card.rules[0].status == "CAUTION"
    assert card.rules[0].detail["reject_days"] == 30


@pytest.mark.parametrize("days, expected", [(-1, False), (0, True), (59, True), (60, False)])
def test_p0b_veto_hold_boundaries(days, expected):
    assert _earnings_veto(_Card([_ev("CAUTION", days, reject_days=30)]), 60) is expected


@pytest.mark.parametrize("horizon, hold, reject, expected", [
    ("Intraday", None, 0, 2), ("Swing", None, 0, 15),
    ("Position", None, 30, 45), ("Position", 60, 30, 60),
    ("Position", 0, 0, 0), ("Position", 0, 30, 30),
    ("Position", 15, 70, 70),
])
def test_p0b_effective_veto_days(horizon, hold, reject, expected):
    from app.scoring.stock_scorer import effective_veto_days
    assert effective_veto_days(horizon, {"event_reject_days": reject}, hold) == expected


@pytest.mark.parametrize("hold, expected", [(60, 60), (None, 45)])
def test_p0b_position_scan_veto_covers_hold_and_echoes_it(client, hold, expected):
    result = _scan_with_calendar(client, date.today() + timedelta(days=40),
                                 horizon="Position", hold_max_days=hold, return_result=True)
    assert result["event_window"] == {"reject_days": 30, "caution_days": 60,
                                      "veto_days": expected}
    for card in result["candidates"]:
        assert card["status"] == "CAUTION"  # unchanged Position conviction cap
        assert card["earningsDays"] == 40
        assert card["earningsVeto"] is True
        assert card["finalStatus"] == "REJECT"


@pytest.mark.parametrize("days, expected", [(60, False), (59, True)])
def test_p0b_position_scan_hold_boundary(client, days, expected):
    result = _scan_with_calendar(client, date.today() + timedelta(days=days),
                                 horizon="Position", hold_max_days=60, return_result=True)
    assert result["event_window"]["veto_days"] == 60
    assert all(c["earningsVeto"] is expected for c in result["candidates"])


def test_p0b_eventwindow_old_result_is_readable():
    from app.schemas import EventWindow
    assert EventWindow(reject_days=30, caution_days=60).veto_days is None


def test_p0b_scan_veto_failure_falls_back_to_echoed_reject_window(client):
    with patch("app.routers.scan.effective_veto_days", side_effect=RuntimeError("window"), create=True):
        result = _scan_with_calendar(client, date.today() + timedelta(days=20),
                                     horizon="Position", hold_max_days=60, return_result=True)
    assert result["event_window"]["veto_days"] == 30
    assert all(c["earningsVeto"] is True for c in result["candidates"])


def test_p0b_scan_missing_event_window_falls_back_to_widest_default(client):
    import app.scoring.stock_scorer as scorer
    calls = []
    def fail_request_only(horizon, overrides, hold):
        calls.append((horizon, overrides, hold))
        if overrides is not None:
            raise RuntimeError("request window")
        return max(scorer.effective_event_window(horizon, None)[0],
                   {"Intraday": 2, "Swing": 15, "Position": 45}[horizon])
    with patch("app.routers.scan.effective_event_window", side_effect=RuntimeError("event window")), \
         patch("app.routers.scan.effective_veto_days", side_effect=fail_request_only, create=True):
        result = _scan_with_calendar(client, date.today() + timedelta(days=40),
                                     horizon="Position", hold_max_days=60, return_result=True)
    assert result["event_window"] is None
    assert all(c["earningsVeto"] is True and c["finalStatus"] == "REJECT"
               for c in result["candidates"])
    assert [c[0] for c in calls[1:]] == ["Intraday", "Swing", "Position"]
