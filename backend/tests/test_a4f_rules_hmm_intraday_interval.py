"""A4f-rules (decision A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25).

A composite HMM_intraday chart-alert RULE stored on '1D'/'1W' never fires:
evaluate_and_notify_for_symbol hands the HMM no intraday bars on those intervals.
The rules API now refuses such a pair (422), a PUT may keep a legacy pair it does not
change, and run_chart_alert_scheduler migrates stored ones to '5min' before its first
tick (name marked "(interval was 1D)", sustain clock reset, one WARNING).

Isolation: every test uses its own in-memory SQLite engine; nothing here runs the app
lifespan, writes backend/config/*.yaml, or dispatches a notification.
"""
from __future__ import annotations

import json
import logging
import types

import pytest
from httpx import AsyncClient, ASGITransport

HMM = {"primary": {"model": "HMM_intraday", "to_state": "Bull"}, "confirmations": [], "n_of_m": 0}
OMM = {"primary": {"model": "OMM", "to_state": "Bull"}, "confirmations": [], "n_of_m": 0}


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_alerts import router as chart_alerts_router
    app = FastAPI()
    app.include_router(chart_alerts_router)
    app.dependency_overrides[get_db] = override_get_db
    return app, Session


async def _seed(Session, rid, interval, rule_json, *, name='R', enabled=True, user_id='default',
                condition_state='{}'):
    from app.models.alert import AlertRuleModel
    async with Session() as db:
        db.add(AlertRuleModel(
            id=rid, user_id=user_id, name=name, symbol='AAPL', interval=interval, enabled=enabled,
            rule_json=rule_json if isinstance(rule_json, str) else json.dumps(rule_json),
            cooldown_minutes=60, expiry_date=None, created_at='2026-09-01T00:00:00',
            last_triggered_at=None, condition_state=condition_state,
        ))
        await db.commit()


async def _get(Session, rid):
    from app.models.alert import AlertRuleModel
    async with Session() as db:
        return await db.get(AlertRuleModel, rid)


def _composite(td):
    return {"__type": "composite", **td}


def _body(interval, td=HMM, *, enabled=True, name='R', rule_type='composite'):
    b = {"name": name, "symbol": "AAPL", "interval": interval, "enabled": enabled,
         "cooldown_minutes": 60, "expiry_date": None}
    if rule_type == 'composite':
        b.update(rule_type='composite', composite_def=td)
    return b


# ── R1: the predicate ────────────────────────────────────────────────────────

def test_r1_predicate_rejects_hmm_intraday_on_non_intraday_only():
    from app.services.composite_trigger_evaluator import hmm_intraday_interval_error as err
    for bad in ('1D', '1W', ['5m']):
        assert err(HMM, bad), bad
    for ok in ('5m', '15m', '60m', '4h'):
        assert err(HMM, ok) is None, ok
    assert err(OMM, '1D') is None
    assert err({"primary": {"model": "HMM_daily"}}, '1D') is None
    assert err({}, '1D') is None
    assert err({"primary": "HMM_intraday"}, '1D') is None
    for td in ('x', None, ['HMM_intraday']):
        assert err(td, '1D') is None


def test_r1_predicate_agrees_with_the_watch_store(monkeypatch, tmp_path):
    # Plain import (no reload). In a full run app.main has usually imported the module
    # already, so its module-level store has READ the tracked yaml by then (read-only,
    # not this test's doing); the setenv only matters if this test imports it first.
    # The test itself uses StrategyWatchStore(path=None): no file read, no write.
    monkeypatch.setenv("BAMENDJOU_STRATEGY_WATCHES_PATH", str(tmp_path / "watches.yaml"))
    from app.services.strategy_watch_store import StrategyWatchStore
    from app.services.composite_trigger_evaluator import hmm_intraday_interval_error as err

    store = StrategyWatchStore(path=None)  # no file read, save() is a no-op
    for iv in ['5m', '15m', '30m', '1h', '60m', '4h', '1min', '1D', '1W', 'daily', '1d', 'foo']:
        try:
            store.add_composite_watch('AAPL', dict(HMM), interval=iv)
            watch_msg = None
        except ValueError as exc:
            watch_msg = str(exc)
        assert err(HMM, iv) == watch_msg, iv


# ── R2: POST ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_r2_post_refuses_hmm_intraday_on_daily():
    app, _ = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        assert (await c.get('/alerts/rules')).status_code == 200  # the path exists
        r = await c.post('/alerts/rules', json=_body('1D'))
        assert r.status_code == 422
        assert 'HMM_intraday needs an intraday interval' in r.text
        assert (await c.get('/alerts/rules')).json() == []
        assert (await c.post('/alerts/rules', json=_body('5m'))).status_code == 201
        assert (await c.post('/alerts/rules', json=_body('1D', OMM))).status_code == 201
        std = _body('1D', rule_type='standard')
        std['group'] = {"logic": "AND", "conditions": []}
        assert (await c.post('/alerts/rules', json=std)).status_code == 201


# ── R3: PUT ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_r3_put_keeps_legacy_pair_but_refuses_new_bad_pairs():
    app, Session = await _make_app()
    await _seed(Session, 'legacy', '1D', _composite(HMM), name='L')
    await _seed(Session, 'migr', '5m', _composite(HMM))
    await _seed(Session, 'omm', '1D', _composite(OMM))
    await _seed(Session, 'std', '1D', {"logic": "AND", "conditions": []})
    await _seed(Session, 'junk', '1D', 'not json')
    await _seed(Session, 'fine', '5m', _composite(HMM))
    await _seed(Session, 'strprim', '1D', {"__type": "composite", "primary": "HMM_intraday"})
    await _seed(Session, 'notype', '1D', {"primary": {"model": "HMM_intraday"}, "logic": "AND", "conditions": []})
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        # (a) same pair: a toggle on a legacy rule the migration could not move
        r = await c.put('/alerts/rules/legacy', json=_body('1D', enabled=False, name='L'))
        assert r.status_code == 200
        row = await _get(Session, 'legacy')
        assert row.enabled is False and row.interval == '1D'
        # (b) changed pair, still invalid -> refused, row untouched
        r = await c.put('/alerts/rules/legacy', json=_body('1W', enabled=True, name='L2'))
        assert r.status_code == 422
        row = await _get(Session, 'legacy')
        assert (row.interval, row.enabled, row.name) == ('1D', False, 'L')
        # (c) stale localStorage '1D' sent back onto a migrated '5m' rule
        assert (await c.put('/alerts/rules/migr', json=_body('1D'))).status_code == 422
        assert (await _get(Session, 'migr')).interval == '5m'
        # (d) OMM -> HMM_intraday on '1D'
        assert (await c.put('/alerts/rules/omm', json=_body('1D'))).status_code == 422
        # (e) standard -> composite HMM_intraday '1D'
        assert (await c.put('/alerts/rules/std', json=_body('1D'))).status_code == 422
        # (f) unparseable stored rule counts as changed
        assert (await c.put('/alerts/rules/junk', json=_body('1D'))).status_code == 422
        # (h) a stored composite with a malformed (string) primary compares as changed
        #     -- a clean 422, not a 500 from reading the stored pair
        assert (await c.put('/alerts/rules/strprim', json=_body('1D'))).status_code == 422
        # (i) a stored NON-composite row that happens to carry an HMM_intraday primary
        #     is not "the same pair" as a composite HMM_intraday on '1D'
        assert (await c.put('/alerts/rules/notype', json=_body('1D'))).status_code == 422
        # (g) intraday -> intraday is fine
        assert (await c.put('/alerts/rules/fine', json=_body('15m'))).status_code == 200
        assert (await _get(Session, 'fine')).interval == '15min'  # W2-INTERVAL: stored in the chart spelling


# ── R4: the migration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_r4_migration_moves_only_dead_composite_hmm_intraday_rules(caplog):
    from app.routers.chart_alerts import migrate_hmm_intraday_rule_intervals
    _, Session = await _make_app()
    long_name = 'N' * 195
    await _seed(Session, 'd1', '1D', _composite(HMM), name='Dead daily',
                condition_state='{"composite": "2026-09-25T10:00:00"}')
    await _seed(Session, 'w1', '1W', _composite(HMM), name=long_name)
    await _seed(Session, 'off', '1D', _composite(HMM), name='Disabled', enabled=False)
    await _seed(Session, 'usr', '1D', _composite(HMM), name='Other user', user_id='other')
    untouched = {
        'ok5': ('5m', _composite(HMM)),
        'omm': ('1D', _composite(OMM)),
        'std': ('1D', {"logic": "AND", "conditions": [
            {"kind": "regime", "model": "HMM_intraday", "state": "Bull"}]}),
        'notype': ('1D', {"primary": {"model": "HMM_intraday"}, "logic": "AND", "conditions": []}),
        'junk': ('1D', 'not json'),
        'list': ('1D', '[]'),
        'strprim': ('1D', {"__type": "composite", "primary": "HMM_intraday"}),
        'daily': ('daily', _composite(HMM)),
    }
    for rid, (iv, rj) in untouched.items():
        await _seed(Session, rid, iv, rj, name=rid)
    before = {rid: (await _get(Session, rid)) for rid in untouched}
    before = {rid: (r.interval, r.name, r.rule_json, r.condition_state, r.enabled) for rid, r in before.items()}

    with caplog.at_level(logging.WARNING, logger='app.routers.chart_alerts'):
        out = await migrate_hmm_intraday_rule_intervals(Session)

    assert sorted(m['id'] for m in out) == ['d1', 'off', 'usr', 'w1']
    d1 = await _get(Session, 'd1')
    assert d1.interval == '5min' and d1.name == 'Dead daily (interval was 1D)'
    assert d1.condition_state == '{}'
    assert d1.enabled is True and json.loads(d1.rule_json) == _composite(HMM)
    w1 = await _get(Session, 'w1')
    assert w1.interval == '5min' and w1.name.endswith(' (interval was 1W)') and len(w1.name) <= 200
    off = await _get(Session, 'off')
    assert off.interval == '5min' and off.enabled is False
    assert (await _get(Session, 'usr')).interval == '5min'
    for rid, snap in before.items():
        r = await _get(Session, rid)
        assert (r.interval, r.name, r.rule_json, r.condition_state, r.enabled) == snap, rid

    warns = [r for r in caplog.records if 'A4f: migrated' in r.getMessage()]
    assert len(warns) == 1
    assert all(i in warns[0].getMessage() for i in ('d1', 'w1', 'off', 'usr'))

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='app.routers.chart_alerts'):
        assert await migrate_hmm_intraday_rule_intervals(Session) == []
    assert not [r for r in caplog.records if 'A4f: migrated' in r.getMessage()]
    assert (await _get(Session, 'd1')).name == 'Dead daily (interval was 1D)'


# ── R5: before/after through the real evaluation path ───────────────────────

@pytest.mark.asyncio
async def test_r5_migrated_rule_reaches_the_hmm_fit(monkeypatch, caplog):
    """Patched side effects: chart_alerts.AsyncSessionLocal (in-memory DB),
    chart_alerts._dispatch (AsyncMock), chart_alerts._load_notification_config ({}),
    regime_hmm.compute_intraday_hmm (recorder, resolved lazily by the evaluator via
    the module attribute). No strategy_confirmations -> no get_bars; no standard rules
    -> no indicator/regime work; '5min' is a Tradier interval -> feed lag read."""
    from unittest.mock import AsyncMock
    import app.routers.chart_alerts as ca
    import app.services.regime_hmm as regime_hmm

    _, Session = await _make_app()
    await _seed(Session, 'dead', '1D', _composite(HMM), name='Dead')
    monkeypatch.setattr(ca, 'AsyncSessionLocal', Session)
    dispatch = AsyncMock()
    monkeypatch.setattr(ca, '_dispatch', dispatch)
    monkeypatch.setattr(ca, '_load_notification_config', lambda: {})
    calls: list[int] = []
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: calls.append(len(bars)) or None)

    as_of = 1_790_000_000.0
    candles = [
        {"time": int(as_of - 300 * (260 - i)), "open": 100 + i * 0.1, "high": 101 + i * 0.1,
         "low": 99 + i * 0.1, "close": 100 + (i % 7) * 0.3 + i * 0.05, "volume": 1000 + i}
        for i in range(250)
    ]

    with caplog.at_level(logging.WARNING):
        await ca.evaluate_and_notify_for_symbol('AAPL', '1D', candles[-2], candles, [], as_of=as_of)
    assert any('no intraday bars supplied' in r.getMessage() for r in caplog.records)
    assert calls == []

    await ca.migrate_hmm_intraday_rule_intervals(Session)

    await ca.evaluate_and_notify_for_symbol('AAPL', '5min', candles[-2], candles, [], as_of=as_of)
    assert calls and calls[0] > 0
    dispatch.assert_not_awaited()  # the recorder returns None -> the primary check fails closed


# ── R6: ordering in the scheduler ────────────────────────────────────────────

class _Stop(Exception):
    pass


def _drive_scheduler(monkeypatch, migrate_side_effects):
    import app.routers.chart_alerts as ca
    import app.services.chart_alert_scheduler as sched
    order: list[str] = []
    effects = list(migrate_side_effects)

    async def migrate(*a, **k):
        order.append('migrate')
        eff = effects.pop(0) if effects else None
        if eff:
            raise eff
        return []

    async def respell(*a, **k):
        order.append('respell')   # W2-INTERVAL: runs after the A4f migration
        return []

    async def tick():
        order.append('tick')

    sleeps = {'n': 0}

    async def sleep(_s):
        sleeps['n'] += 1
        if sleeps['n'] >= 2:
            raise _Stop()

    monkeypatch.setattr(ca, 'migrate_hmm_intraday_rule_intervals', migrate)
    monkeypatch.setattr(ca, 'migrate_rule_interval_spellings', respell)
    monkeypatch.setattr(sched, '_tick', tick)
    monkeypatch.setattr(sched, '_load_check_interval_seconds', lambda: 15)
    # Module-local: only chart_alert_scheduler's `asyncio` name is replaced. Its other
    # use (asyncio.to_thread) lives inside the stubbed _tick.
    monkeypatch.setattr(sched, 'asyncio', types.SimpleNamespace(sleep=sleep))
    return sched, order


@pytest.mark.asyncio
async def test_r6_scheduler_migrates_once_before_the_first_tick(monkeypatch):
    sched, order = _drive_scheduler(monkeypatch, [None])
    with pytest.raises(_Stop):
        await sched.run_chart_alert_scheduler()
    assert order == ['migrate', 'respell', 'tick', 'tick']


@pytest.mark.asyncio
async def test_r6_failed_migration_is_logged_and_retried_until_it_succeeds(monkeypatch, caplog):
    sched, order = _drive_scheduler(monkeypatch, [RuntimeError('db not up')])
    with caplog.at_level(logging.ERROR, logger='app.services.chart_alert_scheduler'):
        with pytest.raises(_Stop):
            await sched.run_chart_alert_scheduler()
    assert order == ['migrate', 'tick', 'migrate', 'respell', 'tick']
    assert any('migration failed' in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_r4b_one_unexpected_row_does_not_block_the_others(monkeypatch, caplog):
    import app.routers.chart_alerts as ca
    _, Session = await _make_app()
    await _seed(Session, 'boom', '1D', {**_composite(HMM), "boom": True}, name='Boom')
    await _seed(Session, 'good', '1D', _composite(HMM), name='Good')
    real = ca._composite_primary_model

    def flaky(parsed):
        if isinstance(parsed, dict) and parsed.get('boom'):
            raise RuntimeError('unexpected shape')
        return real(parsed)

    monkeypatch.setattr(ca, '_composite_primary_model', flaky)
    with caplog.at_level(logging.WARNING, logger='app.routers.chart_alerts'):
        out = await ca.migrate_hmm_intraday_rule_intervals(Session)
    assert [m['id'] for m in out] == ['good']
    assert (await _get(Session, 'good')).interval == '5min'
    boom = await _get(Session, 'boom')
    assert (boom.interval, boom.name) == ('1D', 'Boom')
    assert any('skipping boom' in r.getMessage() for r in caplog.records)
