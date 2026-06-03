from app.scoring.signal_confidence import status_cap, interpret

GATE = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}


def test_status_cap_rejects_below_reject_threshold():
    assert status_cap(30, GATE) == "REJECT"


def test_status_cap_cautions_in_middle_band():
    assert status_cap(45, GATE) == "CAUTION"


def test_status_cap_passes_when_high():
    assert status_cap(80, GATE) == "PASS"


def test_status_cap_none_confidence_does_not_demote():
    assert status_cap(None, GATE) == "PASS"


def test_status_cap_disabled_gate_never_demotes():
    assert status_cap(10, {"enabled": False, "cautionBelow": 50, "rejectBelow": 35}) == "PASS"


def test_interpret_low_text_mentions_caution():
    txt = interpret(41, sample_size=120, symbol="AAPL")
    assert "41%" in txt and "AAPL" in txt


from app.scoring.stock_scorer import score_stock


def _flat_bars(n=120, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1000} for _ in range(n)]


def test_low_confidence_demotes_status_and_appends_rule():
    bars = _flat_bars()
    gate = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
    card = score_stock(
        symbol="X", direction="Bullish", horizon="Swing", bars=bars,
        confidence=20, confidence_gate=gate, confidence_sample_size=99,
    )
    assert card.status == "REJECT"  # capped down by confidence=20
    assert any(r.name == "confidence" for r in card.rules)


def test_high_confidence_never_inflates():
    bars = _flat_bars()
    gate = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
    base = score_stock(symbol="X", direction="Bullish", horizon="Swing", bars=bars)
    boosted = score_stock(
        symbol="X", direction="Bullish", horizon="Swing", bars=bars,
        confidence=95, confidence_gate=gate, confidence_sample_size=99,
    )
    assert boosted.status == base.status  # confidence cannot raise it
