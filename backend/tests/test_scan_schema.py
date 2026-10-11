import pytest
from pydantic import ValidationError

from app.schemas import ScanRequest, TradeCardData
from app.schemas.stock_scan import StockScanRequest


def test_scan_request_accepts_confidence_overrides():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bullish",
        "horizon": "Swing",
        "confidence_caution_below": 60,
        "confidence_reject_below": 40,
    })
    assert req.confidence_caution_below == 60
    assert req.confidence_reject_below == 40


def test_confidence_overrides_default_none():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bullish",
        "horizon": "Swing",
    })
    assert req.confidence_caution_below is None
    assert req.confidence_reject_below is None


def test_scan_request_accepts_bearish_fundamentals_overrides():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bearish",
        "horizon": "Swing",
        "fundamentals_caution_above": 65,
        "fundamentals_reject_above": 85,
    })
    assert req.fundamentals_caution_above == 65
    assert req.fundamentals_reject_above == 85


def test_trade_card_has_optional_confidence_fields():
    assert "confidence" in TradeCardData.model_fields
    assert "confidenceText" in TradeCardData.model_fields


# ── New StockScanRequest tolerance field tests ──────────────────────────────────

def _base() -> dict:
    return dict(universe=["SP500"], direction="Bullish",
                horizon="Swing", strategy="pullback_ema")


def test_new_fields_have_correct_defaults():
    # STOCKS-HORIZON-T1 H4: omitted strategy fields are None (the backend
    # profile applies), no longer the frozen 0.08 / 10 / 1.5 defaults.
    req = StockScanRequest(**_base())
    assert req.pullback_tolerance_pct is None
    assert req.ma_crossover_lookback is None
    assert req.breakout_volume_mult is None


def test_new_fields_accept_custom_values():
    req = StockScanRequest(
        **_base(),
        pullback_tolerance_pct=0.06,
        ma_crossover_lookback=15,
        breakout_volume_mult=1.3,
    )
    assert req.pullback_tolerance_pct == 0.06
    assert req.ma_crossover_lookback == 15
    assert req.breakout_volume_mult == 1.3


def test_new_fields_reject_invalid_values():
    with pytest.raises(ValidationError):
        StockScanRequest(**_base(), pullback_tolerance_pct=-0.01)
    with pytest.raises(ValidationError):
        StockScanRequest(**_base(), ma_crossover_lookback=0)
    with pytest.raises(ValidationError):
        StockScanRequest(**_base(), breakout_volume_mult=0.8)
