# backend/tests/test_chart_ws_1d_1w_rules.py
"""CHART-WS-1D-1W-RULES: the chart WS evaluates 1D/1W rules with the stored
spelling, and a closed daily/weekly bar is judged once across the chart WS and
the background scheduler (one shared claim). Plan:
docs/superpowers/plans/2026-09-27-chart-ws-1d-1w-rules-plan.md."""
from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.chart_alert_scheduler as sched
from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

DAY = 86400
CANDLES = [
    {'time': 1_700_000_000 + i * DAY, 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 103.0, 'volume': 1000}
    for i in range(6)
]
NEXT_BAR = {'time': CANDLES[-1]['time'] + DAY, 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 103.0, 'volume': 1000}
TIMEOUT = object()   # queue item: the 30 s wait times out (a ping)


@pytest.fixture(autouse=True)
def _clear_markers():
    sched._last_seen_candle.clear()
    sched._last_newest_bar.clear()
    yield
    sched._last_seen_candle.clear()
    sched._last_newest_bar.clear()


class _Queue:
    """Yields ticks (dicts) or a timeout, then ends the stream."""
    def __init__(self, *items):
        self._items = list(items)

    async def get(self):
        if not self._items:
            raise WebSocketDisconnect()
        item = self._items.pop(0)
        if item is TIMEOUT:
            raise asyncio.TimeoutError()
        return item


def _run_ws(interval, queue, evaluate, *, has_rule=True, candles=CANDLES):
    """Open the chart WS, drain it, return (messages, has_enabled_rule mock)."""
    from starlette.testclient import TestClient
    from app.main import app

    has_rule_mock = AsyncMock(return_value=has_rule)
    msgs = []
    with patch('app.routers.chart.get_intraday', AsyncMock(return_value=candles)), \
         patch('app.routers.chart.get_intraday_with_fetched_at', AsyncMock(return_value=(candles, 0.0))), \
         patch('app.routers.chart.compute_structure', lambda *a, **kw: []), \
         patch('app.routers.chart_alerts.closed_candle_structure', lambda *a, **kw: []), \
         patch('app.routers.chart_alerts.evaluate_and_notify_for_symbol', evaluate), \
         patch.object(sched, 'has_enabled_rule', has_rule_mock), \
         patch('app.routers.chart.get_stream_client') as sc:
        sc.return_value.subscribe = AsyncMock(return_value=queue)
        sc.return_value.unsubscribe = lambda *a: None
        with TestClient(app).websocket_connect(f'/chart/stream/AAPL?interval={interval}') as ws:
            while True:
                try:
                    msgs.append(ws.receive_json())
                except WebSocketDisconnect:
                    break
    return msgs, has_rule_mock


def _tick(t='2024-01-02T10:00:00'):
    return {'symbol': 'AAPL', 'price': 103.0, 'volume': 1, 'timestamp': t}


# ── T1: the stored spelling ──────────────────────────────────────────────────

@pytest.mark.parametrize('ws_iv, rule_iv', [('daily', '1D'), ('weekly', '1W')])
def test_t1_ws_evaluates_with_the_stored_spelling(ws_iv, rule_iv):
    evaluate = AsyncMock(return_value=[])
    _, has_rule = _run_ws(ws_iv, _Queue(_tick()), evaluate)
    assert evaluate.await_count == 1
    args = evaluate.await_args.args
    assert args[0] == 'AAPL' and args[1] == rule_iv
    assert args[2] == CANDLES[-2] and args[3] == CANDLES
    has_rule.assert_awaited_with('AAPL', rule_iv)


# ── T2: the tick's time is irrelevant ────────────────────────────────────────

def test_t2_empty_tick_timestamp_still_evaluates():
    evaluate = AsyncMock(return_value=[])
    _run_ws('daily', _Queue(_tick('')), evaluate)
    assert evaluate.await_count == 1


def test_t2_no_tick_at_all_a_ping_still_evaluates():
    evaluate = AsyncMock(return_value=[])
    msgs, _ = _run_ws('daily', _Queue(TIMEOUT), evaluate)
    assert 'ping' in [m['type'] for m in msgs]
    assert evaluate.await_count == 1


# ── T3: once per bar however many ticks ──────────────────────────────────────

def test_t3_many_ticks_judge_the_bar_once(monkeypatch):
    monkeypatch.setattr('app.routers.chart._DAILY_ALERT_CHECK_SECONDS', 0)
    evaluate = AsyncMock(return_value=[])
    _, has_rule = _run_ws('daily', _Queue(_tick('a'), _tick('b'), _tick('c')), evaluate)
    assert has_rule.await_count == 3          # the check ran on every tick...
    assert evaluate.await_count == 1          # ...but the bar was judged once
    assert sched._last_seen_candle[('AAPL', '1D')] == CANDLES[-2]['time']


def test_t3_check_is_throttled():
    evaluate = AsyncMock(return_value=[])
    _, has_rule = _run_ws('daily', _Queue(_tick('a'), _tick('b'), TIMEOUT), evaluate)
    assert has_rule.await_count == 1          # 60 s cadence: one check in this burst


# ── T4: once per bar across the WS and the scheduler ─────────────────────────

async def _session_with_rule(interval='1D'):
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as db:
        db.add(AlertRuleModel(
            id='rule-1', user_id='default', name='Rule', symbol='AAPL', interval=interval, enabled=True,
            rule_json=json.dumps({'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]}),
            cooldown_minutes=0, expiry_date=None, created_at='2024-01-01T00:00:00Z',
            last_triggered_at=None, condition_state='{}',
        ))
        await db.commit()
    return Session


def _scheduler_tick(monkeypatch, evaluate, candles):
    async def run():
        monkeypatch.setattr(sched, 'AsyncSessionLocal', await _session_with_rule())
        monkeypatch.setattr(sched, 'get_intraday_with_fetched_at', AsyncMock(return_value=(candles, 0.0)))
        monkeypatch.setattr('app.routers.chart_alerts.closed_candle_structure', lambda *a, **kw: [])
        monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', evaluate)
        await sched._tick()
    asyncio.run(run())


def test_t4_ws_first_then_scheduler_does_not_rejudge(monkeypatch):
    evaluate = AsyncMock(return_value=[])
    _run_ws('daily', _Queue(_tick()), evaluate)
    _scheduler_tick(monkeypatch, evaluate, CANDLES)
    assert evaluate.await_count == 1
    # A new daily bar: judged exactly once more, by the scheduler here.
    _scheduler_tick(monkeypatch, evaluate, CANDLES + [NEXT_BAR])
    assert evaluate.await_count == 2
    assert evaluate.await_args.args[2] == CANDLES[-1]
    _run_ws('daily', _Queue(_tick()), evaluate, candles=CANDLES + [NEXT_BAR])
    assert evaluate.await_count == 2


def test_t4_scheduler_first_then_ws_does_not_rejudge(monkeypatch):
    evaluate = AsyncMock(return_value=[])
    _scheduler_tick(monkeypatch, evaluate, CANDLES)
    assert evaluate.await_count == 1 and evaluate.await_args.args[1] == '1D'
    _run_ws('daily', _Queue(_tick()), evaluate)
    assert evaluate.await_count == 1
    # A new daily bar: judged once, by the WS here.
    _run_ws('daily', _Queue(_tick()), evaluate, candles=CANDLES + [NEXT_BAR])
    assert evaluate.await_count == 2
    _scheduler_tick(monkeypatch, evaluate, CANDLES + [NEXT_BAR])
    assert evaluate.await_count == 2


# ── T5: a WS fire reaches the chart ──────────────────────────────────────────

def test_t5_ws_fire_is_pushed_to_the_chart():
    entry = {'id': 'h1', 'rule_id': 'rule-1', 'symbol': 'AAPL', 'interval': '1D', 'reason': 'x'}
    msgs, _ = _run_ws('daily', _Queue(_tick()), AsyncMock(return_value=[entry]))
    assert {'type': 'alert_triggered', 'entry': entry} in msgs


# ── T6: intraday unchanged ───────────────────────────────────────────────────

def test_t6_intraday_keeps_the_tick_path_and_claims_nothing():
    evaluate = AsyncMock(return_value=[])
    _, has_rule = _run_ws('15min', _Queue(_tick('new-candle')), evaluate)
    assert evaluate.await_count == 1
    assert evaluate.await_args.args[1] == '15min'
    has_rule.assert_not_awaited()
    assert ('AAPL', '15min') not in sched._last_seen_candle


# ── T7: the claim precedes any evaluation ────────────────────────────────────

def test_t7_claim_moves_the_marker_to_the_newest_before_evaluating():
    key = ('AAPL', '1D')
    sched._last_seen_candle[key] = CANDLES[-4]['time']
    idxs = sched._claim_candles_to_evaluate(key, CANDLES)
    assert idxs == [len(CANDLES) - 3, len(CANDLES) - 2]
    assert sched._last_seen_candle[key] == CANDLES[-2]['time']
    assert sched._claim_candles_to_evaluate(key, CANDLES) == []


@pytest.mark.asyncio
async def test_t7_marker_is_newest_while_the_older_candle_is_evaluated(monkeypatch):
    key = ('AAPL', '1D')
    sched._last_seen_candle[key] = CANDLES[-4]['time']
    seen = []

    async def evaluate(symbol, interval, closed, view, signals, as_of=None):
        seen.append((closed['time'], sched._last_seen_candle[key]))
        return []

    monkeypatch.setattr('app.routers.chart_alerts.closed_candle_structure', lambda *a, **kw: [])
    monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', evaluate)
    await sched.evaluate_closed_candles('AAPL', '1D', CANDLES, 0.0)
    assert seen == [(CANDLES[-3]['time'], CANDLES[-2]['time']), (CANDLES[-2]['time'], CANDLES[-2]['time'])]


# ── T9: a failure does not close the stream ──────────────────────────────────

def test_t9_evaluation_failure_is_logged_and_the_stream_continues(caplog):
    evaluate = AsyncMock(side_effect=RuntimeError('boom'))
    with caplog.at_level(logging.WARNING):
        msgs, _ = _run_ws('daily', _Queue(_tick(), TIMEOUT), evaluate)
    assert [m['type'] for m in msgs][-1] == 'ping'      # still streaming after the failure
    assert 'chart alert background check failed' in caplog.text
    assert sched._last_seen_candle[('AAPL', '1D')] == CANDLES[-2]['time']   # claimed, not retried


# ── T10: no claim without an enabled rule ────────────────────────────────────

def test_t10_no_rule_no_claim_so_a_new_rule_gets_its_first_sighting(monkeypatch):
    evaluate = AsyncMock(return_value=[])
    _run_ws('daily', _Queue(_tick()), evaluate, has_rule=False)
    evaluate.assert_not_awaited()
    assert ('AAPL', '1D') not in sched._last_seen_candle
    _scheduler_tick(monkeypatch, evaluate, CANDLES)      # the rule now exists
    assert evaluate.await_count == 1
    assert evaluate.await_args.args[2] == CANDLES[-2]


@pytest.mark.asyncio
async def test_t10_has_enabled_rule_matches_the_schedulers_filter(monkeypatch):
    Session = await _session_with_rule('1D')
    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    assert await sched.has_enabled_rule('AAPL', '1D') is True
    assert await sched.has_enabled_rule('AAPL', 'daily') is False
    assert await sched.has_enabled_rule('MSFT', '1D') is False
    async with Session() as db:
        row = await db.get(AlertRuleModel, 'rule-1')
        row.enabled = False
        await db.commit()
    assert await sched.has_enabled_rule('AAPL', '1D') is False
