"""TRADIER-GOVERNOR T3 (#217): the fire-path markers in the auto-trader, the
remaining Tradier sites (C, D, E, F, G1, G2, H), the three on-loop callers
moved to worker threads, and the AST ratchets (plan r6, D3/D4, task T3).

"Saturated bucket" means the REAL governor's `tradier` bucket
(`build_default_governor()`: 120/min, capacity 15) held at 0 by background
threads of normal, unlimited admissions -- an options or stock scan running.
Every test builds its own governor and swaps `governor.get_governor`, so no
test depends on (or leaves anything in) the process singleton.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import pathlib
import sys
import threading
import time
import types
from datetime import date, datetime, timedelta

import httpx
import pytest
import respx

import app.services.auto_trader as at
from app.data import governor as gov_mod
from app.data import market
from app.data.governor import Governor, RateLimited, build_default_governor

BASE = "https://api.tradier.com"
SANDBOX = "https://sandbox.tradier.com"
OCC = "AAPL261016C00185000"

P_HISTORY = "/v1/markets/history"
P_TIMESALES = "/v1/markets/timesales"
P_QUOTES = "/v1/markets/quotes"
P_CHAINS = "/v1/markets/options/chains"
P_CALENDARS = "/beta/markets/fundamentals/calendars"
P_SESSION = "/v1/markets/events/session"
P_CLOCK = "/v1/markets/clock"

TRADIER_DAILY_CLOSE = 181.0
YF_DAILY_CLOSE = 1.0
TRADIER_INTRADAY_CLOSE = 50.0
YF_INTRADAY_CLOSE = 2.0
TRADIER_PRICE = 187.5

BACKEND = pathlib.Path(__file__).resolve().parent.parent
APP = BACKEND / "app"


# ── Spy governor ──────────────────────────────────────────────────────────────
class SpyGovernor(Governor):
    """A real Governor (the production providers) that records the admission
    API calls made on it, except the background pollers'."""

    def __init__(self, providers, refuse: set[str] | None = None) -> None:
        super().__init__(providers)
        self.api: list[tuple] = []          # (thread ident, method, kwargs, result)
        self.refuse = refuse or set()       # providers admit_sync refuses outright

    def admit_sync(self, provider, **kw):
        ok = False if provider in self.refuse else super().admit_sync(provider, **kw)
        self.api.append((threading.get_ident(), "admit_sync", dict(kw, provider=provider), ok))
        return ok

    async def call(self, provider, factory, **kw):
        self.api.append((threading.get_ident(), "call", dict(kw, provider=provider), None))
        return await super().call(provider, factory, **kw)

    async def call_overdraft(self, provider, factory):
        self.api.append((threading.get_ident(), "call_overdraft", {"provider": provider}, None))
        return await super().call_overdraft(provider, factory)

    def bucket(self, provider: str = "tradier"):
        return self._providers[provider].bucket

    def methods(self) -> list[str]:
        return [a[1] for a in self.api]


def make_gov(**kw) -> SpyGovernor:
    return SpyGovernor(build_default_governor()._providers, **kw)


OVERDRAFT = {"provider": "tradier", "admit_timeout": 0.0, "overdraft": True}


class Saturated:
    """`n` daemon threads of normal, unlimited admissions on `provider`,
    holding the bucket at 0 (they call the base Governor, so the spy does not
    record them). Stopping only sets the flag: a poller finishes its current
    wait on its own, so a test never waits for it."""

    def __init__(self, gov: Governor, n: int = 5, provider: str = "tradier") -> None:
        self.gov, self.n, self.provider = gov, n, provider
        self.stop = threading.Event()

    def _poll(self) -> None:
        while not self.stop.is_set():
            Governor.admit_sync(self.gov, self.provider, admit_timeout=None)

    def __enter__(self):
        for _ in range(self.n):
            threading.Thread(target=self._poll, daemon=True).start()
        bucket = self.gov._providers[self.provider].bucket
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with bucket._lock:
                bucket._refill()
                queued = bucket._next_ticket - bucket._serving
                tokens = bucket._tokens
            if tokens < 1 and queued >= self.n:
                return self
            time.sleep(0.005)
        raise AssertionError("bucket never saturated")

    def __exit__(self, *exc):
        self.stop.set()
        return False


# ── Fixtures ──────────────────────────────────────────────────────────────────
def _daily_payload() -> dict:
    today = date.today()
    days = [today - timedelta(days=i) for i in range(300, 0, -1)]
    return {"history": {"day": [
        {"date": d.isoformat(), "open": 180.0, "high": 182.0, "low": 179.0,
         "close": TRADIER_DAILY_CLOSE, "volume": 1000} for d in days
    ]}}


def _yf_daily() -> list[dict]:
    return [{"time": d["date"], "open": 1.0, "high": 1.0, "low": 1.0,
             "close": YF_DAILY_CLOSE, "volume": 1} for d in _daily_payload()["history"]["day"]]


def _intraday_starts() -> list[datetime]:
    first = (datetime.now(market._EASTERN) - timedelta(days=20)).replace(
        second=0, microsecond=0, tzinfo=None)
    return [first + timedelta(minutes=15 * i) for i in range(200)]


def _timesales_payload() -> dict:
    return {"series": {"data": [
        {"time": t.isoformat(), "open": 50.0, "high": 50.5, "low": 49.5,
         "close": TRADIER_INTRADAY_CLOSE, "volume": 100} for t in _intraday_starts()
    ]}}


def _yf_intraday(*_a, **_k) -> list[dict]:
    return [{"time": int(t.replace(tzinfo=market._EASTERN).timestamp()), "open": 2.0,
             "high": 2.0, "low": 2.0, "close": YF_INTRADAY_CLOSE, "volume": 1}
            for t in _intraday_starts()]


def _calendar_payload(report: date) -> list:
    return [{"request": "AAPL", "results": [{"tables": {"earnings": {"report_date": report.isoformat()}}}]}]


class Env:
    def __init__(self) -> None:
        self.gov: SpyGovernor = make_gov()
        self.requests: list[httpx.Request] = []
        self.report_date = date.today() + timedelta(days=3)
        self.quote_status = 200
        self.yf_daily_calls = 0
        self.yf_earnings_calls = 0
        self.yf_price: float | None = None   # fake yfinance fast_info price

    def paths(self, host: str = "api.tradier.com") -> list[str]:
        return [r.url.path for r in self.requests if r.url.host == host]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == P_HISTORY:
            return httpx.Response(200, json=_daily_payload())
        if path == P_TIMESALES:
            return httpx.Response(200, json=_timesales_payload())
        if path == P_CALENDARS:
            return httpx.Response(200, json=_calendar_payload(self.report_date))
        if path == P_QUOTES:
            if self.quote_status != 200:
                return httpx.Response(self.quote_status, headers={"Retry-After": "5"}, json={"fault": "x"})
            sym = request.url.params.get("symbols")
            if sym == OCC:
                return httpx.Response(200, json={"quotes": {"quote": {"symbol": OCC, "ask": 2.5, "last": 2.4}}})
            return httpx.Response(200, json={"quotes": {"quote": {"symbol": sym, "last": TRADIER_PRICE}}})
        if path == P_CHAINS:
            now_ms = time.time() * 1000
            return httpx.Response(200, json={"options": {"option": [
                {"symbol": OCC, "bid": 2.0, "ask": 3.0, "bid_date": now_ms, "ask_date": now_ms},
            ]}})
        if path == P_SESSION:
            return httpx.Response(200, json={"stream": {"url": "https://stream.tradier.test/v1/markets/events"}})
        if path == P_CLOCK:
            return httpx.Response(200, json={"clock": {}})
        if path.endswith("/orders"):
            return httpx.Response(200, json={"order": {"id": 7, "status": "ok", "partner_id": "p"}})
        return httpx.Response(404, json={})


@pytest.fixture
def env(monkeypatch):
    e = Env()
    monkeypatch.setattr(gov_mod, "get_governor", lambda: e.gov)
    from app.routers import data_sources
    monkeypatch.setattr(data_sources, "get_governor", lambda: e.gov)
    creds = lambda: ("tok", BASE)  # noqa: E731
    monkeypatch.setattr(market, "get_tradier_creds", creds)
    from app.routers import sectors
    from app.data import tradier_stream
    monkeypatch.setattr(sectors, "get_tradier_creds", creds)
    monkeypatch.setattr(tradier_stream, "get_tradier_creds", creds)
    monkeypatch.setattr(market, "_TRADIER_ON_LOOP_WARNED", set())

    def _yf_daily_stub(symbol):
        e.yf_daily_calls += 1
        return _yf_daily()

    monkeypatch.setattr(market, "_fetch_daily_yf", _yf_daily_stub)
    monkeypatch.setattr(market, "_fetch_intraday_yf", _yf_intraday)

    def _yf_earnings(symbol):
        e.yf_earnings_calls += 1
        return None  # a genuine "no date on file"

    monkeypatch.setattr(market, "yfinance_next_earnings_date", _yf_earnings)
    monkeypatch.setattr(at, "_fetch_earnings_date", at._lookup_earnings_date)
    monkeypatch.setattr(market, "log_event", lambda *a, **k: None)

    fake_yf = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, sym):
            self.fast_info = types.SimpleNamespace(last_price=e.yf_price, previous_close=e.yf_price)

    fake_yf.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.tradier.com").mock(side_effect=e.handler)
        router.route(host="sandbox.tradier.com").mock(side_effect=e.handler)
        yield e


@pytest.fixture
def omm(monkeypatch):
    """Record the closes `_measure_trade_regime` measures on."""
    seen: list[list[float]] = []

    def _compute_omm(closes, **_kw):
        seen.append(list(closes))
        return None

    import app.services.regime_omm as regime_omm
    monkeypatch.setattr(regime_omm, "compute_omm", _compute_omm)
    return seen


def _armed(horizon: str) -> at.ArmedStrategy:
    return at.ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL", option_symbol=OCC,
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.5, conid=None, entry_premium=2.5, portfolio_value=100_000.0,
        horizon=horizon,
    )


class _Strategy:
    symbol = "AAPL"
    horizon = "Swing"
    direction = "Bullish"
    hold_max_days = None


def _overdrafts(gov: SpyGovernor) -> list[tuple]:
    return [a for a in gov.api if a[1] == "admit_sync" and a[2] == OVERDRAFT]


# ── 1. Fire path under a saturated bucket (R3-G1) ─────────────────────────────
@pytest.mark.parametrize("horizon,path,close", [
    ("Intraday", P_TIMESALES, TRADIER_INTRADAY_CLOSE),
])
def test_regime_fetch_on_saturated_bucket_is_admitted_by_overdraft(env, omm, horizon, path, close):
    with Saturated(env.gov):
        start = time.monotonic()
        assert at._measure_trade_regime(_armed(horizon)) is None  # compute_omm stub
        elapsed = time.monotonic() - start
    assert elapsed < 1.5 < at._REGIME_FETCH_DEADLINE_S
    assert set(omm[-1]) == {close}          # Tradier's bars, not yfinance's
    assert env.paths() == [path]
    assert env.yf_daily_calls == 0
    ods = _overdrafts(env.gov)
    assert len(ods) == 1 and ods[0][3] is True
    assert ods[0][0] != threading.get_ident()   # in the fetch's worker thread


@pytest.mark.parametrize("cooldown", [False, True])
def test_daily_regime_reads_database_without_governor_admission(env, omm, monkeypatch, cooldown):
    """Uniform daily DB history supersedes the old Swing provider fallback."""
    calls = []
    def read(symbol, count):
        calls.append((symbol, count, threading.get_ident()))
        return [{"close": 123.5}] * 800
    monkeypatch.setattr(at, "get_daily_regime_bars_sync", read)
    with Saturated(env.gov):
        if cooldown:
            env.gov.note_rate_limited("tradier", 30.0)
        assert at._measure_trade_regime(_armed("Swing")) is None
    assert calls[0][:2] == ("AAPL", 800)
    assert calls[0][2] != threading.get_ident()
    assert set(omm[-1]) == {123.5}
    assert env.paths() == [] and env.yf_daily_calls == 0
    assert _overdrafts(env.gov) == []


def test_event_veto_lookup_on_saturated_bucket_gets_tradier_date_by_overdraft(env):
    with Saturated(env.gov):
        start = time.monotonic()
        with pytest.raises(at.EventVetoError) as info:
            at._apply_event_veto(_Strategy())
        elapsed = time.monotonic() - start
    assert info.value.unknown is False      # vetoed on Tradier's (in-window) date
    assert elapsed < 1.5 < at._TRADIER_LOOKUP_DEADLINE_S
    assert env.paths() == [P_CALENDARS]
    assert env.yf_earnings_calls == 0
    ods = _overdrafts(env.gov)
    assert len(ods) == 1 and ods[0][3] is True
    # The fire path makes no prepay (no normal admission at all).
    assert [a for a in env.gov.api if a[1] == "admit_sync" and not a[2].get("overdraft")] == []
    assert market._TRADIER_FIRE_PATH.get() is False


def test_market_is_open_on_saturated_bucket_is_admitted_by_overdraft(env):
    with Saturated(env.gov):
        start = time.monotonic()
        assert at._market_is_open("AAPL") is True
        elapsed = time.monotonic() - start
    assert elapsed < 1.5
    assert env.paths() == [P_QUOTES]
    ods = _overdrafts(env.gov)
    assert len(ods) == 1 and ods[0][3] is True
    assert ods[0][0] != threading.get_ident()


# ── 2. Fire path during a 429 cooldown: today's failure path, nothing sent ────
@pytest.mark.parametrize("horizon,yf_close", [("Intraday", YF_INTRADAY_CLOSE)])
def test_regime_fetch_during_cooldown_takes_yfinance_without_request(env, omm, monkeypatch, horizon, yf_close):
    monkeypatch.setattr(at, "_REGIME_FETCH_DEADLINE_S", 1.5)
    env.gov.note_rate_limited("tradier", 30.0)
    assert at._measure_trade_regime(_armed(horizon)) is None
    assert set(omm[-1]) == {yf_close}
    assert env.paths() == []
    ods = _overdrafts(env.gov)
    assert len(ods) == 1 and ods[0][3] is False   # refused at once


def test_event_veto_during_cooldown_is_unknown_veto_without_request(env, monkeypatch):
    monkeypatch.setattr(at, "_TRADIER_LOOKUP_DEADLINE_S", 1.0)
    env.gov.note_rate_limited("tradier", 30.0)
    start = time.monotonic()
    with pytest.raises(at.EventVetoError) as info:
        at._apply_event_veto(_Strategy())
    assert time.monotonic() - start < 0.9
    assert info.value.unknown is True        # yfinance then "unknown" -> D4 veto
    assert env.yf_earnings_calls >= 1
    assert env.paths() == []
    ods = _overdrafts(env.gov)
    assert ods and all(a[3] is False for a in ods)


def test_market_is_open_during_cooldown_takes_fetch_price_fallback(env):
    env.gov.note_rate_limited("tradier", 30.0)
    env.yf_price = None                       # the fallback has no price either
    start = time.monotonic()
    assert at._market_is_open("AAPL") is False  # closed
    assert time.monotonic() - start < 1.5
    assert env.paths() == []
    ods = _overdrafts(env.gov)
    assert len(ods) == 1 and ods[0][3] is False


# ── 3. The stock scan's earnings lookup prepays before its deadline ──────────
def test_stock_scan_lookup_prepays_before_the_deadline_on_saturated_bucket(env, monkeypatch):
    # A deadline far shorter than the queue wait: only a wait taken BEFORE the
    # deadline starts lets Tradier answer inside it.
    monkeypatch.setattr(at, "_TRADIER_LOOKUP_DEADLINE_S", 0.5)
    with Saturated(env.gov):
        start = time.monotonic()
        found = at._lookup_earnings_date("AAPL")
        elapsed = time.monotonic() - start
    assert found == env.report_date           # Tradier's date
    assert env.yf_earnings_calls == 0
    assert env.paths() == [P_CALENDARS]
    assert elapsed > 0.5                       # it did wait (in the prepay)
    mine = [a for a in env.gov.api if a[0] == threading.get_ident()]
    assert [(a[1], a[2], a[3]) for a in mine] == [
        ("admit_sync", {"provider": "tradier", "admit_timeout": None}, True),
    ]
    # The worker consumed the prepaid token: no second admission anywhere.
    assert len(env.gov.api) == 1
    assert market._TRADIER_PREPAID.get() == 0  # nothing leaks into the caller


def test_stock_scan_lookup_skips_prepay_on_same_day_cache_hit(env):
    market._fundamentals_calendar_cache["AAPL"] = (
        {"tables": {"earnings": {"report_date": env.report_date.isoformat()}}},
        date.today().isoformat(),
    )
    assert at._lookup_earnings_date("AAPL") == env.report_date
    assert env.gov.api == []
    assert env.paths() == []


# ── 4. D, the daily-risk opening price, on the fire path ─────────────────────
async def test_opening_price_option_on_saturated_bucket_is_overdraft(env):
    from app.services.daily_risk_hooks import opening_price
    with Saturated(env.gov):
        start = time.monotonic()
        assert await opening_price(OCC, "MKT", None) == 2.5
        elapsed = time.monotonic() - start
    assert elapsed < 0.5
    assert env.gov.methods() == ["call_overdraft"]
    assert env.paths() == [P_QUOTES]
    req = env.requests[-1]
    assert req.url.params.get("symbols") == OCC
    # The client's timeout (AsyncClient(timeout=10)) is carried.
    assert req.extensions["timeout"] == {"connect": 10, "read": 10, "write": 10, "pool": 10}
    assert market._TRADIER_FIRE_PATH.get() is False


async def test_opening_price_stock_on_saturated_bucket_is_overdraft(env):
    from app.services.daily_risk_hooks import opening_price
    with Saturated(env.gov):
        start = time.monotonic()
        assert await opening_price("AAPL|STOCK", "MKT", None) == TRADIER_PRICE
        elapsed = time.monotonic() - start
    assert elapsed < 0.5
    assert env.gov.methods() == ["call_overdraft"]
    assert env.paths() == [P_QUOTES]


async def test_opening_price_during_cooldown_raises_without_request(env):
    from app.services import daily_risk
    from app.services.daily_risk_hooks import opening_price
    env.gov.note_rate_limited("tradier", 30.0)
    with pytest.raises(RateLimited):
        await opening_price(OCC, "MKT", None)
    with pytest.raises(daily_risk.DailyRiskError):   # yfinance has no price either
        await opening_price("AAPL|STOCK", "MKT", None)
    assert env.paths() == []


async def test_opening_price_429_is_one_attempt_no_retry(env):
    from app.services.daily_risk_hooks import opening_price
    env.quote_status = 429
    with pytest.raises(RateLimited):
        await opening_price(OCC, "MKT", None)
    assert env.paths() == [P_QUOTES]          # retries=0: exactly one request
    assert env.gov._providers["tradier"].retry_at > time.monotonic() + 4


# ── 5. Repayment ──────────────────────────────────────────────────────────────
def test_bulk_call_after_a_fire_path_overdraft_waits_for_repayment(env):
    gov = env.gov
    bucket = gov.bucket()                      # the real 2 tokens/s
    while bucket.try_acquire():
        pass
    assert at._market_is_open("AAPL") is True  # fire path: overdraft
    assert bucket._tokens < 0
    debt = bucket._tokens
    start = time.monotonic()
    assert market.fetch_price("AAPL") == TRADIER_PRICE   # bulk: waits
    elapsed = time.monotonic() - start
    assert elapsed >= (1 - debt) * bucket.per / bucket.rate - 0.15
    assert gov.api[-1][2] == {"provider": "tradier", "admit_timeout": None}


# ── 6. Site F ─────────────────────────────────────────────────────────────────
@pytest.fixture
def quote_gate(monkeypatch):
    from app.scoring import contract_validator
    from app.services import market_session
    monkeypatch.setattr(market_session, "_market_session_open", lambda _: True)
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)
    monkeypatch.setattr(contract_validator, "max_quote_age_seconds", lambda: 1800)


@pytest.mark.real_quote_gate
def test_site_f_on_saturated_bucket_is_admitted_by_overdraft(env, quote_gate):
    with Saturated(env.gov):
        assert at._option_quote_state(OCC) == "live"
    assert env.paths() == [P_CHAINS]
    assert [(a[1], a[2], a[3]) for a in env.gov.api] == [("admit_sync", OVERDRAFT, True)]


@pytest.mark.real_quote_gate
def test_site_f_during_cooldown_is_unavailable_without_request(env, quote_gate):
    env.gov.note_rate_limited("tradier", 30.0)
    assert at._option_quote_state(OCC) == "unavailable"
    assert env.paths() == []


# ── 7. C, E, G1, G2, H ────────────────────────────────────────────────────────
async def test_sectors_c_admitted_on_tradier_with_its_timeout(env):
    from app.routers.sectors import _fetch_etf_change
    async with httpx.AsyncClient() as client:
        etf, pct = await _fetch_etf_change(client, "XLK")
    assert etf == "XLK" and pct == 0.0        # two equal closes
    assert env.gov.methods() == ["call"]
    assert env.gov.api[0][2]["provider"] == "tradier"
    assert env.paths() == [P_HISTORY]
    assert env.requests[-1].extensions["timeout"] == {"connect": 10, "read": 10, "write": 10, "pool": 10}


async def test_stream_session_e_admitted_on_tradier(env):
    from app.data.tradier_stream import TradierStreamClient
    url = await TradierStreamClient()._create_session()
    assert url == "https://stream.tradier.test/v1/markets/events"
    assert env.gov.methods() == ["call"]
    assert env.gov.api[0][2]["provider"] == "tradier"
    assert [(r.method, r.url.path) for r in env.requests] == [("POST", P_SESSION)]


def test_probe_g1_admitted_on_tradier_with_probe_budget(env):
    from app.routers import data_sources
    assert data_sources._probe_tradier() == ("connected", None)
    assert [(a[1], a[2]) for a in env.gov.api] == [
        ("admit_sync", {"provider": "tradier", "admit_timeout": float(data_sources._PROBE_TIMEOUT)}),
    ]
    assert env.paths() == [P_CLOCK]
    assert env.requests[-1].extensions["timeout"]["read"] == data_sources._PROBE_TIMEOUT


def test_probe_g1_not_admitted_is_degraded_without_http(env):
    from app.routers import data_sources
    env.gov.refuse = {"tradier"}
    status, detail = data_sources._probe_tradier()
    assert status == "degraded"
    assert "probe skipped" in detail
    assert env.requests == []


def _paper_creds(monkeypatch):
    from app.services.credential_store import credential_store
    monkeypatch.setattr(credential_store, "get",
                        lambda slot: {"token": "ptok", "account_id": "VA1"} if slot == "tradier_paper" else None)


def test_probe_g2_admitted_on_tradier_paper(env, monkeypatch):
    from app.routers import data_sources
    _paper_creds(monkeypatch)
    assert data_sources._probe_tradier_paper() == ("connected", None)
    assert [(a[1], a[2]) for a in env.gov.api] == [
        ("admit_sync", {"provider": "tradier_paper", "admit_timeout": float(data_sources._PROBE_TIMEOUT)}),
    ]
    assert env.paths("sandbox.tradier.com") == [P_CLOCK]


def test_probe_g2_not_admitted_sends_nothing(env, monkeypatch):
    from app.routers import data_sources
    _paper_creds(monkeypatch)
    env.gov.refuse = {"tradier_paper"}
    status, _ = data_sources._probe_tradier_paper()
    assert status == "degraded"
    assert env.requests == []


def _paper_order():
    from app.data.tradier_paper import BrokerOrder
    return BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
                       order_type="LMT", limit_price=1.0)


def test_paper_order_h_admitted_on_tradier_paper(env):
    from app.data.tradier_paper import TradierPaperAdapter
    result = TradierPaperAdapter("ptok", "VA1", timeout=7.0).place_order(_paper_order())
    assert result.order_id == "7"
    assert [(a[1], a[2], a[3]) for a in env.gov.api] == [
        ("admit_sync", {"provider": "tradier_paper", "admit_timeout": 7.0}, True),
    ]
    assert [(r.method, r.url.path) for r in env.requests] == [("POST", "/v1/accounts/VA1/orders")]


def test_paper_order_h_not_admitted_raises_and_makes_no_post(env):
    from app.data.tradier_paper import TradierPaperAdapter
    env.gov.refuse = {"tradier_paper"}
    with pytest.raises(RuntimeError, match="Tradier paper order failed"):
        TradierPaperAdapter("ptok", "VA1").place_order(_paper_order())
    assert env.requests == []                 # zero requests: never sent


# ── 8. Off the loop: the three moved callers and the AST scan ────────────────
_SYNC_FETCHES = {
    "fetch_candles", "fetch_intraday_candles", "fetch_price", "fetch_option_chain",
    "fetch_quotes", "fetch_earnings_date", "fetch_dividend_date", "fetch_company_name",
    "fetch_news", "tradier_next_earnings_date", "_fundamentals_calendar_sync",
}


def _direct_calls(node):
    """Calls in `node`'s own body: a nested def, lambda or class is skipped (it
    runs wherever it is called -- e.g. inside run_in_executor), and a function
    merely passed to asyncio.to_thread is a reference, not a call."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, ast.Call):
            f = child.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name in _SYNC_FETCHES:
                yield child.lineno, name
        yield from _direct_calls(child)


def _on_loop_sync_fetches(tree: ast.AST) -> list[tuple[str, int, str]]:
    return [(fn.name, line, name)
            for fn in ast.walk(tree) if isinstance(fn, ast.AsyncFunctionDef)
            for line, name in _direct_calls(fn)]


def test_on_loop_scan_detects_a_direct_call_and_allows_thread_handoff():
    src = (
        "async def bad(s):\n    return fetch_candles(s)\n"
        "async def ok(s, loop):\n"
        "    a = await asyncio.to_thread(fetch_candles, s)\n"
        "    b = await loop.run_in_executor(None, lambda: market.fetch_price(s))\n"
        "    def inner():\n        return fetch_news([s])\n"
        "    return await asyncio.to_thread(inner)\n"
    )
    assert _on_loop_sync_fetches(ast.parse(src)) == [("bad", 2, "fetch_candles")]


def test_no_sync_tradier_fetch_is_called_directly_on_the_event_loop():
    found = []
    for path in sorted(APP.rglob("*.py")):
        for fn, line, name in _on_loop_sync_fetches(ast.parse(path.read_text())):
            found.append(f"{path.relative_to(BACKEND)}:{line} {fn} -> {name}")
    assert found == []


async def test_candles_router_fetches_in_a_worker_thread(monkeypatch):
    from app.routers import candles
    loop_thread = threading.get_ident()
    seen = []

    def _fetch(symbol):
        seen.append((symbol, threading.get_ident()))
        return []

    monkeypatch.setattr(candles, "fetch_candles", _fetch)
    assert await candles.get_candles("aapl") == []
    assert seen and seen[0][0] == "AAPL" and seen[0][1] != loop_thread


async def test_regime_snapshot_intraday_fetch_runs_in_a_worker_thread(monkeypatch):
    import app.data.market as mkt
    import app.services.historical_store as hs
    from app.routers import composite_watch
    loop_thread = threading.get_ident()
    seen = []

    def _fetch(symbol, interval="15min", days=55):
        seen.append((symbol, interval, days, threading.get_ident()))
        return []

    async def _bars(*_a, **_k):
        return []

    monkeypatch.setattr(mkt, "fetch_intraday_candles", _fetch)
    monkeypatch.setattr(hs, "get_bars", _bars)
    with pytest.raises(Exception):
        await composite_watch.get_regime_snapshot("AAPL", direction="Bullish", model="HMM_intraday",
                                                  interval="15min")
    assert seen and seen[0][3] != loop_thread


# ── 9. Ratchet: every direct Tradier HTTP call is an allowlisted one ─────────
_TRADIER_MARKERS = {"_tradier_base", "get_tradier_creds", "TRADIER_BASE_URL", "_SANDBOX_BASE"}
_HTTP_METHODS = {"get", "post", "put", "delete", "request", "stream"}

# (file, enclosing function) -> why a direct Tradier HTTP call is allowed there.
# Every other one must go through market._tradier_get / _tradier_get_async.
RATCHET_ALLOWLIST = {
    ("app/data/market.py", "_tradier_get"):
        "the sync helper itself: admits on `tradier`, then sends",
    ("app/data/market.py", "_tradier_get_async"):
        "the async helper itself: admits through Governor.call / call_overdraft",
    ("app/services/auto_trader.py", "_option_quote_state.probe"):
        "site F: admitted by admit_sync(tradier, overdraft=True) just before (D3)",
    ("app/data/tradier_stream.py", "TradierStreamClient._run"):
        "site E's long-lived stream connection: one connection, not a request rate (D4)",
    ("app/routers/data_sources.py", "_probe_tradier_paper"):
        "site G2: sandbox account, admitted on `tradier_paper` just before (D4)",
    ("app/data/tradier_paper.py", "TradierPaperAdapter.place_order"):
        "site H: sandbox orders, admitted on `tradier_paper` just before (D4)",
}


def _references_tradier(node: ast.AST, tainted: set[str]) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and (n.id in _TRADIER_MARKERS or n.id in tainted):
            return True
        if isinstance(n, ast.Attribute) and n.attr in _TRADIER_MARKERS:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "tradier.com" in n.value:
            return True
    return False


def _names(target: ast.AST):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _names(elt)
    elif isinstance(target, ast.Starred):
        yield from _names(target.value)


def _own_nodes(scope: ast.AST):
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _url_arg(call: ast.Call):
    for kw in call.keywords:
        if kw.arg == "url":
            return kw.value
    idx = 1 if call.func.attr in ("request", "stream") else 0
    return call.args[idx] if len(call.args) > idx else None


def direct_tradier_calls(tree: ast.AST) -> list[tuple[str, int, str]]:
    """Every `<x>.get/post/put/delete/request/stream(...)` whose URL argument
    references a Tradier base (`_tradier_base`, `get_tradier_creds`,
    `TRADIER_BASE_URL`, `_SANDBOX_BASE`, a "tradier.com" literal) directly or
    through a local name assigned from one (in this scope or an enclosing one).
    Returns (enclosing qualname, line, callee)."""
    out = []

    def visit(scope, qual: str, inherited: set[str]) -> None:
        tainted = set(inherited)
        nodes = list(_own_nodes(scope))
        changed = True
        while changed:
            changed = False
            for n in nodes:
                pairs = []
                if isinstance(n, ast.Assign):
                    pairs = [(t, n.value) for t in n.targets]
                elif isinstance(n, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and n.value is not None:
                    pairs = [(n.target, n.value)]
                elif isinstance(n, (ast.With, ast.AsyncWith)):
                    pairs = [(i.optional_vars, i.context_expr) for i in n.items if i.optional_vars is not None]
                for target, value in pairs:
                    if _references_tradier(value, tainted):
                        for name in _names(target):
                            if name not in tainted:
                                tainted.add(name)
                                changed = True
        for n in nodes:
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in _HTTP_METHODS):
                url = _url_arg(n)
                if url is not None and _references_tradier(url, tainted):
                    out.append((qual, n.lineno, ast.unparse(n.func)))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(n, f"{qual}.{n.name}" if qual else n.name, tainted)

    visit(tree, "", set())
    return sorted(out, key=lambda r: r[1])


def test_ratchet_scanner_detects_direct_tradier_calls():
    src = (
        "def a():\n    return httpx.get(f'{_tradier_base()}/v1/x')\n"
        "def b():\n    token, base = get_tradier_creds()\n    return httpx.post(f'{base}/v1/y')\n"
        "async def c(client):\n    return await client.get('https://api.tradier.com/v1/z')\n"
        "def d():\n    _, base = get_tradier_creds()\n"
        "    def inner():\n        return client.stream('POST', base + '/s')\n    return inner\n"
        "def ok(url):\n    return httpx.get(url)\n"
        "def ok2():\n    return httpx.get('https://api.tiingo.com/x')\n"
    )
    assert [(q, c) for q, _, c in direct_tradier_calls(ast.parse(src))] == [
        ("a", "httpx.get"), ("b", "httpx.post"), ("c", "client.get"), ("d.inner", "client.stream"),
    ]


def test_every_direct_tradier_http_call_is_allowlisted():
    found: dict[tuple[str, str], list[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        for qual, line, callee in direct_tradier_calls(ast.parse(path.read_text())):
            found.setdefault((rel, qual), []).append(f"{rel}:{line} {callee}")
    unexpected = {k: v for k, v in found.items() if k not in RATCHET_ALLOWLIST}
    assert unexpected == {}, (
        "Direct Tradier HTTP call outside the governor helpers; route it through "
        "market._tradier_get / market._tradier_get_async (or justify it in RATCHET_ALLOWLIST)"
    )
    # The URL-tracing sites of the allowlist really are found (the scan works).
    for key in [("app/services/auto_trader.py", "_option_quote_state.probe"),
                ("app/routers/data_sources.py", "_probe_tradier_paper"),
                ("app/data/tradier_paper.py", "TradierPaperAdapter.place_order")]:
        assert key in found, key
    # Every allowlisted function still exists.
    for rel, qual in RATCHET_ALLOWLIST:
        tree = ast.parse((BACKEND / rel).read_text())
        quals = set()

        def walk(node, prefix=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    q = f"{prefix}.{child.name}" if prefix else child.name
                    quals.add(q)
                    walk(child, q)
                else:
                    walk(child, prefix)

        walk(tree)
        assert qual in quals, (rel, qual)
