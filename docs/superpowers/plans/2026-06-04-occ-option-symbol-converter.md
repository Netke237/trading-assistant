# OCC Option Symbol Converter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a utility that converts Bamendjou's pipe-delimited contract id (`AAPL|185|2025-05-16|C`) to OCC option symbol format (`AAPL250516C00185000`), and wire it into the Tradier paper adapter so both the `/broker/option-order` endpoint and the auto-trade fire path send the format Tradier's API requires.

**Architecture:** A pure, I/O-free converter (`backend/app/data/option_symbol.py`) is called inside `TradierPaperAdapter._build_params()` when `option_symbol` is present. Because every option order path for Tradier converges at that method, a single change covers both direct orders and auto-trade triggers. Already-OCC strings are passed through unchanged, so callers that already send OCC format keep working.

**Tech Stack:** Python stdlib only (`re`, `math`). No new dependencies. Tests use `pytest`.

---

## File Structure

**Backend — new**
- `backend/app/data/option_symbol.py` — pure converter: `is_occ`, `pipe_to_occ`, `to_occ`
- `backend/tests/test_option_symbol.py` — unit tests for all conversion cases

**Backend — modified**
- `backend/app/data/tradier_paper.py` — call `to_occ()` inside `_build_params()` when `option_symbol` is present
- `backend/tests/test_tradier_paper.py` — add tests for pipe→OCC conversion and OCC passthrough via the adapter

---

## Background: format reference

| Format | Example | When produced |
|---|---|---|
| Pipe-delimited (Bamendjou) | `AAPL\|185\|2025-05-16\|C` | `contractId()` in `frontend/types/domain.ts` |
| Display label | `AAPL 185C 05/16` | `contractLabel()` in `frontend/types/domain.ts` |
| OCC (required by Tradier) | `AAPL250516C00185000` | This converter |

**OCC construction rules:**
1. Ticker (as-is, up to 6 chars)
2. Year (last 2 digits of YYYY)
3. Month (2-digit MM)
4. Day (2-digit DD)
5. Right (`C` or `P`)
6. Strike × 1000, zero-padded to 8 digits  
   e.g. `185` → `185000` → `00185000`; `1.5` → `1500` → `00001500`; `1000` → `1000000` → `01000000`

---

## Task 1: Option symbol converter utility

**Files:**
- Create: `backend/app/data/option_symbol.py`
- Create: `backend/tests/test_option_symbol.py`

### Step 1: Write the failing tests

Create `backend/tests/test_option_symbol.py`:

```python
import pytest
from app.data.option_symbol import is_occ, pipe_to_occ, to_occ


# ── is_occ ────────────────────────────────────────────────────────────────────

def test_is_occ_recognises_valid_occ():
    assert is_occ("AAPL250516C00185000") is True


def test_is_occ_recognises_put():
    assert is_occ("NVDA260620P00130000") is True


def test_is_occ_rejects_pipe_format():
    assert is_occ("AAPL|185|2025-05-16|C") is False


def test_is_occ_rejects_display_label():
    assert is_occ("AAPL 185C 05/16") is False


# ── pipe_to_occ ───────────────────────────────────────────────────────────────

def test_pipe_to_occ_basic_call():
    assert pipe_to_occ("AAPL|185|2025-05-16|C") == "AAPL250516C00185000"


def test_pipe_to_occ_put():
    assert pipe_to_occ("NVDA|130|2026-06-20|P") == "NVDA260620P00130000"


def test_pipe_to_occ_fractional_strike():
    # 1.5 × 1000 = 1500 → 00001500
    assert pipe_to_occ("SPY|1.5|2025-05-16|C") == "SPY250516C00001500"


def test_pipe_to_occ_large_strike():
    # 1000 × 1000 = 1_000_000 → 01000000
    assert pipe_to_occ("AMZN|1000|2025-05-16|C") == "AMZN250516C01000000"


def test_pipe_to_occ_half_dollar_strike():
    # 185.5 × 1000 = 185500 → 00185500
    assert pipe_to_occ("AAPL|185.5|2025-05-16|C") == "AAPL250516C00185500"


def test_pipe_to_occ_three_char_symbol():
    assert pipe_to_occ("SPY|450|2025-12-31|P") == "SPY251231P00450000"


def test_pipe_to_occ_invalid_raises():
    with pytest.raises(ValueError, match="Cannot convert"):
        pipe_to_occ("AAPL_185_2025-05-16_C")   # underscore delimiters


def test_pipe_to_occ_display_label_raises():
    with pytest.raises(ValueError, match="Cannot convert"):
        pipe_to_occ("AAPL 185C 05/16")


# ── to_occ ────────────────────────────────────────────────────────────────────

def test_to_occ_converts_pipe_format():
    assert to_occ("AAPL|185|2025-05-16|C") == "AAPL250516C00185000"


def test_to_occ_passthrough_already_occ():
    occ = "AAPL250516C00185000"
    assert to_occ(occ) == occ
```

### Step 2: Run to verify failure

```bash
cd backend && python -m pytest tests/test_option_symbol.py -v
```

Expected: `ModuleNotFoundError: app.data.option_symbol`

### Step 3: Implement the converter

Create `backend/app/data/option_symbol.py`:

```python
"""Utilities for converting option symbol formats.

Bamendjou's pipe-delimited format:  "AAPL|185|2025-05-16|C"
OCC option symbol format (Tradier): "AAPL250516C00185000"

OCC construction:
  <SYMBOL><YY><MM><DD><C/P><strike*1000 zero-padded to 8 digits>
"""
from __future__ import annotations

import re

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
    return f"{symbol}{year[2:]}{month}{day}{right}{strike_millis:08d}"


def to_occ(option_symbol: str) -> str:
    """Return *option_symbol* in OCC format, converting from pipe format if necessary.

    If *option_symbol* is already in OCC format it is returned unchanged.
    """
    if is_occ(option_symbol):
        return option_symbol
    return pipe_to_occ(option_symbol)
```

### Step 4: Run to verify all 13 tests pass

```bash
cd backend && python -m pytest tests/test_option_symbol.py -v
```

Expected: `13 passed`

### Step 5: Commit

```bash
git add backend/app/data/option_symbol.py backend/tests/test_option_symbol.py
git commit -m "feat(broker): OCC option symbol converter — pipe-delimited → OCC format"
```

---

## Task 2: Wire converter into Tradier paper adapter

**Files:**
- Modify: `backend/app/data/tradier_paper.py`
- Modify: `backend/tests/test_tradier_paper.py`

### Step 1: Write the failing tests

Append to `backend/tests/test_tradier_paper.py`:

```python
# ── OCC conversion in _build_params ──────────────────────────────────────────

def test_build_params_converts_pipe_to_occ():
    """Adapter converts Bamendjou pipe id to OCC when building option params."""
    adapter = _adapter()
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="LMT", limit_price=2.50, tif="DAY",
        option_symbol="AAPL|185|2025-05-16|C",   # pipe format in
    )
    params = adapter._build_params(order)
    assert params["option_symbol"] == "AAPL250516C00185000"  # OCC out
    assert params["class"] == "option"


def test_build_params_passthrough_occ():
    """Adapter passes already-OCC symbols through unchanged."""
    adapter = _adapter()
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="LMT", limit_price=2.50, tif="DAY",
        option_symbol="AAPL250516C00185000",   # already OCC
    )
    params = adapter._build_params(order)
    assert params["option_symbol"] == "AAPL250516C00185000"
```

### Step 2: Run to verify failure

```bash
cd backend && python -m pytest tests/test_tradier_paper.py::test_build_params_converts_pipe_to_occ tests/test_tradier_paper.py::test_build_params_passthrough_occ -v
```

Expected: both FAIL — the adapter currently passes `option_symbol` through as-is without conversion.

### Step 3: Wire `to_occ` into `_build_params`

In `backend/app/data/tradier_paper.py`, add one import at the top of the file (after the existing imports):

```python
from app.data.option_symbol import to_occ
```

Then in `_build_params`, update the block where `option_symbol` is added to params. Change:

```python
        if is_option:
            params["option_symbol"] = order.option_symbol
```

to:

```python
        if is_option:
            params["option_symbol"] = to_occ(order.option_symbol)
```

That is the entire code change. The full updated `_build_params` method for reference:

```python
    def _build_params(self, order: BrokerOrder) -> dict:
        is_option = bool(order.option_symbol)
        params: dict = {
            "class":    "option" if is_option else "equity",
            "symbol":   order.symbol,
            "side":     order.action.lower(),
            "quantity": str(order.quantity),
            "type":     "market" if order.order_type == "MKT" else "limit",
            "duration": order.tif.lower(),
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            params["price"] = str(order.limit_price)
        if is_option:
            params["option_symbol"] = to_occ(order.option_symbol)
        return params
```

### Step 4: Run to verify all Tradier tests pass

```bash
cd backend && python -m pytest tests/test_tradier_paper.py -v
```

Expected: all 6 tests pass (4 original + 2 new).

### Step 5: Run the full backend suite to confirm no regressions

```bash
cd backend && python -m pytest tests/ -q
```

Expected: all pass (no new failures).

### Step 6: Commit

```bash
git add backend/app/data/tradier_paper.py backend/tests/test_tradier_paper.py
git commit -m "feat(broker): wire OCC converter into TradierPaperAdapter — covers option-order + auto-trade paths"
```

---

## Coverage verification

After Task 2, both option-order paths for Tradier are covered by the single change in `_build_params`:

| Path | Call chain | Covered? |
|---|---|---|
| Direct `/broker/option-order` | `broker.py → BrokerOrder → TradierPaperAdapter._build_params` | ✅ |
| Auto-trade fire (all 3 triggers) | `auto_trader.fire() → execute_option_order() → BrokerRouter.execute() → TradierPaperAdapter._build_params` | ✅ |
| IBKR paper orders | `IbkrPaperAdapter._build_payload` (uses `conid`, not `option_symbol`) | No change needed |
