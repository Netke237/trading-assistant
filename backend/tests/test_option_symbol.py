import pytest
from app.data.option_symbol import is_occ, pipe_to_occ, to_occ


# ── is_occ ────────────────────────────────────────────────────────────────────

def test_is_occ_recognises_valid_occ():
    assert is_occ("AAPL250516C00185000") is True


def test_is_occ_recognises_put():
    assert is_occ("NVDA260620P00130000") is True


def test_is_occ_rejects_pipe_format():
    assert is_occ("AAPL|185|2025-05-16|C") is False


def test_is_occ_rejects_display_label():
    assert is_occ("AAPL 185C 05/16") is False


# ── pipe_to_occ ───────────────────────────────────────────────────────────────

def test_pipe_to_occ_basic_call():
    assert pipe_to_occ("AAPL|185|2025-05-16|C") == "AAPL250516C00185000"


def test_pipe_to_occ_put():
    assert pipe_to_occ("NVDA|130|2026-06-20|P") == "NVDA260620P00130000"


def test_pipe_to_occ_fractional_strike():
    # 1.5 × 1000 = 1500 → 00001500
    assert pipe_to_occ("SPY|1.5|2025-05-16|C") == "SPY250516C00001500"


def test_pipe_to_occ_large_strike():
    # 1000 × 1000 = 1_000_000 → 01000000
    assert pipe_to_occ("AMZN|1000|2025-05-16|C") == "AMZN250516C01000000"


def test_pipe_to_occ_half_dollar_strike():
    # 185.5 × 1000 = 185500 → 00185500
    assert pipe_to_occ("AAPL|185.5|2025-05-16|C") == "AAPL250516C00185500"


def test_pipe_to_occ_three_char_symbol():
    assert pipe_to_occ("SPY|450|2025-12-31|P") == "SPY251231P00450000"


def test_pipe_to_occ_invalid_raises():
    with pytest.raises(ValueError, match="Cannot convert"):
        pipe_to_occ("AAPL_185_2025-05-16_C")   # underscore delimiters


def test_pipe_to_occ_display_label_raises():
    with pytest.raises(ValueError, match="Cannot convert"):
        pipe_to_occ("AAPL 185C 05/16")


# ── to_occ ────────────────────────────────────────────────────────────────────

def test_to_occ_converts_pipe_format():
    assert to_occ("AAPL|185|2025-05-16|C") == "AAPL250516C00185000"


def test_to_occ_passthrough_already_occ():
    occ = "AAPL250516C00185000"
    assert to_occ(occ) == occ
