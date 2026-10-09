"""H0a (STOCKS-HORIZON-T1): scripts/fill_sectors.py builds sector_overrides.csv.

S&P 500 names take the GICS Sector column of Wikipedia's "List of S&P 500
companies" table (BeautifulSoup + html.parser); NDX-only names take yfinance's
`.info` sector. Every name is mapped through `sector_names.NORMALIZE`; a name that
maps to nothing canonical is an error, and a symbol neither source resolves is
listed as unmatched, never written as `Unknown`.

The script lives under scripts/ and is run directly, so it is loaded by path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_PATH = _BACKEND / "scripts" / "fill_sectors.py"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wikipedia_sp500_constituents_excerpt.html"


def _load():
    spec = importlib.util.spec_from_file_location("fill_sectors_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def _html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


# ── Wikipedia parser ────────────────────────────────────────────────────────

def test_parser_reads_the_constituents_table_into_canonical_sectors(mod):
    got = mod.parse_sp500_constituents(_html())
    assert got == {
        "MMM": "Industrials",
        "AES": "Utilities",
        "GOOGL": "Comm. Services",
        "AAPL": "Technology",          # "Information Technology"
        "BRK.B": "Financials",
        "BF.B": "Consumer Staples",
    }


def test_parser_keeps_the_csv_ticker_spelling(mod):
    got = mod.parse_sp500_constituents(_html().replace(">BRK.B<", ">BRK-B<"))
    assert "BRK.B" in got and "BRK-B" not in got


def test_parser_names_an_unknown_gics_sector(mod):
    html = _html().replace(">Utilities<", ">Space Mining<")
    with pytest.raises(mod.UnknownSectorError, match="Space Mining"):
        mod.parse_sp500_constituents(html)


def test_parser_without_the_constituents_table_is_an_error(mod):
    html = _html().replace('id="constituents"', 'id="something-else"')
    with pytest.raises(ValueError, match="constituents"):
        mod.parse_sp500_constituents(html)


def test_information_technology_is_canonical_technology():
    from app.data.sector_names import NORMALIZE
    assert NORMALIZE["Information Technology"] == "Technology"


# ── NDX-only names: yfinance ────────────────────────────────────────────────

class _FakeTicker:
    infos: dict = {}
    seen: list = []

    def __init__(self, key):
        _FakeTicker.seen.append(key)
        self._key = key

    @property
    def info(self):
        val = _FakeTicker.infos[self._key]
        if isinstance(val, Exception):
            raise val
        return val


@pytest.fixture
def fake_yf(mod, monkeypatch):
    _FakeTicker.infos = {}
    _FakeTicker.seen = []
    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    return _FakeTicker


def test_yfinance_sector_is_mapped_to_the_canonical_name(mod, fake_yf):
    fake_yf.infos = {"ASML": {"sector": "Technology"}, "MELI": {"sector": "Consumer Cyclical"}}
    assert mod.yfinance_sector("ASML") == "Technology"
    assert mod.yfinance_sector("MELI") == "Consumer Discretionary"


def test_yfinance_failure_or_empty_sector_is_none(mod, fake_yf):
    fake_yf.infos = {"SGEN": RuntimeError("404"), "OKTA": {}, "ZS": {"sector": ""}}
    assert mod.yfinance_sector("SGEN") is None
    assert mod.yfinance_sector("OKTA") is None
    assert mod.yfinance_sector("ZS") is None


def test_yfinance_uses_the_yahoo_ticker_spelling(mod, fake_yf):
    fake_yf.infos = {"BF-B": {"sector": "Consumer Defensive"}}
    assert mod.yfinance_sector("BF.B") == "Consumer Staples"
    assert fake_yf.seen == ["BF-B"]


def test_yfinance_unknown_sector_name_is_an_error(mod, fake_yf):
    fake_yf.infos = {"JD": {"sector": "Space Mining"}}
    with pytest.raises(mod.UnknownSectorError, match="Space Mining"):
        mod.yfinance_sector("JD")


def test_build_overrides_sources_and_unmatched(mod, fake_yf):
    gics = mod.parse_sp500_constituents(_html())
    fake_yf.infos = {"ASML": {"sector": "Technology"}, "SGEN": RuntimeError("delisted")}
    rows, unmatched = mod.build_overrides(
        sp500_symbols=["MMM", "BRK.B", "STALE"],
        ndx_symbols=["AAPL", "ASML", "SGEN"],
        sp500_gics=gics,
        as_of="2026-10-09",
    )
    assert rows == [
        {"symbol": "AAPL", "sector": "Technology", "source": "wikipedia-gics", "as_of": "2026-10-09"},
        {"symbol": "ASML", "sector": "Technology", "source": "yfinance", "as_of": "2026-10-09"},
        {"symbol": "BRK.B", "sector": "Financials", "source": "wikipedia-gics", "as_of": "2026-10-09"},
        {"symbol": "MMM", "sector": "Industrials", "source": "wikipedia-gics", "as_of": "2026-10-09"},
    ]
    # STALE is in sp500.csv but not in the S&P table and not NDX: no yfinance call.
    assert unmatched == ["SGEN", "STALE"]
    assert fake_yf.seen == ["ASML", "SGEN"]
    assert all(r["sector"] != "Unknown" for r in rows)


# ── After the real run (2026-10-09): the committed sector_overrides.csv ─────

# Listed by the script's real run as unmatched: in sp500.csv (or NDX100) but in
# neither the current Wikipedia S&P 500 table nor (for NDX-only names) yfinance.
# Mostly former S&P members still in sp500.csv; SGEN is NDX100 only (acquired).
# sp500.csv's own sector for each of these is Unknown, so they stay without one.
_UNMATCHED_UNKNOWN = {
    "AAL", "ALV", "AXL", "BCB", "BLDR", "BWA", "CE", "CTLT", "CTRA", "CTVA", "CZR",
    "DAY", "DFS", "EMN", "EPAM", "ETSY", "FBHS", "FI", "FMC", "GT", "H", "ICLR",
    "IPG", "JNPR", "L3H", "LEA", "LKQ", "LNC", "LW", "MGA", "MHK", "MKTX", "MOH",
    "MRO", "NWL", "OVV", "PAYC", "PKI", "POOL", "PRGO", "PTVE", "QRVO", "RS",
    "SAIC", "SGEN", "SWN", "TAP", "VC", "VFC", "VIAV", "VWO", "WEX", "WHR", "WU",
}


def _universe() -> set[str]:
    import csv
    from app.data.universe_presets import NDX100
    with (_BACKEND / "app" / "data" / "sp500.csv").open(newline="", encoding="utf-8") as f:
        return {r["symbol"].strip().upper() for r in csv.DictReader(f)} | set(NDX100)


def test_unknown_covers_no_symbol_of_sp500_csv_or_ndx100_except_the_unmatched():
    from app.data import sector_map
    sector_map._symbol_to_raw_sector.cache_clear()
    try:
        missing = {s for s in _universe() if sector_map.sector_for_symbol(s)[0] in (None, "Unknown")}
    finally:
        sector_map._symbol_to_raw_sector.cache_clear()
    assert missing == _UNMATCHED_UNKNOWN


def test_committed_overrides_are_canonical_and_never_unknown():
    import csv
    from app.data.sector_map import _NAME_TO_ETF
    with (_BACKEND / "app" / "data" / "sector_overrides.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["symbol", "sector", "source", "as_of"]
        rows = list(reader)
    syms = [r["symbol"] for r in rows]
    assert len(syms) == len(set(syms))
    assert {r["sector"] for r in rows} <= set(_NAME_TO_ETF)
    assert {r["source"] for r in rows} <= {"wikipedia-gics", "yfinance"}
    assert not set(syms) & _UNMATCHED_UNKNOWN
    assert set(syms) <= _universe()
