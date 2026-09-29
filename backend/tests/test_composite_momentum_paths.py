"""COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD unit A: the rule path (plan 3.3), the
watch path (3.4), their parity and save validation (Q10c). Plan tests 8-11, 13
and 16; each names the mutation it must kill.

Isolation: in-memory SQLite per test, every feed stubbed (parity_harness), no
YAML written, no notification dispatched.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.indicator_compute as ic
import app.services.regime_omm as regime_omm
import app.services.strategy_watch_evaluator as ev
from app.database import Base
from app.models.alert import AlertRuleModel
from tests.momentum_fixtures import (
    DAY, HOURLY_SLOTS, bar, daily_bars, et_ts, intraday_bars, osc_closes, session_times,
    weekdays, with_last,
)
from tests.parity_harness import daily_rows, parity_no_real_feeds, patch_feeds  # noqa: F401

N = ic.MOMENTUM_RSI_MACD_HISTORY + 1
RSI_BULL = {"type": "momentum", "signal_kind": "rsi_cross", "direction": "Bullish", "min_confidence": 60}


@pytest.fixture(autouse=True)
def _fresh_warnings():
    ic._momentum_warned.clear()
    yield
    ic._momentum_warned.clear()


def _td(*confs, min_conf=1, **extra):
    return {"primary": {"model": "any"}, "min_confirmations": min_conf,
            "confirmations": list(confs), **extra}


# ── series ───────────────────────────────────────────────────────────────────

def _hourly(closes, volumes=None, opens=None):
    days = weekdays(date(2025, 3, 3), len(closes) // len(HOURLY_SLOTS) + 2)
    times = session_times(days, HOURLY_SLOTS)[:len(closes)]
    return intraday_bars(times, closes, volumes, opens)


def _four_hour(closes, volumes=None, opens=None):
    days = weekdays(date(2025, 4, 1), len(closes) // 2 + 2)
    times = session_times(days, [(8, 0), (12, 0)])[:len(closes)]     # EDT UTC-epoch buckets
    return intraday_bars(times, closes, volumes, opens)


def _weekly(closes, volumes=None, opens=None):
    t0 = et_ts(date(2020, 1, 6), 0, 0)
    return [bar(t0 + i * 7 * DAY, c, open_=None if opens is None else opens[i],
                volume=1000 if volumes is None else volumes[i]) for i, c in enumerate(closes)]


def _daily(closes, volumes=None, opens=None):
    return daily_bars(closes, volumes=volumes, opens=opens, t0=et_ts(date(2024, 1, 2), 0, 0))


BUILDERS = {"1h": _hourly, "4h": _four_hour, "1D": _daily, "1W": _weekly}


def _cross_closes(delta):
    """N+30 closes whose last is an RSI/MACD cross (delta>0 up, <0 down)."""
    base = osc_closes(N + 29)
    if delta < 0:
        base = osc_closes(N + 30)[:-1]
    return with_last(base, delta)


def _next_time(bars):
    """The time of the bar after bars[-1] on its interval's own calendar (the
    next regular slot on intraday, so a synthetic forming bar is never an
    after-hours bar the session filter would drop)."""
    step = min(b["time"] - a["time"] for a, b in zip(bars[-6:], bars[-5:]))    # the bar span
    t = bars[-1]["time"] + step
    if step < DAY:
        from app.services.indicator_compute import _is_regular_bar
        while not _is_regular_bar(t, step) or datetime.fromtimestamp(t, timezone.utc).weekday() >= 5:
            t += step
    return t


def _with_forming(bars):
    last = bars[-1]
    return bars + [bar(_next_time(bars), last["close"], volume=last["volume"])]


# ── rule harness ─────────────────────────────────────────────────────────────

async def _db(monkeypatch):
    from app.routers import chart_alerts
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(chart_alerts, "AsyncSessionLocal", Session)
    monkeypatch.setattr(chart_alerts, "_load_notification_config", lambda: {})
    monkeypatch.setattr(regime_omm, "compute_omm", lambda *a, **kw: None)
    chart_alerts._DAILY_ROWS_MEMO.clear()
    return Session


async def _seed(Session, td, interval, *, cooldown=0, state="{}", rid="r1"):
    async with Session() as db:
        db.add(AlertRuleModel(
            id=rid, user_id="default", name="C", symbol="AAPL", interval=interval, enabled=True,
            rule_json=json.dumps({**td, "__type": "composite"}), cooldown_minutes=cooldown,
            expiry_date=None, created_at="2024-01-01T00:00:00Z", last_triggered_at=None,
            condition_state=state))
        await db.commit()


async def _row(Session, rid="r1"):
    async with Session() as db:
        return await db.get(AlertRuleModel, rid)


async def _eval(interval, candles, closed=None, as_of=None):
    from app.routers import chart_alerts
    closed = candles[-2] if closed is None else closed
    return await chart_alerts.evaluate_and_notify_for_symbol("AAPL", interval, closed, candles, [], as_of=as_of)


UP_H = _with_forming(_hourly(_cross_closes(5)))
FLAT_H = _with_forming(_hourly(osc_closes(N + 30)))


# ── test 8: the rule judges the closed candle on its own prefix ──────────────

@pytest.mark.asyncio
async def test_rule_fires_on_a_cross_completed_by_the_closed_candle(monkeypatch):
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "1h")
    fired = await _eval("1h", UP_H)
    assert len(fired) == 1
    assert fired[0]["trigger_values"]["momentum_matched"] == ["rsi_cross"]
    assert fired[0]["checklist"][1] == {"label": "RSI crosses up through 60", "met": True}


@pytest.mark.asyncio
async def test_rule_ignores_a_cross_only_on_the_forming_candle(monkeypatch):
    """Mutation: use all_candles uncut (the forming bar would be judged)."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "1h")
    bars = _hourly(_cross_closes(5))          # the cross is on the LAST bar = forming
    assert await _eval("1h", bars) == []


@pytest.mark.asyncio
async def test_catch_up_candle_is_judged_on_its_own_prefix(monkeypatch):
    """evaluate_closed_candles with a primed marker judges two closed candles;
    only the older one holds the cross. Mutation: use all_candles uncut."""
    import app.services.chart_alert_scheduler as sched
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "1h")
    cross = _hourly(_cross_closes(5))
    after = bar(_next_time(cross), cross[-1]["close"])               # closed, no cross
    candles = _with_forming(cross + [after])
    monkeypatch.setattr(sched, "get_intraday", AsyncMock(return_value=[]))
    monkeypatch.setitem(sched._last_seen_candle, ("AAPL", "1h"), cross[-2]["time"])
    fired = await sched.evaluate_closed_candles("AAPL", "1h", candles, None)
    assert [e["candle"]["time"] for e in fired] == [cross[-1]["time"]]


@pytest.mark.asyncio
async def test_lagged_4h_closed_candle_is_still_judged(monkeypatch):
    """With an explicit as_of the closed 4h candle is not yet 'completed' for the
    regime (_regime_candles drops it); momentum still judges it. Mutation: read
    _regime_candles."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "4h")
    candles = _with_forming(_four_hour(_cross_closes(5)))
    closed = candles[-2]
    fired = await _eval("4h", candles, as_of=float(closed["time"] + 4 * 3600 + 60))
    assert len(fired) == 1


# ── test 9: once per crossing candle ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_closed_candle_twice_fires_once(monkeypatch):
    """cooldown 0. Mutation: drop composite_fired_candle."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "1h")
    assert len(await _eval("1h", UP_H)) == 1
    assert await _eval("1h", UP_H) == []
    st = json.loads((await _row(Session)).condition_state)
    assert st["composite_fired_candle"] == {"interval": "1h", "time": UP_H[-2]["time"]}


@pytest.mark.asyncio
async def test_an_older_candle_after_a_newer_fired_one_does_not_fire(monkeypatch):
    """Mutation: `==` instead of `<=`."""
    Session = await _db(monkeypatch)
    state = json.dumps({"composite_fired_candle": {"interval": "1h", "time": UP_H[-2]["time"] + 3600}})
    await _seed(Session, _td(RSI_BULL), "1h", state=state)
    assert await _eval("1h", UP_H) == []


@pytest.mark.asyncio
async def test_next_candle_without_a_cross_does_not_fire(monkeypatch):
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "1h")
    assert len(await _eval("1h", UP_H)) == 1
    nxt = _with_forming(UP_H[:-1] + [bar(_next_time(UP_H[:-1]), UP_H[-2]["close"])])
    assert await _eval("1h", nxt) == []


@pytest.mark.asyncio
async def test_4h_second_evaluation_after_the_cooldown_still_fires_once(monkeypatch):
    """60-min cooldown, second evaluation 90 min later. Mutation: drop composite_fired_candle."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "4h", cooldown=60)
    candles = _with_forming(_four_hour(_cross_closes(5)))
    assert len(await _eval("4h", candles)) == 1
    async with Session() as db:
        r = await db.get(AlertRuleModel, "r1")
        r.last_triggered_at = (datetime.now() - timedelta(minutes=90)).isoformat()
        await db.commit()
    assert await _eval("4h", candles) == []


@pytest.mark.asyncio
async def test_interval_edit_1h_to_1D_first_daily_cross_fires(monkeypatch):
    """replace_rule keeps condition_state across an interval edit; a marker of
    another interval never suppresses. Mutation: ignore the interval key."""
    Session = await _db(monkeypatch)
    daily = _with_forming(_daily(_cross_closes(5)))
    state = json.dumps({"composite_fired_candle": {"interval": "1h", "time": daily[-1]["time"] + 10 * DAY}})
    await _seed(Session, _td(RSI_BULL), "1D", state=state)
    assert len(await _eval("1D", daily)) == 1


# ── test 13: sustain is ignored for momentum triggers (rule) ─────────────────

@pytest.mark.asyncio
async def test_rule_momentum_trigger_ignores_sustain(monkeypatch, caplog):
    """Mutation: keep sustain (a one-bar cross could never be sustained)."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL, sustain_minutes=30), "1h")
    with caplog.at_level(logging.WARNING):
        assert len(await _eval("1h", UP_H)) == 1
    assert sum("sustain_minutes=30 ignored" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_rule_min_zero_with_momentum_still_honours_sustain(monkeypatch):
    """Mutation: has_momentum ignoring the minimum."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL, min_conf=0, sustain_minutes=30), "1h")
    assert await _eval("1h", UP_H) == []         # first sighting starts the clock
    assert "composite" in json.loads((await _row(Session)).condition_state)


@pytest.mark.asyncio
async def test_rule_non_momentum_trigger_keeps_its_sustain(monkeypatch):
    """Mutation: skip sustain for every trigger."""
    Session = await _db(monkeypatch)
    await _seed(Session, _td(min_conf=0, sustain_minutes=30), "1h")
    assert await _eval("1h", UP_H) == []


# ── watch harness ────────────────────────────────────────────────────────────

class _Store:
    def __init__(self):
        self.writes: list[tuple[str, dict]] = []

    def update_state(self, wid, state):
        self.writes.append((wid, state))


def _watch(td, interval, state=None, wid="w1"):
    return {"id": wid, "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
            "enabled": True, "interval": interval, "trigger_def": td,
            "last_state": state if state is not None else {"phase": "idle"}}


_NOW = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)


async def _run_watch(monkeypatch, w, rows, store=None, daily=None):
    """One _eval_composite_watch run whose chart fetch returns `rows`."""
    patch_feeds(monkeypatch, intraday=rows, daily=daily if daily is not None else daily_rows(30, date(2026, 9, 28)))
    store = store or _Store()
    monkeypatch.setattr(ev, "strategy_watch_store", store)
    return await ev._eval_composite_watch(w, date(2024, 9, 29), date(2026, 9, 29), _NOW.timestamp(), _NOW), store


# ── test 10: the watch judges rows[-2] of the chart fetch ────────────────────

@pytest.mark.asyncio
async def test_watch_passes_momentum_ending_at_rows_minus_2(monkeypatch):
    """Mutations: pass None; judge rows[-1]."""
    import app.services.composite_trigger_evaluator as cte
    seen = []
    real = cte.evaluate_scheduled

    def spy(*a, **k):
        seen.append(k.get("momentum"))
        return real(*a, **k)

    monkeypatch.setattr(cte, "evaluate_scheduled", spy)
    daily = _with_forming(_daily(_cross_closes(5)))
    t, _ = await _run_watch(monkeypatch, _watch(_td(RSI_BULL), "1D"), daily)
    assert seen and seen[0] is not None
    assert seen[0].bars[-1]["time"] == daily[-2]["time"]
    assert seen[0].interval == "1D" and seen[0].log_key == "w1"
    assert t is not None and "momentum judged on the 1D bar" in t.event.reason
    # the cross on the forming row only: not judged
    t2, _ = await _run_watch(monkeypatch, _watch(_td(RSI_BULL), "1D"), _daily(_cross_closes(5)))
    assert t2 is None


@pytest.mark.asyncio
async def test_watch_fetch_failure_without_other_confirmation_is_no_reading(monkeypatch):
    import app.data.chart_cache as cc
    patch_feeds(monkeypatch, daily=daily_rows(30, date(2026, 9, 28)))
    monkeypatch.setattr(cc, "get_intraday_with_fetched_at", AsyncMock(side_effect=RuntimeError("down")))
    store = _Store()
    monkeypatch.setattr(ev, "strategy_watch_store", store)
    w = _watch(_td(RSI_BULL), "1D", state={"phase": "armed"})
    t = await ev._eval_composite_watch(w, date(2024, 9, 29), date(2026, 9, 29), _NOW.timestamp(), _NOW)
    assert t is None and store.writes == []          # armed watch not re-armed on a blip


@pytest.mark.asyncio
async def test_watch_fetch_failure_with_structure_meeting_the_minimum_fires(monkeypatch):
    import app.data.chart_cache as cc
    import app.services.market_structure as ms
    patch_feeds(monkeypatch, daily=daily_rows(30, date(2026, 9, 28)))
    monkeypatch.setattr(cc, "get_intraday_with_fetched_at", AsyncMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr(ms, "compute_structure",
                        lambda *a, **k: [{"kind": "BOS", "direction": "bullish", "confidence": 90}])
    monkeypatch.setattr(ev, "strategy_watch_store", _Store())
    bos = {"type": "structure", "signal_kind": "BOS", "direction": "Bullish", "min_confidence": 50}
    w = _watch(_td(bos, RSI_BULL), "1D")
    t = await ev._eval_composite_watch(w, date(2024, 9, 29), date(2026, 9, 29), _NOW.timestamp(), _NOW)
    assert t is not None


@pytest.mark.asyncio
async def test_watch_same_cross_bar_alerts_once_then_rearms(monkeypatch):
    daily = _with_forming(_daily(_cross_closes(5)))
    t, _ = await _run_watch(monkeypatch, _watch(_td(RSI_BULL), "1D"), daily)
    assert t is not None and t.new_state["phase"] == "armed"
    armed = _watch(_td(RSI_BULL), "1D", state=t.new_state)
    t2, store = await _run_watch(monkeypatch, armed, daily)
    assert t2 is None and store.writes == []              # still armed, no second alert
    no_cross = _with_forming(daily[:-1] + [bar(daily[-1]["time"], daily[-2]["close"])])
    t3, store = await _run_watch(monkeypatch, armed, no_cross)
    assert t3 is None and store.writes[-1][1]["phase"] == "idle"


# ── test 13: sustain (watch) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watch_momentum_trigger_ignores_sustain(monkeypatch, caplog):
    daily = _with_forming(_daily(_cross_closes(5)))
    with caplog.at_level(logging.WARNING):
        t, _ = await _run_watch(monkeypatch, _watch(_td(RSI_BULL, sustain_minutes=30), "1D"), daily)
    assert t is not None
    assert sum("sustain_minutes=30 ignored" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_watch_min_zero_with_momentum_honours_sustain(monkeypatch):
    daily = _with_forming(_daily(_cross_closes(5)))
    t, store = await _run_watch(monkeypatch, _watch(_td(RSI_BULL, min_conf=0, sustain_minutes=30), "1D"), daily)
    assert t is None and "pending_entry_since" in store.writes[-1][1]


# ── test 17 (watch): a 16:15 ET run judges a regular bar ─────────────────────

@pytest.mark.asyncio
async def test_watch_after_the_close_judges_a_regular_bar(monkeypatch):
    """Tradier-style 5min rows running into the post-market: rows[-2] is taken
    after the session filter, so the judged bar is a regular one."""
    import app.services.composite_trigger_evaluator as cte
    seen = []
    real = cte.evaluate_scheduled
    monkeypatch.setattr(cte, "evaluate_scheduled", lambda *a, **k: (seen.append(k.get("momentum")), real(*a, **k))[1])
    days = weekdays(date(2025, 3, 3), 40)
    times = session_times(days, [(15, 30 + 5 * i) for i in range(6)])
    rows = intraday_bars(times, osc_closes(len(times)))
    rows += [bar(et_ts(days[-1], 16, 5), 100.0), bar(et_ts(days[-1], 16, 10), 100.0)]
    await _run_watch(monkeypatch, _watch(_td(RSI_BULL), "5min"), rows)
    judged = seen[0].bars[-1]["time"]
    assert judged == et_ts(days[-1], 15, 50)          # the regular bar before the newest regular one


# ── test 11: rule / watch parity ─────────────────────────────────────────────

def _parity_series(interval):
    b = BUILDERS[interval]
    n = N + 30
    spike_vol = [1000] * (n - 1) + [5000]
    return {
        "up": b(_cross_closes(5)),
        "down": b(_cross_closes(-5)),
        "flat": b(osc_closes(n)),
        "vol_up": b([100.0] * (n - 1) + [101.0], volumes=spike_vol, opens=[100.0] * n),
        "vol_down": b([100.0] * (n - 1) + [99.0], volumes=spike_vol, opens=[100.0] * n),
    }


_KINDS = [
    {"type": "momentum", "signal_kind": "rsi_cross", "min_confidence": 60},
    {"type": "momentum", "signal_kind": "macd_cross"},
    {"type": "momentum", "signal_kind": "volume_spike"},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", ["1h", "4h", "1D", "1W"])
async def test_rule_and_watch_give_the_same_answer(monkeypatch, interval):
    """Rule on closed candle X vs a watch whose fetch returns rows up to X+1.
    Mutation: the watch judges rows[-1]. Stated limit: it cannot see a real
    fetch difference between the two paths."""
    answers = []
    tds = [_td({**k, "direction": d}) for k in _KINDS for d in ("Bullish", "Bearish", None)]
    tds.append(_td({**_KINDS[0], "direction": "Bullish"}, {**_KINDS[2], "direction": "Bullish"}, min_conf=2))
    for name, series in _parity_series(interval).items():
        candles = _with_forming(series)
        for i, td in enumerate(tds):
            Session = await _db(monkeypatch)
            await _seed(Session, td, interval, rid=f"r{i}")
            rule = bool(await _eval(interval, candles))
            t, _ = await _run_watch(monkeypatch, _watch(td, interval, wid=f"w{i}"), candles)
            watch = t is not None
            assert rule == watch, (interval, name, td["confirmations"])
            answers.append(rule)
    assert any(answers) and not all(answers)


@pytest.mark.asyncio
async def test_after_close_1D_both_judge_d_minus_1(monkeypatch):
    """After the close the newest daily row D is complete, yet both paths judge
    D-1 (the same pick as the rule scheduler): a cross on D alone fires neither."""
    daily = _daily(_cross_closes(5))          # the cross is on D, the newest row
    Session = await _db(monkeypatch)
    await _seed(Session, _td(RSI_BULL), "1D")
    assert await _eval("1D", daily) == []
    t, _ = await _run_watch(monkeypatch, _watch(_td(RSI_BULL), "1D"), daily)
    assert t is None


# ── test 16: save validation (Q10c) ──────────────────────────────────────────

async def _rules_app(monkeypatch):
    from fastapi import FastAPI
    from app.database import get_db
    from app.routers.chart_alerts import router
    Session = await _db(monkeypatch)

    async def override_get_db():
        async with Session() as s:
            yield s

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db
    return app, Session


def _body(td, enabled=True):
    return {"name": "R", "symbol": "AAPL", "interval": "1h", "enabled": enabled, "cooldown_minutes": 60,
            "expiry_date": None, "rule_type": "composite", "composite_def": td}


_BAD = [
    {**RSI_BULL, "min_confidence": 0}, {**RSI_BULL, "min_confidence": "60"},
    {**RSI_BULL, "signal_kind": "rsi_crossing"}, {**RSI_BULL, "direction": "up"},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", _BAD)
async def test_rule_create_refuses_a_momentum_confirmation_that_cannot_fire(monkeypatch, bad):
    """Mutation: drop the check."""
    app, _ = await _rules_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/alerts/rules", json=_body(_td(bad)))
        assert r.status_code == 422
        r = await c.post("/alerts/rules", json=_body(_td(RSI_BULL)))
        assert r.status_code == 201


@pytest.mark.asyncio
async def test_rule_put_refuses_new_bad_momentum_but_lets_an_unchanged_one_toggle(monkeypatch):
    """Mutation: drop the PUT exemption."""
    app, Session = await _rules_app(monkeypatch)
    bad_td = _td(_BAD[0])
    await _seed(Session, bad_td, "1h", rid="legacy")
    await _seed(Session, _td(RSI_BULL), "1h", rid="good")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put("/alerts/rules/legacy", json=_body(bad_td, enabled=False))
        assert r.status_code == 200 and r.json()["enabled"] is False
        r = await c.put("/alerts/rules/good", json=_body(bad_td))
        assert r.status_code == 422
        r = await c.put("/alerts/rules/good", json=_body(_td({**RSI_BULL, "min_confidence": 70})))
        assert r.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", _BAD)
async def test_watch_create_refuses_a_momentum_confirmation_that_cannot_fire(monkeypatch, bad):
    from fastapi import FastAPI
    import app.routers.composite_watch as cw

    class _WS:
        def add_composite_watch(self, **kw):
            return {"id": "w", **kw}

    monkeypatch.setattr(cw, "strategy_watch_store", _WS())
    app = FastAPI()
    app.include_router(cw.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/composite-watches/", json={"symbol": "AAPL", "trigger_def": _td(bad)})
        assert r.status_code == 422
        r = await c.post("/api/composite-watches/", json={"symbol": "AAPL", "trigger_def": _td(RSI_BULL)})
        assert r.status_code == 201
