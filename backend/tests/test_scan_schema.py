from app.schemas import ScanRequest, TradeCardData


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


def test_trade_card_has_optional_confidence_fields():
    assert "confidence" in TradeCardData.model_fields
    assert "confidenceText" in TradeCardData.model_fields
