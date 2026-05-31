"""Tests for portfolio_alert_monitor: fire-once suppress and enabledType filtering."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import AlertItem


def _make_alert(alert_type: str, rec_id: str = 'pos1') -> AlertItem:
    return AlertItem(
        id=f'{rec_id}-{alert_type}',
        kind='Action',
        symbol='AAPL',
        reason=f'{alert_type} triggered',
        timestamp=datetime.now(timezone.utc).isoformat(),
        recId=rec_id,
        alertType=alert_type,
    )


def _fake_db_with_positions(rec_ids: list[str], symbol: str = 'AAPL'):
    """Return a context-manager mock whose positions list has the given recIds."""
    positions = []
    for rec_id in rec_ids:
        p = MagicMock()
        p.symbol = symbol
        p.rec_id = rec_id
        positions.append(p)

    fake_db = AsyncMock()
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=False)
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = positions
    fake_db.execute = AsyncMock(return_value=fake_result)
    return fake_db


def _reset_monitor_state():
    from app.services import portfolio_alert_monitor as mon
    mon._fired_once.clear()
    mon._known_rec_ids.clear()
    mon._last_regime = None


@pytest.mark.asyncio
async def test_disabled_type_is_not_dispatched():
    """An alert whose type is not in enabledTypes must not call notify_enabled_channels."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()

    delivery_cfg = {
        'masterEnabled': True,
        'enabledTypes': ['TP_HIT'],  # STOP_REACHED excluded
    }

    fake_db = _fake_db_with_positions(['pos1'])

    with (
        patch.object(mon, '_load_delivery_config', return_value=delivery_cfg),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[
            _make_alert('STOP_REACHED'),
        ])),
        patch.object(mon, 'notify_enabled_channels') as mock_notify,
        patch.object(mon, 'compute_overall_regime', return_value='PASS'),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch('app.services.portfolio_alert_monitor.asyncio.to_thread',
              new=AsyncMock(return_value={'AAPL': {'last': 150.0}})),
    ):
        await mon._run_once()

    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_type_is_dispatched():
    """An alert whose type is in enabledTypes fires notify_enabled_channels on first trigger."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()

    delivery_cfg = {'masterEnabled': True, 'enabledTypes': ['TP_HIT']}

    fake_db = _fake_db_with_positions(['pos1'])

    with (
        patch.object(mon, '_load_delivery_config', return_value=delivery_cfg),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[_make_alert('TP_HIT')])),
        patch.object(mon, 'notify_enabled_channels') as mock_notify,
        patch.object(mon, 'compute_overall_regime', return_value='PASS'),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch('app.services.portfolio_alert_monitor.asyncio.to_thread',
              new=AsyncMock(return_value={'AAPL': {'last': 150.0}})),
    ):
        await mon._run_once()

    mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_fire_once_suppresses_repeat():
    """Once an alert has been dispatched, repeat triggers for the same position are silenced."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()
    mon._fired_once.add('pos1|TP_HIT')  # already sent this lifetime

    delivery_cfg = {'masterEnabled': True, 'enabledTypes': ['TP_HIT']}

    fake_db = _fake_db_with_positions(['pos1'])

    with (
        patch.object(mon, '_load_delivery_config', return_value=delivery_cfg),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[_make_alert('TP_HIT')])),
        patch.object(mon, 'notify_enabled_channels') as mock_notify,
        patch.object(mon, 'compute_overall_regime', return_value='PASS'),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch('app.services.portfolio_alert_monitor.asyncio.to_thread',
              new=AsyncMock(return_value={'AAPL': {'last': 150.0}})),
    ):
        await mon._run_once()

    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_fire_once_clears_when_position_closes():
    """When a position disappears, its fired_once entry is removed so a future re-entry can alert."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()

    # Simulate: position was open last tick, alert already fired
    mon._known_rec_ids = {'pos1'}
    mon._fired_once.add('pos1|TP_HIT')

    delivery_cfg = {'masterEnabled': True, 'enabledTypes': ['TP_HIT']}

    # This tick: no positions (position was closed)
    fake_db = _fake_db_with_positions([])

    with (
        patch.object(mon, '_load_delivery_config', return_value=delivery_cfg),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[])),
        patch.object(mon, 'notify_enabled_channels'),
        patch.object(mon, 'compute_overall_regime', return_value='PASS'),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch('app.services.portfolio_alert_monitor.asyncio.to_thread',
              new=AsyncMock(return_value={})),
    ):
        await mon._run_once()

    # fired_once entry must have been cleared on position close
    assert 'pos1|TP_HIT' not in mon._fired_once


@pytest.mark.asyncio
async def test_master_disabled_skips_all():
    """When masterEnabled is false, no alerts are dispatched."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()

    delivery_cfg = {'masterEnabled': False, 'enabledTypes': ['TP_HIT']}

    with (
        patch.object(mon, '_load_delivery_config', return_value=delivery_cfg),
        patch.object(mon, 'notify_enabled_channels') as mock_notify,
    ):
        await mon._run_once()

    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_regime_flip_dispatched():
    """A regime change from one state to another fires a REGIME_CHANGE alert."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()
    mon._last_regime = 'PASS'  # previous state

    delivery_cfg = {'masterEnabled': True, 'enabledTypes': ['REGIME_CHANGE']}

    fake_db = _fake_db_with_positions([])  # no positions — only testing regime flip

    with (
        patch.object(mon, '_load_delivery_config', return_value=delivery_cfg),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[])),
        patch.object(mon, 'notify_enabled_channels') as mock_notify,
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch('app.services.portfolio_alert_monitor.asyncio.to_thread',
              new=AsyncMock(return_value='REJECT')),
    ):
        await mon._run_once()

    mock_notify.assert_called_once()
    subject, plain, _html = mock_notify.call_args[0]
    assert 'REGIME_CHANGE' in subject
    assert 'REJECT' in plain
