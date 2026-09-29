"""P4b T6 (open_questions[61]): composite momentum confirmations compare a
number -- the closed candle's value -- and never raise on a series."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.regime_omm as regime_omm
from app.database import Base
from app.models.alert import AlertRuleModel
from app.services.composite_trigger_evaluator import _matched_confirmations, indicator_values_at
from tests.parity_harness import parity_no_real_feeds  # noqa: F401  (WATCH-RULE-BAR-PARITY: no real feeds)

_TD = {"confirmations": [{"type": "momentum", "signal_kind": "rsi_cross", "min_confidence": 60}]}


def test_indicator_values_at_reads_the_point_at_t():
    series = {"rsi_cross": [{"time": 1, "value": 10}, {"time": 2, "value": 70}, {"time": 3, "value": 5}],
              "gap": [{"time": 1, "value": 1}], "none_at_t": [{"time": 2, "value": None}], "bad": 7}
    assert indicator_values_at(series, 2) == {"rsi_cross": 70}
    assert indicator_values_at({}, 2) == {}


@pytest.mark.parametrize("val, matched", [
    (70, True), (60.0, True), (59.9, False), (float("nan"), False), (float("inf"), False),
    (True, False), ([{"time": 1, "value": 99}], False), ("99", False), (None, False),
])
def test_momentum_matches_only_a_real_number(val, matched):
    assert (_matched_confirmations(_TD, [], {"rsi_cross": val}) == ["rsi_cross"]) is matched


async def _fire(monkeypatch, candles, closed):
    from app.routers import chart_alerts
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(chart_alerts, "AsyncSessionLocal", Session)
    monkeypatch.setattr(chart_alerts, "get_bars", AsyncMock(return_value=[]))
    monkeypatch.setattr(regime_omm, "compute_omm", lambda *a, **kw: None)
    # the indicator series a standard rule on the same symbol/interval computed
    monkeypatch.setattr(chart_alerts, "compute_indicators_for_conditions", lambda c, conds: {
        "rsi_cross": [{"time": c_["time"], "value": c_["close"]} for c_ in c]})
    td = {"primary": {"model": "any"}, "min_confirmations": 1, "direction": "Bullish", **_TD}
    async with Session() as db:
        db.add(AlertRuleModel(
            id="r1", user_id="default", name="C", symbol="AAPL", interval="1h", enabled=True,
            rule_json=json.dumps({**td, "__type": "composite"}), cooldown_minutes=0,
            expiry_date=None, created_at="2024-01-01T00:00:00Z", last_triggered_at=None))
        await db.commit()
    return await chart_alerts.evaluate_and_notify_for_symbol("AAPL", "1h", closed, candles, [])


def _candles(closed_value, forming_value):
    base = [{"time": 1000 + i, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(5)]
    base[-2] = {**base[-2], "close": closed_value}
    base[-1] = {**base[-1], "close": forming_value}
    return base


@pytest.mark.asyncio
async def test_rule_path_reads_the_closed_candle_value(monkeypatch):
    c = _candles(closed_value=80, forming_value=1)
    assert len(await _fire(monkeypatch, c, c[-2])) == 1


@pytest.mark.asyncio
async def test_rule_path_ignores_the_forming_value(monkeypatch):
    c = _candles(closed_value=1, forming_value=80)
    assert await _fire(monkeypatch, c, c[-2]) == []


def test_a_bool_never_counts_as_a_momentum_reading():
    """True == 1 would clear a minimum of 1 without the bool guard (code round 1, finding 2)."""
    td = {"confirmations": [{"type": "momentum", "signal_kind": "rsi_cross", "min_confidence": 1}]}
    assert _matched_confirmations(td, [], {"rsi_cross": True}) == []
    assert _matched_confirmations(td, [], {"rsi_cross": 1}) == ["rsi_cross"]
