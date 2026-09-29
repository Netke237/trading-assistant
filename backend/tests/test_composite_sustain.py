# backend/tests/test_composite_sustain.py
"""sustain_minutes on composite trigger_defs — both the AlertRuleModel/WS path
(chart_alerts.evaluate_and_notify_for_symbol) and the strategy-watch path
(strategy_watch_evaluator.evaluate_all's composite-watches loop)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401
from tests.parity_harness import parity_no_real_feeds  # noqa: F401  (WATCH-RULE-BAR-PARITY: no real feeds)


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _composite_rule_row(condition_state: str = '{}') -> AlertRuleModel:
    trigger_def = {
        "primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0,
        "sustain_minutes": 5, "__type": "composite",
    }
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Composite', symbol='AAPL', interval='15min',
        enabled=True, rule_json=json.dumps(trigger_def), cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state=condition_state,
    )


_FLAT_CANDLES = [
    {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
    for i in range(120)
]


# The WS composite path imports `evaluate_from_context_detailed` and
# `format_composite_reason` from composite_trigger_evaluator INSIDE
# evaluate_and_notify_for_symbol at call time, so patch them on that module.
# evaluate_from_context_detailed returns a (fired, detail) tuple.
_DETAIL = {'structure_matched': [], 'structure_total': 0, 'strategy_matched': [], 'strategy_total': 0}


@pytest.mark.asyncio
async def test_ws_composite_path_delays_fire_until_sustained(monkeypatch):
    from app.routers import chart_alerts
    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(
        'app.services.composite_trigger_evaluator.evaluate_from_context_detailed',
        lambda *a, **kw: (True, _DETAIL),
    )

    async with Session() as db:
        db.add(_composite_rule_row())
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert triggered == []

    async with Session() as db:
        from sqlalchemy import select
        row = (await db.execute(select(AlertRuleModel).where(AlertRuleModel.id == 'rule-1'))).scalar_one()
        assert 'composite' in json.loads(row.condition_state)


@pytest.mark.asyncio
async def test_ws_composite_path_fires_once_sustained(monkeypatch):
    from app.routers import chart_alerts
    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(
        'app.services.composite_trigger_evaluator.evaluate_from_context_detailed',
        lambda *a, **kw: (True, _DETAIL),
    )

    past = (datetime.now() - timedelta(minutes=6)).isoformat()
    async with Session() as db:
        db.add(_composite_rule_row(condition_state=json.dumps({'composite': past})))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1


@pytest.mark.asyncio
async def test_strategy_watch_composite_delays_fire_until_sustained():
    from app.services.strategy_watch_evaluator import evaluate_all

    def _bars(close: float, n: int = 260) -> list[dict]:
        return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                 "open": close, "high": close + 1, "low": close - 1,
                 "close": close, "volume": 1_000_000} for i in range(n)]

    watch = {
        "id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
        "strategy_key": "composite", "direction": "Bullish", "enabled": True,
        "trigger_def": {"primary": {"model": "any"}, "sustain_minutes": 5},
        "last_state": {},
    }
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=True):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_called_once()
    assert "pending_entry_since" in store.update_state.call_args[0][1]


@pytest.mark.asyncio
async def test_strategy_watch_composite_fires_once_sustained():
    from app.services.strategy_watch_evaluator import evaluate_all

    def _bars(close: float, n: int = 260) -> list[dict]:
        return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                 "open": close, "high": close + 1, "low": close - 1,
                 "close": close, "volume": 1_000_000} for i in range(n)]

    past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    watch = {
        "id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
        "strategy_key": "composite", "direction": "Bullish", "enabled": True,
        "trigger_def": {"primary": {"model": "any"}, "sustain_minutes": 5},
        "last_state": {"pending_entry_since": past},
    }
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=True), \
         patch("app.services.composite_trigger_evaluator.describe_match",
               return_value={"structure_matched": [], "strategy_matched": []}):
        events = await evaluate_all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_ws_composite_path_corrupted_state_does_not_fire(monkeypatch):
    """A corrupted condition_state must suppress the fire, not bypass sustain
    and fire immediately — regression test for the except-block fail-open bug."""
    from app.routers import chart_alerts
    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(
        'app.services.composite_trigger_evaluator.evaluate_from_context_detailed',
        lambda *a, **kw: (True, _DETAIL),
    )

    async with Session() as db:
        db.add(_composite_rule_row(condition_state='not-valid-json{{{'))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert triggered == []


@pytest.mark.asyncio
async def test_strategy_watch_composite_corrupted_pending_since_does_not_fire():
    """A corrupted pending_entry_since must suppress the fire, not bypass
    sustain and fire immediately — regression test for the except-block
    fail-open bug."""
    from app.services.strategy_watch_evaluator import evaluate_all

    def _bars(close: float, n: int = 260) -> list[dict]:
        return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
                 "open": close, "high": close + 1, "low": close - 1,
                 "close": close, "volume": 1_000_000} for i in range(n)]

    watch = {
        "id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
        "strategy_key": "composite", "direction": "Bullish", "enabled": True,
        "trigger_def": {"primary": {"model": "any"}, "sustain_minutes": 5},
        "last_state": {"pending_entry_since": "not-a-valid-timestamp"},
    }
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=True):
        events = await evaluate_all()
    assert events == []
