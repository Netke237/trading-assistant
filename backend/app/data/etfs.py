"""The ONE curated set of exchange-traded funds the backend recognises.

There is no asset-type field anywhere in the data path, so "is this an ETF?" is
answered by membership in this hand-kept set. It exists for decision D4 as
amended by Kenneth on 2026-10-03: an UNKNOWN earnings date caps a single stock's
options trade card at CAUTION and makes the auto-trader refuse to fire it, while
an ETF -- which has no earnings at all -- is unaffected.

FAILURE DIRECTION, deliberately: a symbol NOT in this set is treated as a single
stock. An ETF missing from the list therefore gets a CAUTION card and a refused
auto-fire when its earnings date is unknown (which, for an ETF, is always). That
is the safe direction -- a stock wrongly treated as an ETF would PASS and
auto-fire straight through an earnings print nobody looked up. To stop a
missing ETF being capped, add it here.

`SECTOR_ETFS` and `INDEX_ETFS` keep their order (routers/sectors.py renders the
sector heatmap and index tiles in it) and are imported from here by that router.
"""
from __future__ import annotations

# Order matters: routers/sectors.py renders tiles in this order.
SECTOR_ETFS: list[str] = ["XLK", "XLC", "XLY", "XLI", "XLF", "XLP", "XLV", "XLB", "XLRE", "XLU", "XLE"]
INDEX_ETFS: list[str] = ["SPY", "QQQ"]

_OTHER_ETFS: frozenset[str] = frozenset({
    # Broad US index
    "IWM", "DIA", "VOO", "IVV", "VTI", "RSP", "MDY", "IJH", "IJR", "QQQM", "SPLG", "OEF", "VTV", "VUG",
    # Industry / thematic
    "SMH", "SOXX", "XBI", "IBB", "KRE", "KBE", "XHB", "ITB", "XRT", "XOP", "OIH", "XME", "GDX",
    "GDXJ", "JETS", "XAR", "ITA", "KWEB", "TAN", "ICLN", "ARKK", "ARKG", "IGV", "VNQ", "IYR",
    "XLG", "IYT", "XTN", "XSD", "HACK", "CIBR", "BOTZ", "LIT", "URA", "MOO", "PAVE",
    # Rates / credit
    "TLT", "IEF", "SHY", "HYG", "LQD", "JNK", "AGG", "BND", "TIP", "EMB", "SGOV", "BIL", "VCIT",
    # Commodities / currencies
    "GLD", "SLV", "USO", "UNG", "DBC", "IAU", "GLDM", "PDBC", "CPER", "DBA", "UUP", "FXE", "FXY",
    # International
    "EEM", "EFA", "EWZ", "EWJ", "FXI", "VEA", "VWO", "INDA", "EWW", "EWG", "EWT", "EWY", "EWC",
    "EWU", "EWA", "EWH", "MCHI", "ASHR", "IEMG", "ACWI",
    # Volatility
    "VXX", "UVXY", "SVXY", "VIXY",
    # Leveraged / inverse
    "SQQQ", "TQQQ", "SPXL", "SPXS", "SPXU", "UPRO", "SDS", "SSO", "QLD", "SOXL", "SOXS", "TNA",
    "TZA", "LABU", "LABD", "FAS", "FAZ", "TMF", "TBT", "NUGT", "JNUG", "UCO", "SCO", "BOIL",
    "KOLD", "YINN", "YANG", "PSQ", "SH", "DOG", "RWM", "TECL", "FNGU", "NVDL", "TSLL",
    # Spot crypto / crypto futures
    "IBIT", "FBTC", "GBTC", "ETHE", "BITO",
})

KNOWN_ETFS: frozenset[str] = frozenset(SECTOR_ETFS) | frozenset(INDEX_ETFS) | _OTHER_ETFS


def is_etf(symbol: str | None) -> bool:
    """True when `symbol` is in the curated ETF set (case/whitespace-insensitive).

    False for anything else, including an empty or None symbol: an unrecognised
    symbol is a single stock, which is the safe direction (see module docstring).
    """
    return bool(symbol) and symbol.strip().upper() in KNOWN_ETFS
