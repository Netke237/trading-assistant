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


# ── H0a (STOCKS-HORIZON-T1): sp500.csv first, then sector_overrides.csv ─────

import pytest

from app.data import sector_map


@pytest.fixture
def sector_files(tmp_path, monkeypatch):
    sp500 = tmp_path / "sp500.csv"
    sp500.write_text(
        "symbol,sector,liquidity\n"
        "KNOWN,Industrials,10.0\n"
        "BOTH,Healthcare,10.0\n"
        "FILLED,Unknown,10.0\n"
        "NEITHER,Unknown,10.0\n",
        encoding="utf-8",
    )
    overrides = tmp_path / "sector_overrides.csv"
    overrides.write_text(
        "symbol,sector,source,as_of\n"
        "BOTH,Energy,wikipedia-gics,2026-10-09\n"
        "FILLED,Comm. Services,wikipedia-gics,2026-10-09\n"
        "NDXONLY,Technology,yfinance,2026-10-09\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sector_map, "_SP500_CSV", sp500)
    monkeypatch.setattr(sector_map, "_OVERRIDES_CSV", overrides)
    sector_map._symbol_to_raw_sector.cache_clear()
    yield
    sector_map._symbol_to_raw_sector.cache_clear()


def test_known_sp500_sector_wins_over_the_override(sector_files):
    assert sector_for_symbol("KNOWN") == ("Industrials", "XLI")
    assert sector_for_symbol("BOTH") == ("Health Care", "XLV")


def test_unknown_sp500_sector_falls_back_to_the_override(sector_files):
    assert sector_for_symbol("FILLED") == ("Comm. Services", "XLC")
    assert sector_for_symbol("ndxonly") == ("Technology", "XLK")


def test_neither_file_knows_the_sector_returns_none(sector_files):
    assert sector_for_symbol("NEITHER") == (None, None)
    assert sector_for_symbol("ABSENT") == (None, None)


def test_missing_overrides_file_is_not_an_error(sector_files, tmp_path, monkeypatch):
    monkeypatch.setattr(sector_map, "_OVERRIDES_CSV", tmp_path / "gone.csv")
    sector_map._symbol_to_raw_sector.cache_clear()
    assert sector_for_symbol("KNOWN") == ("Industrials", "XLI")
    assert sector_for_symbol("FILLED") == (None, None)
