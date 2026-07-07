"""Tests for regime_monitor background task and conviction cache."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_no_alert_when_regime_is_pass(mocker):
    """Monitor must not broadcast when regime is PASS."""
    mocker.patch(
        "app.services.regime_monitor._update_conviction_cache",
        new=AsyncMock(),
    )
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="PASS"),
    )
    mocker.patch(
        "app.services.regime_monitor._check_overnight_gaps",
        new=AsyncMock(),
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
        "app.services.regime_monitor._update_conviction_cache",
        new=AsyncMock(),
    )
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=True),
    )
    mocker.patch(
        "app.services.regime_monitor._check_overnight_gaps",
        new=AsyncMock(),
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
        "app.services.regime_monitor._update_conviction_cache",
        new=AsyncMock(),
    )
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=False),
    )
    mocker.patch(
        "app.services.regime_monitor._check_overnight_gaps",
        new=AsyncMock(),
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


@pytest.mark.asyncio
async def test_regime_flip_alert_includes_close_advice(mocker):
    """The REGIME_FLIP_WARNING payload must tell the trader to consider closing."""
    mocker.patch(
        "app.services.regime_monitor._get_overall_regime",
        new=AsyncMock(return_value="REJECT"),
    )
    mocker.patch(
        "app.services.regime_monitor._has_open_positions",
        new=AsyncMock(return_value=True),
    )
    mocker.patch(
        "app.services.regime_monitor._check_overnight_gaps",
        new=AsyncMock(),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _tick
    await _tick()
    payload = broadcast_mock.call_args[0][0]
    assert "Consider closing" in payload["message"]


@pytest.mark.asyncio
async def test_gap_check_broadcasts_when_stop_breached(mocker):
    """When a bullish position's stop level is breached, broadcast OVERNIGHT_GAP_RISK."""
    positions = [
        {"symbol": "AAPL", "direction": "Bullish", "stop": 180.0},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    mocker.patch(
        "app.services.regime_monitor._fetch_stock_price",
        new=AsyncMock(return_value=175.0),  # below stop of 180
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_called_once()
    payload = broadcast_mock.call_args[0][0]
    assert payload["type"] == "OVERNIGHT_GAP_RISK"
    assert payload["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_gap_check_no_alert_when_stop_not_breached(mocker):
    """No alert when price is above stop for a bullish position."""
    positions = [
        {"symbol": "NVDA", "direction": "Bullish", "stop": 100.0},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    mocker.patch(
        "app.services.regime_monitor._fetch_stock_price",
        new=AsyncMock(return_value=120.0),  # above stop — safe
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_not_called()


@pytest.mark.asyncio
async def test_gap_check_bearish_stop_breached(mocker):
    """For bearish positions, a stop breach means price went ABOVE the stop level."""
    positions = [
        {"symbol": "SPY", "direction": "Bearish", "stop": 450.0},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    mocker.patch(
        "app.services.regime_monitor._fetch_stock_price",
        new=AsyncMock(return_value=460.0),  # above bearish stop
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_called_once()
    assert broadcast_mock.call_args[0][0]["type"] == "OVERNIGHT_GAP_RISK"


@pytest.mark.asyncio
async def test_gap_check_skips_position_with_no_stop(mocker):
    """Positions without a stop value must be skipped."""
    positions = [
        {"symbol": "MSFT", "direction": "Bullish", "stop": None},
    ]
    mocker.patch(
        "app.services.regime_monitor._get_open_positions",
        new=AsyncMock(return_value=positions),
    )
    broadcast_mock = mocker.patch(
        "app.services.regime_monitor._broadcast_alert",
        new=AsyncMock(),
    )
    from app.services.regime_monitor import _check_overnight_gaps
    await _check_overnight_gaps()
    broadcast_mock.assert_not_called()


@pytest.mark.asyncio
async def test_reject_alert_delayed_until_sustain_window_elapses(mocker):
    """With regime_flip_sustain_minutes=5, the first REJECT+open-positions tick
    must NOT broadcast — only once 5 minutes have elapsed across ticks."""
    import app.services.regime_monitor as rm
    rm._reject_since = None  # reset module state between tests
    mocker.patch("app.services.regime_monitor._update_conviction_cache", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._check_overnight_gaps", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._get_overall_regime", new=AsyncMock(return_value="REJECT"))
    mocker.patch("app.services.regime_monitor._has_open_positions", new=AsyncMock(return_value=True))
    mocker.patch("app.services.regime_monitor._load_regime_flip_sustain_minutes", new=AsyncMock(return_value=5))
    broadcast_mock = mocker.patch("app.services.regime_monitor._broadcast_alert", new=AsyncMock())

    await rm._tick()
    broadcast_mock.assert_not_called()
    assert rm._reject_since is not None


@pytest.mark.asyncio
async def test_reject_alert_fires_once_sustain_window_elapses(mocker):
    import app.services.regime_monitor as rm
    from datetime import datetime, timedelta, timezone
    rm._reject_since = datetime.now(timezone.utc) - timedelta(minutes=6)
    mocker.patch("app.services.regime_monitor._update_conviction_cache", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._check_overnight_gaps", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._get_overall_regime", new=AsyncMock(return_value="REJECT"))
    mocker.patch("app.services.regime_monitor._has_open_positions", new=AsyncMock(return_value=True))
    mocker.patch("app.services.regime_monitor._load_regime_flip_sustain_minutes", new=AsyncMock(return_value=5))
    broadcast_mock = mocker.patch("app.services.regime_monitor._broadcast_alert", new=AsyncMock())

    await rm._tick()
    broadcast_mock.assert_called_once()


@pytest.mark.asyncio
async def test_reject_clock_resets_when_regime_recovers(mocker):
    import app.services.regime_monitor as rm
    from datetime import datetime, timezone
    rm._reject_since = datetime.now(timezone.utc)
    mocker.patch("app.services.regime_monitor._update_conviction_cache", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._check_overnight_gaps", new=AsyncMock())
    mocker.patch("app.services.regime_monitor._get_overall_regime", new=AsyncMock(return_value="PASS"))
    broadcast_mock = mocker.patch("app.services.regime_monitor._broadcast_alert", new=AsyncMock())

    await rm._tick()
    broadcast_mock.assert_not_called()
    assert rm._reject_since is None
