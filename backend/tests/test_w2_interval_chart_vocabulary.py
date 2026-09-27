"""W2-INTERVAL (phase INTERVAL-SPELLING-CHART-VOCABULARY; decisions
FOLLOWUPS-QUEUE-2026-09-25 (1), P4B-FOLLOWUPS-2026-09-26 (2)).

Composite rules and watches are stored under the chart's interval spelling
('5min', not '5m'): every write maps it, stored rows/watches migrate once
(reported), and notifications label the interval correctly.
Plan: docs/superpowers/plans/2026-09-27-w2-interval-chart-vocabulary-plan.md
"""
from __future__ import annotations

import json
import logging
import types

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from app.data.market import _CHART_SPELLING, chart_interval
from app.services.strategy_watch_store import StrategyWatchStore
from tests.test_a4f_rules_hmm_intraday_interval import (
    HMM, OMM, _body, _composite, _get, _make_app, _seed,
)

SHORT = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "1h"}


# ── 1a: the map ──────────────────────────────────────────────────────────────

def test_chart_interval_maps_every_short_spelling():
    assert _CHART_SPELLING == SHORT
    for short, chart in SHORT.items():
        assert chart_interval(short) == chart


@pytest.mark.parametrize("iv", ["1h", "4h", "1D", "1W", "5min", "15min", "30min", "1min", "2h", None, 5])
def test_chart_interval_passes_everything_else_through(iv):
    assert chart_interval(iv) == iv


# ── 2a: rule writes ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("sent, stored", [("5m", "5min"), ("15m", "15min"), ("30m", "30min"),
                                          ("1h", "1h"), ("4h", "4h"), ("5min", "5min")])
async def test_post_stores_the_chart_spelling(sent, stored):
    app, Session = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://t') as c:
        r = await c.post('/alerts/rules', json={"id": "p1", **_body(sent)})
    assert r.status_code == 201
    assert r.json()['interval'] == stored
    assert (await _get(Session, 'p1')).interval == stored


@pytest.mark.asyncio
async def test_post_standard_rule_is_mapped_too():
    app, Session = await _make_app()
    body = _body('15m', rule_type='standard')
    body['group'] = {"logic": "AND", "conditions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://t') as c:
        assert (await c.post('/alerts/rules', json={"id": "s1", **body})).status_code == 201
    assert (await _get(Session, 's1')).interval == '15min'


@pytest.mark.asyncio
async def test_post_hmm_intraday_on_daily_is_still_refused():
    app, _ = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://t') as c:
        r = await c.post('/alerts/rules', json=_body('1D'))
    assert r.status_code == 422
    assert 'e.g. 5min, 15min, 1h' in r.json()['detail']


@pytest.mark.asyncio
async def test_put_stale_short_spelling_onto_migrated_rule_is_accepted_and_mapped():
    app, Session = await _make_app()
    await _seed(Session, 'm', '15min', _composite(HMM))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://t') as c:
        r = await c.put('/alerts/rules/m', json=_body('15m', name='renamed'))
    assert r.status_code == 200
    row = await _get(Session, 'm')
    assert row.interval == '15min' and row.name == 'renamed'


@pytest.mark.asyncio
async def test_put_legacy_pair_comparison_uses_the_chart_spelling():
    """A legacy HMM_intraday rule on '1D' may be re-PUT unchanged; a '1D' body
    onto a '5min' row is a changed pair and still refused."""
    app, Session = await _make_app()
    await _seed(Session, 'legacy', '1D', _composite(HMM))
    await _seed(Session, 'migr', '5min', _composite(HMM))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://t') as c:
        assert (await c.put('/alerts/rules/legacy', json=_body('1D'))).status_code == 200
        assert (await c.put('/alerts/rules/migr', json=_body('1D'))).status_code == 422
    assert (await _get(Session, 'migr')).interval == '5min'


# ── 3a: stored rules migrate once ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rule_migration_moves_every_short_spelling_and_nothing_else(caplog):
    import app.routers.chart_alerts as ca
    _, Session = await _make_app()
    state = json.dumps({"composite": {"pending_since": "2026-09-26T10:00:00"}})
    for short in SHORT:
        await _seed(Session, f'r{short}', short, _composite(HMM), name=f'N{short}',
                    enabled=(short != '30m'), user_id=('other' if short == '1m' else 'default'),
                    condition_state=state)
    std = {"logic": "AND", "conditions": [{"kind": "price", "op": ">", "value": 1}]}
    await _seed(Session, 'std5', '5m', std, name='Std')
    for keep in ('5min', '15min', '1h', '4h', '1D', '1W'):
        await _seed(Session, f'k{keep}', keep, _composite(OMM), name=f'K{keep}')
    before = {rid: (await _get(Session, rid)) for rid in [f'r{s}' for s in SHORT] + ['std5']}
    snap = {rid: (r.name, r.enabled, r.rule_json, r.condition_state, r.user_id, r.symbol)
            for rid, r in before.items()}

    with caplog.at_level(logging.WARNING, logger='app.routers.chart_alerts'):
        out = await ca.migrate_rule_interval_spellings(Session)

    assert sorted(m['id'] for m in out) == sorted(snap)
    for short, chart in SHORT.items():
        row = await _get(Session, f'r{short}')
        assert row.interval == chart
        assert (row.name, row.enabled, row.rule_json, row.condition_state, row.user_id, row.symbol) \
            == snap[f'r{short}']
    assert (await _get(Session, 'std5')).interval == '5min'
    for keep in ('5min', '15min', '1h', '4h', '1D', '1W'):
        assert (await _get(Session, f'k{keep}')).interval == keep
    warns = [r for r in caplog.records if 'W2-INTERVAL' in r.getMessage()]
    assert len(warns) == 1 and warns[0].levelno == logging.WARNING
    assert "r5m AAPL '5m'->'5min'" in warns[0].getMessage()

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='app.routers.chart_alerts'):
        assert await ca.migrate_rule_interval_spellings(Session) == []
    assert not [r for r in caplog.records if 'W2-INTERVAL' in r.getMessage()]


@pytest.mark.asyncio
async def test_a4f_then_respell_leaves_every_rule_on_the_chart_spelling():
    import app.routers.chart_alerts as ca
    _, Session = await _make_app()
    await _seed(Session, 'dead', '1D', _composite(HMM), name='Dead')
    await _seed(Session, 'short', '15m', _composite(HMM))
    await ca.migrate_hmm_intraday_rule_intervals(Session)
    await ca.migrate_rule_interval_spellings(Session)
    assert (await _get(Session, 'dead')).interval == '5min'
    assert (await _get(Session, 'short')).interval == '15min'


@pytest.mark.asyncio
async def test_scheduler_retries_both_migrations_when_the_respell_fails(monkeypatch):
    import app.routers.chart_alerts as ca
    import app.services.chart_alert_scheduler as sched

    class _Stop(Exception):
        pass

    order: list[str] = []
    fails = [RuntimeError('db not up')]

    async def a4f(*a, **k):
        order.append('a4f')
        return []

    async def respell(*a, **k):
        order.append('respell')
        if fails:
            raise fails.pop()
        return []

    async def tick():
        order.append('tick')

    n = {'s': 0}

    async def sleep(_s):
        n['s'] += 1
        if n['s'] >= 3:
            raise _Stop()

    monkeypatch.setattr(ca, 'migrate_hmm_intraday_rule_intervals', a4f)
    monkeypatch.setattr(ca, 'migrate_rule_interval_spellings', respell)
    monkeypatch.setattr(sched, '_tick', tick)
    monkeypatch.setattr(sched, '_load_check_interval_seconds', lambda: 15)
    monkeypatch.setattr(sched, 'asyncio', types.SimpleNamespace(sleep=sleep))
    with pytest.raises(_Stop):
        await sched.run_chart_alert_scheduler()
    assert order == ['a4f', 'respell', 'tick', 'a4f', 'respell', 'tick', 'tick']


# ── 2b / 3b: watches ─────────────────────────────────────────────────────────

def _watch(wid, interval, *, model="HMM_intraday", **extra):
    w = {"id": wid, "watch_type": "composite", "symbol": "AAPL", "direction": "Bullish",
         "interval": interval, "trigger_def": {"primary": {"model": model}}, "enabled": True,
         "created_at": "2026-09-01T00:00:00+00:00",
         "last_state": {"phase": "armed", "last_event": "entry", "entry_price": 101.5}}
    w.update(extra)
    return w


def _write(path, watches):
    path.write_text(yaml.dump({"schedule": {"enabled": True, "mode": "eod"}, "watches": watches},
                              sort_keys=False))


def test_add_composite_watch_stores_the_chart_spelling(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    for short, chart in SHORT.items():
        assert store.add_composite_watch("AAPL", {"primary": {"model": "HMM_intraday"}},
                                         interval=short)["interval"] == chart
    assert store.add_composite_watch("AAPL", {"primary": {"model": "OMM"}})["interval"] == "1D"


def test_load_migrates_short_spellings_persists_and_reports(tmp_path, caplog):
    path = tmp_path / "w.yaml"
    _write(path, [
        _watch("c5", "5m"), _watch("c15", "15m", model="OMM"),
        _watch("cA", "5m", interval_migrated_from="1D"),
        _watch("k1h", "1h"), _watch("k1d", "1D", model="OMM"), _watch("k5", "5min"),
    ])
    with caplog.at_level(logging.WARNING, logger="app.services.strategy_watch_store"):
        store = StrategyWatchStore(path=path)
    by_id = {w["id"]: w for w in store.list_watches()}
    assert {k: by_id[k]["interval"] for k in by_id} == {
        "c5": "5min", "c15": "15min", "cA": "5min", "k1h": "1h", "k1d": "1D", "k5": "5min"}
    assert by_id["cA"]["interval_migrated_from"] == "1D"
    assert "interval_migrated_from" not in by_id["c5"]
    assert by_id["c5"]["last_state"] == {"phase": "armed", "last_event": "entry", "entry_price": 101.5}
    on_disk = {w["id"]: w for w in yaml.safe_load(path.read_text())["watches"]}
    assert on_disk["c5"]["interval"] == "5min" and on_disk["c15"]["interval"] == "15min"
    assert yaml.safe_load(path.read_text())["schedule"]["mode"] == "eod"
    warns = [r for r in caplog.records if "W2-INTERVAL" in r.getMessage()]
    assert len(warns) == 1
    assert "c5 AAPL '5m'->'5min'" in warns[0].getMessage()
    assert "k1h" not in warns[0].getMessage()

    before = path.read_text()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.services.strategy_watch_store"):
        StrategyWatchStore(path=path)
    assert path.read_text() == before
    assert not [r for r in caplog.records if "W2-INTERVAL" in r.getMessage()]


def test_load_save_failure_keeps_the_migration_in_memory(tmp_path, monkeypatch, caplog):
    path = tmp_path / "w.yaml"
    _write(path, [_watch("c5", "5m")])

    def boom(self):
        raise OSError("read-only")

    monkeypatch.setattr(StrategyWatchStore, "save", boom)
    with caplog.at_level(logging.ERROR, logger="app.services.strategy_watch_store"):
        store = StrategyWatchStore(path=path)
    assert store.list_watches()[0]["interval"] == "5min"
    assert any("could not persist" in r.getMessage() for r in caplog.records)


# ── 5: labels ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("iv, label", [
    ("5m", "5-minute chart"), ("5min", "5-minute chart"), ("15m", "15-minute chart"),
    ("30min", "30-minute chart"), ("30m", "30-minute chart"), ("60m", "Hourly chart"),
    ("1D", "Daily chart"), ("2h", "2h chart"),
])
def test_interval_label(iv, label):
    from app.routers.chart_alerts import _interval_label
    assert _interval_label(iv) == label
