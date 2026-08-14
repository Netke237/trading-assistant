"""Tests for portfolio_alert_monitor._run_once.

The monitor no longer owns dedup state — it generates alert conditions and
funnels every one through the shared ``notify_alert`` (which enforces
masterEnabled/enabledTypes and dedups). These tests therefore verify the
monitor's orchestration: master gate, per-alert dispatch, closed-position
cleanup, and regime-flip detection. The dedup/reminder behaviour itself is
covered in ``test_alert_notifier.py``.
"""
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


def _make_position(rec_id: str, symbol: str = 'AAPL') -> MagicMock:
    p = MagicMock()
    p.symbol = symbol
    p.rec_id = rec_id
    p.contract = None  # None → skip the live option-price httpx branch
    return p


class _FakeNestedTransaction:
    """Real async-context-manager shape for AsyncSession.begin_nested(),
    which a bare AsyncMock does not provide — AsyncMock auto-specs
    `begin_nested` as a coroutine-returning mock, so `async with
    db.begin_nested():` fails (caught internally by log_position_alert, but
    noisily) unless this is modeled explicitly."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _fake_db_with_positions(rec_ids: list[str], symbol: str = 'AAPL'):
    """Return an async-context-manager mock whose positions have the given recIds."""
    positions = [_make_position(rid, symbol) for rid in rec_ids]

    fake_db = AsyncMock()
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=False)
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = positions
    fake_db.execute = AsyncMock(return_value=fake_result)
    # begin_nested() is sync (it returns the async context manager, it isn't
    # itself awaited) — must be a plain MagicMock, not an AsyncMock.
    fake_db.begin_nested = MagicMock(return_value=_FakeNestedTransaction())
    return fake_db


def _reset_monitor_state():
    from app.services import portfolio_alert_monitor as mon
    from app.services.notifications import alert_notifier as an
    mon._known_rec_ids.clear()
    mon._last_regime = None
    an._fired.clear()
    an._first_seen.clear()


@pytest.mark.asyncio
async def test_master_disabled_skips_all():
    """masterEnabled=False short-circuits before any dispatch — even with a
    real alert-worthy position in play, generate_alerts/notify_alert must
    never be reached. (A prior version of this test asserted only
    notify_alert.assert_not_called() with no position fixture, which is
    vacuously true regardless of the gate — there was nothing to alert on
    either way. This reproduces the fixture from
    test_position_alert_dispatched_via_notify_alert, which proves an alert
    WOULD fire absent the gate, so the negative assertion here is meaningful.)"""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()

    fake_db = _fake_db_with_positions(['pos1'])

    with (
        patch.object(mon, '_load_settings', return_value={'alert_delivery': {'masterEnabled': False}}),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[_make_alert('TP_HIT')])) as m_generate,
        patch.object(mon, 'notify_alert') as m_notify,
        patch.object(mon.alert_service, 'broadcast', new=AsyncMock()),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch.object(mon.asyncio, 'to_thread', new=AsyncMock(return_value={'AAPL': {'last': 150.0}})),
    ):
        await mon._run_once()

    m_generate.assert_not_called()
    m_notify.assert_not_called()


@pytest.mark.asyncio
async def test_position_alert_dispatched_via_notify_alert():
    """Each generated alert is handed to notify_alert with (symbol, type, reason, recId, ts)."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()

    fake_db = _fake_db_with_positions(['pos1'])

    with (
        patch.object(mon, '_load_settings',
                     return_value={'alert_delivery': {'masterEnabled': True, 'enabledTypes': ['TP_HIT']}}),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[_make_alert('TP_HIT')])),
        patch.object(mon, 'notify_alert') as m_notify,
        patch.object(mon.alert_service, 'broadcast', new=AsyncMock()),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch.object(mon.asyncio, 'to_thread', new=AsyncMock(return_value={'AAPL': {'last': 150.0}})),
    ):
        await mon._run_once()

    m_notify.assert_called_once()
    symbol, alert_type, _reason, rec_id, _ts = m_notify.call_args[0]
    assert alert_type == 'TP_HIT'
    assert rec_id == 'pos1'
    assert symbol == 'AAPL'


@pytest.mark.asyncio
async def test_closed_position_calls_forget_alerts():
    """A position present last tick but gone this tick triggers forget_alerts for its recId."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()
    mon._known_rec_ids = {'pos1'}

    fake_db = _fake_db_with_positions([])  # position closed this tick

    with (
        patch.object(mon, '_load_settings',
                     return_value={'alert_delivery': {'masterEnabled': True, 'enabledTypes': ['TP_HIT']}}),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[])),
        patch.object(mon, 'notify_alert'),
        patch.object(mon, 'forget_alerts') as m_forget,
        patch.object(mon.alert_service, 'broadcast', new=AsyncMock()),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
    ):
        await mon._run_once()

    m_forget.assert_called_once_with({'pos1'})


@pytest.mark.asyncio
async def test_regime_flip_dispatched():
    """A regime change from the prior state fires a REGIME_CHANGE alert via notify_alert."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()
    mon._last_regime = 'PASS'

    fake_db = _fake_db_with_positions([])  # no positions — only testing the flip

    with (
        patch.object(mon, '_load_settings',
                     return_value={'alert_delivery': {'masterEnabled': True, 'enabledTypes': ['REGIME_CHANGE']}}),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[])),
        patch.object(mon, 'notify_alert') as m_notify,
        patch.object(mon.alert_service, 'broadcast', new=AsyncMock()),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch.object(mon.asyncio, 'to_thread', new=AsyncMock(return_value='REJECT')),
    ):
        await mon._run_once()

    m_notify.assert_called_once()
    _symbol, alert_type, reason, _rec_id, _ts = m_notify.call_args[0]
    assert alert_type == 'REGIME_CHANGE'
    assert 'PASS' in reason and 'REJECT' in reason


@pytest.mark.asyncio
async def test_no_regime_flip_when_state_unchanged():
    """Same regime state as last tick must NOT fire a REGIME_CHANGE alert."""
    from app.services import portfolio_alert_monitor as mon
    _reset_monitor_state()
    mon._last_regime = 'PASS'

    fake_db = _fake_db_with_positions([])

    with (
        patch.object(mon, '_load_settings',
                     return_value={'alert_delivery': {'masterEnabled': True, 'enabledTypes': ['REGIME_CHANGE']}}),
        patch.object(mon, 'generate_alerts', new=AsyncMock(return_value=[])),
        patch.object(mon, 'notify_alert') as m_notify,
        patch.object(mon.alert_service, 'broadcast', new=AsyncMock()),
        patch('app.services.portfolio_alert_monitor.AsyncSessionLocal', return_value=fake_db),
        patch.object(mon.asyncio, 'to_thread', new=AsyncMock(return_value='PASS')),
    ):
        await mon._run_once()

    m_notify.assert_not_called()
