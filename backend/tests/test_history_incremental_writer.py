"""B2 (HISTORY-INCREMENTAL-NIGHTLY plan 2.3-2.6, 2.8 and section 5): the incremental writer.

Each test runs ``update_history`` night by night against an in-memory database and a
deterministic provider world. A night runs at 20:00 ET on its ET date ``day`` (that day's bar
has settled at 18:00 ET), with ``end = day`` and tonight's Alpaca reply ``SEAM .. day``. The
world models raw closes (splits raise the raw closes before their ex-date) and, per provider,
which adjustment events it has applied on a given night: ``adj_factor(d)`` is the product of
the step ratios of every applied event dated after ``d``. Tiingo/yfinance replies are what
``fetch_historical_candles`` / ``_yfinance_fetch`` return (yfinance: adjusted prices, factor 1).

Test numbers refer to the B2 list in the plan's section 5.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import tiingo
from app.data.governor import ProviderUnavailable
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs
from app.services import history_backfill as history
from app.services import history_incremental as hi
from app.services.history_basis import verified_boundary

ET = hs.MARKET_TZ
START = date(2020, 6, 1)     # Monday
SEAM = date(2020, 7, 27)     # Monday: Alpaca's first date; R = 07-27 .. 07-31
R = [SEAM + timedelta(days=i) for i in range(5)]
L = hi.DEFAULT_PARAMS.provider_lag_days
SEED = date(2020, 9, 1)      # Tuesday: the first (full) nightly write
SYMBOL = "TEST"
Q8 = Decimal("0.00000001")


def wd(d: date, n: int) -> date:
    """``d`` moved ``n`` weekdays (test-side reference, independent of the module)."""
    step = 1 if n >= 0 else -1
    while n:
        d += timedelta(days=step)
        if d.weekday() < 5:
            n -= step
    return d


def weekdays(a: date, b: date) -> list[date]:
    out = []
    while a <= b:
        if a.weekday() < 5:
            out.append(a)
        a += timedelta(days=1)
    return out


def et(d: date, hour: int = 20) -> datetime:
    """``hour``:00 ET on ``d``, as the UTC instant the clock (``hs._utcnow``) returns."""
    return datetime.combine(d, time(hour), tzinfo=ET).astimezone(timezone.utc)


def base_close(d: date) -> float:
    return 100 + (d.toordinal() % 7) * 0.25 + (d.toordinal() % 3) * 0.13


def bar(d: date, close: float, f: float, source: str) -> dict:
    return {"time": d.isoformat(), "open": close, "high": round(close + 1, 4),
            "low": round(close - 1, 4), "close": close, "volume": 1000 + d.toordinal() % 50,
            "adj_factor": f, "split_factor": 1.0, "div_cash": 0.0, "source": source}


@dataclass
class Ev:
    date: date
    s: float                       # step ratio f(P(E)) / f(E)
    split: bool = False
    alpaca_from: date | None = None    # first night the provider applies it (default: E)
    tiingo_from: date | None = None
    yfinance_from: date | None = None


PREFIX_EV = Ev(date(2020, 6, 15), 0.99)      # inside the prefix: no Alpaca row sees it
OLD_EV = Ev(date(2020, 8, 20), 0.997)        # an old suffix step both providers know


@dataclass
class World:
    events: list = field(default_factory=list)
    tiingo_bias: float = 1.0
    night: date = SEED

    def __post_init__(self):
        self.events = [PREFIX_EV, OLD_EV, *self.events]

    def applied(self, e: Ev, provider: str) -> bool:
        return self.night >= (getattr(e, f"{provider}_from") or e.date)

    def raw(self, d: date) -> float:
        r = base_close(d)
        for e in self.events:
            if e.split and d < e.date:
                r /= e.s
        return round(r, 4)

    def factor(self, d: date, provider: str, *, all_events: bool = False) -> float:
        f = 1.0
        for e in self.events:
            if d < e.date and (all_events or self.applied(e, provider)):
                f *= e.s
        return f

    def bar(self, d: date, provider: str) -> dict:
        raw, f = self.raw(d), self.factor(d, provider)
        if provider == "yfinance":
            return bar(d, round(raw * f, 4), 1.0, "yfinance")
        if provider == "tiingo":
            f *= self.tiingo_bias
        return bar(d, raw, round(f, 8), provider)

    def reply(self, provider: str, start: date, end: date) -> list[dict]:
        return [self.bar(d, provider) for d in weekdays(start, min(end, self.night))]

    def alpaca(self) -> list[dict]:
        return self.reply("alpaca", SEAM, self.night)

    def truth(self, d: date) -> float:
        """The fully adjusted close once every provider has applied every event."""
        return self.raw(d) * self.factor(d, "alpaca", all_events=True)


class Env:
    def __init__(self, monkeypatch, factory, world):
        self.monkeypatch = monkeypatch
        self.factory = factory
        self.world = world
        self.now = et(SEED)
        self.tiingo_error: Exception | None = None
        self.yfinance_empty = False
        self.tiingo = AsyncMock(side_effect=self._tiingo)
        self.yfinance = MagicMock(side_effect=self._yfinance)
        self.notify = MagicMock()
        monkeypatch.setattr(hs, "_utcnow", lambda: self.now)
        monkeypatch.setattr(tiingo, "fetch_historical_candles", self.tiingo)
        monkeypatch.setattr(hs, "_yfinance_fetch", self.yfinance)
        monkeypatch.setattr(history, "notify_bars_changed", self.notify)
        self.use(factory)

    def use(self, factory):
        self.factory = factory
        self.monkeypatch.setattr(history, "AsyncSessionLocal", factory)
        self.monkeypatch.setattr(hs, "AsyncSessionLocal", factory)

    async def _tiingo(self, symbol, start, end, *, strict_adjustments):
        assert strict_adjustments is True
        if self.tiingo_error is not None:
            raise self.tiingo_error
        return self.world.reply("tiingo", start, end)

    def _yfinance(self, symbol, start, end):
        return [] if self.yfinance_empty else self.world.reply("yfinance", start, end)

    def at(self, day: date, hour: int = 20):
        self.world.night = day
        self.now = et(day, hour)

    def provider_calls(self) -> int:
        return self.tiingo.await_count + self.yfinance.call_count

    async def night(self, day: date, *, alpaca="world", **kw):
        self.at(day)
        bars = self.world.alpaca() if alpaca == "world" else alpaca
        return await history.update_history(SYMBOL, START, day, alpaca_bars=bars, **kw)

    async def rows(self, before: date | None = None):
        async with self.factory() as db:
            query = select(M).where(M.symbol == SYMBOL).order_by(M.date)
            if before is not None:
                query = query.where(M.date < before)
            found = (await db.execute(query)).scalars().all()
        cols = [c.name for c in M.__table__.columns]
        return [tuple(getattr(r, c) for c in cols) for r in found]

    async def rowmap(self):
        async with self.factory() as db:
            found = (await db.execute(select(M).where(M.symbol == SYMBOL).order_by(M.date))).scalars().all()
        return {r.date: r for r in found}

    async def state(self) -> State | None:
        async with self.factory() as db:
            return await db.get(State, SYMBOL)

    async def snapshot(self):
        async with self.factory() as db:
            st = (await db.execute(select(State))).scalars().all()
        scols = [c.name for c in State.__table__.columns]
        return await self.rows(), [tuple(getattr(s, c) for c in scols) for s in st]

    async def read(self, end: date):
        async with self.factory() as db:
            return await hs._read_bars(SYMBOL, START, end, db)

    async def stale(self):
        async with self.factory() as db:
            return await hs.find_stale_adjustment(SYMBOL, db)

    async def mutate(self, fn):
        async with self.factory() as db:
            await fn(db)
            await db.commit()


async def make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def engines():
    made = []

    async def new():
        engine, factory = await make_factory()
        made.append(engine)
        return factory

    yield new
    for engine in made:
        await engine.dispose()


async def make_env(monkeypatch, engines, world=None) -> Env:
    return Env(monkeypatch, await engines(), world or World())


def rel(a: float, b: float) -> float:
    return abs(a / b - 1)


def assert_close_to_truth(read: list[dict], world: World, tol: float = 1e-6):
    for row in read:
        d = date.fromisoformat(row["time"])
        assert rel(row["close"], world.truth(d)) <= tol, (d, row["close"], world.truth(d))


def prefix_factors(rowmap) -> dict:
    return {d: r.adj_factor for d, r in rowmap.items() if d < SEAM}


def assert_prefix_is_reply(rowmap, reply: list[dict]):
    """The stored prefix rows are exactly the provider reply (raw close and factor)."""
    by_date = {date.fromisoformat(b["time"]): b for b in reply}
    prefix = {d: r for d, r in rowmap.items() if d < SEAM}
    assert prefix and set(prefix) == {d for d in by_date if d < SEAM}
    for d, r in prefix.items():
        assert r.close == Decimal(str(by_date[d]["close"])).quantize(Decimal("0.0001")), d
        assert r.adj_factor == Decimal(str(by_date[d]["adj_factor"])).quantize(Q8), d
        assert r.source == by_date[d]["source"]


def expected_r_a(stored: dict, tonight: list[dict]) -> Decimal:
    """r_A as the classifier computes it: the mean of f_new / f_stored over R."""
    new = {date.fromisoformat(b["time"]): b["adj_factor"] for b in tonight}
    ratios = [Decimal(str(new[d])) / Decimal(str(stored[d].adj_factor)) for d in R]
    return sum(ratios, Decimal(0)) / len(ratios)


# ── 1. SUFFIX_ONLY ──────────────────────────────────────────────────────────

async def test_1_suffix_only_keeps_the_prefix_byte_identical(monkeypatch, engines):
    env = await make_env(monkeypatch, engines)
    first = await env.night(SEED)
    assert env.tiingo.await_count == 1
    prefix_before = await env.rows(before=SEAM)
    st_before = await env.state()
    env.tiingo.reset_mock()
    env.yfinance.reset_mock()
    env.notify.reset_mock()
    day = wd(SEED, 1)
    result = await env.night(day)
    env.tiingo.assert_not_awaited()
    env.yfinance.assert_not_called()
    assert await env.rows(before=SEAM) == prefix_before          # raw, factor, fetched_at
    rowmap = await env.rowmap()
    suffix = {d: r for d, r in rowmap.items() if d >= SEAM}
    assert sorted(suffix) == weekdays(SEAM, day)
    assert {hs._as_utc(r.fetched_at) for r in suffix.values()} == {env.now}  # rewritten
    st = await env.state()
    assert (st.seam_date, st.old_source) == (SEAM, "tiingo")
    assert hs._as_utc(st.floor_checked_at) == hs._as_utc(st_before.floor_checked_at)
    assert (st.floor_date, st.floor_provider, st.floor_requested_start) == (
        st_before.floor_date, st_before.floor_provider, st_before.floor_requested_start)
    async with env.factory() as db:
        tuples = (await db.execute(select(M.date, M.close, M.adj_factor, M.split_factor,
                                          M.div_cash, M.source, M.fetched_at)
                                   .where(M.symbol == SYMBOL).order_by(M.date))).all()
    assert st.seam_signature != st_before.seam_signature          # seam row re-fetched
    assert verified_boundary(tuples, st.verified_seam()) == len(prefix_before)
    assert hs.stale_reasons(tuples, st.verified_seam()) is None
    assert await env.stale() is None
    env.notify.assert_called_once_with(SYMBOL)
    assert result.action == "SUFFIX_ONLY" and result.reason == "trusted"
    assert result.stored == len(suffix) and result.provider is None
    assert not result.backfilled and first.action == "FULL"


# ── 2. Equivalence: full path and incremental path, two DB copies ───────────

async def test_2_suffix_only_equals_the_full_path_over_the_whole_window(monkeypatch, engines):
    world = World(tiingo_bias=1.0005)             # Tiingo's prefix factor is not Alpaca's
    env = await make_env(monkeypatch, engines, world)
    full_db, incremental_db = env.factory, await engines()
    nights = [SEED, wd(SEED, 1), wd(SEED, 2), wd(SEED, 3)]

    def tonight(day):
        bars = world.alpaca()
        if day >= wd(SEED, 2):
            # Alpaca corrects a later suffix bar (outside R): both paths must write it.
            for b in bars:
                if b["time"] == "2020-08-25":
                    b["close"] = round(b["close"] + 0.37, 4)
                    b["volume"] += 11
        return bars

    for i, day in enumerate(nights):
        for factory, force in ((full_db, i > 0), (incremental_db, False)):
            env.use(factory)
            calls = env.tiingo.await_count
            env.at(day)
            result = await history.update_history(SYMBOL, START, day, alpaca_bars=tonight(day),
                                                  force_backfill=force)
            fetched = env.tiingo.await_count - calls
            if i == 0 or force:
                assert result.action == "FULL" and fetched == 1
            else:
                assert result.action == "SUFFIX_ONLY" and fetched == 0
        env.use(full_db)
        full_read, full_rows = await env.read(day), await env.rows()
        env.use(incremental_db)
        inc_read, inc_rows = await env.read(day), await env.rows()
        assert len(full_read) == len(weekdays(START, day))
        assert full_read == inc_read                               # the gate
        # Same stored values too (only the prefix rows' fetched_at differs).
        strip = [c.name for c in M.__table__.columns].index("fetched_at")
        assert ([r[:strip] + r[strip + 1:] for r in full_rows]
                == [r[:strip] + r[strip + 1:] for r in inc_rows])
        assert await env.stale() is None
    env.yfinance.assert_not_called()


# ── 3./4. Adjustment events: RESCALE, CONFIRM (D1-a), D1-b ──────────────────

E = date(2020, 9, 9)          # Wednesday; P(E) = 09-08, E + L = 09-16


@pytest.mark.parametrize("prefix_provider", ["tiingo", "yfinance"])
@pytest.mark.parametrize("event", [Ev(E, 0.995), Ev(E, 0.25, split=True)], ids=["dividend", "split"])
async def test_3_4_event_night_rescales_then_confirms_after_the_lag_window(
        monkeypatch, engines, event, prefix_provider):
    world = World([event])
    env = await make_env(monkeypatch, engines, world)
    if prefix_provider == "yfinance":
        env.tiingo_error = ProviderUnavailable("tiingo requests_per_day budget exhausted")
    await env.night(SEED)
    st0 = await env.state()
    assert st0.old_source == prefix_provider
    await env.night(wd(E, -1))
    before = await env.rowmap()
    calls = env.provider_calls()

    result = await env.night(E)                                    # the event night
    assert env.provider_calls() == calls                           # no provider call
    assert result.action == "RESCALE" and result.reason == "new_events"
    after = await env.rowmap()
    r_a = expected_r_a(before, world.alpaca())
    assert abs(float(r_a) - event.s) < 1e-6
    for d, old in prefix_factors(before).items():
        expected = (Decimal(str(old)) * Decimal(str(r_a))).quantize(Q8, rounding=ROUND_HALF_EVEN)
        assert after[d].adj_factor == expected, d
        assert after[d].close == before[d].close
        assert hs._as_utc(after[d].fetched_at) == env.now
    st = await env.state()
    assert hs._as_utc(st.floor_checked_at) == hs._as_utc(st0.floor_checked_at)   # F unchanged
    assert_close_to_truth(await env.read(E), world, 2e-6)          # continuous across the seam
    assert await env.stale() is None
    async with env.factory() as db:
        tuples = (await db.execute(select(M.date, M.close, M.adj_factor, M.split_factor,
                                          M.div_cash, M.source, M.fetched_at)
                                   .where(M.symbol == SYMBOL).order_by(M.date))).all()
    assert verified_boundary(tuples, st.verified_seam()) is not None

    for day in weekdays(wd(E, 1), wd(E, L - 1)):                    # inside the lag window
        assert (await env.night(day)).action == "SUFFIX_ONLY"
    assert env.provider_calls() == calls

    confirm_day = wd(E, L)
    result = await env.night(confirm_day)
    assert result.action == "CONFIRM" and result.reason == "confirm_due"
    used = "tiingo" if prefix_provider == "tiingo" else "yfinance"
    reply = world.reply(used, START, R[4])
    assert_prefix_is_reply(await env.rowmap(), reply)              # the provider's own values
    st = await env.state()
    assert hs._as_utc(st.floor_checked_at) == et(confirm_day)          # F = that day
    assert (await env.night(wd(confirm_day, 1))).action == "SUFFIX_ONLY"


async def test_3_d1b_never_calls_a_provider_after_the_event(monkeypatch, engines):
    world = World([Ev(E, 0.995)])
    env = await make_env(monkeypatch, engines, world)
    params = hi.IncrementalParams(confirm=False)
    await env.night(SEED, params=params)
    calls = env.provider_calls()
    assert (await env.night(E, params=params)).action == "RESCALE"
    for day in weekdays(wd(E, 1), wd(E, L + 3)):
        assert (await env.night(day, params=params)).action == "SUFFIX_ONLY"
    assert env.provider_calls() == calls
    assert_close_to_truth(await env.read(wd(E, L + 3)), world, 2e-6)


async def test_3_r4f1_a_late_alpaca_dividend_after_a_revalidate_is_not_rescaled(monkeypatch, engines):
    """Alpaca applies a 0.3 % dividend X late; the prefix was re-fetched (REVALIDATE) on
    X + L + 1 trading days, after Tiingo applied X. The night Alpaca's step first appears is
    FULL (condition iii), and no prefix factor is multiplied: the prefix is Tiingo's reply."""
    x = date(2020, 9, 2)
    assert x > R[4] and 0.997 > 0.995
    revalidate_day = wd(x, L + 1)
    world = World([Ev(x, 0.997, alpaca_from=wd(revalidate_day, 1))])
    env = await make_env(monkeypatch, engines, world)
    params = hi.IncrementalParams(revalidate_days=0)
    await env.night(SEED, params=params)
    result = await env.night(revalidate_day, params=params, revalidate=True)
    assert result.action == "REVALIDATE"
    before = await env.rowmap()
    late = wd(revalidate_day, 1)
    result = await env.night(late, params=params)
    assert result.action == "FULL" and result.reason == "event_before_fetch"
    after = await env.rowmap()
    reply = world.reply("tiingo", START, R[4])
    assert_prefix_is_reply(after, reply)
    r_a = expected_r_a(before, world.alpaca())
    for d, old in prefix_factors(before).items():                  # no prefix factor multiplied
        assert after[d].adj_factor == old
        assert after[d].adj_factor != (Decimal(str(old)) * r_a).quantize(Q8)
    assert_close_to_truth(await env.read(late), world, 2e-6)


async def test_3_r4f1_b_alpaca_corrects_an_old_step_is_not_rescaled(monkeypatch, engines):
    e = date(2020, 8, 5)
    assert e > R[4]
    world = World([Ev(e, 0.995)])
    env = await make_env(monkeypatch, engines, world)
    await env.night(SEED)
    before = await env.rowmap()
    day = wd(SEED, 2)
    env.at(day)
    bars = world.alpaca()
    for b in bars:                                  # Alpaca now says the step was 0.993
        if date.fromisoformat(b["time"]) < e:
            b["adj_factor"] = round(b["adj_factor"] * 0.993 / 0.995, 8)
    result = await env.night(day, alpaca=bars)
    assert result.action == "FULL" and result.reason == "event_before_fetch"
    after = await env.rowmap()
    assert_prefix_is_reply(after, world.reply("tiingo", START, R[4]))
    r_a = expected_r_a(before, bars)
    for d, old in prefix_factors(before).items():                  # no prefix factor multiplied
        assert after[d].adj_factor == old
        assert after[d].adj_factor != (Decimal(str(old)) * r_a).quantize(Q8)


@pytest.mark.parametrize("why", ["T6_inside_window", "step_product_mismatch"])
async def test_3_refused_rescale_multiplies_no_prefix_factor(monkeypatch, engines, why):
    """Every other RESCALE refusal goes to the full path; the prefix is the provider reply.
    T6 case: Tiingo lags (0.4 %), so its reply is not the rescaled prefix either."""
    if why == "T6_inside_window":
        world = World([Ev(E, 0.996, tiingo_from=wd(E, 2))])
    else:
        world = World([Ev(E, 0.995)])
    env = await make_env(monkeypatch, engines, world)
    await env.night(SEED)
    if why == "T6_inside_window":
        await env.night(wd(E, -1), force_backfill=True)       # F = P(E): lag-exposed
        expected_reason = "T6_lag_window"
    else:
        await env.night(wd(E, -1))
        expected_reason = "ratio_product_mismatch"
    before = await env.rowmap()
    env.at(E)
    bars = world.alpaca()
    if why == "step_product_mismatch":
        for b in bars:                       # R moves by 0.995 * 0.999, the steps say 0.995
            b["adj_factor"] = round(b["adj_factor"] * 0.999, 8)
    result = await env.night(E, alpaca=bars)
    assert result.action == "FULL" and result.reason == expected_reason
    after = await env.rowmap()
    r_a = expected_r_a(before, bars)
    for d, old in prefix_factors(before).items():
        assert after[d].adj_factor != (Decimal(str(old)) * r_a).quantize(Q8)
    assert_prefix_is_reply(after, world.reply("tiingo", START, R[4]))


# ── 5. Provider lag ─────────────────────────────────────────────────────────

LAG_EV = Ev(E, 0.996, tiingo_from=wd(E, 2))       # Tiingo applies it two nights late


@pytest.mark.parametrize("trigger", ["T1", "empty_alpaca"])
async def test_5i_full_prefix_inside_the_lag_window_is_refetched_until_e_plus_l(
        monkeypatch, engines, trigger):
    world = World([LAG_EV])
    env = await make_env(monkeypatch, engines, world)
    await env.night(SEED)
    if trigger == "T1":
        async def clear(db):
            (await db.get(State, SYMBOL)).seam_signature = None
        await env.mutate(clear)
        first = await env.night(E)
    else:
        first = await env.night(E, alpaca=[])
    assert first.action == "FULL" and first.reason == trigger
    reply = await env.rowmap()
    lagging = world.reply("tiingo", START, E)
    assert {date.fromisoformat(b["time"]): Decimal(str(b["adj_factor"])).quantize(Q8)
            for b in lagging if b["time"] < SEAM.isoformat()} == prefix_factors(reply)
    # 0.4 % off Alpaca, inside the 0.5 % seam tolerance: today's code accepts it.
    assert rel(float(reply[START].adj_factor), world.factor(START, "alpaca")) == pytest.approx(0.004, abs=1e-4)
    reasons = []
    for day in weekdays(wd(E, 1), wd(E, L)):
        result = await env.night(day)
        assert result.action == "FULL", (day, result)
        reasons.append(result.reason)
        if day >= wd(E, 2):                     # Tiingo has caught up: the prefix is its reply
            assert_prefix_is_reply(await env.rowmap(), world.reply("tiingo", START, R[4]))
    expected = ["T6_lag_window"] * L
    if trigger == "empty_alpaca":
        expected[0] = "T1"                      # the whole-window write cleared the seam
    assert reasons == expected
    calls = env.provider_calls()
    trusted = wd(E, L + 1)                      # F = E + L: trusted from the next night
    result = await env.night(trusted)
    assert result.action == "SUFFIX_ONLY" and env.provider_calls() == calls
    assert_close_to_truth(await env.read(trusted), world, 2e-6)    # no step at the seam
    assert await env.stale() is None


async def test_5ii_the_deploy_night_prefix_inside_a_lag_window_is_not_trusted(monkeypatch, engines):
    """Alpaca applies E the evening before (P(E)); today's code (the full path) stores the
    lagging Tiingo prefix that night. From the deploy on, T6 keeps the symbol FULL."""
    world = World([Ev(E, 0.996, alpaca_from=wd(E, -1), tiingo_from=wd(E, 2))])
    env = await make_env(monkeypatch, engines, world)
    await env.night(SEED)
    deploy_eve = wd(E, -1)
    assert (await env.night(deploy_eve, force_backfill=True)).action == "FULL"  # today's code
    assert hs._as_utc((await env.state()).floor_checked_at) == et(deploy_eve)
    for day in weekdays(E, wd(E, L)):
        result = await env.night(day)
        assert (result.action, result.reason) == ("FULL", "T6_lag_window"), day
    result = await env.night(wd(E, L + 1))
    assert result.action == "SUFFIX_ONLY"
    assert_prefix_is_reply(await env.rowmap(), world.reply("tiingo", START, R[4]))
    assert_close_to_truth(await env.read(wd(E, L + 1)), world, 2e-6)


async def _confirm_due_env(monkeypatch, engines):
    world = World([Ev(E, 0.995)])
    env = await make_env(monkeypatch, engines, world)
    await env.night(SEED)
    assert (await env.night(E)).action == "RESCALE"
    return env, world


async def test_5iii_confirm_with_tiingo_refused_is_written_from_yfinance(monkeypatch, engines):
    env, world = await _confirm_due_env(monkeypatch, engines)
    env.tiingo_error = ProviderUnavailable("tiingo requests_per_day budget exhausted (900/900)")
    day = wd(E, L)
    result = await env.night(day)
    assert result.action == "CONFIRM"
    assert env.yfinance.call_count == 1
    assert_prefix_is_reply(await env.rowmap(), world.reply("yfinance", START, R[4]))
    st = await env.state()
    assert st.old_source == "yfinance" and hs._as_utc(st.floor_checked_at) == et(day)


async def test_5iii_confirm_with_no_usable_reply_writes_suffix_only_and_retries(monkeypatch, engines):
    env, world = await _confirm_due_env(monkeypatch, engines)
    rescaled_prefix = await env.rows(before=SEAM)
    st0 = await env.state()
    env.tiingo_error = ProviderUnavailable("tiingo requests_per_day budget exhausted (900/900)")
    env.yfinance_empty = True
    day = wd(E, L)
    env.notify.reset_mock()
    result = await env.night(day)
    assert env.tiingo.await_count >= 1 and env.yfinance.call_count == 1
    assert (result.action, result.reason) == ("SUFFIX_ONLY", "confirm_retry")
    assert await env.rows(before=SEAM) == rescaled_prefix          # rescaled prefix kept
    assert max(await env.rowmap()) == day                          # tonight's suffix written
    st = await env.state()
    assert hs._as_utc(st.floor_checked_at) == hs._as_utc(st0.floor_checked_at)
    env.notify.assert_called_once_with(SYMBOL)
    env.tiingo_error, env.yfinance_empty = None, False
    result = await env.night(wd(day, 1))                           # tried again next night
    assert result.action == "CONFIRM"
    assert_prefix_is_reply(await env.rowmap(), world.reply("tiingo", START, R[4]))


async def test_5iii_confirm_seam_mismatch_on_a_real_reply_keeps_todays_rule(monkeypatch, engines):
    env, world = await _confirm_due_env(monkeypatch, engines)
    before = await env.snapshot()
    real = env._tiingo

    async def off_by_one_percent(symbol, start, end, *, strict_adjustments):
        bars = await real(symbol, start, end, strict_adjustments=strict_adjustments)
        return [{**b, "close": round(b["close"] * 1.01, 4)} for b in bars]

    env.tiingo.side_effect = off_by_one_percent
    env.yfinance_empty = True
    env.at(wd(E, L))
    with pytest.raises(history.HistorySeamMismatch):
        await history.update_history(SYMBOL, START, wd(E, L), alpaca_bars=world.alpaca())
    assert await env.snapshot() == before


@pytest.mark.parametrize("reply", ["none", "real"])
async def test_5iii_revalidate_with_no_usable_reply_writes_suffix_only(monkeypatch, engines, reply):
    env = await make_env(monkeypatch, engines)
    params = hi.IncrementalParams(revalidate_days=0)
    await env.night(SEED, params=params)
    st0 = await env.state()
    prefix = await env.rows(before=SEAM)
    if reply == "none":
        env.tiingo_error = ProviderUnavailable("tiingo budget")
        env.yfinance_empty = True
    day = wd(SEED, 2)
    result = await env.night(day, params=params, revalidate=True)
    st = await env.state()
    if reply == "none":
        assert (result.action, result.reason) == ("SUFFIX_ONLY", "revalidate_no_reply")
        assert await env.rows(before=SEAM) == prefix
        assert hs._as_utc(st.floor_checked_at) == hs._as_utc(st0.floor_checked_at)
    else:
        assert result.action == "REVALIDATE"
        assert hs._as_utc(st.floor_checked_at) == et(day)
    assert max(await env.rowmap()) == day


# ── 6. Empty Alpaca reply ───────────────────────────────────────────────────

@pytest.mark.parametrize("how", ["empty_reply", "batch_failure"])
async def test_6_empty_alpaca_reply_takes_the_full_window_path(monkeypatch, engines, how):
    from app.data import alpaca
    world = World([Ev(wd(SEED, 1), 0.995)])          # an event the empty night lands inside
    env = await make_env(monkeypatch, engines, world)
    await env.night(SEED)
    day = wd(SEED, 1)
    if how == "empty_reply":
        result = await env.night(day, alpaca=[])
    else:
        monkeypatch.setattr(alpaca, "get_alpaca_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(alpaca, "fetch_daily_bars_single",
                            AsyncMock(side_effect=RuntimeError("batch failed")))
        env.at(day)
        result = await history.update_history(SYMBOL, START, day)
    assert (result.action, result.reason) == ("FULL", "empty_alpaca")
    assert env.tiingo.await_args.args[1:3] == (START, day + timedelta(days=1))
    rowmap = await env.rowmap()
    assert sorted(rowmap) == weekdays(START, day)
    reply = {date.fromisoformat(b["time"]): b for b in world.reply("tiingo", START, day)}
    for d, r in rowmap.items():                       # every row rewritten, current factors
        assert r.source == "tiingo" and hs._as_utc(r.fetched_at) == env.now
        assert r.adj_factor == Decimal(str(reply[d]["adj_factor"])).quantize(Q8)
    st = await env.state()
    assert st.seam_date is None and st.seam_signature is None
    result = await env.night(wd(day, 1))
    assert (result.action, result.reason) == ("FULL", "T1")   # seam cleared
    result = await env.night(wd(day, 2))
    assert (result.action, result.reason) == ("FULL", "T6_lag_window")   # T6 then applies


# ── 7. Each trust-condition failure takes today's full path ─────────────────

async def _t1(env, bars):
    async def fn(db):
        (await db.get(State, SYMBOL)).seam_signature = None
    await env.mutate(fn)
    return bars


async def _t2(env, bars):
    async def fn(db):
        row = await db.get(M, (SYMBOL, wd(SEAM, -1)))
        row.adj_factor = row.adj_factor * Decimal("1.0001")
    await env.mutate(fn)
    return bars


async def _t3(env, bars):
    async def fn(db):
        await db.execute(delete(M).where(M.symbol == SYMBOL, M.date >= date(2020, 6, 8),
                                         M.date <= date(2020, 6, 19)))
    await env.mutate(fn)
    return bars


async def _t4(env, bars):
    async def fn(db):
        await db.execute(delete(M).where(M.symbol == SYMBOL, M.date == R[2]))
    await env.mutate(fn)
    return bars


async def _t5_raw(env, bars):
    bars[1]["close"] = round(bars[1]["close"] + 0.1, 4)
    return bars


async def _t5_non_uniform(env, bars):
    bars[0]["adj_factor"] = round(bars[0]["adj_factor"] * 0.999, 8)
    return bars


async def _t5_unexplained(env, bars):
    return [{**b, "adj_factor": round(b["adj_factor"] * 0.999, 8)} for b in bars]


async def _t6(env, bars):
    async def fn(db):
        (await db.get(State, SYMBOL)).floor_checked_at = et(date(2020, 8, 21))
    await env.mutate(fn)
    return bars


@pytest.mark.parametrize("mutate, reason", [
    (_t1, "T1"), (_t2, "T2"), (_t3, "T3"), (_t4, "T4"), (_t5_raw, "raw_close_changed"),
    (_t5_non_uniform, "non_uniform_ratio"), (_t5_unexplained, "unexplained_adjustment"),
    (_t6, "T6_lag_window"),
])
async def test_7_each_trust_failure_takes_todays_full_path(monkeypatch, engines, mutate, reason):
    env = await make_env(monkeypatch, engines)
    await env.night(SEED)
    spy = AsyncMock(side_effect=history._fetch_fallback)
    monkeypatch.setattr(history, "_fetch_fallback", spy)
    day = wd(SEED, 1)
    env.at(day)
    bars = await mutate(env, env.world.alpaca())
    result = await history.update_history(SYMBOL, START, day, alpaca_bars=bars)
    spy.assert_awaited_once()
    assert spy.await_args.args[:2] == (SYMBOL, START)
    assert (result.action, result.reason) == ("FULL", reason)
    rowmap = await env.rowmap()
    assert sorted(rowmap) == weekdays(START, day)
    assert {hs._as_utc(r.fetched_at) for r in rowmap.values()} == {env.now}
    assert hs._as_utc((await env.state()).floor_checked_at) == env.now


# ── 8. Tiingo-only symbols: the anchored recent window ──────────────────────

N0 = SEED                      # the full single-provider write: anchor = N0


async def _tiingo_only_env(monkeypatch, engines, world=None):
    env = await make_env(monkeypatch, engines, world)
    env.at(N0)
    await history.rebuild_single_provider(SYMBOL, START, N0)
    st = await env.state()
    assert st.basis_provider == "tiingo" and st.window_verified_through == N0
    env.tiingo.reset_mock()
    env.notify.reset_mock()
    return env


async def _sp_night(env, day, hour=20, **kw):
    env.at(day, hour)
    return await history.update_history(SYMBOL, START, day, alpaca_bars=[], **kw)


@pytest.mark.parametrize("written, night", [
    ((N0, 20), (N0, 23)),                                     # same evening, after the write
    ((date(2020, 9, 4), 20), (date(2020, 9, 5), 21)),         # Friday write, Saturday night
])
async def test_8_current_anchor_makes_no_request_and_no_write(monkeypatch, engines, written, night):
    env = await make_env(monkeypatch, engines)
    env.at(*written)
    await history.rebuild_single_provider(SYMBOL, START, written[0])
    env.tiingo.reset_mock()
    env.notify.reset_mock()
    before = await env.snapshot()
    result = await _sp_night(env, *night)
    assert (result.action, result.reason) == ("SINGLE_PROVIDER_CURRENT", "current")
    assert result.provider == "tiingo" and result.stored == 0
    env.tiingo.assert_not_awaited()
    env.notify.assert_not_called()
    assert await env.snapshot() == before


async def test_8_recent_window_without_event_rewrites_only_the_window(monkeypatch, engines):
    env = await _tiingo_only_env(monkeypatch, engines)
    older_before = await env.rows(before=N0 - timedelta(days=21))
    day = wd(N0, 1)
    result = await _sp_night(env, day)
    assert (result.action, result.reason) == ("SINGLE_PROVIDER_RECENT", "window_unchanged")
    assert result.provider == "tiingo"
    env.tiingo.assert_awaited_once()
    assert env.tiingo.await_args.args[1:3] == (N0 - timedelta(days=21), day + timedelta(days=1))
    assert await env.rows(before=N0 - timedelta(days=21)) == older_before
    rowmap = await env.rowmap()
    window = {d: r for d, r in rowmap.items() if d >= N0 - timedelta(days=21)}
    assert max(window) == day
    assert {hs._as_utc(r.fetched_at) for r in window.values()} == {env.now}
    st = await env.state()
    assert st.window_verified_through == day and hs._as_utc(st.window_verified_at) == env.now
    env.notify.assert_called_once_with(SYMBOL)


async def _on_demand_append(env, start, end, hour=19):
    """What an on-demand ``get_bars`` stores: rows after the last stored date, with the
    factors of its own fetch moment (written as ``_get_bars_locked`` writes them)."""
    env.at(end, hour)
    async with env.factory() as db:
        await hs._store_bars(SYMBOL, env.world.reply("tiingo", start, end), db)
        await db.commit()


@pytest.mark.parametrize("full", ["ok", "refused"])
@pytest.mark.parametrize("case", ["append_after_boundary", "chunk_after_gap"])
async def test_8_event_after_the_anchor_refreshes_every_older_row(monkeypatch, engines, case, full):
    if case == "append_after_boundary":
        event, day, append_from = Ev(wd(N0, 1), 0.995), wd(N0, 1), wd(N0, 1)
    else:
        event, day, append_from = Ev(date(2020, 9, 15), 0.995), date(2020, 9, 25), wd(N0, 1)
    world = World([event])
    env = await _tiingo_only_env(monkeypatch, engines, world)
    await _on_demand_append(env, append_from, day)
    appended = await env.rowmap()
    assert hs._as_utc(appended[day].fetched_at) >= hs.last_settle_boundary(et(day, 19))
    if full == "refused":
        real = env._tiingo
        calls = []

        async def second_refused(symbol, start, end, *, strict_adjustments):
            calls.append(start)
            if len(calls) == 2:
                raise ProviderUnavailable("tiingo requests_per_hour budget exhausted (50/50)")
            return await real(symbol, start, end, strict_adjustments=strict_adjustments)

        env.tiingo.side_effect = second_refused
    result = await _sp_night(env, day)
    starts = [c.args[1] for c in env.tiingo.await_args_list]
    assert starts == [N0 - timedelta(days=21), START]              # window, then full window
    st = await env.state()
    assert st.window_verified_through == day and hs._as_utc(st.window_verified_at) == env.now
    rowmap = await env.rowmap()
    assert sorted(rowmap) == weekdays(START, day)
    if full == "ok":
        assert (result.action, result.reason) == ("SINGLE_PROVIDER_FULL", "window_event")
        reply = {date.fromisoformat(b["time"]): b for b in world.reply("tiingo", START, day)}
        for d, r in rowmap.items():
            assert r.adj_factor == Decimal(str(reply[d]["adj_factor"])).quantize(Q8), d
    else:
        assert (result.action, result.reason) == ("SINGLE_PROVIDER_RECENT", "window_event_fallback")
        assert {hs._as_utc(r.fetched_at) for r in rowmap.values()} == {env.now}
    assert_close_to_truth(await env.read(day), world, 2e-6)       # no step anywhere
    assert await env.stale() is None
    env.notify.assert_called_once_with(SYMBOL)


async def test_8_d1b_window_event_rescales_without_a_second_request(monkeypatch, engines):
    world = World([Ev(wd(N0, 1), 0.995)])
    env = await _tiingo_only_env(monkeypatch, engines, world)
    result = await _sp_night(env, wd(N0, 1), params=hi.IncrementalParams(confirm=False))
    assert (result.action, result.reason) == ("SINGLE_PROVIDER_RECENT", "window_event_rescale")
    env.tiingo.assert_awaited_once()
    assert_close_to_truth(await env.read(wd(N0, 1)), world, 2e-6)
    assert await env.stale() is None


@pytest.mark.parametrize("anchor, reason", [("null", "no_anchor"), ("old", "anchor_too_old")])
async def test_8_missing_or_old_anchor_takes_the_full_window_path(monkeypatch, engines, anchor, reason):
    env = await _tiingo_only_env(monkeypatch, engines)

    async def fn(db):
        st = await db.get(State, SYMBOL)
        st.window_verified_through = None if anchor == "null" else N0 - timedelta(days=60)
        st.window_verified_at = et(N0 - timedelta(days=60))
    await env.mutate(fn)
    day = wd(N0, 1)
    result = await _sp_night(env, day)
    assert (result.action, result.reason) == ("SINGLE_PROVIDER_FULL", reason)
    env.tiingo.assert_awaited_once()
    assert env.tiingo.await_args.args[1] == START
    st = await env.state()
    assert st.window_verified_through == day


async def test_8_identity_failure_takes_the_full_window_path(monkeypatch, engines):
    env = await _tiingo_only_env(monkeypatch, engines)
    real = env._tiingo
    corrected = N0 - timedelta(days=7)

    async def corrected_close(symbol, start, end, *, strict_adjustments):
        bars = await real(symbol, start, end, strict_adjustments=strict_adjustments)
        return [{**b, "close": round(b["close"] * 1.01, 4)} if b["time"] == corrected.isoformat()
                else b for b in bars]

    env.tiingo.side_effect = corrected_close
    day = wd(N0, 1)
    result = await _sp_night(env, day)
    assert (result.action, result.reason) == ("SINGLE_PROVIDER_FULL", "identity")
    assert [c.args[1] for c in env.tiingo.await_args_list] == [N0 - timedelta(days=21), START]
    assert (await env.rowmap())[corrected].close == Decimal(str(round(base_close(corrected) * 1.01, 4)))


@pytest.mark.parametrize("how", ["window_request_refused", "full_after_bad_window_refused",
                                 "d1a_full_and_fallback_refused"])
async def test_8_refusal_leaves_rows_and_state_untouched(monkeypatch, engines, how):
    world = World([Ev(wd(N0, 1), 0.995)]) if how == "d1a_full_and_fallback_refused" else World()
    env = await _tiingo_only_env(monkeypatch, engines, world)
    before = await env.snapshot()
    real = env._tiingo
    calls = []

    async def scripted(symbol, start, end, *, strict_adjustments):
        calls.append(start)
        if how == "window_request_refused":
            raise ProviderUnavailable("tiingo requests_per_day budget exhausted (1000/1000)")
        if len(calls) == 2:
            raise ProviderUnavailable("tiingo requests_per_hour budget exhausted (50/50)")
        bars = await real(symbol, start, end, strict_adjustments=strict_adjustments)
        if how == "full_after_bad_window_refused":
            bars = [b for b in bars if b["time"] != (N0 - timedelta(days=7)).isoformat()]
        return bars

    env.tiingo.side_effect = scripted
    if how == "d1a_full_and_fallback_refused":
        async def store_fails(*args):
            raise RuntimeError("synthetic store failure")
        monkeypatch.setattr(hs, "_store_bars", store_fails)
    with pytest.raises(history.SingleProviderRefused) as info:
        await _sp_night(env, wd(N0, 1))
    assert "tiingo:" in str(info.value)
    assert await env.snapshot() == before
    env.notify.assert_not_called()
    assert len(calls) == (1 if how == "window_request_refused" else 2)


# ── 9. force_backfill ───────────────────────────────────────────────────────

async def test_9_force_backfill_takes_the_full_path_even_when_trusted(monkeypatch, engines):
    env = await make_env(monkeypatch, engines)
    await env.night(SEED)
    spy = AsyncMock(side_effect=history._fetch_fallback)
    monkeypatch.setattr(history, "_fetch_fallback", spy)
    result = await env.night(wd(SEED, 1), force_backfill=True)
    spy.assert_awaited_once()
    assert (result.action, result.reason) == ("FULL", "force_backfill")


async def test_9_force_backfill_on_a_current_tiingo_only_symbol_requests_the_full_window(
        monkeypatch, engines):
    env = await _tiingo_only_env(monkeypatch, engines)
    result = await _sp_night(env, N0, hour=23, force_backfill=True)
    assert (result.action, result.reason) == ("SINGLE_PROVIDER_FULL", "force_backfill")
    env.tiingo.assert_awaited_once()
    assert env.tiingo.await_args.args[1] == START


# ── 10. Locking ─────────────────────────────────────────────────────────────

async def test_10_concurrent_get_bars_waits_for_the_incremental_write(monkeypatch, engines):
    env = await make_env(monkeypatch, engines)
    await env.night(SEED)
    day = wd(SEED, 1)
    env.at(day)
    started, release = asyncio.Event(), asyncio.Event()
    real_store = hs._store_bars

    async def blocking_store(*args):
        started.set()
        await release.wait()
        return await real_store(*args)

    monkeypatch.setattr(hs, "_store_bars", blocking_store)
    reads = []

    async def locked_read(symbol, start, end):
        async with env.factory() as db:
            reads.append(await hs._read_bars(symbol, start, end, db))
        return reads[-1]

    monkeypatch.setattr(hs, "_get_bars_locked", locked_read)
    write = asyncio.create_task(
        history.update_history(SYMBOL, START, day, alpaca_bars=env.world.alpaca()))
    await started.wait()
    reader = asyncio.create_task(hs.get_bars(SYMBOL, START, day))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not reader.done() and reads == []
    release.set()
    result = await write
    got = await reader
    assert result.action == "SUFFIX_ONLY"
    assert got[-1]["time"] == day.isoformat()


# ── tiingo_allowed=False (pass 1 of 2.7) ────────────────────────────────────

async def test_tiingo_allowed_false_defers_every_tiingo_needing_action(monkeypatch, engines):
    world = World([Ev(E, 0.995)])
    env = await make_env(monkeypatch, engines, world)
    # FULL (no state yet): deferred, nothing written.
    result = await env.night(SEED, tiingo_allowed=False)
    assert (result.action, result.reason) == ("deferred", "FULL")
    env.tiingo.assert_not_awaited()
    assert await env.snapshot() == ([], [])
    await env.night(SEED)
    calls = env.provider_calls()
    # SUFFIX_ONLY and RESCALE need no Tiingo request: they run.
    assert (await env.night(wd(E, -1), tiingo_allowed=False)).action == "SUFFIX_ONLY"
    assert (await env.night(E, tiingo_allowed=False)).action == "RESCALE"
    assert env.provider_calls() == calls
    # CONFIRM is deferred: nothing written, nothing committed.
    before = await env.snapshot()
    env.notify.reset_mock()
    result = await env.night(wd(E, L), tiingo_allowed=False)
    assert (result.action, result.reason) == ("deferred", "CONFIRM")
    assert await env.snapshot() == before and env.provider_calls() == calls
    env.notify.assert_not_called()


@pytest.mark.parametrize("provider, night, expected", [
    ("tiingo", (wd(N0, 1), 20), ("deferred", "SINGLE_PROVIDER_RECENT")),
    ("tiingo", (N0, 23), ("SINGLE_PROVIDER_CURRENT", "current")),
    ("yfinance", (wd(N0, 1), 20), ("SINGLE_PROVIDER_FULL", "yfinance_basis")),
])
async def test_tiingo_allowed_false_on_single_provider_symbols(monkeypatch, engines, provider,
                                                               night, expected):
    env = await make_env(monkeypatch, engines)
    if provider == "yfinance":
        env.tiingo_error = ProviderUnavailable("tiingo down")
    env.at(N0)
    await history.rebuild_single_provider(SYMBOL, START, N0)
    assert (await env.state()).basis_provider == provider
    env.tiingo.reset_mock()
    before = await env.snapshot()
    result = await _sp_night(env, *night, tiingo_allowed=False)
    assert (result.action, result.reason) == expected
    env.tiingo.assert_not_awaited()
    if expected[0] != "SINGLE_PROVIDER_FULL":
        assert await env.snapshot() == before


async def test_results_keep_their_existing_fields():
    result = history.HistoryUpdateResult(1, True, False)
    assert result.action is None and result.reason is None and result.provider is None
