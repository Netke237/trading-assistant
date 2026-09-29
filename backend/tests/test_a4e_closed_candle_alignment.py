# backend/tests/test_a4e_closed_candle_alignment.py
"""A4e: chart-rule alert decisions read structure computed up to the CLOSED candle.

Plan: docs/superpowers/plans/2026-09-25-a4e-closed-candle-alignment-plan.md.
Indicators need no change (causal, read at closed_candle['time']) and are pinned here.
"""
from __future__ import annotations

import json
import random
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertHistoryModel, AlertRuleModel
from app.services.alert_evaluator import _evaluate_condition
from app.services.indicator_compute import compute_indicators_for_conditions
from app.services.market_structure import compute_structure

_T0 = 1_700_000_000
_SPAN = 900  # 15min


def _bar(i: int, close: float, high: float | None = None) -> dict:
    return {'time': _T0 + _SPAN * i, 'open': 100.0, 'high': high if high is not None else 100.5,
            'low': 99.5, 'close': close, 'volume': 1000}


def _forming_break() -> list[dict]:
    """Flat bars (swing highs at 100.5); only the FORMING bar closes above them."""
    bars = [_bar(i, 100.0) for i in range(30)]
    bars[10] = _bar(10, 100.0, high=105.0)
    bars[-1] = _bar(29, 101.0, high=101.0)
    return bars


def _closed_break() -> list[dict]:
    """Same, but the CLOSED bar (candles[-2]) is the one that breaks."""
    bars = _forming_break()
    bars[-2] = _bar(28, 101.0, high=101.0)
    bars[-1] = _bar(29, 100.0)
    return bars


def _bull_bos(signals: list[dict]) -> list[dict]:
    return [s for s in signals if s.get('kind') == 'BOS' and s.get('direction') == 'bullish']


def _random_series(rng: random.Random, n: int) -> list[dict]:
    p, out = 100.0, []
    for i in range(n):
        o = p
        p = max(1.0, p + rng.gauss(0, 1))
        out.append({'time': _T0 + 300 * i, 'open': o, 'high': max(o, p) + abs(rng.gauss(0, .5)),
                    'low': min(o, p) - abs(rng.gauss(0, .5)), 'close': p, 'volume': rng.randint(0, 9000)})
    return out


# ── T1: indicators are already aligned ───────────────────────────────────────

_INDICATORS = ['ema', 'ema20', 'ema(20)', 'ema9', 'ema(9)', 'ema50', 'ema(50)', 'sma', 'sma20',
               'sma(20)', 'sma50', 'sma(50)', 'rsi', 'rsi(14)', 'macd', 'macd_line', 'macd_signal',
               'atr', 'atr(14)', 'bb_upper', 'bollinger_upper', 'bb_lower', 'bollinger_lower',
               'bb_mid', 'bollinger_mid', 'vwap', 'volume', 'close']


def _outcome(cond, closed, indicators):
    # An exception counts as an outcome: crosses_* on the first post-warm-up bar
    # raises TypeError on main (prev value None) -- pre-existing, logged, not A4e.
    try:
        return _evaluate_condition(cond, closed, indicators, [], closed['time'])
    except TypeError as exc:
        return ('TypeError', str(exc))


def test_t1_forming_bar_cannot_move_an_indicator_reading_at_the_closed_candle():
    rng = random.Random(4)
    checked = 0
    for _ in range(40):
        candles = _random_series(rng, rng.randint(3, 120))
        closed = candles[-2]
        for name in _INDICATORS:
            for op in ('>', '<', 'crosses_above', 'crosses_below'):
                cond = NS(kind='indicator', indicator=name, operator=op, value=closed['close'])
                full = compute_indicators_for_conditions(candles, [cond])
                pre = compute_indicators_for_conditions(candles[:-1], [cond])
                assert (_outcome(cond, closed, full) == _outcome(cond, closed, pre)), (name, op, len(candles))
                checked += 1
    assert checked == 40 * len(_INDICATORS) * 4


# ── T2-T4: the helper ────────────────────────────────────────────────────────

def test_t2_a_break_on_the_forming_bar_is_not_an_alert_signal():
    from app.routers.chart_alerts import closed_candle_structure
    candles = _forming_break()
    full_bos = _bull_bos(compute_structure(candles, '15min', 'AAPL'))
    assert [s['time'] for s in full_bos] == [candles[-1]['time']]  # the defect's precondition
    assert _bull_bos(closed_candle_structure(candles, candles[-2], '15min', 'AAPL')) == []


def test_t2b_a_break_on_the_closed_bar_is_kept():
    from app.routers.chart_alerts import closed_candle_structure
    candles = _closed_break()
    got = _bull_bos(closed_candle_structure(candles, candles[-2], '15min', 'AAPL'))
    assert [s['time'] for s in got] == [candles[-2]['time']]


def test_t3_equals_structure_on_the_candles_through_the_closed_one():
    from app.routers.chart_alerts import closed_candle_structure
    rng = random.Random(7)
    for _ in range(60):
        candles = _random_series(rng, rng.randint(12, 160))
        k = rng.randint(0, len(candles) - 1)
        assert (closed_candle_structure(candles, candles[k], '5m', 'X')
                == compute_structure(candles[:k + 1], '5m', 'X'))


def test_t4_edges():
    from app.routers.chart_alerts import closed_candle_structure
    rng = random.Random(9)
    candles = _random_series(rng, 80)
    assert closed_candle_structure(candles, {'time': -1}, '5m', 'X') == []
    assert closed_candle_structure(candles, candles[-1], '5m', 'X') == compute_structure(candles, '5m', 'X')
    ht = _random_series(rng, 40)
    with patch('app.routers.chart_alerts.compute_structure', return_value=[]) as cs:
        closed_candle_structure(candles, candles[-2], '1h', 'X', ht)
    args = cs.call_args.args
    assert args[0] == candles[:-1] and args[1:] == ('1h', 'X', ht)


# ── T5/T6: the background scheduler, end to end ──────────────────────────────

async def _session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _row(rule_json: dict) -> AlertRuleModel:
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Rule', symbol='AAPL', interval='15min',
        enabled=True, rule_json=json.dumps(rule_json), cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state='{}',
    )


_STANDARD = {'logic': 'AND', 'conditions': [{'kind': 'structure', 'signal_kind': 'BOS', 'direction': 'bullish'}]}
_COMPOSITE = {'__type': 'composite', 'primary': {'model': 'any'}, 'min_confirmations': 1,
              'confirmations': [{'type': 'structure', 'signal_kind': 'BOS', 'direction': 'Bullish'}]}


async def _tick_with(monkeypatch, rule_json: dict, candles: list[dict]) -> int:
    import app.routers.chart_alerts as chart_alerts
    import app.services.chart_alert_scheduler as sched
    Session = await _session_factory()
    async with Session() as db:
        db.add(_row(rule_json))
        await db.commit()
    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, '_load_notification_config', lambda: {})
    monkeypatch.setattr(chart_alerts, '_dispatch', AsyncMock())
    monkeypatch.setattr(sched, 'get_intraday_with_fetched_at',
                        AsyncMock(return_value=(candles, candles[-1]['time'] + 60)))
    sched._last_seen_candle.clear()
    await sched._tick()
    async with Session() as db:
        return len((await db.execute(select(AlertHistoryModel))).scalars().all())


@pytest.mark.asyncio
async def test_t5_standard_structure_rule_ignores_a_forming_bar_break(monkeypatch):
    assert await _tick_with(monkeypatch, _STANDARD, _forming_break()) == 0


@pytest.mark.asyncio
async def test_t5b_standard_structure_rule_fires_on_a_closed_bar_break(monkeypatch):
    assert await _tick_with(monkeypatch, _STANDARD, _closed_break()) == 1


@pytest.mark.asyncio
async def test_t6_composite_confirmation_ignores_a_forming_bar_break(monkeypatch):
    # No bullish BOS anywhere in the closed prefix: the composite has no time filter,
    # so an earlier one would make this pass for the wrong reason.
    candles = _forming_break()
    assert _bull_bos(compute_structure(candles[:-1], '15min', 'AAPL')) == []
    assert await _tick_with(monkeypatch, _COMPOSITE, candles) == 0


@pytest.mark.asyncio
async def test_t6b_composite_confirmation_fires_on_a_closed_bar_break(monkeypatch):
    assert await _tick_with(monkeypatch, _COMPOSITE, _closed_break()) == 1


# ── T7: the chart websocket ──────────────────────────────────────────────────

class _OneTickQueue:
    """Yields one tick with a new timestamp, then ends the stream."""
    def __init__(self, tick_time):
        self._items = [{'timestamp': tick_time}]

    async def get(self):
        from fastapi import WebSocketDisconnect
        if self._items:
            return self._items.pop(0)
        raise WebSocketDisconnect()


def test_t7_ws_displays_full_list_structure_but_evaluates_on_the_closed_prefix():
    from fastapi import WebSocketDisconnect
    from starlette.testclient import TestClient
    from app.main import app

    candles = _forming_break()
    evaluate = AsyncMock(return_value=[])
    with patch('app.routers.chart.get_intraday', AsyncMock(return_value=candles)), \
         patch('app.routers.chart.get_intraday_with_fetched_at', AsyncMock(return_value=(candles, 0.0))), \
         patch('app.routers.chart_alerts.evaluate_and_notify_for_symbol', evaluate), \
         patch('app.routers.chart.get_stream_client') as sc:
        sc.return_value.subscribe = AsyncMock(return_value=_OneTickQueue('new-candle'))
        sc.return_value.unsubscribe = lambda *a: None
        # Drain until the SERVER closes (the queue's second get ends the stream),
        # never a fixed count: the handler awaits `evaluate` only AFTER sending the
        # 4th message, and leaving this block cancels the handler, so a client that
        # stopped at 4 raced that await and failed under CPU load (BACKEND-INTERMITTENT-TEST).
        msgs = []
        with TestClient(app).websocket_connect('/chart/stream/AAPL?interval=15min') as ws:
            while True:
                try:
                    msgs.append(ws.receive_json())
                except WebSocketDisconnect:
                    break
                assert len(msgs) <= 10, f'server never closed the stream: {msgs}'  # fail, never hang
    assert [m['type'] for m in msgs] == ['history', 'structure', 'tick', 'structure']
    full = compute_structure(candles, '15min', 'AAPL')
    assert msgs[3]['signals'] == json.loads(json.dumps(full))  # display: full list
    assert _bull_bos(msgs[3]['signals'])                          # ...forming break shown
    assert evaluate.await_count == 1
    args = evaluate.await_args.args
    assert args[2] == candles[-2] and args[3] == candles
    assert args[4] == compute_structure(candles[:-1], '15min', 'AAPL')  # decision: closed prefix
    assert _bull_bos(args[4]) == []
