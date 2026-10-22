"""The one owner of the option-strike representation (EXACT-STRIKE).

Every contract id is `SYMBOL|STRIKE|YYYY-MM-DD|C/P`. Until EXACT-STRIKE the
STRIKE part, and the chain rows' `strike` field, were `int(strike)`, so a
fractional strike such as 22.5 was truncated to 22 everywhere (plan
docs/superpowers/plans/2026-10-09-exact-strike-plan.md section 1).

Contracts (pinned by tests/test_strike.py):
  - An INTEGRAL strike is returned as an `int` (185.0 -> 185), so every id
    string and JSON value for an integer strike is byte-identical to the old
    `int(strike)` output and persisted ids keep matching with no migration.
  - A fractional strike is kept exactly, rounded to STRIKE_DP (OCC resolution:
    strike * 1000 is an integer). Its text is Python's shortest round-trip
    repr, which equals JS `${x}` for every value this module can return, so
    the frontend's `contractId` builds the same id
    (tests/fixtures/strike_format_golden.json, read by pytest and Jest).
  - Non-finite, <= 0 (after rounding) and bool inputs are refused with
    ValueError; a non-number raises TypeError or ValueError.
"""
from __future__ import annotations

import math
import re

STRIKE_DP = 3  # OCC resolution: strike * 1000 is an integer

# ASCII digits only: `\d` and float() would also accept other scripts' digits.
_STRIKE_TEXT = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,3})?")


def canonical_strike(raw) -> int | float:
    """Finite positive strike rounded to 3 dp; an integral value is returned as
    int (185.0 -> 185) so JSON and f-strings stay byte-identical to today for
    integer strikes. Raises ValueError for non-finite, <= 0 or bool input."""
    if isinstance(raw, bool):
        raise ValueError(f"strike must be a number, not {raw!r}")
    value = round(float(raw), STRIKE_DP)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"strike must be finite and > 0, got {raw!r}")
    if value.is_integer():
        return int(value)
    return value


def format_strike(raw) -> str:
    """The strike text inside a contract id: str(canonical_strike(raw)).
    185 / 185.0 / '185' / '185.0' -> '185';  22.5 / '22.50' -> '22.5'."""
    return str(canonical_strike(raw))


def parse_strike_text(text: str) -> int | float:
    """Strike text from an id or query param -> canonical_strike. Accepts
    ^\\d{1,5}(\\.\\d{1,3})?$ only (no sign, exponent, underscore, whitespace)."""
    if not isinstance(text, str):
        raise TypeError(f"strike text must be str, got {type(text).__name__}")
    if _STRIKE_TEXT.fullmatch(text) is None:
        raise ValueError(f"malformed strike text {text!r}")
    return canonical_strike(text)
