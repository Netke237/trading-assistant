"""B3 (HISTORY-INCREMENTAL-NIGHTLY plan 2.7, section 4 "Visible", section 5 B3): the two-pass
nightly run, the Tiingo priority queue and the run counters.

The integration tests run ``ingestion_job.run_ingestion`` night by night against an in-memory
database, the real ``update_history`` / ``rebuild_single_provider`` and the real Tiingo usage
ledger (``tiingo_budget.send_recorded`` / ``ensure_room`` on its own in-memory table). Each
symbol has its own deterministic provider world. A night runs at 20:00 ET on its ET date
(that day's bar has settled), with ``date.today()`` = that date.

The symbols of the main scenario, by the night ``N = E + L``:

- ``SPY`` / ``TT``: Tiingo-only (their seam is refused on the first night and they are rebuilt
  from Tiingo), so ``SINGLE_PROVIDER_RECENT`` every later night;
- ``AAA``: joins on ``E``; ``SUFFIX_ONLY`` on ``N``;
- ``CCC``: a dividend ``E`` after the seam: ``RESCALE`` on ``E``, ``CONFIRM`` on ``N``;
- ``RRR``: prefix older than ``revalidate_days`` on ``N``: ``SUFFIX_ONLY`` + ``REVALIDATE``;
- ``FFF``: joins on ``N`` with no state: ``FULL``.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import tiingo
from app.data import tiingo_budget as budget
from app.data.governor import ProviderUnavailable
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.models.provider_usage import ProviderRequestLog as Log, ProviderUsageBase
from app.services import historical_store as hs
from app.services import history_backfill as history
from app.services import history_incremental as hi
from app.services import ingestion_job as job

ET = hs.MARKET_TZ
SEAM = date(2020, 7, 27)     # Monday: Alpaca's first date
SEED = date(2020, 9, 1)      # Tuesday: the first nightly run
E = date(2020, 9, 9)         # Wednesday: CCC's ex-date; P(E) = 09-08
L = hi.DEFAULT_PARAMS.provider_lag_days
N = date(2020, 9, 16)        # E + L trading days: CONFIRM due, RRR revalidation due
REPLY_BYTES = 1000

COUNTERS = ("suffix_only", "adjustment_changed", "prefix_refetched", "prefix_rescaled",
            "prefix_confirmed", "confirm_retry", "lag_window_full", "single_provider_recent",
            "single_provider_skipped_current", "revalidated", "revalidation_skipped_budget",
            "tiingo_requests", "tiingo_bytes")

BIG = {"data_providers": {"tiingo": {
    "requests_per_hour": 100000, "requests_per_day": 100000, "symbols_per_month": 100000,
    "bytes_per_month": 10 ** 12,
    "nightly_reserve": {"requests_per_day": 1, "symbols_per_month": 1, "bytes_per_month": 1},
}}}
# The nightly stops at requests_per_day - reserve = 2 requests in the rolling 24 h.
TWO_PER_DAY = {"data_providers": {"tiingo": {
    **BIG["data_providers"]["tiingo"], "requests_per_day": 3,
    "nightly_reserve": {"requests_per_day": 1, "symbols_per_month": 1, "bytes_per_month": 1},
}}}
# RRR (F = SEED) is due on N (age 15), not on E (age 8); AAA (F = E) is not due on N (age 7).
SETTINGS = {"history_incremental": {"revalidate_days": 14, "revalidate_per_night": 10}}


def weekdays(a: date, b: date) -> list[date]:
    out = []
    while a <= b:
        if a.weekday() < 5:
            out.append(a)
        a += timedelta(days=1)
    return out


def et(d: date, hour: int = 20) -> datetime:
    return datetime.combine(d, time(hour), tzinfo=ET).astimezone(timezone.utc)


def base_close(d: date) -> float:
    return 100 + (d.toordinal() % 7) * 0.25 + (d.toordinal() % 3) * 0.13


@dataclass
class Ev:
    date: date
    s: float


@dataclass
class World:
    """One symbol's provider world; every provider applies an event from its ex-date on."""
    events: list = field(default_factory=list)
    tiingo_bias: float = 1.0
    yfinance_empty: bool = False

    def factor(self, d: date, night: date) -> float:
        f = 1.0
        for e in self.events:
            if d < e.date <= night:
                f *= e.s
        return f

    def bar(self, d: date, provider: str, night: date) -> dict:
        raw, f = round(base_close(d), 4), self.factor(d, night)
        if provider == "yfinance":
            close, f = round(raw * f, 4), 1.0
        else:
            close = raw
            if provider == "tiingo":
                f *= self.tiingo_bias
        return {"time": d.isoformat(), "open": close, "high": round(close + 1, 4),
                "low": round(close - 1, 4), "close": close, "volume": 1000,
                "adj_factor": round(f, 8), "split_factor": 1.0, "div_cash": 0.0,
                "source": provider}

    def reply(self, provider: str, start: date, end: date, night: date) -> list[dict]:
        return [self.bar(d, provider, night) for d in weekdays(start, min(end, night))]


def worlds() -> dict[str, World]:
    return {
        "SPY": World(tiingo_bias=0.9, yfinance_empty=True),   # seam refused -> Tiingo-only
        "TT": World(tiingo_bias=0.9, yfinance_empty=True),
        "AAA": World(),
        "CCC": World([Ev(E, 0.995)]),
        "RRR": World(),
        "FFF": World(),
    }


class Nightly:
    def __init__(self, monkeypatch, factory, ledger):
        self.monkeypatch = monkeypatch
        self.factory = factory
        self.ledger = ledger
        self.worlds = worlds()
        self.night = SEED
        self.now = et(SEED)
        self.log: list[tuple] = []
        self.settings = dict(SETTINGS)
        self.limits = BIG
        env = self

        class FixedDate(date):
            @classmethod
            def today(cls):
                return env.night

        for module in (history, hs, job):
            monkeypatch.setattr(module, "AsyncSessionLocal", factory)
        monkeypatch.setattr(hs, "_utcnow", lambda: self.now)
        monkeypatch.setattr(job, "date", FixedDate)
        monkeypatch.setattr(job, "effective_years", lambda years=None: 1)
        monkeypatch.setattr(job, "_state", dict(job._state))
        monkeypatch.setattr(job, "_load_settings", lambda: self.settings)
        monkeypatch.setattr(history, "notify_bars_changed", MagicMock())
        monkeypatch.setattr(budget, "AsyncSessionLocal", ledger)
        monkeypatch.setattr(budget, "_utcnow", lambda: self.now)
        monkeypatch.setattr(budget, "_load_settings", lambda: self.limits)
        monkeypatch.setattr(tiingo, "fetch_historical_candles", self._tiingo)
        monkeypatch.setattr(hs, "_yfinance_fetch", self._yfinance)
        monkeypatch.setattr(job, "get_alpaca_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(job, "fetch_daily_bars_batch", self._batch)
        real_update, real_rebuild = job.update_history, job.rebuild_single_provider

        async def update(symbol, *args, **kwargs):
            self.log.append(("update", symbol, kwargs.get("tiingo_allowed", True),
                             kwargs.get("revalidate", False)))
            try:
                return await real_update(symbol, *args, **kwargs)
            finally:
                self.log.append(("done", symbol))

        async def rebuild(symbol, *args, **kwargs):
            self.log.append(("rebuild", symbol))
            return await real_rebuild(symbol, *args, **kwargs)

        monkeypatch.setattr(job, "update_history", update)
        monkeypatch.setattr(job, "rebuild_single_provider", rebuild)

    async def _batch(self, chunk, start, end, *, client, strict_adjustments):
        assert strict_adjustments is True
        self.log.append(("batch",))
        return {s: self.worlds[s].reply("alpaca", SEAM, end, self.night) for s in chunk}

    async def _tiingo(self, symbol, start, end, *, strict_adjustments):
        """``fetch_historical_candles`` through the real ledger, as ``tiingo.request`` does."""
        assert strict_adjustments is True
        self.log.append(("tiingo", symbol))

        async def send():
            return SimpleNamespace(content=b"x" * REPLY_BYTES, status_code=200)

        try:
            await budget.send_recorded(symbol, send)
        except budget.BudgetRefused as exc:
            raise ProviderUnavailable(str(exc)) from None
        return self.worlds[symbol].reply("tiingo", start, end, self.night)

    def _yfinance(self, symbol, start, end):
        self.log.append(("yfinance", symbol))
        w = self.worlds[symbol]
        return [] if w.yfinance_empty else w.reply("yfinance", start, end, self.night)

    async def run(self, day: date, symbols: list[str], *, hour: int = 20, **kwargs):
        self.night, self.now = day, et(day, hour)
        self.log.clear()
        with budget.caller("nightly"):
            return await job.run_ingestion(symbols, **kwargs)

    async def state(self, symbol: str) -> State | None:
        async with self.factory() as db:
            return await db.get(State, symbol)

    async def rowmap(self, symbol: str) -> dict:
        async with self.factory() as db:
            found = (await db.execute(select(M).where(M.symbol == symbol)
                                      .order_by(M.date))).scalars().all()
        return {r.date: r for r in found}

    async def snapshot(self):
        async with self.factory() as db:
            found = (await db.execute(select(M).order_by(M.symbol, M.date))).scalars().all()
            states = (await db.execute(select(State).order_by(State.symbol))).scalars().all()
        cols = [c.name for c in M.__table__.columns]
        scols = [c.name for c in State.__table__.columns]
        return ([tuple(getattr(r, c) for c in cols) for r in found],
                [tuple(getattr(x, c) for c in scols) for x in states])

    def pass_two(self) -> list[tuple]:
        """The update calls after the last pass-1 call, as (symbol, revalidate)."""
        calls = [e for e in self.log if e[0] == "update"]
        return [(e[1], e[3]) for e in calls if e[2] is True]

    def tiingo_symbols(self) -> list[str]:
        return [e[1] for e in self.log if e[0] == "tiingo"]


@pytest_asyncio.fixture
async def nightly(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    ledger_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with ledger_engine.begin() as conn:
        await conn.run_sync(ProviderUsageBase.metadata.create_all)
    env = Nightly(monkeypatch, async_sessionmaker(engine, expire_on_commit=False),
                  async_sessionmaker(ledger_engine, expire_on_commit=False))
    yield env
    await engine.dispose()
    await ledger_engine.dispose()


async def seed_to_n_minus(env: Nightly) -> None:
    """Nights SEED and E: SPY/TT become Tiingo-only, CCC is rescaled on E, AAA joins on E."""
    first = await env.run(SEED, ["CCC", "RRR", "TT", "SPY"])
    assert first.rebuilt_symbols == ["SPY", "TT"] and first.failed == 0, first.errors
    second = await env.run(E, ["AAA", "CCC", "RRR", "TT", "SPY"])
    assert second.failed == 0, second.errors
    state = job.get_ingestion_state()
    assert state["prefix_rescaled"] == 1 and state["adjustment_changed"] == 1   # CCC
    assert state["prefix_refetched"] == 1                                        # AAA (FULL)
    assert state["suffix_only"] == 1                                             # RRR
    assert state["single_provider_recent"] == 2                                  # SPY, TT
    for sym in ("SPY", "TT"):
        assert (await env.state(sym)).basis_provider == "tiingo"


N_UNIVERSE = ["AAA", "CCC", "FFF", "RRR", "TT", "SPY"]


# ── pass order: no Tiingo call before pass 1 finishes; SPY first in pass 2 ──

async def test_pass_one_makes_no_tiingo_request_and_pass_two_runs_in_priority_order(nightly):
    env = nightly
    await seed_to_n_minus(env)
    result = await env.run(N, N_UNIVERSE)
    assert result.failed == 0, result.errors
    log = env.log
    pass_one = [e for e in log if e[0] == "update" and e[2] is False]
    assert [e[1] for e in pass_one] == N_UNIVERSE                  # every symbol, input order
    assert all(e[3] is False for e in pass_one)                    # revalidate=False in pass 1
    pass_two_start = next(i for i, e in enumerate(log) if e[0] == "update" and e[2] is True)
    assert all(log.index(e) < pass_two_start for e in pass_one)
    assert log[pass_two_start - 1] == ("done", N_UNIVERSE[-1])      # pass 1 has finished
    assert [e for e in log[:pass_two_start] if e[0] == "tiingo"] == []   # no Tiingo in pass 1
    assert log.index(("batch",)) < log.index(pass_one[0])          # the Alpaca batch first
    # SPY first (whatever its position in the universe), then the other single-provider
    # symbol, then FULL, then CONFIRM, then the revalidation (revalidate=True) last.
    assert env.pass_two() == [("SPY", False), ("TT", False), ("FFF", False), ("CCC", False),
                              ("RRR", True)]
    assert env.tiingo_symbols() == ["SPY", "TT", "FFF", "CCC", "RRR"]
    assert result.total == 6 and job.get_ingestion_state()["done"] == 6


# ── the counters ──────────────────────────────────────────────────────────────

async def test_counters_for_a_two_pass_night_reset_on_the_next_run(nightly):
    env = nightly
    await seed_to_n_minus(env)
    await env.run(N, N_UNIVERSE)
    state = job.get_ingestion_state()
    assert {k: state[k] for k in COUNTERS} == {
        "suffix_only": 2,                      # AAA, RRR (pass 1)
        "adjustment_changed": 0,
        "prefix_refetched": 3,                 # FFF (FULL), CCC (CONFIRM), RRR (REVALIDATE)
        "prefix_rescaled": 0,
        "prefix_confirmed": 1,                 # CCC
        "confirm_retry": 0,
        "lag_window_full": 0,
        "single_provider_recent": 2,           # SPY, TT
        "single_provider_skipped_current": 0,
        "revalidated": 1,                      # RRR
        "revalidation_skipped_budget": 0,
        "tiingo_requests": 5,                  # ledger rows, caller "nightly", this run
        "tiingo_bytes": 5 * REPLY_BYTES,
    }
    st = await env.state("CCC")
    assert hs._as_utc(st.floor_checked_at) == et(N)                # CONFIRM: F = tonight
    st = await env.state("RRR")
    assert hs._as_utc(st.floor_checked_at) == et(N)                # REVALIDATE: F = tonight
    # A second run the same night: everything is current or trusted; counters reset.
    await env.run(N, N_UNIVERSE, hour=21)
    state = job.get_ingestion_state()
    assert {k: state[k] for k in COUNTERS} == {
        "suffix_only": 4, "adjustment_changed": 0, "prefix_refetched": 0, "prefix_rescaled": 0,
        "prefix_confirmed": 0, "confirm_retry": 0, "lag_window_full": 0,
        "single_provider_recent": 0, "single_provider_skipped_current": 2, "revalidated": 0,
        "revalidation_skipped_budget": 0, "tiingo_requests": 0, "tiingo_bytes": 0,
    }
    assert env.tiingo_symbols() == []


async def test_summary_log_line_carries_every_counter(nightly, caplog):
    env = nightly
    await seed_to_n_minus(env)
    with caplog.at_level(logging.INFO, logger="app.services.ingestion_job"):
        await env.run(N, N_UNIVERSE)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ingestion complete")]
    assert len(lines) == 1
    state = job.get_ingestion_state()
    for key in COUNTERS:
        assert f"{key}={state[key]}" in lines[0], key


# ── a budget refusal mid-pass-2 does not stop the pass ────────────────────────

async def test_budget_refusal_mid_pass_two_writes_full_via_yfinance_confirm_suffix_skips_revalidate(
        nightly):
    env = nightly
    await seed_to_n_minus(env)
    env.limits = TWO_PER_DAY                 # SPY and TT take the nightly share tonight
    env.worlds["CCC"].yfinance_empty = True  # CONFIRM: Tiingo refused, yfinance empty
    rrr_before = await env.rowmap("RRR")
    rrr_state_before = await env.state("RRR")
    result = await env.run(N, N_UNIVERSE)
    assert result.failed == 0, result.errors
    # Pass 2 kept going after the refusal: FFF and CCC still ran, RRR's revalidation did not.
    assert env.pass_two() == [("SPY", False), ("TT", False), ("FFF", False), ("CCC", False)]
    assert env.tiingo_symbols() == ["SPY", "TT", "FFF", "CCC"]     # FFF/CCC refused unsent
    async with env.ledger() as db:
        sent = (await db.execute(select(Log.symbol).where(Log.requested_at == et(N))
                                 .order_by(Log.id))).scalars().all()
    assert sent == ["SPY", "TT"]
    # FULL: written via yfinance.
    fff = await env.rowmap("FFF")
    assert fff and {r.source for d, r in fff.items() if d < SEAM} == {"yfinance"}
    assert (await env.state("FFF")).old_source == "yfinance"
    # CONFIRM: no usable reply -> SUFFIX_ONLY, the rescaled prefix kept, F unchanged.
    ccc_state = await env.state("CCC")
    assert hs._as_utc(ccc_state.floor_checked_at) == et(SEED)
    # REVALIDATE: skipped; RRR was written SUFFIX_ONLY in pass 1 (prefix untouched).
    rrr_after = await env.rowmap("RRR")
    kept = [d for d in rrr_after if d < SEAM]          # rows older than the window are pruned
    assert kept and all(d in rrr_before for d in kept)
    for d in kept:
        assert (rrr_after[d].fetched_at, rrr_after[d].adj_factor, rrr_after[d].close) == (
            rrr_before[d].fetched_at, rrr_before[d].adj_factor, rrr_before[d].close)
    assert {hs._as_utc(r.fetched_at) for d, r in rrr_after.items() if d >= SEAM} == {et(N)}
    assert (hs._as_utc((await env.state("RRR")).floor_checked_at)
            == hs._as_utc(rrr_state_before.floor_checked_at))
    state = job.get_ingestion_state()
    assert {k: state[k] for k in COUNTERS} == {
        "suffix_only": 3,                      # AAA, RRR, CCC (confirm_retry)
        "adjustment_changed": 0,
        "prefix_refetched": 1,                 # FFF
        "prefix_rescaled": 0,
        "prefix_confirmed": 0,
        "confirm_retry": 1,                    # CCC
        "lag_window_full": 0,
        "single_provider_recent": 2,
        "single_provider_skipped_current": 0,
        "revalidated": 0,
        "revalidation_skipped_budget": 1,      # RRR
        "tiingo_requests": 2,
        "tiingo_bytes": 2 * REPLY_BYTES,
    }
    # The next night, with room again, CCC's CONFIRM is tried again.
    env.limits = BIG
    env.worlds["CCC"].yfinance_empty = False
    nxt = date(2020, 9, 17)
    await env.run(nxt, N_UNIVERSE)
    assert ("CCC", False) in env.pass_two()
    assert job.get_ingestion_state()["prefix_confirmed"] == 1
    assert hs._as_utc((await env.state("CCC")).floor_checked_at) == et(nxt)


# ── after a restart a due CONFIRM is still found ──────────────────────────────

async def test_due_confirm_is_found_after_a_restart(nightly, monkeypatch):
    env = nightly
    await seed_to_n_minus(env)
    # A restart: the process loses every in-memory value; only the database survives.
    monkeypatch.setattr(job, "_state", {"status": "idle"})
    monkeypatch.setattr(job, "_task", None)
    await env.run(N, ["CCC"])
    assert env.pass_two() == [("CCC", False)]
    assert env.tiingo_symbols() == ["CCC"]
    state = job.get_ingestion_state()
    assert state["prefix_confirmed"] == 1 and state["prefix_refetched"] == 1
    assert hs._as_utc((await env.state("CCC")).floor_checked_at) == et(N)


# ── invalid history_incremental config fails the run before any write ─────────

async def test_invalid_incremental_config_fails_the_run_before_any_write(nightly):
    env = nightly
    await seed_to_n_minus(env)
    before = await env.snapshot()
    env.settings = {"history_incremental": {"revalidate_per_night": -1}}
    result = await env.run(N, N_UNIVERSE)
    state = job.get_ingestion_state()
    assert state["status"] == "error"
    assert "history_incremental.revalidate_per_night" in state["error"]
    assert [e for e in env.log if e[0] in {"batch", "update", "tiingo", "yfinance", "rebuild"}] == []
    assert await env.snapshot() == before
    assert any("history_incremental.revalidate_per_night" in e for e in result.errors)


# ── the ledger read never fails the run ───────────────────────────────────────

async def test_unreadable_ledger_reports_none_and_the_run_completes(nightly, monkeypatch):
    """The ledger is down for the whole run: every attempt is admitted unchecked and none can
    be recorded, so the run's own Tiingo usage is unknown."""
    env = nightly
    await seed_to_n_minus(env)

    class Broken:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(budget, "AsyncSessionLocal", Broken)
    result = await env.run(N, N_UNIVERSE)
    assert env.tiingo_symbols()                       # the run still asked Tiingo
    state = job.get_ingestion_state()
    assert state["status"] == "completed" and result.failed == 0
    assert state["tiingo_requests"] is None and state["tiingo_bytes"] is None
    assert state["prefix_confirmed"] == 1


async def test_manual_run_counts_its_own_on_demand_tiingo_requests(nightly):
    """A manual POST /api/data/ingest run has no caller("nightly") context: its Tiingo
    requests are ledgered as on_demand, and its counters must count those rows."""
    env = nightly
    await seed_to_n_minus(env)
    env.night, env.now = N, et(N)
    env.log.clear()
    assert budget.current_caller() == "on_demand"
    await job.run_ingestion(N_UNIVERSE)                 # outside caller("nightly")
    async with env.ledger() as db:
        rows = (await db.execute(select(Log.caller, Log.response_bytes)
                                 .where(Log.requested_at == et(N)))).all()
    assert env.tiingo_symbols() and len(rows) == len(env.tiingo_symbols())
    assert {c for c, _ in rows} == {"on_demand"}
    state = job.get_ingestion_state()
    assert state["tiingo_requests"] == len(rows) > 0
    assert state["tiingo_bytes"] == sum(b for _, b in rows) > 0


def concurrent_traffic(env: Nightly, callers: list[str]) -> asyncio.Task:
    """Another task, created outside the run (so not part of it), that records one Tiingo
    request per entry of `callers` through the real ``send_recorded`` while the run waits
    inside its first Tiingo call: the other requests land in the ledger inside the run's
    window, deterministically."""
    go, done = asyncio.Event(), asyncio.Event()

    async def other():
        await go.wait()
        for i, name in enumerate(callers):
            async def send():
                return SimpleNamespace(content=b"y" * 7, status_code=200)

            with budget.caller(name):
                await budget.send_recorded(f"OTH{i}", send)
        done.set()

    task = asyncio.create_task(other())
    run_tiingo = env._tiingo

    async def tiingo_call(symbol, start, end, *, strict_adjustments):
        if not go.is_set():
            go.set()
            await done.wait()
        return await run_tiingo(symbol, start, end, strict_adjustments=strict_adjustments)

    env.monkeypatch.setattr(tiingo, "fetch_historical_candles", tiingo_call)
    return task


async def ledger_rows_tonight(env: Nightly):
    async with env.ledger() as db:
        return (await db.execute(select(Log.symbol, Log.caller, Log.response_bytes)
                                 .where(Log.requested_at == et(N)).order_by(Log.id))).all()


async def test_manual_run_does_not_count_concurrent_on_demand_requests(nightly):
    """R2-F1: a manual run and every other Tiingo user share the on_demand caller; the run's
    counters are its own attempts only."""
    env = nightly
    await seed_to_n_minus(env)
    env.night, env.now = N, et(N)
    env.log.clear()
    other = concurrent_traffic(env, ["on_demand"] * 3)
    await job.run_ingestion(N_UNIVERSE)                 # outside caller("nightly")
    await other
    rows = await ledger_rows_tonight(env)
    own = [r for r in rows if not r.symbol.startswith("OTH")]
    assert len(rows) == len(own) + 3 and {r.caller for r in rows} == {"on_demand"}
    assert len(own) == len(env.tiingo_symbols()) > 0
    state = job.get_ingestion_state()
    assert state["status"] == "completed"
    assert state["tiingo_requests"] == len(own)
    assert state["tiingo_bytes"] == sum(r.response_bytes for r in own) == len(own) * REPLY_BYTES


async def test_nightly_run_does_not_count_concurrent_requests(nightly):
    """The same for a nightly run, with concurrent on_demand traffic and another task's
    request under the nightly caller."""
    env = nightly
    await seed_to_n_minus(env)
    other = concurrent_traffic(env, ["on_demand", "on_demand", "nightly"])
    await env.run(N, N_UNIVERSE)
    await other
    rows = await ledger_rows_tonight(env)
    assert len(rows) == 5 + 3
    state = job.get_ingestion_state()
    assert state["status"] == "completed"
    assert (state["tiingo_requests"], state["tiingo_bytes"]) == (5, 5 * REPLY_BYTES)


async def test_ledger_write_failure_during_the_run_reports_none(nightly):
    """One attempt the ledger could not record makes the run's true usage unknown: both
    counters None, and the run still completes."""
    env = nightly
    await seed_to_n_minus(env)
    good_factory, commits = env.ledger, []

    def flaky_ledger():
        session = good_factory()
        real_commit = session.commit

        async def commit():
            commits.append(1)
            if len(commits) == 2:
                raise RuntimeError("ledger write failed")
            await real_commit()

        session.commit = commit
        return session

    env.monkeypatch.setattr(budget, "AsyncSessionLocal", flaky_ledger)
    result = await env.run(N, N_UNIVERSE)
    assert result.failed == 0, result.errors
    rows = await ledger_rows_tonight(env)
    assert len(rows) == 4 and len(env.tiingo_symbols()) == 5     # one attempt unrecorded
    state = job.get_ingestion_state()
    assert state["status"] == "completed"
    assert state["tiingo_requests"] is None and state["tiingo_bytes"] is None


# ── counter mapping and queue mechanics (update_history mocked) ───────────────

def R(action, reason=None, **kw):
    return history.HistoryUpdateResult(1, False, False, action=action, reason=reason, **kw)


MAPPING = [
    (R("SUFFIX_ONLY", "trusted"), {"suffix_only"}),
    (R("SUFFIX_ONLY", "confirm_retry"), {"suffix_only", "confirm_retry"}),
    (R("SUFFIX_ONLY", "revalidate_no_reply"), {"suffix_only"}),
    (R("RESCALE", "new_events"), {"prefix_rescaled", "adjustment_changed"}),
    (R("FULL", "no_state"), {"prefix_refetched"}),
    (R("FULL", "T6_lag_window"), {"prefix_refetched", "lag_window_full"}),
    *[(R("FULL", reason), {"prefix_refetched", "adjustment_changed"})
      for reason in ("non_uniform_ratio", "unexplained_adjustment", "ratio_product_mismatch",
                     "event_before_fetch", "raw_close_changed")],
    (R("CONFIRM", "confirm_due"), {"prefix_refetched", "prefix_confirmed"}),
    (R("SINGLE_PROVIDER_RECENT", "window_unchanged", provider="tiingo"), {"single_provider_recent"}),
    (R("SINGLE_PROVIDER_CURRENT", "current", provider="tiingo"),
     {"single_provider_skipped_current"}),
    (R("SINGLE_PROVIDER_FULL", "yfinance_basis", provider="yfinance"), set()),
    (R(None), set()),
]


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr(job, "_state", {"status": "idle"})
    monkeypatch.setattr(job, "_task", None)
    monkeypatch.setattr(job, "effective_years", lambda years=None: 17)
    monkeypatch.setattr(job, "_load_settings", lambda: {})
    monkeypatch.setattr(job, "get_alpaca_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(job, "fetch_daily_bars_batch", AsyncMock(return_value={}))
    monkeypatch.setattr(job, "_prune_old_rows", AsyncMock(return_value=0))
    calls: list[tuple] = []
    rebuild = AsyncMock(side_effect=history.SingleProviderRefused("synthetic refusal"))

    async def logged_rebuild(symbol, *args, **kwargs):
        calls.append(("rebuild", symbol))
        return await rebuild(symbol, *args, **kwargs)

    monkeypatch.setattr(job, "rebuild_single_provider", logged_rebuild)
    return SimpleNamespace(calls=calls, monkeypatch=monkeypatch)


@pytest.mark.parametrize("result,expected", MAPPING,
                         ids=[f"{r.action}-{r.reason}" for r, _ in MAPPING])
async def test_counter_mapping(mocked, result, expected):
    mocked.monkeypatch.setattr(job, "update_history", AsyncMock(return_value=result))
    await job.run_ingestion(["X"])
    state = job.get_ingestion_state()
    action_counters = [k for k in COUNTERS if k not in {"tiingo_requests", "tiingo_bytes"}]
    assert {k for k in action_counters if state[k]} == expected
    assert all(state[k] in (0, 1) for k in action_counters)


async def test_revalidated_counter_and_budget_skip_from_mocked_results(mocked):
    async def update(symbol, *args, revalidate=False, tiingo_allowed=True, **kwargs):
        mocked.calls.append(("update", symbol, tiingo_allowed, revalidate))
        if revalidate:
            return R("REVALIDATE", "revalidate")
        return R("SUFFIX_ONLY", "trusted", revalidation_due=True,
                 prefix_age_days={"OLD": 200, "MID": 150, "NEW": 100}[symbol])

    refused = {"MID"}

    async def ensure_room(symbol, caller_name=None):
        assert caller_name == "nightly"
        if symbol in refused:
            raise ProviderUnavailable("tiingo requests_per_day budget exhausted (2/2)")

    mocked.monkeypatch.setattr(job, "update_history", update)
    mocked.monkeypatch.setattr(budget, "ensure_room", ensure_room)
    mocked.monkeypatch.setattr(job, "_load_settings",
                               lambda: {"history_incremental": {"revalidate_per_night": 2}})
    await job.run_ingestion(["NEW", "MID", "OLD"])
    # select_revalidations: oldest first, capped at 2 -> OLD, MID; MID refused by the budget.
    assert [c for c in mocked.calls if c[3]] == [("update", "OLD", True, True)]
    state = job.get_ingestion_state()
    assert state["revalidated"] == 1 and state["revalidation_skipped_budget"] == 1
    assert state["suffix_only"] == 3 and state["prefix_refetched"] == 1
    assert state["done"] == 3


async def test_seam_refusal_in_pass_one_is_rebuilt_in_pass_two(mocked):
    async def update(symbol, *args, tiingo_allowed=True, **kwargs):
        mocked.calls.append(("update", symbol, tiingo_allowed))
        if symbol == "S":
            raise history.HistorySeamMismatch("seam moved since classification", 1.01)
        return R("SUFFIX_ONLY", "trusted")

    mocked.monkeypatch.setattr(job, "update_history", update)
    result = await job.run_ingestion(["S", "T"])
    # The rebuild (a Tiingo request) waits for pass 1 to finish.
    assert mocked.calls == [("update", "S", False), ("update", "T", False), ("rebuild", "S")]
    assert result.seam_mismatch_symbols == ["S"] and result.seam_ratios == {"S": 1.01}
    assert result.rebuild_refused_symbols == ["S"] and result.failed == 1


async def test_deferred_results_queue_by_reason_with_spy_first(mocked):
    kinds = {"F1": "FULL", "C1": "CONFIRM", "S1": "SINGLE_PROVIDER_RECENT",
             "S2": "SINGLE_PROVIDER_FULL", "SPY": "CONFIRM", "F2": "FULL"}

    async def update(symbol, *args, tiingo_allowed=True, **kwargs):
        mocked.calls.append(("update", symbol, tiingo_allowed))
        if not tiingo_allowed:
            return history.HistoryUpdateResult(0, False, False, action="deferred",
                                               reason=kinds[symbol])
        return R(kinds[symbol], "x")

    mocked.monkeypatch.setattr(job, "update_history", update)
    await job.run_ingestion(["F1", "C1", "S1", "SPY", "S2", "F2"])
    assert [c[1] for c in mocked.calls if c[2] is False] == ["F1", "C1", "S1", "SPY", "S2", "F2"]
    assert [c[1] for c in mocked.calls if c[2] is True] == ["SPY", "S1", "S2", "F1", "F2", "C1"]
    state = job.get_ingestion_state()
    assert state["done"] == 6 and state["prefix_confirmed"] == 2


async def test_force_backfill_and_rebuild_keep_one_full_pass(mocked):
    update = AsyncMock(return_value=R("FULL", "force_backfill"))
    mocked.monkeypatch.setattr(job, "update_history", update)
    await job.run_ingestion(["B", "A"], force_backfill=True)
    assert [c.args[0] for c in update.await_args_list] == ["B", "A"]
    assert all(c.kwargs["force_backfill"] is True and c.kwargs.get("tiingo_allowed", True) is True
               for c in update.await_args_list)
    assert job.get_ingestion_state()["prefix_refetched"] == 2
    update.reset_mock()
    await job.run_ingestion(["B", "A"], rebuild=True)
    update.assert_not_awaited()
    assert mocked.calls == [("rebuild", "B"), ("rebuild", "A")]
