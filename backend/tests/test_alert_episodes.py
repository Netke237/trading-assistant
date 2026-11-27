"""PORTFOLIO-ALERT-ACTION T1 — episode core + alert-history read API.

Plan: docs/superpowers/plans/2026-11-27-portfolio-alert-action-plan.md,
"Definitions" and "### 1. Episode core + read API (backend)".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel

UTC = timezone.utc
H = timedelta(hours=1)
D = timedelta(days=1)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False,
    autoflush=False, autocommit=False,
)

DEFAULT_CFG = {"reminderIntervalHours": 4, "positionAlertRetentionDays": 30}


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    from app.models import portfolio, watchlist, audit_event, position_alert  # noqa: F401
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    from app.database import get_db
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _insert_position(db, rec_id, symbol, contract=None):
    db.add(PortfolioPositionModel(
        rec_id=rec_id, symbol=symbol, contract=contract or f"{symbol}|STOCK|{rec_id}",
        direction="Bullish", entry_price=100.0, qty=1, entry_date="2026-10-01",
    ))
    await db.commit()


async def _insert_rows(db, rec_id, symbol, alert_type, timestamps, source="backend"):
    for ts in timestamps:
        db.add(PositionAlertHistoryModel(
            rec_id=rec_id, symbol=symbol, alert_type=alert_type, source=source,
            price=50.0, reference_value=55.0, reference_kind="price", triggered_at=ts,
        ))
    await db.commit()


def _every(start, end, step):
    out = []
    t = start
    while t <= end:
        out.append(t)
        t += step
    return out


# ── pure: split_episodes ─────────────────────────────────────────────────────

def test_constants():
    from app.services import alert_episodes as ae
    assert ae.EPISODE_GAP_HOURS == 72
    assert ae.REMINDER_PERIOD_HOURS == 24
    assert ae.DAILY_SUMMARY_HOUR_BERLIN == 9


def test_bmy_style_four_hourly_rows_are_one_episode():
    from app.services.alert_episodes import split_episodes
    start = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    ts = _every(start, datetime(2026, 11, 11, 9, 0, tzinfo=UTC), 4 * H)
    eps = split_episodes(ts, 72 * H)
    assert len(eps) == 1
    assert eps[0].start == start
    assert eps[0].last == datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
    assert eps[0].count == len(ts)


def test_split_is_order_independent():
    from app.services.alert_episodes import split_episodes
    a = datetime(2026, 10, 18, tzinfo=UTC)
    eps = split_episodes([a + 8 * H, a, a + 4 * H], 72 * H)
    assert len(eps) == 1 and eps[0].start == a and eps[0].last == a + 8 * H


def test_gap_splits_above_72h_not_at_71h_or_exactly_72h():
    from app.services.alert_episodes import split_episodes
    a = datetime(2026, 10, 18, tzinfo=UTC)
    assert len(split_episodes([a, a + 71 * H], 72 * H)) == 1
    assert len(split_episodes([a, a + 72 * H], 72 * H)) == 1
    eps = split_episodes([a, a + 72 * H + timedelta(seconds=1)], 72 * H)
    assert len(eps) == 2
    assert eps[1].start == a + 72 * H + timedelta(seconds=1)
    assert eps[0].count == 1 and eps[1].count == 1


def test_split_empty():
    from app.services.alert_episodes import split_episodes
    assert split_episodes([], 72 * H) == []


def test_naive_and_aware_timestamps_mix_as_utc():
    from app.services.alert_episodes import split_episodes
    aware = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    naive = datetime(2026, 10, 18, 6, 0)  # naive → UTC, so 4h earlier
    eps = split_episodes([aware, naive], 72 * H)
    assert len(eps) == 1
    assert eps[0].start == datetime(2026, 10, 18, 6, 0, tzinfo=UTC)
    assert eps[0].start.tzinfo is not None
    # an aware non-UTC value is converted, not relabelled
    berlin_like = datetime(2026, 10, 18, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    eps = split_episodes([berlin_like], 72 * H)
    assert eps[0].start == datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    assert eps[0].start.utcoffset() == timedelta(0)


# ── effective_gap ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cfg,hours", [
    ({}, 72),
    ({"reminderIntervalHours": 4}, 72),
    ({"reminderIntervalHours": 36}, 72),
    ({"reminderIntervalHours": 37}, 74),
    ({"reminderIntervalHours": 168}, 336),
    ({"reminderIntervalHours": "bad"}, 72),
    ({"reminderIntervalHours": None}, 72),
    (None, 72),
])
def test_effective_gap_is_max_72h_and_twice_reminder(cfg, hours):
    from app.services.alert_episodes import effective_gap
    assert effective_gap(cfg) == timedelta(hours=hours)


# ── duration text ────────────────────────────────────────────────────────────

# Shared with the TS test (frontend/lib/alertEpisodes) — keep the two in step.
DURATION_CASES = [
    (timedelta(0), False, "under 1 h"),
    (timedelta(minutes=59, seconds=59), False, "under 1 h"),
    (timedelta(hours=1), False, "1 h"),
    (timedelta(hours=23, minutes=59), False, "23 h"),
    (timedelta(hours=24), False, "1 day"),
    (timedelta(hours=47, minutes=59), False, "1 day"),
    (timedelta(hours=48), False, "2 days"),
    (timedelta(days=30, hours=5), False, "30 days"),
    (timedelta(days=30, hours=5), True, "30+ days"),
    (timedelta(days=1), True, "1+ days"),
]


@pytest.mark.parametrize("delta,truncated,text", DURATION_CASES)
def test_format_active_duration(delta, truncated, text):
    from app.services.alert_episodes import format_active_duration
    now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    assert format_active_duration(now - delta, now, truncated) == text


def test_format_active_duration_naive_start_is_utc():
    from app.services.alert_episodes import format_active_duration
    now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    assert format_active_duration(datetime(2026, 11, 27, 9, 0), now, False) == "3 h"


def test_format_active_duration_future_start_is_under_1h():
    from app.services.alert_episodes import format_active_duration
    now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    assert format_active_duration(now + 2 * H, now, False) == "under 1 h"


# ── truncation ───────────────────────────────────────────────────────────────

def test_is_truncated_edge():
    from app.services.alert_episodes import is_start_truncated
    now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
    gap = 72 * H
    edge = now - 30 * D + gap  # start - gap == now - retention → truncated
    assert is_start_truncated(edge, now, gap, 30) is True
    assert is_start_truncated(edge + timedelta(seconds=1), now, gap, 30) is False
    assert is_start_truncated(edge - timedelta(seconds=1), now, gap, 30) is True
    # retention disabled (pruning skipped for <= 0) → nothing can be pruned
    assert is_start_truncated(edge - 100 * D, now, gap, 0) is False


# ── DB: current_episodes / episode_start ─────────────────────────────────────

@pytest.mark.asyncio
async def test_current_episodes_ftnt_separate_keys(db_session):
    from app.services.alert_episodes import current_episodes
    tp = _every(datetime(2026, 10, 18, 9, tzinfo=UTC), datetime(2026, 10, 26, 9, tzinfo=UTC), 4 * H)
    stop = _every(datetime(2026, 10, 31, 9, tzinfo=UTC), datetime(2026, 11, 11, 9, tzinfo=UTC), 4 * H)
    await _insert_rows(db_session, "FTNT-1", "FTNT", "TP_HIT", tp)
    await _insert_rows(db_session, "FTNT-1", "FTNT", "STOP_REACHED", stop)

    now = datetime(2026, 11, 11, 12, tzinfo=UTC)
    out = await current_episodes(db_session, ["FTNT-1"], now, delivery_cfg=DEFAULT_CFG)
    assert ("FTNT-1", "TP_HIT") not in out
    view = out[("FTNT-1", "STOP_REACHED")]
    assert view.start == datetime(2026, 10, 31, 9, tzinfo=UTC)
    assert view.last == datetime(2026, 11, 11, 9, tzinfo=UTC)
    assert view.count == len(stop)
    assert view.truncated is False


@pytest.mark.asyncio
async def test_current_episodes_bmy_truncated_true_and_false(db_session):
    from app.services.alert_episodes import current_episodes
    start = datetime(2026, 10, 18, 9, tzinfo=UTC)
    await _insert_rows(db_session, "BMY-1", "BMY", "STOP_REACHED",
                       _every(start, datetime(2026, 11, 27, 9, tzinfo=UTC), 4 * H))
    # start - 72h = 10-15 09:00; now - 30d = 10-28 12:00 → truncated
    out = await current_episodes(db_session, ["BMY-1"], datetime(2026, 11, 27, 12, tzinfo=UTC),
                                 delivery_cfg=DEFAULT_CFG)
    v = out[("BMY-1", "STOP_REACHED")]
    assert v.start == start and v.truncated is True
    # longer retention → the start is known
    out = await current_episodes(db_session, ["BMY-1"], datetime(2026, 11, 27, 12, tzinfo=UTC),
                                 delivery_cfg={**DEFAULT_CFG, "positionAlertRetentionDays": 60})
    assert out[("BMY-1", "STOP_REACHED")].truncated is False


@pytest.mark.asyncio
async def test_current_episodes_not_current_after_gap(db_session):
    from app.services.alert_episodes import current_episodes
    last = datetime(2026, 11, 1, tzinfo=UTC)
    await _insert_rows(db_session, "R1", "X", "TIME_STOP", [last])
    assert await current_episodes(db_session, ["R1"], last + 72 * H, delivery_cfg=DEFAULT_CFG)
    assert not await current_episodes(db_session, ["R1"], last + 72 * H + timedelta(seconds=1),
                                      delivery_cfg=DEFAULT_CFG)
    # a long reminder window widens the gap
    assert await current_episodes(db_session, ["R1"], last + 100 * H,
                                  delivery_cfg={"reminderIntervalHours": 60})


@pytest.mark.asyncio
async def test_current_episodes_filters_types_and_rec_ids(db_session):
    from app.services.alert_episodes import current_episodes
    t = datetime(2026, 11, 26, tzinfo=UTC)
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", [t])
    await _insert_rows(db_session, "R1", "X", "REGIME_CHANGE", [t])
    await _insert_rows(db_session, "R2", "Y", "STOP_REACHED", [t])
    out = await current_episodes(db_session, ["R1"], t + H, alert_types={"STOP_REACHED"},
                                 delivery_cfg=DEFAULT_CFG)
    assert set(out) == {("R1", "STOP_REACHED")}
    assert await current_episodes(db_session, [], t, delivery_cfg=DEFAULT_CFG) == {}


@pytest.mark.asyncio
async def test_current_episodes_merges_sources(db_session):
    from app.services.alert_episodes import current_episodes
    t = datetime(2026, 11, 20, tzinfo=UTC)
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", [t], source="frontend")
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", [t + 50 * H], source="backend")
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", [t + 100 * H], source="frontend")
    out = await current_episodes(db_session, ["R1"], t + 101 * H, delivery_cfg=DEFAULT_CFG)
    v = out[("R1", "STOP_REACHED")]
    assert v.start == t and v.count == 3


@pytest.mark.asyncio
async def test_current_episodes_naive_db_values_are_utc(db_session):
    from app.services.alert_episodes import current_episodes
    # SQLite returns naive datetimes; insert a naive value and an aware one
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", [datetime(2026, 11, 26, 8, 0)])
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED",
                       [datetime(2026, 11, 26, 14, 0, tzinfo=timezone(timedelta(hours=2)))])
    out = await current_episodes(db_session, ["R1"], datetime(2026, 11, 26, 13, tzinfo=UTC),
                                 delivery_cfg=DEFAULT_CFG)
    v = out[("R1", "STOP_REACHED")]
    assert v.start == datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    assert v.start.utcoffset() == timedelta(0)
    assert v.count == 2


@pytest.mark.asyncio
async def test_episode_start(db_session):
    from app.services.alert_episodes import episode_start
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED",
                       [datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 20, tzinfo=UTC),
                        datetime(2026, 11, 21, tzinfo=UTC)])
    now = datetime(2026, 11, 22, tzinfo=UTC)
    es = await episode_start(db_session, "R1", "STOP_REACHED", now, delivery_cfg=DEFAULT_CFG)
    assert es.start == datetime(2026, 11, 20, tzinfo=UTC)
    assert es.truncated is False
    assert await episode_start(db_session, "R1", "TP_HIT", now, delivery_cfg=DEFAULT_CFG) is None
    assert await episode_start(db_session, "R1", "STOP_REACHED", now + 10 * D,
                               delivery_cfg=DEFAULT_CFG) is None


@pytest.mark.asyncio
async def test_current_episodes_loads_config_when_not_passed(db_session):
    from app.services import alert_episodes as ae
    last = datetime(2026, 11, 1, tzinfo=UTC)
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", [last])
    with patch.object(ae, "load_delivery_config", return_value={"reminderIntervalHours": 60}):
        assert await ae.current_episodes(db_session, ["R1"], last + 100 * H)
    with patch.object(ae, "load_delivery_config", return_value={}):
        assert not await ae.current_episodes(db_session, ["R1"], last + 100 * H)


# ── endpoints ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_episodes_endpoint_open_positions_only(client, db_session):
    from app.services import alert_episodes as ae
    now = datetime.now(UTC).replace(microsecond=0)
    await _insert_position(db_session, "OPEN-1", "BMY")
    # OPEN-1: a current STOP episode, an EVENT_RISK one, and a REGIME_CHANGE (not a position type)
    await _insert_rows(db_session, "OPEN-1", "BMY", "STOP_REACHED", [now - 10 * H, now - 2 * H])
    await _insert_rows(db_session, "OPEN-1", "BMY", "EVENT_RISK", [now - 1 * H])
    await _insert_rows(db_session, "OPEN-1", "BMY", "REGIME_CHANGE", [now - 1 * H])
    # CLOSED-1: rows but no open position → excluded
    await _insert_rows(db_session, "CLOSED-1", "NFLX", "STOP_REACHED", [now - 1 * H])

    with patch.object(ae, "load_delivery_config", return_value=DEFAULT_CFG):
        resp = await client.get("/api/alerts/episodes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gapHours"] == 72
    assert body["retentionDays"] == 30
    assert datetime.fromisoformat(body["generatedAt"]).utcoffset() == timedelta(0)
    eps = body["episodes"]
    assert {(e["recId"], e["alertType"]) for e in eps} == {
        ("OPEN-1", "STOP_REACHED"), ("OPEN-1", "EVENT_RISK"),
    }
    stop = next(e for e in eps if e["alertType"] == "STOP_REACHED")
    assert stop["symbol"] == "BMY"
    assert stop["fireCount"] == 2
    assert stop["startTruncated"] is False
    started = datetime.fromisoformat(stop["startedAt"])
    assert started.utcoffset() == timedelta(0)
    assert started == now - 10 * H
    assert datetime.fromisoformat(stop["lastFiredAt"]) == now - 2 * H


@pytest.mark.asyncio
async def test_episodes_endpoint_gap_hours_follows_reminder(client, db_session):
    from app.services import alert_episodes as ae
    with patch.object(ae, "load_delivery_config",
                      return_value={"reminderIntervalHours": 48, "positionAlertRetentionDays": 14}):
        body = (await client.get("/api/alerts/episodes")).json()
    assert body["gapHours"] == 96
    assert body["retentionDays"] == 14
    assert body["episodes"] == []


@pytest.mark.asyncio
async def test_history_endpoint_404_for_unknown_or_closed(client, db_session):
    now = datetime.now(UTC)
    await _insert_rows(db_session, "CLOSED-1", "NFLX", "STOP_REACHED", [now - H])
    assert (await client.get("/api/alerts/history/CLOSED-1")).status_code == 404
    assert (await client.get("/api/alerts/history/NOPE")).status_code == 404


@pytest.mark.asyncio
async def test_history_endpoint_rows_and_all_episodes(client, db_session):
    from app.services import alert_episodes as ae
    now = datetime.now(UTC).replace(microsecond=0)
    await _insert_position(db_session, "FTNT-1", "FTNT")
    tp = [now - 20 * D, now - 19 * D]               # old, not current
    stop = [now - 10 * D, now - 3 * D, now - 1 * H]  # 10d→3d is a >72h gap: two episodes
    await _insert_rows(db_session, "FTNT-1", "FTNT", "TP_HIT", tp)
    await _insert_rows(db_session, "FTNT-1", "FTNT", "STOP_REACHED", stop)

    with patch.object(ae, "load_delivery_config", return_value=DEFAULT_CFG):
        resp = await client.get("/api/alerts/history/FTNT-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recId"] == "FTNT-1" and body["symbol"] == "FTNT"
    rows = body["rows"]
    assert len(rows) == 5
    times = [datetime.fromisoformat(r["triggeredAt"]) for r in rows]
    assert times == sorted(times, reverse=True)
    assert all(t.utcoffset() == timedelta(0) for t in times)
    r0 = rows[0]
    assert r0["alertType"] == "STOP_REACHED" and r0["source"] == "backend"
    assert r0["price"] == 50.0 and r0["referenceValue"] == 55.0
    assert r0["referenceKind"] == "price" and r0["note"] is None

    eps = body["episodes"]
    assert [(e["alertType"], datetime.fromisoformat(e["startedAt"])) for e in eps] == [
        ("STOP_REACHED", now - 3 * D),
        ("STOP_REACHED", now - 10 * D),
        ("TP_HIT", now - 20 * D),
    ]
    assert eps[0]["fireCount"] == 2
    assert all(e["startTruncated"] is False for e in eps)


@pytest.mark.asyncio
async def test_history_endpoint_caps_rows_at_500(client, db_session):
    from app.services import alert_episodes as ae
    now = datetime.now(UTC).replace(microsecond=0)
    await _insert_position(db_session, "R1", "X")
    ts = [now - i * timedelta(minutes=10) for i in range(510)]
    await _insert_rows(db_session, "R1", "X", "STOP_REACHED", ts)
    with patch.object(ae, "load_delivery_config", return_value=DEFAULT_CFG):
        body = (await client.get("/api/alerts/history/R1")).json()
    assert len(body["rows"]) == 500
    assert datetime.fromisoformat(body["rows"][0]["triggeredAt"]) == now
    # episodes are computed from every row, not the capped page
    assert body["episodes"][0]["fireCount"] == 510


@pytest.mark.asyncio
async def test_read_endpoints_do_not_commit(client, db_session):
    from unittest.mock import AsyncMock
    await _insert_position(db_session, "R1", "X")
    real = db_session.commit
    spy = AsyncMock(wraps=real)
    db_session.commit = spy
    try:
        assert (await client.get("/api/alerts/episodes")).status_code == 200
        assert (await client.get("/api/alerts/history/R1")).status_code == 200
    finally:
        db_session.commit = real
    assert spy.await_count == 0
