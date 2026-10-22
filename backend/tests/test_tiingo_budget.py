"""HISTORY-INCREMENTAL-NIGHTLY A1: the persisted Tiingo usage ledger.

Every Tiingo HTTP attempt is recorded in `provider_request_log`; an attempt is
refused before it is sent when one of the four free-tier limits would be
exceeded (the nightly stops at limit - reserve). Plan section 4, ticket #477.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import anyio
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import governor as g
from app.data import tiingo
from app.data import tiingo_budget as budget
from app.models.provider_usage import ProviderRequestLog as Log, ProviderUsageBase
from app.services import history_backfill as history, historical_store as hs

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
START, END = date(2020, 1, 1), date(2020, 1, 10)
ROW = {"date": "2020-01-02", "open": 99, "high": 101, "low": 98,
       "close": 100, "adjClose": 50, "volume": 100}

SMALL = {"data_providers": {"tiingo": {
    "requests_per_hour": 3, "requests_per_day": 5, "symbols_per_month": 2,
    "bytes_per_month": 1000,
    "nightly_reserve": {"requests_per_day": 2, "symbols_per_month": 1, "bytes_per_month": 400},
}}}


def config(**overrides):
    block = {**SMALL["data_providers"]["tiingo"], **overrides}
    return {"data_providers": {"tiingo": block}}


@pytest_asyncio.fixture
async def ledger(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(ProviderUsageBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(budget, "AsyncSessionLocal", factory)
    monkeypatch.setattr(budget, "_utcnow", lambda: NOW)
    monkeypatch.setattr(budget, "_load_settings", lambda: SMALL)
    yield factory
    await engine.dispose()


@pytest.fixture
def gov(monkeypatch):
    governor = g.Governor.for_testing("tiingo", rate=100000, capacity=100000, fail_threshold=100)
    monkeypatch.setattr(tiingo, "get_governor", lambda: governor)
    return governor


def response(status=200, body=None, retry=None):
    return httpx.Response(status, json=[ROW] if body is None else body,
                          headers={} if retry is None else {"Retry-After": retry},
                          request=httpx.Request("GET", "https://api.tiingo.com/test"))


@pytest.fixture
def http(monkeypatch):
    """Mocked httpx.get: replies are taken from `replies` (default 200 + [ROW])."""
    calls, replies = [], []

    def get(url, **kwargs):
        calls.append(url)
        reply = replies.pop(0) if replies else response()
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(tiingo.httpx, "get", get)
    get.calls, get.replies = calls, replies
    return get


async def seed(factory, *rows):
    """rows: (age, symbol, bytes) tuples, recorded as tiingo 200 replies."""
    async with factory() as db:
        for age, symbol, size in rows:
            db.add(Log(provider="tiingo", requested_at=NOW - age, symbol=symbol,
                       response_bytes=size, status_code=200, caller="on_demand"))
        await db.commit()


async def rows(factory):
    async with factory() as db:
        return (await db.execute(select(Log).order_by(Log.id))).scalars().all()


async def fetch(symbol="ONE", caller=None):
    if caller is None:
        return await tiingo.fetch_historical_candles(symbol, START, END)
    with budget.caller(caller):
        return await tiingo.fetch_historical_candles(symbol, START, END)


# ── 1. Each limit refuses at exactly its limit; a refusal sends nothing ───────

@pytest.mark.asyncio
async def test_hour_limit_refuses_at_exactly_its_limit(ledger, gov, http):
    for _ in range(3):
        assert await fetch("ONE")
    with pytest.raises(g.ProviderUnavailable, match=r"requests_per_hour budget exhausted \(3/3\)"):
        await fetch("ONE")
    assert len(http.calls) == 3
    assert len(await rows(ledger)) == 3


@pytest.mark.asyncio
async def test_day_limit_is_a_rolling_24_hours(ledger, gov, http, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=100))
    h = timedelta(hours=1)
    await seed(ledger, (25 * h, "ONE", 1), (23 * h, "ONE", 1), (20 * h, "ONE", 1),
               (10 * h, "ONE", 1), (2 * h, "ONE", 1))
    with pytest.raises(g.ProviderUnavailable, match=r"requests_per_day budget exhausted \(4/3\)"):
        await fetch("ONE", caller="nightly")   # nightly share is 5 - 2 = 3
    assert await fetch("ONE")                  # on-demand: 4 < 5
    with pytest.raises(g.ProviderUnavailable, match=r"requests_per_day budget exhausted \(5/5\)"):
        await fetch("ONE")
    monkeypatch.setattr(budget, "_utcnow", lambda: NOW + timedelta(hours=1, minutes=1))
    assert await fetch("ONE")                  # the 23 h row left the window
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_symbol_limit_counts_distinct_symbols_over_31_days(ledger, gov, http):
    await seed(ledger, (timedelta(days=32), "OLD", 1), (timedelta(days=30), "ONE", 1))
    assert await fetch("TWO")                  # 1 distinct < 2
    with pytest.raises(g.ProviderUnavailable, match=r"symbols_per_month budget exhausted \(2/2\)"):
        await fetch("THREE")
    assert await fetch("ONE")                  # a repeat symbol is admitted
    assert await fetch("TWO")
    assert len(http.calls) == 3


@pytest.mark.asyncio
async def test_bytes_limit_over_31_days(ledger, gov, http, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=100,
                                                                 requests_per_day=100))
    await seed(ledger, (timedelta(days=40), "ONE", 5000), (timedelta(days=30), "ONE", 999))
    assert await fetch("ONE")                  # 999 < 1000
    with pytest.raises(g.ProviderUnavailable, match=r"bytes_per_month budget exhausted"):
        await fetch("ONE")
    assert len(http.calls) == 1


# ── 2. Nightly stops at limit - reserve; on-demand continues to the limit ─────

@pytest.mark.asyncio
async def test_nightly_stops_at_limit_minus_reserve(ledger, gov, http, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=100))
    await seed(ledger, *[(timedelta(hours=2), "ONE", 1)] * 3)
    with pytest.raises(g.ProviderUnavailable, match=r"requests_per_day budget exhausted \(3/3\)"):
        await fetch("ONE", caller="nightly")
    assert await fetch("ONE", caller="on_demand")
    assert await fetch("ONE")
    with pytest.raises(g.ProviderUnavailable, match=r"\(5/5\)"):
        await fetch("ONE")
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_nightly_symbol_and_byte_reserve(ledger, gov, http, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=100,
                                                                 requests_per_day=100))
    await seed(ledger, (timedelta(days=1), "ONE", 10))
    with pytest.raises(g.ProviderUnavailable, match=r"symbols_per_month budget exhausted \(1/1\)"):
        await fetch("TWO", caller="nightly")
    assert await fetch("TWO")                  # on-demand may take the reserve
    await seed(ledger, (timedelta(days=1), "ONE", 550))  # bytes now 10 + len(reply) + 550
    used = sum(r.response_bytes for r in await rows(ledger))
    assert 600 <= used < 1000
    with pytest.raises(g.ProviderUnavailable, match=r"bytes_per_month budget exhausted"):
        await fetch("ONE", caller="nightly")   # nightly stops at 1000 - 400 = 600
    assert await fetch("ONE")


@pytest.mark.asyncio
async def test_hour_limit_has_no_nightly_reserve(ledger, gov, http):
    await seed(ledger, *[(timedelta(minutes=5), "ONE", 1)] * 2)
    assert await fetch("ONE", caller="nightly")   # 2 < 3: no hourly reserve
    with pytest.raises(g.ProviderUnavailable, match=r"requests_per_hour"):
        await fetch("ONE", caller="nightly")


# ── 3. Every attempt that reached Tiingo is recorded (clarification 3) ────────

@pytest.mark.asyncio
async def test_429_retry_is_recorded_as_two_requests(ledger, gov, http):
    http.replies.extend([response(429, body={"detail": "slow down"}, retry="0"), response()])
    with budget.caller("nightly"):
        assert await fetch("ONE")
    recorded = await rows(ledger)
    assert [r.status_code for r in recorded] == [429, 200]
    assert [r.caller for r in recorded] == ["nightly", "nightly"]
    assert [r.symbol for r in recorded] == ["ONE", "ONE"]
    assert recorded[0].response_bytes == len(response(429, body={"detail": "slow down"}).content)
    assert recorded[1].response_bytes == len(response().content)


@pytest.mark.asyncio
async def test_4xx_and_5xx_replies_are_recorded(ledger, gov, http):
    http.replies.extend([response(404, body={"detail": "Not found."})])
    assert await fetch("NOPE") == []           # existing behaviour: [] on non-429 errors
    http.replies.extend([response(500, body={"detail": "boom"})])
    assert await fetch("ONE") == []
    assert [(r.status_code, r.symbol) for r in await rows(ledger)] == [(404, "NOPE"), (500, "ONE")]


@pytest.mark.asyncio
async def test_attempt_that_never_reached_tiingo_is_not_recorded(ledger, gov, http):
    http.replies.append(httpx.ConnectError("no route"))
    assert await fetch("ONE") == []
    assert await rows(ledger) == []


@pytest.mark.asyncio
async def test_symbol_is_recorded_in_tiingo_spelling(ledger, gov, http):
    assert await fetch("BRK.B")
    assert [r.symbol for r in await rows(ledger)] == ["BRK-B"]


# ── 4. Check-and-record is atomic between concurrent callers ──────────────────

@pytest.mark.asyncio
async def test_concurrent_nightly_and_on_demand_at_limit_minus_one(ledger, gov, http):
    await seed(ledger, *[(timedelta(minutes=5), "ONE", 1)] * 2)   # hour limit 3, used 2
    results = await asyncio.gather(fetch("ONE", caller="nightly"), fetch("ONE", caller="on_demand"),
                                   return_exceptions=True)
    admitted = [r for r in results if isinstance(r, list) and r]
    refused = [r for r in results if isinstance(r, g.ProviderUnavailable)]
    assert len(admitted) == 1 and len(refused) == 1
    assert len(http.calls) == 1
    assert len(await rows(ledger)) == 3


# ── 5. Refusal is ProviderUnavailable; _fetch_fallback moves to yfinance ──────

@pytest.mark.asyncio
async def test_refusal_falls_back_to_yfinance(ledger, gov, http, monkeypatch):
    await seed(ledger, *[(timedelta(minutes=5), "ONE", 1)] * 3)
    monkeypatch.setattr(hs, "_yfinance_fetch", lambda *args: [dict(
        ROW, time="2020-01-02", adj_factor=0.5, source="yfinance")])
    bars = await history._fetch_fallback("TEST", START, END)
    assert bars[0]["source"] == "yfinance"
    assert http.calls == []


# ── 6. Config: validated at load, free-tier defaults when absent ──────────────

def test_absent_block_gives_free_tier_defaults():
    for settings in ({}, {"data_providers": {}}, {"data_providers": {"tiingo": None}}):
        limits = budget.load_limits(settings)
        assert limits.limits == {"requests_per_hour": 50, "requests_per_day": 1000,
                                 "symbols_per_month": 500, "bytes_per_month": 1_000_000_000}
        assert limits.reserve == {"requests_per_day": 100, "symbols_per_month": 25,
                                  "bytes_per_month": 100_000_000}


def test_example_settings_carry_the_free_tier_block():
    import yaml
    from app.services.scheduling_tz import _SETTINGS_EXAMPLE_PATH
    example = yaml.safe_load(_SETTINGS_EXAMPLE_PATH.read_text())
    assert budget.load_limits(example) == budget.load_limits({})
    assert example["data_providers"]["tiingo"]["requests_per_hour"] == 50


@pytest.mark.parametrize("settings, key", [
    (config(requests_per_hour=-1), "data_providers.tiingo.requests_per_hour"),
    (config(requests_per_day=0), "data_providers.tiingo.requests_per_day"),
    (config(bytes_per_month="1GB"), "data_providers.tiingo.bytes_per_month"),
    (config(symbols_per_month=True), "data_providers.tiingo.symbols_per_month"),
    ({"data_providers": {"tiingo": {k: v for k, v in SMALL["data_providers"]["tiingo"].items()
                                    if k != "symbols_per_month"}}},
     "data_providers.tiingo.symbols_per_month"),
    (config(nightly_reserve={"requests_per_day": 5, "symbols_per_month": 1, "bytes_per_month": 1}),
     "data_providers.tiingo.nightly_reserve.requests_per_day"),
    (config(nightly_reserve={"requests_per_day": 1, "symbols_per_month": -1, "bytes_per_month": 1}),
     "data_providers.tiingo.nightly_reserve.symbols_per_month"),
    (config(nightly_reserve={"requests_per_day": 1, "symbols_per_month": 1}),
     "data_providers.tiingo.nightly_reserve.bytes_per_month"),
    (config(nightly_reserve=None), "data_providers.tiingo.nightly_reserve"),
    ({"data_providers": {"tiingo": [1, 2]}}, "data_providers.tiingo"),
    ({"data_providers": "x"}, "data_providers"),
])
def test_invalid_config_names_the_key(settings, key):
    with pytest.raises(budget.TiingoBudgetConfigError) as exc:
        budget.load_limits(settings)
    assert key in str(exc.value)


@pytest.mark.asyncio
async def test_invalid_config_refuses_without_sending(ledger, gov, http, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=-1))
    with pytest.raises(g.ProviderUnavailable, match="data_providers.tiingo.requests_per_hour"):
        await fetch("ONE")
    assert http.calls == []


# ── 7. Prune deletes only rows older than 40 days ─────────────────────────────

@pytest.mark.asyncio
async def test_prune_deletes_only_rows_older_than_40_days(ledger):
    d = timedelta(days=1)
    await seed(ledger, (41 * d, "A", 1), (40 * d + timedelta(seconds=1), "B", 1),
               (40 * d - timedelta(seconds=1), "C", 1), (d, "D", 1))
    assert await budget.prune_usage() == 2
    assert [r.symbol for r in await rows(ledger)] == ["C", "D"]


@pytest.mark.asyncio
async def test_nightly_maintenance_runs_the_prune(monkeypatch):
    from app.services import audit, ingestion_scheduler
    monkeypatch.setattr(audit, "rotate_audit_log", lambda: None)
    monkeypatch.setattr(audit, "prune_audit_log_archives", lambda years: None)
    monkeypatch.setattr("app.services.scan_schedule_store.prune_scheduled_scan_runs",
                        AsyncMock(return_value=0))
    prune = AsyncMock(return_value=0)
    monkeypatch.setattr(budget, "prune_usage", prune)
    await ingestion_scheduler._run_nightly_maintenance()
    prune.assert_awaited_once_with()


# ── Clarification 1: who counts as "nightly" ──────────────────────────────────

@pytest.mark.asyncio
async def test_caller_context_default_and_task_inheritance():
    assert budget.current_caller() == "on_demand"
    seen = []

    async def job():
        await asyncio.sleep(0)
        seen.append(budget.current_caller())

    with budget.caller("nightly"):
        task = asyncio.create_task(job())
    assert budget.current_caller() == "on_demand"
    await task
    assert seen == ["nightly"]
    with pytest.raises(ValueError):
        with budget.caller("bogus"):
            pass


@pytest.mark.asyncio
async def test_scheduled_nightly_starts_ingestion_as_nightly(monkeypatch):
    from app.services import ingestion_job, ingestion_scheduler
    seen = []
    monkeypatch.setattr(ingestion_job, "start_ingestion_task",
                        lambda *a, **k: seen.append(budget.current_caller()) or True)
    monkeypatch.setattr(ingestion_job, "ingestion_universe", lambda: ["SPY"])
    monkeypatch.setattr(ingestion_scheduler, "_run_nightly_maintenance", AsyncMock())
    await ingestion_scheduler._run_nightly()
    assert seen == ["nightly"]
    assert budget.current_caller() == "on_demand"


@pytest.mark.asyncio
async def test_startup_catch_up_starts_ingestion_as_nightly(monkeypatch):
    from app.services import ingestion_job

    class Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    seen = []
    monkeypatch.setattr(ingestion_job, "AsyncSessionLocal", Session)
    monkeypatch.setattr(ingestion_job, "_last_stored_date", AsyncMock(return_value=None))
    monkeypatch.setattr(ingestion_job, "ingestion_universe", lambda: ["SPY"])
    monkeypatch.setattr(ingestion_job, "start_ingestion_task",
                        lambda *a, **k: seen.append(budget.current_caller()) or True)
    assert await ingestion_job.startup_catch_up()
    assert seen == ["nightly"]
    assert budget.current_caller() == "on_demand"


@pytest.mark.asyncio
async def test_nightly_task_records_nightly_caller(ledger, gov, http):
    with budget.caller("nightly"):
        task = asyncio.create_task(fetch("ONE"))
    assert await task
    assert [r.caller for r in await rows(ledger)] == ["nightly"]


# ── R2-F1 (#498): a run-scoped tally of the run's own recorded attempts ───────

@pytest.mark.asyncio
async def test_run_usage_counts_only_attempts_recorded_in_its_context(ledger, gov, http):
    started, sibling_done = asyncio.Event(), asyncio.Event()

    async def sibling():                       # same caller, created outside the tally
        await started.wait()
        await fetch("TWO")
        sibling_done.set()

    other = asyncio.create_task(sibling())
    with budget.run_usage() as usage:
        await fetch("ONE")
        await asyncio.create_task(fetch("ONE"))   # a child task created inside: counted
        started.set()
        await sibling_done.wait()              # recorded while the tally is open: not counted
    await other
    recorded = await rows(ledger)
    assert [(r.symbol, r.caller) for r in recorded] == [("ONE", "on_demand")] * 2 + [
        ("TWO", "on_demand")]
    assert (usage.requests, usage.bytes, usage.unrecorded) == (
        2, sum(r.response_bytes for r in recorded if r.symbol == "ONE"), False)
    assert usage.bytes > 0


@pytest.mark.asyncio
async def test_run_usage_does_not_count_a_refused_attempt(ledger, gov, http):
    with budget.run_usage() as usage:
        for _ in range(3):
            await fetch("ONE")
        with pytest.raises(g.ProviderUnavailable, match="requests_per_hour budget exhausted"):
            await fetch("ONE")
    assert len(http.calls) == 3
    assert (usage.requests, usage.unrecorded) == (3, False)


@pytest.mark.asyncio
async def test_run_usage_flags_an_attempt_the_ledger_could_not_record(gov, http, monkeypatch):
    class Broken:
        async def __aenter__(self):
            raise RuntimeError("database down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(budget, "AsyncSessionLocal", Broken)
    monkeypatch.setattr(budget, "_load_settings", lambda: SMALL)
    with budget.run_usage() as usage:
        assert await fetch("ONE")
    assert len(http.calls) == 1
    assert (usage.requests, usage.bytes, usage.unrecorded) == (0, 0, True)


@pytest.mark.asyncio
async def test_probe_records_probe_caller_and_reports_exhaustion(ledger, monkeypatch):
    from app.routers import data_sources
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json={"message": "hello"}, request=httpx.Request("GET", url))

    monkeypatch.setenv("TIINGO_API_TOKEN", "test-token")
    monkeypatch.setattr(data_sources.httpx, "get", get)
    assert await anyio.to_thread.run_sync(data_sources._probe_tiingo) == ("connected", None)
    recorded = await rows(ledger)
    assert [(r.caller, r.symbol, r.status_code) for r in recorded] == [("probe", None, 200)]

    await seed(ledger, (timedelta(days=1), "ONE", 1), (timedelta(days=1), "TWO", 1))
    status, detail = await anyio.to_thread.run_sync(data_sources._probe_tiingo)
    assert status == "degraded" and "symbols_per_month budget exhausted (2/2)" in detail
    assert len(calls) == 2                     # symbols do not block the symbol-less probe

    await seed(ledger, (timedelta(minutes=1), None, 1))   # hour: 3/3
    status, detail = await anyio.to_thread.run_sync(data_sources._probe_tiingo)
    assert status == "degraded" and "requests_per_hour budget exhausted (3/3)" in detail
    assert len(calls) == 2                     # refused probe sent nothing


# ── Clarification 2: a budget refusal is not a provider failure ───────────────

@pytest.mark.asyncio
async def test_refusal_does_not_touch_breaker_status_or_retries(ledger, gov, http):
    ps = gov._providers["tiingo"]
    ps.status = "connected"
    await seed(ledger, *[(timedelta(minutes=5), "ONE", 1)] * 3)
    for _ in range(5):
        with pytest.raises(g.ProviderUnavailable, match="budget exhausted"):
            await fetch("ONE")
    assert ps.breaker._failures == 0 and not ps.breaker.is_open
    assert ps.status == "connected"
    assert http.calls == []


@pytest.mark.asyncio
async def test_refusal_on_a_governor_retry_is_not_booked_or_retried(ledger, gov, http, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=1))
    http.replies.extend([response(429, body={"detail": "slow"}, retry="0"), response()])
    ps = gov._providers["tiingo"]
    with pytest.raises(g.ProviderUnavailable, match=r"requests_per_hour budget exhausted \(1/1\)"):
        await fetch("ONE")
    assert len(http.calls) == 1                # the retry was refused before sending
    assert ps.breaker._failures == 1           # only the real 429
    assert ps.status == "degraded"             # from the 429, never "down"
    assert [r.status_code for r in await rows(ledger)] == [429]


# ── A ledger outage never blocks data (stated assumption, module docstring) ───

@pytest.mark.asyncio
async def test_unreadable_ledger_admits_and_logs(gov, http, monkeypatch, caplog):
    class Broken:
        async def __aenter__(self):
            raise RuntimeError("database down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(budget, "AsyncSessionLocal", Broken)
    monkeypatch.setattr(budget, "_load_settings", lambda: SMALL)
    assert await fetch("ONE")
    assert len(http.calls) == 1
    assert "ledger" in caplog.text


# ── A2 (#478): read-only usage summary for GET /api/data/ingest/status ────────

@pytest.mark.asyncio
async def test_usage_summary_reports_each_limit_from_the_ledger(ledger):
    await seed(ledger,
               (timedelta(minutes=10), "ONE", 100),     # in every window
               (timedelta(minutes=70), "TWO", 50),      # outside the hour
               (timedelta(hours=25), "ONE", 30),        # outside the day
               (timedelta(days=5), None, 20),           # probe-like: no symbol
               (timedelta(days=32), "OLD", 999))        # outside every window
    async with ledger() as db:                          # another provider: never counted
        db.add(Log(provider="alpaca", requested_at=NOW, symbol="X", response_bytes=7,
                   status_code=200, caller="on_demand"))
        await db.commit()
    summary = await budget.usage_summary()
    assert summary == {
        "requests_per_hour": {"used": 1, "limit": 3, "nightly_stop_at": 3, "window": "rolling 1 h"},
        "requests_per_day": {"used": 2, "limit": 5, "nightly_stop_at": 3, "window": "rolling 24 h"},
        "symbols_per_month": {"used": 2, "limit": 2, "nightly_stop_at": 1, "window": "rolling 31 d"},
        "bytes_per_month": {"used": 200, "limit": 1000, "nightly_stop_at": 600,
                            "window": "rolling 31 d"},
    }


@pytest.mark.asyncio
async def test_usage_summary_defaults_when_config_block_absent(ledger, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: {})
    summary = await budget.usage_summary()
    assert {k: (v["used"], v["limit"], v["nightly_stop_at"]) for k, v in summary.items()} == {
        "requests_per_hour": (0, 50, 50),
        "requests_per_day": (0, 1000, 900),
        "symbols_per_month": (0, 500, 475),
        "bytes_per_month": (0, 1_000_000_000, 900_000_000),
    }


@pytest.mark.asyncio
async def test_usage_summary_matches_the_admission_check(ledger):
    """At used == nightly_stop_at the nightly is refused with the same numbers;
    on-demand (stop at limit) is still admitted."""
    await seed(ledger, *[(timedelta(hours=2), "ONE", 1)] * 3)
    day = (await budget.usage_summary())["requests_per_day"]
    assert (day["used"], day["nightly_stop_at"], day["limit"]) == (3, 3, 5)
    reason = await budget._refusal("ONE", "nightly", NOW)
    assert reason == (f"tiingo requests_per_day budget exhausted "
                      f"({day['used']}/{day['nightly_stop_at']})")
    assert await budget._refusal("ONE", "on_demand", NOW) is None


@pytest.mark.asyncio
async def test_usage_summary_raises_on_invalid_config(ledger, monkeypatch):
    monkeypatch.setattr(budget, "_load_settings", lambda: config(requests_per_hour=-1))
    with pytest.raises(budget.TiingoBudgetConfigError, match="requests_per_hour"):
        await budget.usage_summary()


@pytest.mark.asyncio
async def test_ingest_status_shows_tiingo_usage_from_the_ledger(ledger, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.main import create_app
    from app.routers import ingestion

    await seed(ledger, (timedelta(minutes=5), "ONE", 120))
    monkeypatch.setattr(ingestion, "get_ingestion_state", lambda: {"status": "idle"})
    monkeypatch.setattr(ingestion, "single_provider_symbols", AsyncMock(return_value={}))
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as ac:
        resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tiingo_usage"] == await budget.usage_summary()
    assert body["tiingo_usage"]["bytes_per_month"] == {
        "used": 120, "limit": 1000, "nightly_stop_at": 600, "window": "rolling 31 d"}
    assert body["tiingo_usage_error"] is None
