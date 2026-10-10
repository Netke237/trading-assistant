"""Task 10b (D4 amended 2026-10-03): ONE curated ETF set decides whether an
unknown earnings date matters. A symbol NOT in the set is treated as a single
stock -- the safe direction (CAUTION / auto-fire refused, never a silent PASS)."""
from app.data.etfs import INDEX_ETFS, KNOWN_ETFS, SECTOR_ETFS, is_etf


def test_index_sector_and_common_etfs_are_etfs():
    for s in ("SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "XLK", "XLRE", "SMH", "XBI",
              "KRE", "ARKK", "EEM", "EFA", "HYG", "LQD", "VXX", "UVXY", "SQQQ", "TQQQ"):
        assert is_etf(s), s


def test_case_and_whitespace_insensitive():
    assert is_etf("spy") and is_etf(" qqq ")


def test_single_stocks_and_junk_are_not_etfs():
    for s in ("AAPL", "MSFT", "NVDA", "", None):
        assert not is_etf(s), s


def test_sector_and_index_lists_are_inside_the_set():
    assert set(SECTOR_ETFS) <= KNOWN_ETFS and set(INDEX_ETFS) <= KNOWN_ETFS


def test_sectors_router_uses_the_shared_lists():
    """No duplicate list to drift: sectors.py imports these from app.data.etfs."""
    from app.routers import sectors
    assert sectors.SECTOR_ETFS is SECTOR_ETFS
    assert sectors.INDEX_ETFS is INDEX_ETFS


# Audit round 1, F2. A fund that tracks ONE company carries that company's
# earnings print (leveraged, for most of them) but has no earnings date of its
# own, so as an "ETF" it was exempt from D4 and auto-fired through the print.
# These must count as single stocks -- the safe direction.
SINGLE_STOCK_FUNDS = (
    "NVDL", "NVDU", "NVDX", "NVDD", "NVDQ", "NVDS",      # NVDA
    "TSLL", "TSLR", "TSLT", "TSLQ", "TSLS", "TSLZ",      # TSLA
    "AAPU", "AAPD", "AMZU", "AMZD", "GGLL", "GGLS",      # AAPL, AMZN, GOOGL
    "METU", "METD", "MSFU", "MSFD", "CONL", "MSTU",      # META, MSFT, COIN, MSTR
    "MSTX", "MSTZ", "PLTU", "AMDL", "AVL", "NFXL",       # MSTR, PLTR, AMD, AVGO, NFLX
)


def test_single_stock_leveraged_funds_are_not_etfs():
    assert not is_etf("NVDL") and not is_etf("TSLL")
    for s in SINGLE_STOCK_FUNDS:
        assert s not in KNOWN_ETFS, s
