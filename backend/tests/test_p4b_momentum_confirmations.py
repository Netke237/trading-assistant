"""P4b T6 (open_questions[61]), rewritten by COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD
(plan test 18): momentum confirmations are computed from the rule's own
candles (momentum_match), never read from a standard rule's indicator series
-- so a series named like a momentum kind neither matches nor raises."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.regime_omm as regime_omm
from app.database import Base
from app.models.alert import AlertRuleModel
from app.services.composite_trigger_evaluator import _matched_confirmations
from tests.parity_harness import parity_no_real_feeds  # noqa: F401  (WATCH-RULE-BAR-PARITY: no real feeds)

_TD = {"confirmations": [{"type": "momentum", "signal_kind": "rsi_cross", "min_confidence": 60}]}


@pytest.mark.parametrize("val", [70, 60.0, float("nan"), True, [{"time": 1, "value": 99}], "99", None])
def test_an_indicator_value_is_never_a_momentum_reading(val):
    """The old matcher compared indicator_values[kind]; whatever is passed where
    that dict used to go, nothing matches and nothing raises."""
    assert _matched_confirmations(_TD, [], None) == []
    assert _matched_confirmations(_TD, [], {"rsi_cross": val}) == []


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
async def test_a_leaked_standard_series_no_longer_fires_the_rule(monkeypatch):
    """P4b T6's closed-candle value of 80 used to clear min_confidence 60 (the
    leak, plan 1.2). It is no longer read at all."""
    c = _candles(closed_value=80, forming_value=1)
    assert await _fire(monkeypatch, c, c[-2]) == []
