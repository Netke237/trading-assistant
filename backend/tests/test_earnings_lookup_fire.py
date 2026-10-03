"""Audit round 1, F3 + F11 (Kenneth 2026-10-03: yes): the fire-time earnings
lookup.

Still FAIL-CLOSED -- a single stock whose date is still unknown is refused --
but:
  (a) the scan does not day-cache a FAILED yfinance lookup, only real answers
      (a genuine "no date" included);
  (b) the fire path reads the scan's source chain -- Tradier fundamentals
      first, then yfinance -- not yfinance alone;
  (c) a failed lookup is retried once;
  (d) the lookup has a bounded deadline, so a hang cannot stall the single
      fire worker;
and a failed lookup is told apart from "no date on file" where the source
allows, so the refusal says which. These tests drive the REAL path, stubbing
only the network edge (httpx.get and yfinance.Ticker).
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

import pytest

import app.data.market as market
import app.services.auto_trader as at


class _Strategy:
    symbol = "AAPL"
    horizon = "Swing"
    direction = "Bullish"


IN_30 = date.today() + timedelta(days=30)
IN_60 = date.today() + timedelta(days=60)


@pytest.fixture(autouse=True)
def _real_lookup_and_clean_caches(monkeypatch):
    # conftest stubs `_fetch_earnings_date` for the whole suite; this file
    # tests the real thing underneath it.
    monkeypatch.setattr(at, "_fetch_earnings_date", at._lookup_earnings_date)
    monkeypatch.setattr(market, "_fundamentals_calendar_cache", {})
    monkeypatch.setattr(market, "_yf_cal_cache", {})
    monkeypatch.setattr(market, "_yf_cal_cache_date", "")
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("tok", "https://tradier.test"))


# ── Network edges ───────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _fund_payload(report_date):
    tables = {"earnings": {"report_date": report_date.isoformat()}} if report_date else {}
    return [{"results": [{"tables": tables}]}]


def _install_tradier(monkeypatch, *, report_date=None, fail=False, calls=None):
    def _get(url, **kw):
        if calls is not None:
            calls.append(url)
        if fail:
            raise RuntimeError("tradier unreachable")
        return _Resp(_fund_payload(report_date))
    monkeypatch.setattr(market.httpx, "get", _get)


def _install_yf(monkeypatch, outcomes, calls=None):
    """`outcomes` is consumed one per `.calendar` read: an Exception raises,
    anything else is returned as the calendar."""
    import yfinance
    queue = list(outcomes)

    class _Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def calendar(self):
            if calls is not None:
                calls.append(self.symbol)
            out = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(out, Exception):
                raise out
            return out

    monkeypatch.setattr(yfinance, "Ticker", _Ticker)


# ── (a) the scan's yfinance cache ───────────────────────────────────────────

def test_strict_yf_lookup_raises_on_a_failed_request(monkeypatch):
    _install_yf(monkeypatch, [RuntimeError("rate limited")])
    with pytest.raises(market.EarningsLookupError):
        market._calendar_dates_yf_strict("AAPL")
    # The lenient wrapper every other caller uses keeps its contract.
    assert market._calendar_dates_yf("AAPL") == (None, None)


def test_strict_yf_lookup_returns_none_for_a_genuinely_empty_calendar(monkeypatch):
    _install_yf(monkeypatch, [{}])
    assert market._calendar_dates_yf_strict("AAPL") == (None, None)


def test_scan_does_not_day_cache_a_failed_lookup(monkeypatch):
    calls: list[str] = []
    _install_yf(monkeypatch, [RuntimeError("rate limited"), {"Earnings Date": [IN_30]}], calls)
    assert asyncio.run(market.fetch_calendar_dates_async("AAPL")) == (None, None)
    assert asyncio.run(market.fetch_calendar_dates_async("AAPL"))[0] == IN_30
    assert len(calls) == 2, "the failure was cached for the day"


def test_scan_does_cache_a_genuine_no_date(monkeypatch):
    calls: list[str] = []
    _install_yf(monkeypatch, [{}], calls)
    asyncio.run(market.fetch_calendar_dates_async("AAPL"))
    asyncio.run(market.fetch_calendar_dates_async("AAPL"))
    assert len(calls) == 1


# ── (b) the fire path uses the scan's source chain ──────────────────────────

def test_fundamentals_answer_first_and_yfinance_is_not_asked(monkeypatch):
    yf_calls: list[str] = []
    _install_tradier(monkeypatch, report_date=IN_30)
    _install_yf(monkeypatch, [{"Earnings Date": [IN_60]}], yf_calls)
    assert at._lookup_earnings_date("AAPL") == IN_30
    assert yf_calls == []


def test_yfinance_is_the_fallback_when_fundamentals_have_no_date(monkeypatch):
    _install_tradier(monkeypatch, report_date=None)
    _install_yf(monkeypatch, [{"Earnings Date": [IN_60]}])
    assert at._lookup_earnings_date("AAPL") == IN_60


def test_yfinance_still_answers_when_tradier_is_down(monkeypatch):
    """The auditor's scenario: one source failing must not refuse a card the
    other source can date."""
    _install_tradier(monkeypatch, fail=True)
    _install_yf(monkeypatch, [{"Earnings Date": [IN_60]}])
    assert at._lookup_earnings_date("AAPL") == IN_60
    at._apply_event_veto(_Strategy())   # 60d is outside Swing's window: fires


def test_the_scans_same_day_fundamentals_answer_is_reused(monkeypatch):
    tradier_calls: list[str] = []
    _install_tradier(monkeypatch, fail=True, calls=tradier_calls)
    _install_yf(monkeypatch, [RuntimeError("rate limited")])
    market._fundamentals_calendar_cache["AAPL"] = (
        _fund_payload(IN_30)[0]["results"][0], date.today().isoformat(),
    )
    assert at._lookup_earnings_date("AAPL") == IN_30
    assert tradier_calls == []


# ── failure vs "none on file" reaches the refusal ───────────────────────────

def test_both_sources_failing_refuses_as_lookup_failed(monkeypatch):
    _install_tradier(monkeypatch, fail=True)
    _install_yf(monkeypatch, [RuntimeError("rate limited")])
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_Strategy())
    assert info.value.unknown is True
    assert "lookup failed" in str(info.value)
    assert "none on file" not in str(info.value)


def test_both_sources_answering_no_date_refuses_as_none_on_file(monkeypatch):
    _install_tradier(monkeypatch, report_date=None)
    _install_yf(monkeypatch, [{}])
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_Strategy())
    assert info.value.unknown is True
    assert "none on file" in str(info.value)


# ── (c) one retry ───────────────────────────────────────────────────────────

def test_a_failed_lookup_is_retried_once(monkeypatch):
    yf_calls: list[str] = []
    _install_tradier(monkeypatch, fail=True)
    _install_yf(monkeypatch, [RuntimeError("rate limited"), {"Earnings Date": [IN_60]}], yf_calls)
    assert at._lookup_earnings_date("AAPL") == IN_60
    assert len(yf_calls) == 2


def test_a_genuine_no_date_is_not_retried(monkeypatch):
    yf_calls: list[str] = []
    _install_tradier(monkeypatch, report_date=None)
    _install_yf(monkeypatch, [{}], yf_calls)
    assert at._lookup_earnings_date("AAPL") is None
    assert len(yf_calls) == 1


# ── (d) a bounded deadline ──────────────────────────────────────────────────

def test_a_hung_lookup_is_abandoned_at_the_deadline(monkeypatch):
    monkeypatch.setattr(at, "_EARNINGS_LOOKUP_DEADLINE_S", 0.2)
    monkeypatch.setattr(market, "fetch_next_earnings_date", lambda s: time.sleep(3))
    t0 = time.monotonic()
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_Strategy())
    assert time.monotonic() - t0 < 2.0, "the hang held the fire worker"
    assert "lookup failed" in str(info.value) and "within" in str(info.value)
