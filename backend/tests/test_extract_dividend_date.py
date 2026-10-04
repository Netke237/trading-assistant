"""Audit round 2, R2-F1 (High): `_extract_dividend_date` was gutted by commit
4bcd5fcd -- three new functions were pasted inside its body, after its
`if not fund_data: return None` guard, so it returned None for EVERY Tradier
fundamentals answer and the options scan never read a Tradier dividend date.

No test exercised it and every scan test stubbed `fetch_fundamentals_calendar`
to None, so the whole suite stayed green. These tests pin both ends:
the extractor itself, and a scan that feeds a Tradier dividend through
`fetch_fundamentals_calendar` and sees it scored.
"""
from __future__ import annotations

import ast
import inspect
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import app.data.market as market
from app.data.market import _extract_dividend_date, _extract_earnings_date


def _fund(dividend=None, earnings=None):
    tables: dict = {}
    if dividend is not None:
        tables["dividend"] = {"ex_dividend_date": dividend}
    if earnings is not None:
        tables["earnings"] = {"report_date": earnings}
    return {"tables": tables}


# ── the extractor ───────────────────────────────────────────────────────────

def test_a_future_ex_dividend_date_is_returned():
    d = date.today() + timedelta(days=10)
    assert _extract_dividend_date(_fund(dividend=d.isoformat())) == d


def test_today_counts_as_upcoming():
    assert _extract_dividend_date(_fund(dividend=date.today().isoformat())) == date.today()


def test_a_past_ex_dividend_date_reads_as_none():
    d = date.today() - timedelta(days=1)
    assert _extract_dividend_date(_fund(dividend=d.isoformat())) is None


def test_none_and_missing_tables_read_as_none():
    assert _extract_dividend_date(None) is None
    assert _extract_dividend_date({}) is None
    assert _extract_dividend_date({"tables": {}}) is None
    assert _extract_dividend_date({"tables": {"dividend": {}}}) is None
    assert _extract_dividend_date({"tables": {"dividend": {"ex_dividend_date": None}}}) is None


def test_an_unreadable_date_reads_as_none():
    assert _extract_dividend_date(_fund(dividend="not-a-date")) is None


def test_the_earnings_extractor_is_unaffected_by_a_dividend():
    d = date.today() + timedelta(days=10)
    e = date.today() + timedelta(days=40)
    fund = _fund(dividend=d.isoformat(), earnings=e.isoformat())
    assert _extract_earnings_date(fund) == e
    assert _extract_dividend_date(fund) == d


def test_no_market_function_has_unreachable_code_after_a_return():
    """The shape of the bug: statements after a function's last top-level
    `return`. Walks every function in market.py, so a future mis-paste of the
    same kind fails here rather than silently."""
    tree = ast.parse(inspect.getsource(market))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            for i, stmt in enumerate(body[:-1]):
                if isinstance(stmt, (ast.Return, ast.Raise)):
                    offenders.append(f"{node.name}:{body[i + 1].lineno}")
                    break
    assert offenders == [], f"unreachable code after a top-level return/raise: {offenders}"


# ── end to end through POST /api/scan ───────────────────────────────────────

def _scan_with_tradier_fundamentals(client, fund_data, yf_mock):
    from tests.test_scan_stop_cost import _OVERRIDES, _candles, _contract

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
        # Tradier fundamentals ANSWERS, with the dividend in its real shape.
        stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar",
                                  AsyncMock(return_value=fund_data)))
        # yfinance is rate-limited / has nothing: only Tradier can date the dividend.
        stack.enter_context(patch("app.routers.scan.fetch_calendar_dates_async", yf_mock))
        stack.enter_context(patch("app.scoring.stock_scorer._thresholds",
                                  return_value={"pass": 25, "caution": 10}))
        r = client.post("/api/scan", json={
            "universe": ["MSFT"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {**_OVERRIDES, "min_stock_score": 20},
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert cands, "fixture produced no surviving candidate; every assertion below would be vacuous"
    return cands


def test_scan_scores_a_tradier_dividend_when_yfinance_has_nothing(client):
    div = date.today() + timedelta(days=4)
    earn = date.today() + timedelta(days=90)
    yf = AsyncMock(return_value=(None, None))
    cands = _scan_with_tradier_fundamentals(
        client, _fund(dividend=div.isoformat(), earnings=earn.isoformat()), yf)
    for c in cands:
        assert c["nextEventLabel"] == "Dividend"
        assert c["nextEventDays"] == 4
        assert c["earningsDays"] == 90
        assert c["earningsVeto"] is False      # D3: a dividend is a score penalty only


def test_scan_does_not_ask_yfinance_when_tradier_dated_both(client):
    """R2-F1's second effect: with the extractor gutted, `dividend_date is None`
    was always true, so every candidate also made a yfinance calendar call."""
    div = date.today() + timedelta(days=4)
    earn = date.today() + timedelta(days=90)
    yf = AsyncMock(return_value=(None, None))
    _scan_with_tradier_fundamentals(
        client, _fund(dividend=div.isoformat(), earnings=earn.isoformat()), yf)
    yf.assert_not_called()
