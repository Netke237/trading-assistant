"""Tests for regime_monitor background task and conviction cache."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_no_alert_when_regime_is_pass(mocker):
    """Monitor must not broadcast when regime is PASS."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="PASS"),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    broadcast_mock.assert_not_called()


@pytest.mark.asyncio
async def test_alert_sent_when_regime_reject_with_positions(mocker):
    """Monitor broadcasts when regime=REJECT and open positions exist."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=True),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    broadcast_mock.assert_called_once()
    call_args = broadcast_mock.call_args[0][0]
    assert call_args["type"] == "REGIME_FLIP_WARNING"


@pytest.mark.asyncio
async def test_no_alert_when_regime_reject_but_no_positions(mocker):
    """No alert if regime is REJECT but no open positions."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=False),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    broadcast_mock.assert_not_called()


def test_conviction_cache_set_and_get():
    """set_last_conviction / get_last_conviction round-trip."""
    from app.services.regime_monitor import set_last_conviction, get_last_conviction
    set_last_conviction(42)
    assert get_last_conviction() == 42
    set_last_conviction(0)
    assert get_last_conviction() == 0


@pytest.mark.asyncio
async def test_update_conviction_cache_stores_value(mocker):
    """_update_conviction_cache must call set_last_conviction when OMM returns a value."""
    mock_loop = MagicMock()
    # run_in_executor is called as `await loop.run_in_executor(None, fn)` — must be a coroutine
    mock_loop.run_in_executor = AsyncMock(return_value=37.0)
    mocker.patch("app.services.regime_monitor.asyncio.get_running_loop", return_value=mock_loop)

    set_conv_spy = mocker.patch("app.services.regime_monitor.set_last_conviction")

    from app.services.regime_monitor import _update_conviction_cache
    await _update_conviction_cache()

    set_conv_spy.assert_called_once_with(37.0)


@pytest.mark.asyncio
async def test_update_conviction_cache_no_op_on_none(mocker):
    """If OMM returns None (no candles), set_last_conviction must not be called."""
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=None)
    mocker.patch("app.services.regime_monitor.asyncio.get_running_loop", return_value=mock_loop)

    set_conv_spy = mocker.patch("app.services.regime_monitor.set_last_conviction")

    from app.services.regime_monitor import _update_conviction_cache
    await _update_conviction_cache()

    set_conv_spy.assert_not_called()
