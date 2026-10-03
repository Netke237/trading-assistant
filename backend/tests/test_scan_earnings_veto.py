from app.routers.scan import _earnings_unknown_caps, _earnings_veto, _final_status
from app.scoring.stock_scorer import RuleResult


class _Card:
    def __init__(self, rules):
        self.rules = rules


def _ev(status, earnings_days, reject_days=21, event="earnings"):
    return RuleResult("event", status, 5, {"event": event, "earnings_days": earnings_days,
                                           "reject_days": reject_days})


def test_veto_when_earnings_inside_reject_window():
    assert _earnings_veto(_Card([_ev("REJECT", 3)])) is True


def test_veto_when_dividend_labelled_but_earnings_inside():
    assert _earnings_veto(_Card([_ev("REJECT", 5, event="dividend")])) is True


def test_no_veto_outside_window_or_unknown():
    assert _earnings_veto(_Card([_ev("CAUTION", 30)])) is False
    assert _earnings_veto(_Card([_ev("PASS", None)])) is False
    assert _earnings_veto(_Card([])) is False


def test_no_veto_for_dividend_only_inside_window():
    # D3: a dividend stays a score penalty. Earnings unknown -> no veto.
    assert _earnings_veto(_Card([_ev("REJECT", None, event="dividend")])) is False


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


def _scan_with_calendar(client, earnings, dividend=None, symbol="MSFT"):
    # MSFT's bars for every symbol: the fixture setup is what passes; `symbol`
    # only decides stock vs ETF.
    candles = _candles("MSFT")
    price = candles[-1]["close"]
    chain = [_contract(price, strike_mult=1.0)]
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
        stack.enter_context(patch("app.data.confidence_cache.get_cached",
                                  return_value={"confidence": 70, "sample_size": 40}))
        stack.enter_context(patch("app.data.confidence_cache.set_cached", AsyncMock()))
        stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
        stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles)))
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
            "universe": [symbol], "direction": "Bullish", "horizon": "Swing",
            "overrides": {**_OVERRIDES, "min_stock_score": 20},
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert cands, "fixture produced no surviving candidate; every assertion below would be vacuous"
    return cands


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
