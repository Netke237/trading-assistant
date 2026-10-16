import pytest
from unittest.mock import patch, AsyncMock
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_prebreakout_accepts_universe_field():
    """universe field is accepted and passed to expand_universe."""
    with patch(
        "app.routers.stock_scan.expand_universe",
        return_value=["AAPL", "MSFT"],
    ) as mock_expand, patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "universe": ["DOW30"],
                "direction": "Bullish",
            })
        assert resp.status_code == 200
        mock_expand.assert_called_once_with(["DOW30"])


@pytest.mark.asyncio
async def test_prebreakout_empty_symbols_and_no_universe_returns_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "symbols": [],
            "direction": "Bullish",
        })
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_prebreakout_unknown_preset_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "universe": ["RUSSELL2000"],
            "direction": "Bullish",
        })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_prebreakout_manual_symbols_skips_expand_universe():
    """When symbols are provided without universe, expand_universe must NOT be called."""
    with patch(
        "app.routers.stock_scan.expand_universe",
    ) as mock_expand, patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "symbols": ["AAPL", "MSFT"],
                "direction": "Bullish",
            })
        assert resp.status_code == 200
        mock_expand.assert_not_called()


@pytest.mark.asyncio
async def test_prebreakout_unknown_override_key_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "symbols": ["AAPL"],
            "params_override": {"direction": "injected"},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_prebreakout_valid_override_key_accepted():
    """atr_avg_lookback is whitelisted and must not be rejected."""
    with patch(
        "app.routers.stock_scan.expand_universe",
    ) as mock_expand, patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ):
        mock_expand.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "universe": ["SP500"],
                "params_override": {"atr_avg_lookback": 10},
            })
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_prebreakout_fib_override_keys_accepted():
    """fib_enabled, fib_swing_lookback, fib_levels, fib_tolerance_pct must be accepted."""
    with patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "symbols": ["AAPL"],
                "params_override": {
                    "fib_enabled": True,
                    "fib_swing_lookback": 80,
                    "fib_levels": [23.6, 38.2, 50.0],
                    "fib_tolerance_pct": 0.02,
                },
            })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_prebreakout_fib_unknown_key_still_rejected():
    """A spurious fib key must still return 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "symbols": ["AAPL"],
            "params_override": {"fib_unknown_key": 1},
        })
    assert resp.status_code == 422


# ── Universe exclusion list (STOCKS-HORIZON-P0A A2) ──────────────────────────
#
# Pre-breakout returns a bare list of setups and has no `rejected` list, so a
# `scope: scan` symbol is skipped and named in one INFO log line. The shipped
# config/universe_exclusions.yaml lists PXD with scope scan.


@pytest.mark.asyncio
async def test_prebreakout_skips_an_excluded_symbol_from_a_preset(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="app.routers.stock_scan")
    with patch(
        "app.routers.stock_scan.expand_universe",
        return_value=["AAPL", "PXD"],
    ), patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_bars:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "universe": ["SP500"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200, resp.text
    assert [c.args[0] for c in mock_bars.call_args_list] == ["AAPL"], "PXD was processed"
    skipped = [r for r in caplog.records
               if r.levelno == logging.INFO and "PXD" in r.getMessage()]
    assert len(skipped) == 1, [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_prebreakout_broken_exclusion_list_returns_500_before_any_symbol_work():
    from app.data.universe_exclusions import ExclusionListError

    msg = "universe_exclusions.yaml: 'version' must be 1, got 2"
    with patch(
        "app.data.universe_exclusions.load_exclusions",
        side_effect=ExclusionListError(msg),
    ), patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_bars:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 500, resp.text
    assert resp.json()["detail"] == msg
    mock_bars.assert_not_called()
