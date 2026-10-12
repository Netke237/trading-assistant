"""TRADIER-GOVERNOR T2 (#216): every market.py Tradier call goes through the
governor, with the fire-path and prepaid markers (plan r6, D3).

Sync A-sites (A1-A11) go through `market._tradier_get`; async B-sites (B1-B6)
through `market._tradier_get_async`. Tradier is mocked with respx (installed),
for both the module-level `httpx.get` and `AsyncClient`. The governor is a spy
around a real `Governor` (monkeypatched `governor.get_governor`), with a fast
bucket wherever timing is not the point.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import httpx
import pytest
import respx

from app.data import governor as gov_mod
from app.data import market
from app.data.governor import (
    CircuitBreaker,
    Governor,
    ProviderUnavailable,
    RateLimited,
    TokenBucket,
    _ProviderState,
)

BASE = "https://api.tradier.com"
EXP = "2099-01-15"

P_HISTORY = "/v1/markets/history"
P_TIMESALES = "/v1/markets/timesales"
P_QUOTES = "/v1/markets/quotes"
P_EXPIRATIONS = "/v1/markets/options/expirations"
P_CHAINS = "/v1/markets/options/chains"
P_CALENDARS = "/beta/markets/fundamentals/calendars"
P_COMPANY = "/beta/markets/fundamentals/company"
P_NEWS = "/v1/markets/news"

# ── Fixture responses ─────────────────────────────────────────────────────────
PAYLOADS: dict[str, object] = {
    P_HISTORY: {"history": {"day": [
        {"date": "2026-10-01", "open": 100.123, "high": 101.456, "low": 99.111, "close": 100.554, "volume": 1000},
        {"date": "2026-10-02", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.25, "volume": 2000},
        {"date": "2026-10-05", "open": "NaN", "high": 102.0, "low": 100.0, "close": 101.0, "volume": 3000},
    ]}},
    P_TIMESALES: {"series": {"data": [
        {"time": "2026-10-01T09:30:00", "open": 100.12346, "high": 100.5, "low": 100.0, "close": 100.25, "volume": 500},
        {"time": "2026-10-01T09:45:00", "open": 100.25, "high": 100.75, "low": 100.2, "close": 100.6, "volume": 700},
    ]}},
    P_QUOTES: {"quotes": {"quote": {"symbol": "AAPL", "last": 187.456, "close": 186.0, "prevclose": 185.5}}},
    P_EXPIRATIONS: {"expirations": {"date": [EXP, "2099-02-19"]}},
    P_CHAINS: {"options": {"option": [
        {"option_type": "call", "strike": 185.0, "bid": 2.0, "ask": 2.5, "volume": 10,
         "open_interest": 100, "implied_volatility": 0.3,
         "greeks": {"delta": 0.51234, "theta": -0.04567}},
        {"option_type": "put", "strike": 185.0, "bid": 1.0, "ask": 1.5, "implied_volatility": 0.3},
        {"option_type": "call", "strike": 190.0, "bid": 1.0, "ask": 0, "implied_volatility": 0.3},
    ]}},
    P_CALENDARS: [{"request": "AAPL", "results": [{"tables": {
        "earnings": {"report_date": "2099-01-28"},
        "dividend": {"ex_dividend_date": "2099-02-07"},
    }}]}],
    P_COMPANY: [{"results": [{"tables": {"company_profile": {"company_name": "Apple Inc."}}}]}],
    P_NEWS: {"news": {"article": [
        {"id": 7, "symbols": "AAPL,MSFT", "title": "Headline", "source": "Src", "datetime": "2026-10-01T12:00:00Z"},
    ]}},
}

# What each source returns when Tradier fails (the stubs installed by `env`).
YF_DAILY = [
    {"time": "2020-01-02", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1},
    {"time": "2020-01-03", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 2},
]
YF_NEWS = [{"id": "yf", "symbol": "AAPL", "headline": "yf", "source": "yf", "timestamp": "", "sentiment": "neutral"}]
YF_PRICE = 42.0
FIXED_QUOTE_INPUTS = (1_000_000_000.0, False, 0.0, 1800.0)


def _et(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=market._EASTERN).timestamp())


# Parsed outputs of PAYLOADS (pinned; parsing must not change).
EXPECTED_DAILY = [
    {"time": "2026-10-01", "open": 100.12, "high": 101.46, "low": 99.11, "close": 100.55, "volume": 1000},
    {"time": "2026-10-02", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.25, "volume": 2000},
]
EXPECTED_INTRADAY = [
    {"time": _et("2026-10-01T09:30:00"), "open": 100.1235, "high": 100.5, "low": 100.0, "close": 100.25, "volume": 500},
    {"time": _et("2026-10-01T09:45:00"), "open": 100.25, "high": 100.75, "low": 100.2, "close": 100.6, "volume": 700},
]


def _expected_chain() -> list[dict]:
    dte = (date.fromisoformat(EXP) - date.today()).days
    return [{
        "id": f"AAPL|185|{EXP}|C", "symbol": "AAPL", "strike": 185, "expiry": EXP, "right": "C",
        "dte": dte, "dteTotal": dte, "price": 2.25, "delta": 0.5123, "theta": -0.0457,
        "iv": 30.0, "ivRank": None, "ivPercentile": None, "spread": 0.5, "volume": 10,
        "open_interest": 100, "score": 0,
        "quoteState": "session_closed", "quoteLive": False, "quoteAgeS": None,
    }]


EXPECTED_CALENDAR = {"tables": {"earnings": {"report_date": "2099-01-28"},
                                "dividend": {"ex_dividend_date": "2099-02-07"}}}
EXPECTED_NEWS = [{"id": "7", "symbol": "AAPL", "headline": "Headline", "source": "Src",
                  "timestamp": "2026-10-01T12:00:00Z", "sentiment": "neutral"}]


# ── Spy governor ──────────────────────────────────────────────────────────────
class SpyBucket(TokenBucket):
    """Records every token taken (an admission) into the shared event log."""

    def __init__(self, events: list, **kw) -> None:
        super().__init__(**kw)
        self.events = events

    async def acquire(self, tokens: float = 1.0) -> None:
        await super().acquire(tokens)
        self.events.append(("admit",))

    def acquire_blocking(self, tokens: float = 1.0, *, admit_timeout):
        ok = super().acquire_blocking(tokens, admit_timeout=admit_timeout)
        if ok:
            self.events.append(("admit",))
        return ok

    def overdraft(self, tokens: float = 1.0) -> None:
        super().overdraft(tokens)
        self.events.append(("admit",))

    def try_acquire(self, tokens: float = 1.0) -> bool:
        ok = super().try_acquire(tokens)
        if ok:
            self.events.append(("admit",))
        return ok


class SpyGovernor(Governor):
    """A real Governor that records the API calls made on it."""

    def __init__(self, providers, events: list) -> None:
        super().__init__(providers)
        self.events = events
        self.api: list[tuple] = []  # (thread ident, method, kwargs, result)

    def admit_sync(self, provider, **kw):
        ok = super().admit_sync(provider, **kw)
        self.api.append((threading.get_ident(), "admit_sync", dict(kw, provider=provider), ok))
        return ok

    async def call(self, provider, factory, **kw):
        self.api.append((threading.get_ident(), "call", dict(kw, provider=provider), None))
        return await super().call(provider, factory, **kw)

    async def call_overdraft(self, provider, factory):
        self.api.append((threading.get_ident(), "call_overdraft", {"provider": provider}, None))
        return await super().call_overdraft(provider, factory)

    @property
    def bucket(self) -> TokenBucket:
        return self._providers["tradier"].bucket

    def drain(self) -> None:
        """Empty the bucket by normal acquisitions."""
        while self.bucket.try_acquire():
            pass
        assert self.bucket._tokens < 1


def make_gov(events: list, rate: float = 1000.0, capacity: float = 1000.0) -> SpyGovernor:
    bucket = SpyBucket(events, rate=rate, per=1.0, capacity=capacity)
    state = _ProviderState(
        name="tradier", bucket=bucket,
        breaker=CircuitBreaker(fail_threshold=10**9, cooldown=60.0),
    )
    return SpyGovernor({"tradier": state}, events)


class RefusingGovernor(SpyGovernor):
    """Admits nothing: the not-admitted path of every helper."""

    def admit_sync(self, provider, **kw):
        self.api.append((threading.get_ident(), "admit_sync", dict(kw, provider=provider), False))
        return False

    async def call(self, provider, factory, **kw):
        self.api.append((threading.get_ident(), "call", dict(kw, provider=provider), None))
        raise ProviderUnavailable("tradier refused (test)")

    async def call_overdraft(self, provider, factory):
        self.api.append((threading.get_ident(), "call_overdraft", {"provider": provider}, None))
        raise RateLimited("tradier refused (test)")


# ── Environment fixture ───────────────────────────────────────────────────────
class Env:
    def __init__(self) -> None:
        self.events: list = []
        self.requests: list[httpx.Request] = []
        self.status_seq: list[tuple[int, dict]] = []  # consumed one per request
        self.exc: Exception | None = None
        self.gov: SpyGovernor = make_gov(self.events)
        self.yf_daily_calls = 0

    def use(self, gov: SpyGovernor) -> SpyGovernor:
        self.gov = gov
        gov.events = self.events
        return gov

    def gets(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "get"]


@pytest.fixture
def env(monkeypatch):
    e = Env()
    monkeypatch.setattr(gov_mod, "get_governor", lambda: e.gov)
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("tok", BASE))

    def _yf_daily(symbol):
        e.yf_daily_calls += 1
        return list(YF_DAILY)

    monkeypatch.setattr(market, "_fetch_daily_yf", _yf_daily)
    monkeypatch.setattr(market, "_fetch_intraday_yf", lambda *a, **k: [])
    monkeypatch.setattr(market, "_fetch_news_yf", lambda symbols, limit=20: list(YF_NEWS))
    monkeypatch.setattr(market, "_yf_iv_for_chain", lambda *a, **k: {})
    monkeypatch.setattr(market, "_quote_liveness_inputs", lambda: FIXED_QUOTE_INPUTS)
    monkeypatch.setattr(market, "log_event", lambda *a, **k: None)
    import app.data.ibkr as ibkr
    import app.data.tastytrade_iv as tt_iv
    monkeypatch.setattr(ibkr, "fetch_iv_metrics_ibkr", lambda symbol: None)
    monkeypatch.setattr(tt_iv, "fetch_iv_metrics_tastytrade", lambda symbols: {})
    # No test may reach the real yfinance; its price fallback answers YF_PRICE.
    fake_yf = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, sym):
            self.fast_info = types.SimpleNamespace(last_price=YF_PRICE, previous_close=YF_PRICE)

    fake_yf.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    monkeypatch.setattr(market, "_TRADIER_ON_LOOP_WARNED", set())

    def handler(request: httpx.Request) -> httpx.Response:
        e.events.append(("get", request.url.path))
        e.requests.append(request)
        if e.exc is not None:
            raise e.exc
        if e.status_seq:
            status, headers = e.status_seq.pop(0)
            if status != 200:
                return httpx.Response(status, headers=headers, json={"fault": "x"})
        return httpx.Response(200, json=PAYLOADS[request.url.path])

    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.tradier.com").mock(side_effect=handler)
        yield e


# ── Call specs: every A-site (sync) and B-site (async) ────────────────────────
class _Raises:
    def __init__(self, exc_type):
        self.exc_type = exc_type

    def __eq__(self, other):
        return isinstance(other, _Raises) and other.exc_type is self.exc_type

    def __repr__(self):
        return f"raises {self.exc_type.__name__}"


def _run(fn):
    try:
        return fn()
    except Exception as exc:  # the A11 site raises by contract
        return _Raises(type(exc))


# name -> (call, request paths, parsed result, fallback result, HTTP timeout)
A_SITES = {
    "fetch_candles": (lambda: market.fetch_candles("AAPL", 5), [P_HISTORY],
                      lambda: EXPECTED_DAILY, lambda: YF_DAILY, 10),
    "fetch_intraday_candles": (lambda: market.fetch_intraday_candles("AAPL", "15min", 5), [P_TIMESALES],
                               lambda: EXPECTED_INTRADAY, lambda: [], 30),
    "fetch_price": (lambda: market.fetch_price("AAPL"), [P_QUOTES], lambda: 187.46, lambda: YF_PRICE, 10),
    "fetch_option_chain": (lambda: market.fetch_option_chain("AAPL", expiry=EXP, option_type="C"),
                           [P_EXPIRATIONS, P_CHAINS], _expected_chain, lambda: [], 10),
    "fetch_quotes": (lambda: market.fetch_quotes(["AAPL"]), [P_QUOTES],
                     lambda: {"AAPL": {"last": 187.456, "prevclose": 185.5}}, lambda: {}, 10),
    "fetch_earnings_date": (lambda: market.fetch_earnings_date("AAPL"), [P_CALENDARS],
                            lambda: date(2099, 1, 28), lambda: None, 10),
    "fetch_dividend_date": (lambda: market.fetch_dividend_date("AAPL"), [P_CALENDARS],
                            lambda: date(2099, 2, 7), lambda: None, 10),
    "fetch_company_name": (lambda: market.fetch_company_name("AAPL"), [P_COMPANY],
                           lambda: "Apple Inc.", lambda: None, 10),
    "fetch_news": (lambda: market.fetch_news(["AAPL"], 5), [P_NEWS], lambda: EXPECTED_NEWS, lambda: YF_NEWS, 10),
    "_fundamentals_calendar_sync": (lambda: market._fundamentals_calendar_sync("AAPL"), [P_CALENDARS],
                                    lambda: EXPECTED_CALENDAR, lambda: _Raises(market.EarningsLookupError),
                                    "A11"),
    "tradier_next_earnings_date": (lambda: market.tradier_next_earnings_date("AAPL"), [P_CALENDARS],
                                   lambda: date(2099, 1, 28), lambda: _Raises(market.EarningsLookupError),
                                   "A11"),
}

# name -> (async call taking a client, request paths, parsed result, fallback result)
B_SITES = {
    "fetch_candles_async": (lambda c: market.fetch_candles_async(c, "AAPL"), [P_HISTORY],
                            lambda: EXPECTED_DAILY, lambda: YF_DAILY),
    "fetch_price_async": (lambda c: market.fetch_price_async(c, "AAPL"), [P_QUOTES],
                          lambda: 187.46, lambda: YF_PRICE),
    "fetch_option_chain_async": (lambda c: market.fetch_option_chain_async(c, "AAPL", expiry=EXP, option_type="C"),
                                 [P_EXPIRATIONS, P_CHAINS], _expected_chain, lambda: []),
    "fetch_company_name_async": (lambda c: market.fetch_company_name_async(c, "ZZZQ"), [P_COMPANY],
                                 lambda: "Apple Inc.", lambda: None),
    "fetch_fundamentals_calendar": (lambda c: market.fetch_fundamentals_calendar(c, "AAPL"), [P_CALENDARS],
                                    lambda: EXPECTED_CALENDAR, lambda: None),
}


async def _run_b(name: str, timeout=None):
    call = B_SITES[name][0]
    kw = {} if timeout is None else {"timeout": timeout}
    async with httpx.AsyncClient(**kw) as client:
        return await call(client)


# ── 1. Exactly one admission per request; parsing unchanged ───────────────────
@pytest.mark.parametrize("name", list(A_SITES))
def test_a_site_one_admission_per_request_and_parsing(env, name):
    call, paths, parsed, _, _ = A_SITES[name]
    assert _run(call) == parsed()
    expected = []
    for p in paths:
        expected += [("admit",), ("get", p)]
    assert env.events == expected
    # A bulk A-site call waits for its slot without limit (R4-G1).
    assert [a[2] for a in env.gov.api] == [
        {"provider": "tradier", "admit_timeout": None}
    ] * len(paths)


@pytest.mark.parametrize("name", list(B_SITES))
async def test_b_site_one_admission_per_request_and_parsing(env, name):
    _, paths, parsed, _ = B_SITES[name]
    assert await _run_b(name) == parsed()
    expected = []
    for p in paths:
        expected += [("admit",), ("get", p)]
    assert env.events == expected
    assert [a[1] for a in env.gov.api] == ["call"] * len(paths)


# ── 2. 429 with Retry-After ───────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(A_SITES))
def test_a_site_429_sets_cooldown_and_matches_other_http_error(env, name):
    call = A_SITES[name][0]
    env.status_seq = [(500, {})]
    on_500 = _run(call)
    market._candles_cache.clear()
    market._fundamentals_calendar_cache.clear()
    env.status_seq = [(429, {"Retry-After": "2"})]
    before = time.monotonic()
    on_429 = _run(call)
    retry_at = env.gov._providers["tradier"].retry_at
    assert before + 1.5 < retry_at <= time.monotonic() + 2.0
    assert on_429 == on_500
    assert env.gov.health("tradier") == "degraded"


@pytest.mark.parametrize("name", list(B_SITES))
async def test_b_site_429_until_retries_run_out_matches_other_http_error(env, name):
    env.status_seq = [(500, {})]
    on_500 = await _run_b(name)
    market._candles_cache.clear()
    env.events.clear()
    env.status_seq = [(429, {"Retry-After": "0.01"})] * 3
    on_429 = await _run_b(name)
    assert on_429 == on_500
    # retries=2: three attempts on the first path, then the site's fallback.
    assert env.gets() == [B_SITES[name][1][0]] * 3


@pytest.mark.parametrize("name", list(B_SITES))
async def test_b_site_429_then_200_retries_once(env, name):
    _, paths, parsed, _ = B_SITES[name]
    env.status_seq = [(429, {"Retry-After": "0.01"})]
    assert await _run_b(name) == parsed()
    assert env.gets() == [paths[0]] + paths
    assert env.gov._providers["tradier"].retry_at > 0


# ── 3. Not admitted: the same fallback as a transport error ───────────────────
@pytest.mark.parametrize("name", list(A_SITES))
def test_a_site_not_admitted_gives_transport_error_fallback(env, name):
    call, _, _, fallback, _ = A_SITES[name]
    env.exc = httpx.ConnectError("boom")
    on_transport = _run(call)
    assert on_transport == fallback()
    env.exc = None
    env.events.clear()
    env.use(RefusingGovernor(env.gov._providers, env.events))
    assert _run(call) == fallback()
    assert env.gets() == []
    assert len(env.gov.api) == 1


@pytest.mark.parametrize("name", list(B_SITES))
async def test_b_site_not_admitted_gives_transport_error_fallback(env, name):
    fallback = B_SITES[name][3]
    env.exc = httpx.ConnectError("boom")
    assert await _run_b(name) == fallback()
    env.exc = None
    env.events.clear()
    market._candles_cache.clear()
    env.use(RefusingGovernor(env.gov._providers, env.events))
    assert await _run_b(name) == fallback()
    assert env.gets() == []


# ── 4. HTTP timeouts pass through unchanged ───────────────────────────────────
@pytest.mark.parametrize("name", list(A_SITES))
def test_a_site_http_timeout_passes_through(env, monkeypatch, name):
    call, paths, _, _, expected = A_SITES[name]
    seen = []
    real_get = httpx.get

    def spy(url, **kw):
        seen.append(kw["timeout"])
        return real_get(url, **kw)

    monkeypatch.setattr(httpx, "get", spy)
    _run(call)
    assert len(seen) == len(paths)
    if expected == "A11":
        assert all(t is market._TRADIER_CALENDAR_HTTP_TIMEOUT for t in seen)
        assert market._TRADIER_CALENDAR_HTTP_TIMEOUT == httpx.Timeout(4.0, connect=2.0)
    else:
        assert seen == [expected] * len(paths)


@pytest.mark.parametrize("name", list(B_SITES))
async def test_b_site_carries_client_timeout(env, name):
    client_timeout = httpx.Timeout(7.5, connect=1.5)
    await _run_b(name, timeout=client_timeout)
    assert env.requests
    for req in env.requests:
        assert req.extensions["timeout"] == client_timeout.as_dict()


async def test_async_helper_never_forwards_timeout_none(env):
    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
        await market._tradier_get_async(client, f"{BASE}{P_QUOTES}", timeout=None)
        await market._tradier_get_async(client, f"{BASE}{P_QUOTES}")
    assert [r.extensions["timeout"] for r in env.requests] == [httpx.Timeout(6.0).as_dict()] * 2


async def test_async_helper_post_method(env):
    async with httpx.AsyncClient() as client:
        resp = await market._tradier_get_async(client, f"{BASE}{P_QUOTES}", method="POST")
    assert resp.status_code == 200
    assert env.requests[0].method == "POST"
    assert env.events == [("admit",), ("get", P_QUOTES)]


# ── 5. Markers ────────────────────────────────────────────────────────────────
def _slow_gov(env) -> SpyGovernor:
    """A real bucket that refills about never, drained by normal acquisitions."""
    gov = env.use(make_gov(env.events, rate=0.001, capacity=2))
    gov.drain()
    env.events.clear()
    return gov


def test_fire_path_on_empty_bucket_is_admitted_at_once_by_overdraft(env):
    gov = _slow_gov(env)
    start = time.monotonic()
    with market.tradier_fire_path():
        assert market.fetch_price("AAPL") == 187.46
    assert time.monotonic() - start < 0.5
    assert env.gets() == [P_QUOTES]
    assert gov.api[-1][2] == {"provider": "tradier", "admit_timeout": 0.0, "overdraft": True}
    assert gov.bucket._tokens < 0


def test_outside_fire_path_waits_up_to_admit_timeout(env):
    gov = _slow_gov(env)
    start = time.monotonic()
    with pytest.raises(ProviderUnavailable):
        market._tradier_get(f"{BASE}{P_QUOTES}", params={"symbols": "AAPL"}, timeout=10, admit_timeout=0.2)
    elapsed = time.monotonic() - start
    assert 0.15 < elapsed < 1.0
    assert env.gets() == []
    assert gov.api[-1][2] == {"provider": "tradier", "admit_timeout": 0.2}


def test_fire_path_during_429_cooldown_is_refused_without_request(env):
    env.gov.note_rate_limited("tradier", 30.0)
    with market.tradier_fire_path():
        # fetch_price's own fallback answers, as on today's 429.
        assert market.fetch_price("AAPL") == YF_PRICE
    assert env.gets() == []


def test_prepaid_call_makes_no_admission_and_decrements(env):
    gov = _slow_gov(env)

    def body():
        market._TRADIER_PREPAID.set(1)
        resp = market._tradier_get(f"{BASE}{P_QUOTES}", params={"symbols": "AAPL"}, timeout=10)
        return resp.status_code, market._TRADIER_PREPAID.get()

    assert contextvars.copy_context().run(body) == (200, 0)
    assert gov.api == []
    assert env.events == [("get", P_QUOTES)]


def test_tradier_prepay(env):
    def ok():
        assert market.tradier_prepay(admit_timeout=None) is True
        return market._TRADIER_PREPAID.get()

    assert contextvars.copy_context().run(ok) == 1
    assert env.gov.api[-1][2] == {"provider": "tradier", "admit_timeout": None}
    assert market._TRADIER_PREPAID.get() == 0  # set in the copied context only

    _slow_gov(env)

    def refused():
        assert market.tradier_prepay(admit_timeout=0.05) is False
        return market._TRADIER_PREPAID.get()

    assert contextvars.copy_context().run(refused) == 0


def test_markers_reset_on_exit_including_exception(env):
    assert market._TRADIER_FIRE_PATH.get() is False
    with market.tradier_fire_path():
        assert market._TRADIER_FIRE_PATH.get() is True
    assert market._TRADIER_FIRE_PATH.get() is False
    with pytest.raises(RuntimeError):
        with market.tradier_fire_path():
            assert market._TRADIER_FIRE_PATH.get() is True
            raise RuntimeError("x")
    assert market._TRADIER_FIRE_PATH.get() is False

    def prepay_then_fail():
        assert market.tradier_prepay(admit_timeout=None)
        assert market._TRADIER_PREPAID.get() == 1
        raise RuntimeError("y")

    with pytest.raises(RuntimeError):
        contextvars.copy_context().run(prepay_then_fail)
    assert market._TRADIER_PREPAID.get() == 0


def test_run_on_fire_path_sets_marker_inside_worker_thread():
    with ThreadPoolExecutor(max_workers=1) as ex:
        assert ex.submit(market.run_on_fire_path, market._TRADIER_FIRE_PATH.get).result() is True
        assert ex.submit(market.run_on_fire_path, lambda a, b: a + b, 2, 3).result() == 5
        # The marker does not leak into the worker's later tasks.
        assert ex.submit(market._TRADIER_FIRE_PATH.get).result() is False
    assert market._TRADIER_FIRE_PATH.get() is False


async def test_on_loop_sync_call_is_admitted_by_overdraft_and_warns(env, caplog):
    gov = _slow_gov(env)
    caplog.set_level(logging.WARNING, logger="app.data.market")
    for _ in range(2):  # the same call site twice
        start = time.monotonic()
        resp = market._tradier_get(f"{BASE}{P_QUOTES}", params={"symbols": "AAPL"}, timeout=10)
        assert time.monotonic() - start < 0.5
        assert resp.status_code == 200
        assert gov.api[-1][2] == {"provider": "tradier", "admit_timeout": 0.0, "overdraft": True}
    assert env.gets() == [P_QUOTES, P_QUOTES]
    # One WARNING per call site, naming it.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "event loop" in r.getMessage()]
    assert len(warnings) == 1
    assert "test_on_loop_sync_call_is_admitted_by_overdraft_and_warns" in warnings[0].getMessage()


async def test_async_fire_path_on_saturated_bucket_single_immediate_attempt(env):
    gov = _slow_gov(env)
    async with httpx.AsyncClient() as client:
        start = time.monotonic()
        with market.tradier_fire_path():
            assert await market.fetch_price_async(client, "AAPL") == 187.46
        assert time.monotonic() - start < 0.5
        assert [a[1] for a in gov.api] == ["call_overdraft"]
        assert env.gets() == [P_QUOTES]

        # A 429 on the fire path: one attempt, no retry, RateLimited raised.
        env.events.clear()
        env.status_seq = [(429, {"Retry-After": "5"})]
        with market.tradier_fire_path():
            with pytest.raises(RateLimited):
                await market._tradier_get_async(client, f"{BASE}{P_QUOTES}", params={"symbols": "AAPL"})
        assert env.gets() == [P_QUOTES]
        assert gov._providers["tradier"].retry_at > time.monotonic() + 4
    assert gov.bucket._tokens < 0


# ── 6. No fallback for waiting (R4-G1) ────────────────────────────────────────
def test_bulk_calls_wait_for_slot_and_never_fall_back(env):
    gov = env.use(make_gov(env.events, rate=40.0, capacity=2))
    stop = threading.Event()

    def contender():
        while not stop.is_set():
            gov.admit_sync("tradier", admit_timeout=None)

    threads = [threading.Thread(target=contender, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    try:
        deadline = time.monotonic() + 2
        while gov.bucket._tokens >= 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert gov.bucket._tokens < 1  # held at 0 by the contenders
        me = threading.get_ident()
        daily = market.fetch_candles("XSYM", 400)
        intraday = market.fetch_intraday_candles("XSYM", "15min", 55)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)

    assert daily == EXPECTED_DAILY
    assert intraday == EXPECTED_INTRADAY
    assert env.yf_daily_calls == 0
    assert market._candles_cache["XSYM"][0] == EXPECTED_DAILY
    mine = [a for a in gov.api if a[0] == me]
    assert [(a[1], a[2], a[3]) for a in mine] == [
        ("admit_sync", {"provider": "tradier", "admit_timeout": None}, True),
    ] * 2
    assert env.gets() == [P_HISTORY, P_TIMESALES]
