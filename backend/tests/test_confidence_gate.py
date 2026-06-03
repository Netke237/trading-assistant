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
