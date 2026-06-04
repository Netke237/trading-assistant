"""Unit tests for /stock-scan endpoint — schema and routing logic only (no live API calls)."""
import pytest
from app.schemas.stock_scan import StockScanRequest


def test_stock_scan_request_accepts_symbols():
    req = StockScanRequest(
        universe=["SP500"],
        symbols=["AAPL", "MSFT"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols == ["AAPL", "MSFT"]


def test_stock_scan_request_symbols_defaults_none():
    req = StockScanRequest(
        universe=["SP500"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols is None
