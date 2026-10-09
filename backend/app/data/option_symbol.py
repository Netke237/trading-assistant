"""Utilities for converting option symbol formats.

Bamendjou's pipe-delimited format:  "AAPL|185|2025-05-16|C"
OCC option symbol format (Tradier): "AAPL250516C00185000"

OCC construction:
  <SYMBOL><YY><MM><DD><C/P><strike*1000 zero-padded to 8 digits>
"""
from __future__ import annotations

import re
from typing import Literal, cast

# Matches OCC symbols: 1-6 uppercase letters + 6 digits + C/P + 8 digits
_OCC_RE = re.compile(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$')

# Matches Bamendjou's pipe-delimited contract id
_PIPE_RE = re.compile(
    r'^([A-Z]{1,6})\|([0-9]+(?:\.[0-9]+)?)\|(\d{4})-(\d{2})-(\d{2})\|([CP])$'
)


def is_occ(s: str) -> bool:
    """Return True if *s* is already in OCC option symbol format."""
    return bool(_OCC_RE.match(s))


def pipe_to_occ(contract_id: str) -> str:
    """Convert a Bamendjou pipe-delimited contract id to OCC option symbol format.

    >>> pipe_to_occ("AAPL|185|2025-05-16|C")
    'AAPL250516C00185000'
    >>> pipe_to_occ("SPY|1.5|2025-05-16|P")
    'SPY250516P00001500'
    """
    m = _PIPE_RE.match(contract_id)
    if not m:
        raise ValueError(
            f"Cannot convert option symbol {contract_id!r}. "
            "Expected format: SYMBOL|STRIKE|YYYY-MM-DD|C/P "
            f"(e.g. 'AAPL|185|2025-05-16|C')."
        )
    symbol, strike_str, year, month, day, right = m.groups()
    strike_millis = int(round(float(strike_str) * 1000))
    if not (0 < strike_millis <= 99_999_999):
        raise ValueError(
            f"Strike {strike_str!r} out of OCC range (must be > 0 and < 100000)."
        )
    return f"{symbol}{year[2:]}{month}{day}{right}{strike_millis:08d}"


def to_occ(option_symbol: str) -> str:
    """Return *option_symbol* in OCC format, converting from pipe format if necessary.

    If *option_symbol* is already in OCC format it is returned unchanged.
    """
    if is_occ(option_symbol):
        return option_symbol
    return pipe_to_occ(option_symbol)


def option_right(option_symbol: str) -> Literal["C", "P"]:
    """Read the right from a complete OCC or pipe symbol; unknown formats raise."""
    if _OCC_RE.fullmatch(option_symbol):
        return cast(Literal["C", "P"], option_symbol[-9])
    match = _PIPE_RE.fullmatch(option_symbol)
    if match:
        return cast(Literal["C", "P"], match.group(6))
    raise ValueError("Cannot determine option right: expected an OCC or pipe option symbol")
