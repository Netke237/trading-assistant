"""Admission refusal releases durable risk; ambiguous POST failure retains it."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import select

from app.data import governor, tradier_paper
from app.models.daily_risk import DailyRiskAttempt
from app.services import auto_trader as at, broker_router, daily_risk_hooks
from tests.test_daily_risk_integration import rig, amounts


def route_adapter(monkeypatch, refused):
    gov = governor.build_default_governor()
    if refused:
        # Exhaust the actual production paper bucket, then require immediate
        # admission: same refusal boundary as a queued caller's expired budget.
        for _ in range(5):
            assert gov.admit_sync('tradier_paper', admit_timeout=0)
    monkeypatch.setattr(governor, 'get_governor', lambda: gov)
    adapter = tradier_paper.TradierPaperAdapter('test-token', 'test-account', timeout=0)
    router = SimpleNamespace(resolve=lambda key: adapter)
    monkeypatch.setattr(at, '_market_is_open', lambda *args: True)
    monkeypatch.setattr(at, '_apply_vol_sizing', lambda strategy: strategy)
    monkeypatch.setattr(at, '_apply_event_veto', lambda strategy: None)
    monkeypatch.setattr(broker_router, 'build_router_from_credentials', lambda: router)
    post = MagicMock(side_effect=httpx.ReadTimeout('reply lost after POST'))
    monkeypatch.setattr(tradier_paper.httpx, 'post', post)
    return router, post


@pytest.mark.asyncio
@pytest.mark.parametrize('refused', [True, False])
async def test_manual_tradier_admission_risk_persists_correctly(rig, monkeypatch, refused):
    from app.routers import broker
    rig.cfg['auto_trade']['max_daily_loss_pct'] = .001  # $100 allowance
    router, post = route_adapter(monkeypatch, refused)
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: router)
    payload = dict(broker='tradier_paper', symbol='AAPL', option_symbol='AAPL261218C00185000',
                   action='BUY', effect='OPEN', quantity=1, order_type='LMT', limit_price=.6, tif='DAY')
    assert (await rig.client.post('/broker/option-order', json=payload)).status_code == 502
    assert post.call_count == (0 if refused else 1)
    assert await amounts(rig) == (0 if refused else 6000, 0)
    async with rig.sessions() as db:
        attempt = (await db.execute(select(DailyRiskAttempt))).scalar_one()
        assert attempt.state == ('released' if refused else 'retained')
    # A distinct $60 opening fits only after the provably unsent first one.
    payload.update(symbol='MSFT', option_symbol='MSFT261218C00185000')
    assert (await rig.client.post('/broker/option-order', json=payload)).status_code == (502 if refused else 422)


@pytest.mark.asyncio
@pytest.mark.parametrize('refused', [True, False])
async def test_auto_tradier_admission_history_and_durable_risk(rig, monkeypatch, refused):
    rig.cfg['auto_trade']['max_daily_loss_pct'] = .001
    _, post = route_adapter(monkeypatch, refused)
    svc = at.AutoTradeService()
    svc.arm(at.ArmedStrategy(broker='tradier_paper', symbol='AAPL', option_symbol='AAPL261218C00185000',
                            action='BUY', direction='Bullish', quantity=1, order_type='LMT',
                            limit_price=.6, conid=None, entry_premium=.6))
    with pytest.raises(RuntimeError):
        await asyncio.to_thread(svc.fire, daily_risk_hooks=daily_risk_hooks.capture_daily_risk_hooks())
    row = svc.get_state().history[-1]
    assert row['status'] == ('not_submitted' if refused else 'order_failed')
    assert row['premium_at_risk'] == (0 if refused else 60)
    if refused:
        assert row['broker_contacted'] is False
    assert post.call_count == (0 if refused else 1)
    assert await amounts(rig) == (0 if refused else 6000, 0)
    async with rig.sessions() as db:
        attempt = (await db.execute(select(DailyRiskAttempt))).scalar_one()
        assert attempt.state == ('released' if refused else 'retained')
