"""Unit tests for the ingestion job."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ingestion_job import (
    IngestionResult,
    run_ingestion,
    _should_ingest,
)


@pytest.mark.asyncio
async def test_run_ingestion_returns_result():
    """Minimal happy path: Alpaca returns bars for all symbols, no gap-fill needed."""
    symbols = ["AAPL", "MSFT"]
    fake_bars = {
        "AAPL": [{"time": "2024-01-02", "open": 180.0, "high": 181.0, "low": 179.0,
                  "close": 180.5, "volume": 1_000_000, "adj_factor": 1.0,
                  "split_factor": 1.0, "div_cash": 0.0, "source": "alpaca"}],
        "MSFT": [{"time": "2024-01-02", "open": 370.0, "high": 372.0, "low": 369.0,
                  "close": 371.0, "volume": 800_000, "adj_factor": 1.0,
                  "split_factor": 1.0, "div_cash": 0.0, "source": "alpaca"}],
    }
    with patch("app.services.ingestion_job.fetch_daily_bars_batch", new_callable=AsyncMock) as mock_batch, \
         patch("app.services.ingestion_job.get_alpaca_client", new_callable=AsyncMock) as mock_client, \
         patch("app.services.ingestion_job.update_history", new_callable=AsyncMock) as mock_update, \
         patch("app.services.ingestion_job._prune_old_rows", new_callable=AsyncMock, return_value=0):

        mock_batch.return_value = fake_bars
        mock_client.return_value = MagicMock()

        from app.services.history_backfill import HistoryUpdateResult
        mock_update.return_value = HistoryUpdateResult(1, False, False)

        result = await run_ingestion(symbols, years=1)

    assert isinstance(result, IngestionResult)
    assert result.total == 2
    assert result.failed == 0
    assert mock_update.await_count == 2


def test_should_ingest_when_stale():
    """_should_ingest returns True if last_date is more than 1 trading day behind."""
    # Use 10 days to stay safely above the boundary on any day of the week
    clearly_stale = date.today() - timedelta(days=10)
    assert _should_ingest(clearly_stale) is True


def test_should_ingest_when_no_data():
    """_should_ingest returns True if no last_date."""
    assert _should_ingest(None) is True


def test_should_not_ingest_when_fresh():
    """_should_ingest returns False if last_date is today."""
    today = date.today()
    assert _should_ingest(today) is False
