"""Network-free T4 measurement of the real options scan's Tradier cost.

This is an all-survivors fetch upper bound: historical DB misses, unknown
company names, and a passing pre-screen for every fixture symbol. Empty option
chains terminate each symbol after its real chain fetch; scoring/plan creation
after that fetch adds no Tradier requests on the default long-option path.
The projection is limiter admission time only, excluding HTTP and computation.
"""

from collections import Counter, defaultdict
from contextvars import ContextVar
from datetime import date, timedelta
from threading import Lock
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.data import market
from app.data.governor import TokenBucket, build_default_governor
from app.routers import scan
from app.scoring.stock_scorer import RuleResult, StockScoreCard


@pytest.mark.asyncio
async def test_options_scan_cold_and_warm_tradier_call_budget(monkeypatch):
    symbols = [f"BUDGET{i:02d}" for i in range(20)]
    today = date.today()
    expiry = (today + timedelta(days=35)).isoformat()
    history = [
        {"date": (today - timedelta(days=251 - i)).isoformat(),
         "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000000}
        for i in range(252)
    ]
    # Replace cache objects, rather than clearing another test's live objects.
    for name in ("_candles_cache", "_company_cache",
                 "_fundamentals_calendar_cache", "_expirations_cache"):
        monkeypatch.setattr(market, name, {})
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("test-token", "https://api.tradier.com"))
    monkeypatch.setattr(scan, "get_tradier_creds", market.get_tradier_creds)
    monkeypatch.setattr("app.services.historical_store.get_bars", AsyncMock(return_value=[]))
    monkeypatch.setattr(scan, "get_fundamentals", AsyncMock(return_value=None))
    monkeypatch.setattr(scan, "fetch_calendar_dates_async", AsyncMock(
        side_effect=AssertionError("fixture calendar must not use yfinance")))
    monkeypatch.setattr(market, "_fetch_daily_yf", MagicMock(
        side_effect=AssertionError("fixture history must not use yfinance")))
    monkeypatch.setattr(scan, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(scan, "_compute_omm", lambda *a, **kw: None)
    monkeypatch.setattr("app.data.ibkr.fetch_iv_metrics_ibkr", lambda *a: None)
    monkeypatch.setattr("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", lambda *a: {})

    def passing_score(symbol, direction, horizon, *args, **kwargs):
        return StockScoreCard(symbol=symbol, direction=direction, horizon=horizon,
                              score=80, status="PASS",
                              rules=[RuleResult("trend", "PASS", 80, {})])

    monkeypatch.setattr(scan, "score_stock", passing_score)
    governor = build_default_governor()
    bucket = TokenBucket(rate=1000000, capacity=1000000)
    governor._providers["tradier"].bucket = bucket
    monkeypatch.setattr("app.data.governor.get_governor", lambda: governor)
    permit = ContextVar("scan_budget_admission", default=0)
    admitted = []
    requests = []
    lock = Lock()
    original_async = bucket.acquire
    original_sync = governor.admit_sync

    async def acquire(*args, **kwargs):
        await original_async(*args, **kwargs)
        permit.set(permit.get() + 1)
        with lock:
            admitted.append("tradier")

    def admit_sync(provider, **kwargs):
        ok = original_sync(provider, **kwargs)
        assert provider == "tradier"
        if ok:
            permit.set(permit.get() + 1)
            with lock:
                admitted.append(provider)
        return ok

    monkeypatch.setattr(bucket, "acquire", acquire)
    monkeypatch.setattr(governor, "admit_sync", admit_sync)

    def respond(request):
        assert permit.get() == 1, f"unadmitted or double-admitted request: {request.url.path}"
        permit.set(0)
        assert request.url.host == "api.tradier.com"
        endpoint = request.url.path
        requested = request.url.params.get("symbol") or request.url.params.get("symbols")
        with lock:
            requests.append((endpoint, requested))
        if endpoint == "/v1/markets/quotes":
            body = {"quotes": {"quote": [{"symbol": s, "last": 101, "prevclose": 100}
                                           for s in requested.split(",")]}}
        elif endpoint == "/v1/markets/history":
            body = {"history": {"day": history}}
        elif endpoint == "/beta/markets/fundamentals/company":
            body = [{"results": [{"tables": {"company_profile": {"company_name": requested}}}]}]
        elif endpoint == "/beta/markets/fundamentals/calendars":
            body = [{"results": [{"tables": {
                "earnings": {"report_date": (today + timedelta(days=180)).isoformat()},
                "dividend": {"ex_dividend_date": (today + timedelta(days=180)).isoformat()},
            }}]}]
        elif endpoint == "/v1/markets/options/expirations":
            body = {"expirations": {"date": [expiry]}}
        elif endpoint == "/v1/markets/options/chains":
            body = {"options": {"option": []}}
        else:
            raise AssertionError(f"unexpected endpoint: {request.url}")
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(respond)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_async_client(transport=transport, **kw))
    with httpx.Client(transport=transport) as sync_client:
        monkeypatch.setattr(httpx, "get", sync_client.get)
        req = scan.ScanRequest(universe=symbols, direction="Bullish", horizon="Swing", overrides={})
        counts = {}
        for mode in ("cold", "expirations_warm", "all_caches_warm"):
            if mode == "expirations_warm":
                for name in ("_candles_cache", "_company_cache", "_fundamentals_calendar_cache"):
                    getattr(market, name).clear()
                assert set(market._expirations_cache) == set(symbols)
            requests.clear()
            admitted.clear()
            result = await scan._execute_scan_core(req, MagicMock(), previous_result=None)
            assert result.pipeline.scanned == len(symbols)
            assert result.pipeline.no_chain == len(symbols), result.rejected
            assert len(admitted) == len(requests)
            assert set(admitted) == {"tradier"}
            counts[mode] = Counter(endpoint for endpoint, _ in requests)
            per_symbol = defaultdict(Counter)
            for endpoint, requested in requests:
                if endpoint != "/v1/markets/quotes":
                    per_symbol[requested][endpoint] += 1
            assert set(per_symbol) == set(symbols)
            assert all(c == per_symbol[symbols[0]] for c in per_symbol.values())
            per_name = sum(per_symbol[symbols[0]].values())
            print(f"\nT4 {mode}: N=20; endpoints={dict(sorted(counts[mode].items()))}; "
                  f"per-symbol endpoints={dict(sorted(per_symbol[symbols[0]].items()))}; "
                  f"total={len(requests)}; per-symbol={len(requests) / 20:.2f} "
                  "(includes one batch quote request)")
            for universe, n in (("SP500", 500), ("NDX100", 100), ("DOW30", 30)):
                projected_calls = n * per_name + 1
                seconds = max(0, projected_calls - 15) / (120 / 60)
                print(f"T4 all-survivors upper bound {mode} {universe}: {projected_calls} requests; "
                      f"minimum limiter time={seconds:.1f}s ({seconds / 60:.2f}min)")

    cold = {"/v1/markets/quotes": 1, "/v1/markets/history": 20,
            "/beta/markets/fundamentals/company": 20,
            "/beta/markets/fundamentals/calendars": 20,
            "/v1/markets/options/expirations": 20, "/v1/markets/options/chains": 20}
    assert counts["cold"] == cold
    assert counts["expirations_warm"] == {k: v for k, v in cold.items() if not k.endswith("expirations")}
    assert counts["all_caches_warm"] == {"/v1/markets/quotes": 1, "/v1/markets/options/chains": 20}
