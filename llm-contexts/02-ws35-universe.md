---
workstream: WS-35
branch: feat/ws-35-universe-expand
phase: 1
depends_on: fix/ws-33-foundation (merged to main)
conflict_class: Zero — creates new files; one targeted modification to scan.py
scan_py_note: WS-35 must merge BEFORE WS-37 (which also touches scan.py). WS-37 rebases on WS-35.
---

# WS-35: Universe Expansion

## Mission

`POST /api/scan` currently accepts `universe: ["SP500"]` from the frontend but iterates over the literal string `"SP500"` as a single symbol — producing no real results (no stock is tickered "SP500"). This workstream makes the backend expand preset strings to their constituent ticker lists before the scoring loop.

**PRD coverage:** B1, FR-07

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/data/universe_presets.py` | Create | `expand_universe()` function + preset symbol lists |
| `backend/app/data/sp500.csv` | Create | ~503 S&P 500 tickers (one per line, header `symbol`) |
| `backend/app/routers/scan.py` | Modify | Call `expand_universe()` before the scoring loop |
| `backend/tests/test_universe.py` | Create | Tests for expansion logic |

**Do NOT touch any other files.**

---

## Read-Only References

- `backend/app/routers/scan.py` lines 109–130 — the `run_scan()` function where `req.universe` is iterated (look for `for symbol in req.universe:`)
- `frontend/lib/universeStore.ts` — preset names: `'SP500' | 'NDX100' | 'DOW30' | 'RUSSELL2000' | 'STOXX600' | 'DAX40' | 'Watchlist' | 'Custom'`

---

## `universe_presets.py` Specification

```python
# backend/app/data/universe_presets.py

from __future__ import annotations
import csv
from pathlib import Path

class PresetUnavailableError(ValueError):
    """Raised when a requested preset is not embedded in this deployment."""
    pass

# NDX100 — embed directly (101 tickers as of 2025-Q1)
NDX100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO",
    "COST", "NFLX", "ASML", "AMD", "AZN", "TMUS", "PEP", "ADBE", "LIN", "QCOM",
    "INTC", "INTU", "AMAT", "TXN", "AMGN", "ISRG", "MU", "BKNG", "VRTX", "LRCX",
    "REGN", "KLAC", "MELI", "PANW", "SNPS", "CDNS", "CRWD", "ORLY", "MAR", "FTNT",
    "ABNB", "CTAS", "WDAY", "MRVL", "MNST", "PYPL", "NXPI", "KDP", "PCAR", "ROST",
    "CPRT", "ODFL", "AEP", "PAYX", "CHTR", "DXCM", "IDXX", "FANG", "FAST", "EXC",
    "VRSK", "GEHC", "BKR", "CTSH", "XEL", "BIIB", "GFS", "EA", "LULU", "CDW",
    "DLTR", "ZS", "ON", "ILMN", "WBD", "SGEN", "SBUX", "TEAM", "ANSS", "CEG",
    "TTWO", "ENPH", "DDOG", "ALGN", "LCID", "PDD", "RIVN", "OKTA", "SIRI", "MRNA",
    "ZM", "EBAY", "MTCH", "NTES", "JD", "MCHP", "HON", "CSCO", "ADSK", "GILD",
    "ADI",
]

# DOW30 — embed directly
DOW30 = [
    "AAPL", "AMGN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW",
    "GS", "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD", "MMM",
    "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "V", "VZ", "WBA", "WMT",
]

_SP500_CSV = Path(__file__).parent / "sp500.csv"


def _load_sp500() -> list[str]:
    if not _SP500_CSV.exists():
        raise PresetUnavailableError("SP500 CSV file not found at backend/app/data/sp500.csv")
    with open(_SP500_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["symbol"].strip() for row in reader if row.get("symbol", "").strip()]


PRESET_UNIVERSES: dict[str, list[str] | None] = {
    "SP500": None,     # loaded lazily from CSV
    "NDX100": NDX100,
    "DOW30": DOW30,
    "RUSSELL2000": None,  # not available — raise error
    "STOXX600": None,     # not available — raise error
    "DAX40": None,        # not available — raise error
}

_UNAVAILABLE = {"RUSSELL2000", "STOXX600", "DAX40"}


def expand_universe(universe: list[str]) -> list[str]:
    """
    Expand any preset keys in `universe` to constituent ticker lists.
    Non-preset strings (individual tickers, custom symbols) pass through unchanged.
    Raises PresetUnavailableError if a preset is flagged as unavailable.
    """
    result: list[str] = []
    seen: set[str] = set()

    for item in universe:
        if item in _UNAVAILABLE:
            raise PresetUnavailableError(
                f"Preset {item} not available in this deployment. "
                f"Available presets: SP500, NDX100, DOW30."
            )
        if item == "SP500":
            tickers = _load_sp500()
        elif item in PRESET_UNIVERSES and PRESET_UNIVERSES[item] is not None:
            tickers = PRESET_UNIVERSES[item]  # type: ignore[assignment]
        else:
            tickers = [item]  # individual ticker — pass through

        for t in tickers:
            if t not in seen:
                seen.add(t)
                result.append(t)

    return result
```

---

## sp500.csv

Create `backend/app/data/sp500.csv` with a header row `symbol` and one S&P 500 ticker per line. Use the Wikipedia S&P 500 component list (as of early 2025). Minimum 500 tickers required (the test checks > 400).

```
symbol
MMM
AOS
ABT
ABBV
...
```

Note: Some tickers have dots (e.g. `BRK.B`) — store them as-is. The scoring loop handles unknown tickers gracefully (they'll be rejected with "no market data").

---

## scan.py Modification

In `backend/app/routers/scan.py`, at the start of `run_scan()`, after logging `scan_started`, add:

```python
# Expand preset universe strings to individual ticker lists
from app.data.universe_presets import expand_universe, PresetUnavailableError
from fastapi import HTTPException

try:
    symbols = expand_universe(req.universe)
except PresetUnavailableError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

Then change `for symbol in req.universe:` to `for symbol in symbols:`.

That is the ONLY change to `scan.py`. Do not touch any other part of the file.

---

## Tests (`backend/tests/test_universe.py`)

```python
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
```

Run: `cd backend && pytest tests/test_universe.py -v` — all pass.

---

## Acceptance Criteria

- [ ] `POST /api/scan` with `universe: ["NDX100"]` routes 101 tickers through the scoring loop
- [ ] `POST /api/scan` with `universe: ["SP500"]` routes > 400 tickers
- [ ] `POST /api/scan` with `universe: ["AAPL", "MSFT"]` still works (custom list passthrough)
- [ ] `POST /api/scan` with `universe: ["RUSSELL2000"]` returns 400 with message containing "not available"
- [ ] `pytest tests/test_universe.py` — all pass
- [ ] No files outside the Owned Files table were modified (especially: no other scan.py changes)

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-35 (Universe Expansion) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-35-universe-expand (already created — checkout before starting)
Base: main (WS-33 merged)

Read the full context doc before writing any code:
F:\Git\GitHub\Trading assistant\llm-contexts\02-ws35-universe.md

Key files to read first (do not modify):
- backend/app/routers/scan.py  (you will add ~6 lines at the top of run_scan())
- frontend/lib/universeStore.ts  (for preset name reference)

Tasks in order:
1. Create backend/app/data/sp500.csv  (~503 S&P 500 tickers, header row "symbol")
2. Create backend/app/data/universe_presets.py  (exactly as specified in context doc)
3. Add expand_universe() call to scan.py run_scan() — only 6 lines, nothing else changes
4. Create backend/tests/test_universe.py
5. Run: cd backend && pytest tests/test_universe.py -v  (all must pass)

IMPORTANT: scan.py merge order — WS-35 must merge before WS-37 (which also touches scan.py).
Make only the minimal change to scan.py described in the context doc.

Return: one-paragraph summary of what you implemented and pytest output.
```
