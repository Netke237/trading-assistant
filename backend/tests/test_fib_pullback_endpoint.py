"""Tests for POST /api/scan/fib-pullback endpoint."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app

BARS_50 = [
    {"open": 100.0 + i * 0.1, "high": 101.0 + i * 0.1,
     "low": 99.0 + i * 0.1, "close": 100.5 + i * 0.1, "volume": 1_000_000}
    for i in range(120)
]


@pytest.mark.asyncio
async def test_fib_pullback_returns_list():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        row = data[0]
        assert "symbol" in row
        assert "fib_level_hit" in row
        assert "fib_dist_pct" in row
        assert "at_level" in row
        assert "confidence" in row


@pytest.mark.asyncio
async def test_fib_pullback_accepts_params_override():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["MSFT"],
                "direction": "Bullish",
                "params_override": {
                    "fib_swing_lookback": 80,
                    "fib_levels": [38.2, 61.8],
                    "fib_tolerance_pct": 0.02,
                },
            })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_fib_pullback_rejects_unknown_override():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"bad_key": 99},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fib_pullback_empty_bars_skipped():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_fib_pullback_universe_expansion():
    with patch("app.routers.stock_scan.expand_universe") as mock_expand, \
         patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_expand.return_value = ["AAPL", "MSFT"]
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": [],
                "direction": "Bullish",
                "universe": ["SP500"],
            })
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_fib_pullback_skips_when_no_swing_found():
    """Symbols where fibonacci_pullback_signal returns level_hit=None must be excluded."""
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars, \
         patch("app.services.strategy_engine.fibonacci_pullback_detail", return_value={
             "at_level": False, "dist_pct": None, "label": None,
             "swing_low": None, "swing_high": None,
         }) as mock_sig:
        mock_bars.return_value = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1_000_000}] * 15
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    assert resp.json() == []
    mock_sig.assert_called_once()


@pytest.mark.asyncio
async def test_fib_pullback_bearish_direction():
    """Bearish direction should be passed through to the signal and appear in results."""
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["TSLA"],
                "direction": "Bearish",
            })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert data[0]["direction"] == "Bearish"


@pytest.mark.asyncio
async def test_fib_pullback_rejects_empty_fib_levels():
    """An empty fib_levels list must be rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"fib_levels": []},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fib_pullback_rejects_invalid_fib_level_values():
    """Non-standard fib level values (e.g. 50.1) must be rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"fib_levels": [50.1]},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fib_pullback_rejects_zero_tolerance():
    """fib_tolerance_pct of 0 must be rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"fib_tolerance_pct": 0.0},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fib_pullback_sort_order_at_level_first():
    """At-level hits must rank before non-at-level results."""
    at_level_result = {"at_level": True, "dist_pct": 0.5, "label": "61.8",
                       "swing_low": None, "swing_high": None}
    not_at_level_result = {"at_level": False, "dist_pct": 3.0, "label": "38.2",
                           "swing_low": None, "swing_high": None}
    call_count = {"n": 0}

    async def fake_bars(sym, *_a, **_kw):
        return BARS_50

    def fake_signal(bars, direction, **kwargs):
        call_count["n"] += 1
        # First symbol returns at-level, second does not
        return at_level_result if call_count["n"] == 1 else not_at_level_result

    with patch("app.routers.stock_scan.get_historical_bars", side_effect=fake_bars), \
         patch("app.services.strategy_engine.fibonacci_pullback_detail", side_effect=fake_signal):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL", "MSFT"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["at_level"] is True, "at-level hit must sort first"
    assert data[1]["at_level"] is False


@pytest.mark.asyncio
async def test_fib_pullback_rejects_lookback_below_minimum():
    """fib_swing_lookback < 10 must be rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"fib_swing_lookback": 5},
        })
    assert resp.status_code == 422


# ── Universe exclusion list (STOCKS-HORIZON-P0A A2) ──────────────────────────
#
# Fib pullback returns a bare list of setups and has no `rejected` list, so a
# `scope: scan` symbol is skipped and named in one INFO log line. The shipped
# config/universe_exclusions.yaml lists PXD with scope scan.


@pytest.mark.asyncio
async def test_fib_pullback_skips_a_typed_excluded_symbol(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="app.routers.stock_scan")
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL", "pxd"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200, resp.text
    assert [c.args[0] for c in mock_bars.call_args_list] == ["AAPL"], "PXD was processed"
    skipped = [r for r in caplog.records
               if r.levelno == logging.INFO and "PXD" in r.getMessage()]
    assert len(skipped) == 1, [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_fib_pullback_broken_exclusion_list_returns_500_before_any_symbol_work():
    from app.data.universe_exclusions import ExclusionListError

    msg = "universe_exclusions.yaml: 'version' must be 1, got 2"
    with patch(
        "app.data.universe_exclusions.load_exclusions",
        side_effect=ExclusionListError(msg),
    ), patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 500, resp.text
    assert resp.json()["detail"] == msg
    mock_bars.assert_not_called()
