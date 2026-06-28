from app.data.sector_map import sector_for_symbol


def test_known_sp500_symbol_maps_to_sector_and_etf():
    name, etf = sector_for_symbol("MMM")   # Industrials in sp500.csv
    assert name == "Industrials"
    assert etf == "XLI"


def test_unknown_symbol_returns_none():
    name, etf = sector_for_symbol("ZZZZ_NOT_A_TICKER")
    assert name is None
    assert etf is None


def test_case_insensitive():
    name, etf = sector_for_symbol("mmm")
    assert etf == "XLI"
