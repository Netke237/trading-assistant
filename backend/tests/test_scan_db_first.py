"""Test that _process_symbol uses DB bars when bars_map is provided."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.routers.scan import _process_symbol


FAKE_BARS = [
    {"time": f"2024-{m:02d}-{d:02d}", "open": 180.0, "high": 182.0, "low": 179.0, "close": 181.0, "volume": 1_000_000}
    for m in range(1, 13) for d in range(1, 22)
][:252]


@pytest.mark.asyncio
async def test_process_symbol_uses_bars_map_not_tradier():
    """When bars_map is provided with the symbol's bars, fetch_candles_async must NOT be called."""
    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=sem)
    sem.__aexit__ = AsyncMock(return_value=False)

    with patch("app.routers.scan.fetch_candles_async") as mock_candles, \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="Apple Inc."), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.score_stock") as mock_score:

        mock_score.return_value = MagicMock(status="REJECT", score=20, components={})

        result = await _process_symbol(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            client=AsyncMock(),
            sem=sem,
            scan_id="test-scan-1",
            bars_map={"AAPL": FAKE_BARS},
        )

    mock_candles.assert_not_called()
    assert result is not None
