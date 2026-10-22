"""Provider spellings of our ticker symbols.

Symbols are stored as the exchange lists them (``BRK.B``). Tiingo and yfinance spell
share classes with a dash (``BRK-B``) and return nothing for the dotted form.
Translate only the request; bars are always stored under the caller's symbol.
"""
from __future__ import annotations


def dash_class_ticker(symbol: str) -> str:
    """``BRK.B`` -> ``BRK-B`` for Tiingo and yfinance; other tickers are unchanged."""
    return symbol.strip().upper().replace(".", "-")
