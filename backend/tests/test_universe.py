from app.data.universe_presets import expand_universe, PresetUnavailableError
import pytest

def test_sp500_expands():
    result = expand_universe(["SP500"])
    assert len(result) > 400

def test_ndx100_expands():
    result = expand_universe(["NDX100"])
    assert len(result) == 101

def test_dow30_expands():
    result = expand_universe(["DOW30"])
    assert len(result) == 30

def test_custom_passthrough():
    result = expand_universe(["AAPL", "MSFT"])
    assert result == ["AAPL", "MSFT"]

def test_mixed_list():
    result = expand_universe(["SP500", "TSLA"])
    assert "TSLA" in result
    assert len(result) > 400

def test_no_duplicates_in_mixed():
    # If TSLA is already in SP500, it should not appear twice
    result = expand_universe(["SP500", "TSLA"])
    assert result.count("TSLA") == 1

def test_russell2000_raises():
    with pytest.raises(PresetUnavailableError):
        expand_universe(["RUSSELL2000"])

def test_stoxx600_raises():
    with pytest.raises(PresetUnavailableError):
        expand_universe(["STOXX600"])
