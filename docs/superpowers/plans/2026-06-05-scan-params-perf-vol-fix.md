# Scan Parameters Panel, Performance Fixes & Vol Rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose five scan-rejection thresholds as user-editable controls, cut the 27-minute scan to ~3 minutes by fixing three backend bottlenecks, and stop the vol rule from silently penalising every stock scan.

**Architecture:** Nine tasks in dependency order — backend-only fixes first (vol YAML, strategy engine signatures, schema, router, historical store guard, confidence cache), then frontend (Zustand store, Settings section, Step 5 override panel). Each task is independently committable.

**Tech Stack:** FastAPI / Python 3.11, Pydantic v2, pytest; Next.js 15 App Router, TypeScript 5.7, Zustand v5, CSS Modules.

---

## File Map

| File | Task | Change |
|---|---|---|
| `backend/config/scoring_rules.yaml` | 1 | Set `iv_rank_pass_max: null` for Swing + Position |
| `backend/app/services/strategy_engine.py` | 2 | Add `tolerance` param to `pullback_ema_signal`; add `lookback` param to `ma_crossover_signal` |
| `backend/app/schemas/stock_scan.py` | 3 | Add `pullback_tolerance_pct`, `ma_crossover_lookback`, `breakout_volume_mult` fields |
| `backend/app/routers/stock_scan.py` | 4 | Add `_SIGNAL_KWARGS` dispatch table; batch price pre-fetch; wire 3 new params |
| `backend/app/services/historical_store.py` | 5 | Add `most_recent_trading_day()`; fix stale-check |
| `backend/app/data/confidence_cache.py` | 6 | Add SQLite L2 layer (startup warm-load + write-through) |
| `frontend/lib/scanParamsStore.ts` | 7 | New persisted Zustand store for 5 scan parameters |
| `frontend/app/(frame)/settings/page.tsx` | 8 | Add `'strategy'` sub-nav entry + `StrategyScanForm` component |
| `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | 9 | Collapsible override panel reading from store |
| `backend/tests/test_vol_rule_fix.py` | 1 | New — vol rule PASS 90 when iv_rank=None on Swing/Position |
| `backend/tests/test_strategy_params.py` | 2 | New — tolerance + lookback params respected |
| `backend/tests/test_scan_schema.py` | 3 | New — schema accepts 3 new fields |
| `backend/tests/test_historical_store_guard.py` | 5 | New — trading day guard skips Tiingo fetch |
| `backend/tests/test_confidence_cache.py` | 6 | New — L2 SQLite warm-load |

---

## Task 1 — Fix vol rule: stop penalising stock scans for missing IV data

**Problem:** `_rule_vol` returns CAUTION 50 for Swing and Position horizons when `iv_rank=None`. Stock scans never pass IV data, so every stock takes a vol-score hit, pushing borderline symbols into REJECT.

**Files:**
- Modify: `backend/config/scoring_rules.yaml` lines 100 and 240
- Create: `backend/tests/test_vol_rule_fix.py`

- [ ] **Step 1.1: Write the failing test**

Create `backend/tests/test_vol_rule_fix.py`:

```python
"""Verify _rule_vol returns PASS 90 (not CAUTION 50) when iv_rank=None on Swing/Position."""
import pytest
from app.scoring.stock_scorer import score_stock
from app.services.strategy_engine import pullback_ema_signal


def _flat_bars(n: int = 200, price: float = 100.0) -> list[dict]:
    return [
        {"open": price, "high": price + 1, "low": price - 1,
         "close": price, "volume": 1_000}
        for _ in range(n)
    ]


def test_swing_vol_rule_pass_when_no_iv():
    """score_stock on Swing without iv_rank should not produce CAUTION from vol rule."""
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Swing", bars=bars)
    # The vol component must be PASS (90), not CAUTION (50).
    # Inspect rule_results if exposed, otherwise verify the score is not dragged down
    # by the vol rule alone.  We do this by checking no rule in the card returns
    # name="vol" with status="CAUTION".
    vol_rules = [r for r in card.rule_results if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "PASS", (
        f"Expected vol rule PASS when iv_rank=None on Swing, got {vol_rules[0].status}"
    )


def test_position_vol_rule_pass_when_no_iv():
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Position", bars=bars)
    vol_rules = [r for r in card.rule_results if r.name == "vol"]
    assert vol_rules, "vol rule must be present"
    assert vol_rules[0].status == "PASS", (
        f"Expected vol rule PASS when iv_rank=None on Position, got {vol_rules[0].status}"
    )


def test_intraday_vol_rule_already_pass():
    """Intraday was already null — verify it stays PASS (regression guard)."""
    bars = _flat_bars(200)
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Intraday", bars=bars)
    vol_rules = [r for r in card.rule_results if r.name == "vol"]
    assert not vol_rules or vol_rules[0].status == "PASS"
```

- [ ] **Step 1.2: Run to confirm failure**

```bash
cd backend && pytest tests/test_vol_rule_fix.py -v
```

Expected: `FAILED` — vol rule returns CAUTION on Swing and Position.

> **If `card.rule_results` does not exist**, run `python -c "from app.scoring.stock_scorer import score_stock; c = score_stock('AAPL','Bullish','Swing',[]); print(dir(c))"` to find the attribute name and adjust the test accordingly.

- [ ] **Step 1.3: Fix `scoring_rules.yaml`**

In `backend/config/scoring_rules.yaml`:

Line ~100 (Swing horizon, `vol` block) — change:
```yaml
      iv_rank_pass_max: 34
```
to:
```yaml
      iv_rank_pass_max: null
```

Line ~240 (Position horizon, `vol` block) — change:
```yaml
      iv_rank_pass_max: 44
```
to:
```yaml
      iv_rank_pass_max: null
```

Intraday (line ~170) already has `iv_rank_pass_max: null` — leave it unchanged.

- [ ] **Step 1.4: Run tests to confirm pass**

```bash
cd backend && pytest tests/test_vol_rule_fix.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
git add backend/config/scoring_rules.yaml backend/tests/test_vol_rule_fix.py
git commit -m "fix(scoring): set iv_rank_pass_max null for Swing+Position — stop penalising stock scans without IV data"
```

---

## Task 2 — Strategy engine: add `tolerance` and `lookback` parameters

**Problem:** Three strategy tolerances are hardcoded literals. They need to be function parameters so the router can pass user-supplied values.

**Files:**
- Modify: `backend/app/services/strategy_engine.py`
- Create: `backend/tests/test_strategy_params.py`

- [ ] **Step 2.1: Write failing tests**

Create `backend/tests/test_strategy_params.py`:

```python
"""Verify strategy signal functions respect caller-supplied tolerance/lookback params."""
import pytest
from app.services.strategy_engine import (
    pullback_ema_signal, ma_crossover_signal, breakout_base_signal,
)


def _uptrend(n: int = 200) -> list[dict]:
    bars, price = [], 100.0
    for _ in range(n):
        price += 0.5
        bars.append({"open": price - 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": 1_000})
    return bars


def test_pullback_ema_respects_tight_tolerance():
    """With tolerance=0.001 (0.1%), the 2% pullback from Task 2 tests must now return None."""
    bars = _uptrend(200)
    # Make last 20 bars sit 2% above the EMA approximation
    ema_approx = bars[-21]["close"]
    target = ema_approx * 1.02
    for i in range(-20, 0):
        bars[i] = {"open": target - 0.1, "high": target + 0.2,
                   "low": target - 0.2, "close": target + 0.1, "volume": 1_000}
    signal = pullback_ema_signal(bars, tolerance=0.001)
    assert signal is None, "With tolerance=0.001, 2% above EMA must be rejected"


def test_pullback_ema_respects_wide_tolerance():
    """With tolerance=0.10 (10%), a 5% pullback must fire."""
    bars = _uptrend(200)
    ema_approx = bars[-21]["close"]
    target = ema_approx * 1.05
    for i in range(-20, 0):
        bars[i] = {"open": target - 0.1, "high": target + 0.2,
                   "low": target - 0.2, "close": target + 0.1, "volume": 1_000}
    signal = pullback_ema_signal(bars, tolerance=0.10)
    assert signal is not None, "With tolerance=0.10, 5% above EMA must fire"


def test_ma_crossover_respects_short_lookback():
    """With lookback=2, a cross 5 bars ago must return None."""
    bars = []
    for _ in range(60):
        bars.append({"open": 79.9, "high": 80.5, "low": 79.5,
                     "close": 80.0, "volume": 1_000})
    price = 80.0
    for _ in range(135):
        price += 2.0
        bars.append({"open": price - 0.1, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 1_000})
    for _ in range(5):
        bars.append({"open": price - 0.1, "high": price + 0.2,
                     "low": price - 0.2, "close": price, "volume": 1_000})
    signal = ma_crossover_signal(bars, lookback=2)
    assert signal is None, "With lookback=2, cross 5 bars ago must be outside window"


def test_ma_crossover_respects_long_lookback():
    """With lookback=20, a cross 5 bars ago must fire."""
    bars = []
    for _ in range(60):
        bars.append({"open": 79.9, "high": 80.5, "low": 79.5,
                     "close": 80.0, "volume": 1_000})
    price = 80.0
    for _ in range(135):
        price += 2.0
        bars.append({"open": price - 0.1, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 1_000})
    for _ in range(5):
        bars.append({"open": price - 0.1, "high": price + 0.2,
                     "low": price - 0.2, "close": price, "volume": 1_000})
    signal = ma_crossover_signal(bars, lookback=20)
    assert signal is not None, "With lookback=20, cross 5 bars ago must fire"
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
cd backend && pytest tests/test_strategy_params.py -v
```

Expected: `FAILED` — functions don't accept `tolerance` or `lookback` yet.

- [ ] **Step 2.3: Add `tolerance` parameter to `pullback_ema_signal`**

In `backend/app/services/strategy_engine.py`, change the function signature from:

```python
def pullback_ema_signal(
    bars: list[dict],
    *,
    ema_period: int = 20,
    trend_sma: int = 50,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
) -> StrategySignal | None:
```

to:

```python
def pullback_ema_signal(
    bars: list[dict],
    *,
    ema_period: int = 20,
    trend_sma: int = 50,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    tolerance: float = 0.04,
) -> StrategySignal | None:
```

Then replace the hardcoded tolerance check (currently `<= 0.04`) with the parameter:

```python
    # Pullback: price within `tolerance` of 20-EMA from above
    if not (0 <= (current - ema_val) / ema_val <= tolerance):
        return None
```

- [ ] **Step 2.4: Add `lookback` parameter to `ma_crossover_signal`**

In `backend/app/services/strategy_engine.py`, change the function signature from:

```python
def ma_crossover_signal(
    bars: list[dict],
    *,
    fast: int = 20,
    slow: int = 50,
) -> StrategySignal | None:
    """Bullish: 20-SMA crosses above 50-SMA within the last 3 bars."""
```

to:

```python
def ma_crossover_signal(
    bars: list[dict],
    *,
    fast: int = 20,
    slow: int = 50,
    lookback: int = 10,
) -> StrategySignal | None:
    """Bullish: 20-SMA crosses above 50-SMA within the last `lookback` bars."""
```

Then update the length guard and the loop:

```python
    if len(fast_ma) < lookback + 1 or len(slow_ma) < lookback + 1:
        return None
    # Recent cross: fast crossed above slow within last `lookback` bars
    for i in range(-lookback, 0):
```

- [ ] **Step 2.5: Run tests**

```bash
cd backend && pytest tests/test_strategy_params.py tests/test_strategy_engine.py -v
```

Expected: all PASS.

- [ ] **Step 2.6: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_params.py
git commit -m "feat(strategy): add tolerance param to pullback_ema_signal, lookback param to ma_crossover_signal"
```

---

## Task 3 — Schema: add three new `StockScanRequest` fields

**Problem:** The API has no way to accept user-supplied signal tolerances.

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Create: `backend/tests/test_scan_schema.py`

- [ ] **Step 3.1: Write failing tests**

Create `backend/tests/test_scan_schema.py`:

```python
"""Verify StockScanRequest accepts the three new tolerance fields."""
from app.schemas.stock_scan import StockScanRequest


def _base() -> dict:
    return dict(universe=["SP500"], direction="Bullish",
                horizon="Swing", strategy="pullback_ema")


def test_new_fields_have_correct_defaults():
    req = StockScanRequest(**_base())
    assert req.pullback_tolerance_pct == 0.04
    assert req.ma_crossover_lookback == 10
    assert req.breakout_volume_mult == 1.1


def test_new_fields_accept_custom_values():
    req = StockScanRequest(
        **_base(),
        pullback_tolerance_pct=0.06,
        ma_crossover_lookback=15,
        breakout_volume_mult=1.3,
    )
    assert req.pullback_tolerance_pct == 0.06
    assert req.ma_crossover_lookback == 15
    assert req.breakout_volume_mult == 1.3
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
cd backend && pytest tests/test_scan_schema.py -v
```

Expected: `FAILED` — fields don't exist yet.

- [ ] **Step 3.3: Add the three fields to `StockScanRequest`**

In `backend/app/schemas/stock_scan.py`, add three lines after `universe` and `symbols`:

```python
class StockScanRequest(BaseModel):
    universe:    list[str]
    symbols:     Optional[list[str]] = None
    direction:   Literal["Bullish", "Bearish"]
    horizon:     Literal["Intraday", "Swing", "Position"]
    strategy:    Strategy
    pullback_tolerance_pct: float = 0.04   # ← new
    ma_crossover_lookback:  int   = 10     # ← new
    breakout_volume_mult:   float = 1.1    # ← new
    min_price:   Optional[float] = None
    max_price:   Optional[float] = None
    min_cap_usd: Optional[float] = None
    max_cap_usd: Optional[float] = None
    account_size:       float = 50_000.0
    risk_pct:           Optional[float] = 0.01
    risk_fixed_usd:     Optional[float] = None
    bt_min_trades:      int   = 10
    bt_min_win_rate:    float = 0.45
```

- [ ] **Step 3.4: Run tests**

```bash
cd backend && pytest tests/test_scan_schema.py -v
```

Expected: both PASS.

- [ ] **Step 3.5: Commit**

```bash
git add backend/app/schemas/stock_scan.py backend/tests/test_scan_schema.py
git commit -m "feat(schema): add pullback_tolerance_pct, ma_crossover_lookback, breakout_volume_mult to StockScanRequest"
```

---

## Task 4 — Router: `_SIGNAL_KWARGS` dispatch + batch price pre-fetch

**Problem:** (a) Signal functions are called with no kwargs — new tolerance fields are ignored. (b) 519 individual Tradier price calls instead of one batch.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`

- [ ] **Step 4.1: Read the current router file**

Open `backend/app/routers/stock_scan.py` and note:
- The `_SIGNAL_FNS` dict (around line 29)
- The `_process_stock` signature (around line 50)
- The `fetch_price_async` call (around line 53)
- The `run_stock_scan` task-gathering block (around line 144)

- [ ] **Step 4.2: Add `_SIGNAL_KWARGS` dispatch table**

After the `_SIGNAL_FNS` dict, add:

```python
_SIGNAL_KWARGS: dict[str, object] = {
    "pullback_ema":       lambda r: {"tolerance":   r.pullback_tolerance_pct},
    "breakout_base":      lambda r: {"volume_mult": r.breakout_volume_mult},
    "ma_crossover":       lambda r: {"lookback":    r.ma_crossover_lookback},
    "mean_reversion_rsi": lambda r: {},
}
```

- [ ] **Step 4.3: Add `fetch_quotes` import**

At the top of the file, add `fetch_quotes` to the imports from `app.data.market`:

```python
from app.data.market import fetch_price_async, fetch_company_name_async, fetch_quotes
```

- [ ] **Step 4.4: Update `_process_stock` to accept `price_map`**

Replace the `_process_stock` signature and the `fetch_price_async` block:

```python
async def _process_stock(
    symbol: str,
    req: StockScanRequest,
    scan_id: str,
    price_map: dict[str, dict],
) -> PositionCardOut | dict:
    async with _SCAN_SEM:
        try:
            quote = price_map.get(symbol)
            price = float(quote["last"]) if quote else None
            if not price:
                return {"symbol": symbol, "reason": "no price data"}

            # Company name (cached after first run — per-symbol is fine)
            async with httpx.AsyncClient(timeout=10) as client:
                company = await fetch_company_name_async(client, symbol)
```

Remove the old `asyncio.gather(fetch_price_async(...), fetch_company_name_async(...))` block.

The rest of `_process_stock` from the `if req.min_price` check onwards is unchanged.

- [ ] **Step 4.5: Wire `_SIGNAL_KWARGS` in `_process_stock`**

Replace the bare `signal = signal_fn(bars[-120:])` call with:

```python
            signal_kwargs = _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req)
            signal = signal_fn(bars[-120:], **signal_kwargs)
```

- [ ] **Step 4.6: Batch price fetch in `run_stock_scan`**

In `run_stock_scan`, replace the task-launching block:

```python
    # Pre-fetch all prices in one Tradier call (removes 519 individual HTTP requests)
    try:
        price_map = await asyncio.to_thread(fetch_quotes, symbols)
    except Exception as exc:
        logger.warning("stock_scan: batch price fetch failed (%s) — falling back to empty map", exc)
        price_map = {}

    tasks = [_process_stock(s, req, scan_id, price_map) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

- [ ] **Step 4.7: Verify backend starts cleanly**

```bash
cd backend && python -m uvicorn app.main:app --port 8000 --reload
```

Expected: server starts, no import errors. Ctrl+C to stop.

- [ ] **Step 4.8: Commit**

```bash
git add backend/app/routers/stock_scan.py
git commit -m "feat(stock-scan): wire signal kwargs from request; batch Tradier price pre-fetch"
```

---

## Task 5 — Historical store: skip Tiingo fetch when data is current

**Problem:** `get_bars()` fetches a delta from Tiingo on every call because `last < end` is always true when `end == date.today()` and you last stored yesterday's bar. After market close, there is no new data to fetch.

**Files:**
- Modify: `backend/app/services/historical_store.py`
- Create: `backend/tests/test_historical_store_guard.py`

- [ ] **Step 5.1: Write failing tests**

Create `backend/tests/test_historical_store_guard.py`:

```python
"""Verify most_recent_trading_day() and the stale-check guard."""
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock
import pytest


def test_most_recent_trading_day_weekday():
    from app.services.historical_store import most_recent_trading_day
    # Wednesday → same day
    wed = date(2025, 6, 4)  # known Wednesday
    with patch("app.services.historical_store.date") as mock_date:
        mock_date.today.return_value = wed
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        result = most_recent_trading_day()
    assert result == wed


def test_most_recent_trading_day_saturday():
    from app.services.historical_store import most_recent_trading_day
    sat = date(2025, 6, 7)  # known Saturday
    with patch("app.services.historical_store.date") as mock_date:
        mock_date.today.return_value = sat
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        result = most_recent_trading_day()
    assert result == date(2025, 6, 6)  # Friday


def test_most_recent_trading_day_sunday():
    from app.services.historical_store import most_recent_trading_day
    sun = date(2025, 6, 8)  # known Sunday
    with patch("app.services.historical_store.date") as mock_date:
        mock_date.today.return_value = sun
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        result = most_recent_trading_day()
    assert result == date(2025, 6, 6)  # Friday
```

- [ ] **Step 5.2: Run to confirm failure**

```bash
cd backend && pytest tests/test_historical_store_guard.py -v
```

Expected: `FAILED` — `most_recent_trading_day` does not exist yet.

- [ ] **Step 5.3: Add `most_recent_trading_day` helper and fix stale-check**

In `backend/app/services/historical_store.py`, at the top of the file (after existing imports, before the first function), add:

```python
def most_recent_trading_day() -> date:
    """Return the most recent US market close date (Mon–Fri, no holiday check).

    On weekends returns the preceding Friday.  During live market hours today
    is returned (data may still be updating).
    """
    today = date.today()
    weekday = today.weekday()   # 0=Mon … 6=Sun
    if weekday == 5:             # Saturday → Friday
        return today - timedelta(days=1)
    if weekday == 6:             # Sunday → Friday
        return today - timedelta(days=2)
    return today
```

Then in `get_bars()`, find the line:

```python
        fetch_needed = (last is None) or (last < end)
```

Replace it with:

```python
        fetch_needed = (last is None) or (last < most_recent_trading_day())
```

- [ ] **Step 5.4: Run tests**

```bash
cd backend && pytest tests/test_historical_store_guard.py -v
```

Expected: all 3 PASS.

- [ ] **Step 5.5: Commit**

```bash
git add backend/app/services/historical_store.py backend/tests/test_historical_store_guard.py
git commit -m "perf(historical-store): skip Tiingo delta fetch when data is already current for the trading day"
```

---

## Task 6 — Confidence cache: SQLite L2 layer (survives server restarts)

**Problem:** `confidence_cache.py` is a pure in-memory dict. Every server restart is a full cold-start: `compute_confidence` runs for every symbol that passes the backtest gate, consuming 8–15 minutes.

**Files:**
- Modify: `backend/app/data/confidence_cache.py`
- Create: `backend/tests/test_confidence_cache.py`

- [ ] **Step 6.1: Write failing tests**

Create `backend/tests/test_confidence_cache.py`:

```python
"""Verify confidence cache L1/L2 behaviour."""
import time
import tempfile
import os
import pytest


def _fresh_module(db_path: str):
    """Import confidence_cache with a patched DB path, simulating fresh process start."""
    import importlib, sys
    # Patch the module-level DB_PATH before importing
    import app.data.confidence_cache as cc
    original_path = cc._DB_PATH
    cc._DB_PATH = db_path
    # Clear L1 to simulate restart
    cc._store.clear()
    # Re-run warm-load
    cc._warm_load()
    return cc, original_path


def test_set_and_get_in_memory():
    import app.data.confidence_cache as cc
    cc._store.clear()
    cc.set_cached("k1", {"confidence": 70, "sample_size": 100})
    result = cc.get_cached("k1")
    assert result == {"confidence": 70, "sample_size": 100}


def test_l2_survives_l1_clear():
    """After clearing L1 and re-running warm_load from SQLite, key is recovered."""
    import app.data.confidence_cache as cc
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Write with temp DB
        original = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc._store.clear()

        cc.set_cached("k_persist", {"confidence": 55, "sample_size": 42})
        assert cc.get_cached("k_persist") is not None

        # Simulate restart: clear L1, reload from DB
        cc._store.clear()
        cc._warm_load()

        result = cc.get_cached("k_persist")
        assert result == {"confidence": 55, "sample_size": 42}
    finally:
        cc._DB_PATH = original
        os.unlink(db_path)


def test_expired_entries_not_returned():
    import app.data.confidence_cache as cc
    import sqlite3
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        original = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc._store.clear()

        # Write an entry that expires 1 second ago
        expired_ts = time.time() - 1
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO confidence_cache VALUES (?, ?, ?)",
            ("expired_key", '{"confidence": 99, "sample_size": 1}', expired_ts),
        )
        conn.commit()
        conn.close()

        # Warm-load should skip expired entries
        cc._warm_load()
        assert cc.get_cached("expired_key") is None
    finally:
        cc._DB_PATH = original
        os.unlink(db_path)
```

- [ ] **Step 6.2: Run to confirm failure**

```bash
cd backend && pytest tests/test_confidence_cache.py -v
```

Expected: `FAILED` — `_DB_PATH`, `_init_db`, `_warm_load` don't exist yet.

- [ ] **Step 6.3: Add SQLite L2 layer to `confidence_cache.py`**

Replace the entire contents of `backend/app/data/confidence_cache.py` with:

```python
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_store: dict[str, dict] = {}

_TTL_SECONDS = 7 * 24 * 3600  # weekly

# L2 SQLite path — sits next to the module; overridable in tests via _DB_PATH.
_DB_PATH: str = str(Path(__file__).parent.parent.parent.parent / "data" / "confidence_cache.db")


def cache_key(symbol: str, direction: str, horizon: str, atr_mult: float = 1.5) -> str:
    return f"{symbol.upper()}|{direction.lower()}|{horizon.lower()}|{float(atr_mult):g}"


# ── SQLite helpers ─────────────────────────────────────────────────────────────

def _init_db() -> None:
    """Create the SQLite table if it doesn't exist."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confidence_cache (
                cache_key  TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _warm_load() -> None:
    """On startup: load all non-expired DB rows into the in-memory store."""
    try:
        _init_db()
        now = time.time()
        conn = sqlite3.connect(_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT cache_key, value, expires_at FROM confidence_cache WHERE expires_at > ?",
                (now,),
            ).fetchall()
        finally:
            conn.close()
        with _lock:
            for key, value_json, expires_at in rows:
                try:
                    parsed = json.loads(value_json)
                    # Re-add a synthetic _ts so get_cached TTL check works
                    parsed["_ts"] = expires_at - _TTL_SECONDS
                    _store[key] = parsed
                except Exception:
                    pass
    except Exception:
        pass  # Never block startup on cache failure


def _write_db(key: str, value: dict, expires_at: float) -> None:
    """Write or update one row in SQLite.  Called from set_cached (inside lock)."""
    try:
        payload = {k: v for k, v in value.items() if k != "_ts"}
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO confidence_cache VALUES (?, ?, ?)",
                (key, json.dumps(payload), expires_at),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # Never block a scan on cache write failure


# ── Public API (unchanged call sites) ─────────────────────────────────────────

def set_cached(key: str, value: dict) -> None:
    now = time.time()
    expires_at = now + _TTL_SECONDS
    with _lock:
        _store[key] = {**value, "_ts": now}
    _write_db(key, value, expires_at)


def get_cached(key: str) -> dict | None:
    with _lock:
        v = _store.get(key)
        if v is None:
            return None
        if time.time() - v.get("_ts", 0) > _TTL_SECONDS:
            del _store[key]
            return None
        return {k: val for k, val in v.items() if k != "_ts"}


def clear_cache() -> None:
    with _lock:
        _store.clear()


# Warm-load on module import (once per process).
_warm_load()
```

- [ ] **Step 6.4: Ensure the `data/` directory exists**

```bash
mkdir -p "F:/Git/GitHub/Trading assistant/backend/data"
```

Add a `.gitkeep`:

```bash
touch "F:/Git/GitHub/Trading assistant/backend/data/.gitkeep"
```

- [ ] **Step 6.5: Run tests**

```bash
cd backend && pytest tests/test_confidence_cache.py -v
```

Expected: all 3 PASS.

- [ ] **Step 6.6: Commit**

```bash
git add backend/app/data/confidence_cache.py backend/tests/test_confidence_cache.py backend/data/.gitkeep
git commit -m "perf(confidence-cache): add SQLite L2 layer so cache survives server restarts"
```

---

## Task 7 — Frontend: `scanParamsStore.ts` (new Zustand store)

**Problem:** No persistent store for scan parameter defaults — needed by both Settings and Step 5.

**Files:**
- Create: `frontend/lib/scanParamsStore.ts`

- [ ] **Step 7.1: Create the store**

Create `frontend/lib/scanParamsStore.ts`:

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface ScanParams {
  pullbackTolerancePct: number;   // fraction: 0.04 = 4%
  maCrossoverLookback:  number;   // bars
  breakoutVolumeMult:   number;   // multiplier
  btMinTrades:          number;   // count
  btMinWinRate:         number;   // fraction: 0.45 = 45%
}

const DEFAULTS: ScanParams = {
  pullbackTolerancePct: 0.04,
  maCrossoverLookback:  10,
  breakoutVolumeMult:   1.1,
  btMinTrades:          10,
  btMinWinRate:         0.45,
};

interface ScanParamsStore extends ScanParams {
  setParam: <K extends keyof ScanParams>(key: K, value: ScanParams[K]) => void;
  resetToDefaults: () => void;
}

export const useScanParamsStore = create<ScanParamsStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setParam: (key, value) => set({ [key]: value }),
      resetToDefaults: () => set({ ...DEFAULTS }),
    }),
    {
      name: 'bamendjou:scan-params',
      version: 1,
    },
  ),
);

export { DEFAULTS as SCAN_PARAM_DEFAULTS };
```

- [ ] **Step 7.2: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 7.3: Commit**

```bash
git add frontend/lib/scanParamsStore.ts
git commit -m "feat(store): add scanParamsStore — persisted scan tolerance + backtest defaults"
```

---

## Task 8 — Settings page: Strategy scan section

**Problem:** No UI for setting the 5 scan parameter defaults persistently.

**Files:**
- Modify: `frontend/app/(frame)/settings/page.tsx`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 8.1: Add `symbols` to the `postStockScan` TypeScript type in `api.ts`**

> **Check first:** open `frontend/lib/api.ts` and search for `postStockScan`. If it already has `pullback_tolerance_pct` fields, skip this step.

In `frontend/lib/api.ts`, update the `postStockScan` type to include the three new tolerance fields:

```typescript
  postStockScan: (req: {
    universe: string[]; direction: string; horizon: string;
    strategy: string; symbols?: string[];
    pullback_tolerance_pct?: number;
    ma_crossover_lookback?: number;
    breakout_volume_mult?: number;
    account_size?: number; risk_pct?: number;
    risk_fixed_usd?: number; bt_min_trades?: number; bt_min_win_rate?: number;
    min_price?: number; max_price?: number;
  }) => post<StockScanResult>('/api/stock-scan', req),
```

- [ ] **Step 8.2: Add `'strategy'` to the Settings sub-nav**

In `frontend/app/(frame)/settings/page.tsx`, update the `Section` type and `SECTIONS` array:

```typescript
type Section = 'broker' | 'theme' | 'scan' | 'brokers' | 'risk' | 'regime' | 'notifications' | 'strategy';

const SECTIONS: { key: Section; label: string; desc: string }[] = [
  { key: 'broker',    label: 'Broker',         desc: 'Credentials + paper trade toggle' },
  { key: 'theme',     label: 'Appearance',      desc: 'Theme + density' },
  { key: 'scan',      label: 'Scan',            desc: 'Continuous scan + cadence' },
  { key: 'strategy',  label: 'Strategy scan',   desc: 'Signal tolerances + backtest thresholds' },
  { key: 'brokers',   label: 'Brokers',         desc: 'Paper trading accounts + live IBKR preparation' },
  { key: 'risk',      label: 'Risk',            desc: 'Exposure limits and portfolio value' },
  { key: 'regime',    label: 'Regime',          desc: 'Daily OMM parameters' },
  { key: 'notifications', label: 'Notifications', desc: 'Gmail + Telegram alert delivery' },
];
```

- [ ] **Step 8.3: Render `StrategyScanForm` in the panel**

In the `SettingsPage` component return block, add:

```tsx
          {active === 'strategy' && <StrategyScanForm />}
```

alongside the other `{active === ...}` conditions.

- [ ] **Step 8.4: Add the `StrategyScanForm` component**

Add this component at the bottom of `page.tsx` (before the closing of the file, after the existing form components):

```tsx
/* ---------- Strategy scan form ---------- */

function StrategyScanForm() {
  const store = useScanParamsStore();

  return (
    <div>
      <SectionIntro
        title="Strategy scan parameters"
        blurb="These values control how strictly each strategy filter and backtest gate applies. Lower tolerances mean fewer matches; higher means more (but potentially noisier) signals."
      />

      <Row
        label="Pullback tolerance"
        hint="How far above the 20-EMA price can be and still count as a pullback"
        defaultValue="4%"
      >
        <input
          type="number"
          className={styles.numInput}
          value={Math.round(store.pullbackTolerancePct * 100 * 10) / 10}
          min={0.5} max={15} step={0.5}
          onChange={(e) =>
            store.setParam('pullbackTolerancePct', Number(e.target.value) / 100)
          }
        />
        <Text size={12} tone="secondary">%</Text>
      </Row>

      <Row
        label="MA crossover lookback"
        hint="How many bars ago the 20/50-SMA cross can have occurred"
        defaultValue="10 bars"
      >
        <input
          type="number"
          className={styles.numInput}
          value={store.maCrossoverLookback}
          min={1} max={30} step={1}
          onChange={(e) =>
            store.setParam('maCrossoverLookback', Number(e.target.value))
          }
        />
        <Text size={12} tone="secondary">bars</Text>
      </Row>

      <Row
        label="Breakout volume multiplier"
        hint="Today's volume must exceed N × the 20-day average"
        defaultValue="1.1×"
      >
        <input
          type="number"
          className={styles.numInput}
          value={store.breakoutVolumeMult}
          min={1.0} max={3.0} step={0.05}
          onChange={(e) =>
            store.setParam('breakoutVolumeMult', Number(e.target.value))
          }
        />
        <Text size={12} tone="secondary">×</Text>
      </Row>

      <Row
        label="Min backtest trades"
        hint="Minimum number of qualifying historical trades for backtest gate to pass"
        defaultValue="10"
      >
        <input
          type="number"
          className={styles.numInput}
          value={store.btMinTrades}
          min={1} max={50} step={1}
          onChange={(e) =>
            store.setParam('btMinTrades', Number(e.target.value))
          }
        />
        <Text size={12} tone="secondary">trades</Text>
      </Row>

      <Row
        label="Min win rate"
        hint="Minimum historical win rate for the backtest gate to pass"
        defaultValue="45%"
      >
        <input
          type="number"
          className={styles.numInput}
          value={Math.round(store.btMinWinRate * 100)}
          min={10} max={80} step={5}
          onChange={(e) =>
            store.setParam('btMinWinRate', Number(e.target.value) / 100)
          }
        />
        <Text size={12} tone="secondary">%</Text>
      </Row>

      <div style={{ marginTop: '16px' }}>
        <button
          type="button"
          className={styles.btn}
          onClick={store.resetToDefaults}
        >
          Reset to defaults
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 8.5: Add the `useScanParamsStore` import**

At the top of `page.tsx`, add to the existing imports:

```typescript
import { useScanParamsStore } from '@/lib/scanParamsStore';
```

- [ ] **Step 8.6: Add `.numInput` CSS if missing**

In `frontend/app/(frame)/settings/page.module.css`, check if `.numInput` exists. If not, append:

```css
.numInput {
  width: 72px;
  padding: 4px 8px;
  font-size: 13px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text-primary);
  text-align: right;
}

.numInput:focus {
  outline: none;
  border-color: var(--border-strong);
}
```

- [ ] **Step 8.7: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 8.8: Commit**

```bash
git add frontend/app/'(frame)'/settings/page.tsx \
        frontend/app/'(frame)'/settings/page.module.css \
        frontend/lib/api.ts
git commit -m "feat(settings): add Strategy scan section for signal tolerances and backtest thresholds"
```

---

## Task 9 — Step 5 page: collapsible per-scan override panel

**Problem:** Settings controls are for persistent defaults, but users also need to override values for a single scan without touching Settings.

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.module.css`

- [ ] **Step 9.1: Read the current Step 5 page**

Open `frontend/app/(frame)/screener/step-5-strategy/page.tsx` and confirm the current structure — it should already have `scanResult`, `startPrefetch`, and the prefetch row from the previous implementation.

- [ ] **Step 9.2: Add store import and local override state**

Add to the imports:

```typescript
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
```

Inside `Step5StrategyPage`, after the existing `useState` declarations, add:

```typescript
  const savedParams = useScanParamsStore();
  const [params, setParams] = useState(() => ({
    pullbackTolerancePct: savedParams.pullbackTolerancePct,
    maCrossoverLookback:  savedParams.maCrossoverLookback,
    breakoutVolumeMult:   savedParams.breakoutVolumeMult,
    btMinTrades:          savedParams.btMinTrades,
    btMinWinRate:         savedParams.btMinWinRate,
  }));

  function resetParams() {
    setParams({
      pullbackTolerancePct: savedParams.pullbackTolerancePct,
      maCrossoverLookback:  savedParams.maCrossoverLookback,
      breakoutVolumeMult:   savedParams.breakoutVolumeMult,
      btMinTrades:          savedParams.btMinTrades,
      btMinWinRate:         savedParams.btMinWinRate,
    });
  }
```

- [ ] **Step 9.3: Wire params into `runScan`**

In the `runScan` function, update the `api.postStockScan` call to include all 5 params:

```typescript
      const result = await api.postStockScan({
        universe: context?.universe ? [context.universe] : ['SP500'],
        symbols: candidateSymbols?.length ? candidateSymbols : undefined,
        direction: context?.direction ?? 'Bullish',
        horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
        strategy: stratKey,
        pullback_tolerance_pct: params.pullbackTolerancePct,
        ma_crossover_lookback:  params.maCrossoverLookback,
        breakout_volume_mult:   params.breakoutVolumeMult,
        bt_min_trades:          params.btMinTrades,
        bt_min_win_rate:        params.btMinWinRate,
        account_size: 50_000,
        risk_pct: 0.01,
      });
```

- [ ] **Step 9.4: Add the collapsible override panel to the JSX**

In the return block, between the header `</div>` and `{error && ...}`, add:

```tsx
      <details className={styles.paramsPanel}>
        <summary className={styles.paramsSummary}>
          <Text size={12} tone="secondary">Scan parameters</Text>
        </summary>

        <div className={styles.paramsGrid}>
          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Pullback tolerance</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={Math.round(params.pullbackTolerancePct * 100 * 10) / 10}
                min={0.5} max={15} step={0.5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, pullbackTolerancePct: Number(e.target.value) / 100 }))
                }
              />
              <Text size={11} tone="dim">%</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">MA crossover lookback</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.maCrossoverLookback}
                min={1} max={30} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, maCrossoverLookback: Number(e.target.value) }))
                }
              />
              <Text size={11} tone="dim">bars</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Breakout vol multiplier</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.breakoutVolumeMult}
                min={1.0} max={3.0} step={0.05}
                onChange={(e) =>
                  setParams((p) => ({ ...p, breakoutVolumeMult: Number(e.target.value) }))
                }
              />
              <Text size={11} tone="dim">×</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Min backtest trades</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.btMinTrades}
                min={1} max={50} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, btMinTrades: Number(e.target.value) }))
                }
              />
              <Text size={11} tone="dim">trades</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Min win rate</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={Math.round(params.btMinWinRate * 100)}
                min={10} max={80} step={5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, btMinWinRate: Number(e.target.value) / 100 }))
                }
              />
              <Text size={11} tone="dim">%</Text>
            </div>
          </label>

          <button type="button" className={styles.resetBtn} onClick={resetParams}>
            Reset to saved
          </button>
        </div>
      </details>
```

- [ ] **Step 9.5: Add CSS**

Append to `frontend/app/(frame)/screener/step-5-strategy/page.module.css`:

```css
.paramsPanel {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 0;
  background: var(--bg-surface);
}

.paramsSummary {
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.paramsSummary::-webkit-details-marker { display: none; }

.paramsGrid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4) var(--space-4);
  border-top: 1px solid var(--border-subtle);
}

.paramLabel {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.paramInput {
  display: flex;
  align-items: center;
  gap: 6px;
}

.paramInput input {
  width: 64px;
  padding: 3px 6px;
  font-size: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text-primary);
  text-align: right;
}

.paramInput input:focus {
  outline: none;
  border-color: var(--border-strong);
}

.resetBtn {
  grid-column: 1 / -1;
  justify-self: end;
  padding: 4px 10px;
  font-size: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.resetBtn:hover {
  border-color: var(--border-default);
  color: var(--text-primary);
}
```

- [ ] **Step 9.6: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 9.7: Commit**

```bash
git add frontend/app/'(frame)'/screener/step-5-strategy/page.tsx \
        frontend/app/'(frame)'/screener/step-5-strategy/page.module.css
git commit -m "feat(step-5): collapsible per-scan parameter override panel"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|---|---|
| Vol rule PASS 90 when iv_rank=None (Swing + Position) | Task 1 |
| `tolerance` param on `pullback_ema_signal` | Task 2 |
| `lookback` param on `ma_crossover_signal` | Task 2 |
| 3 new fields in `StockScanRequest` | Task 3 |
| `_SIGNAL_KWARGS` dispatch in router | Task 4 |
| Batch Tradier price call (1 call vs 519) | Task 4 |
| `most_recent_trading_day()` guard in `historical_store` | Task 5 |
| Confidence cache SQLite L2 layer | Task 6 |
| `scanParamsStore.ts` persisted Zustand store | Task 7 |
| Settings page Strategy scan section | Task 8 |
| `api.ts` 3 new fields in `postStockScan` | Task 8 |
| Step 5 collapsible override panel | Task 9 |
| Step 5 wires all 5 params into `postStockScan` | Task 9 |

### Placeholder check

No TBDs, no "add appropriate error handling" phrases. Every error path has a specific fallback.

### Type consistency

- `ScanParams` keys in `scanParamsStore.ts`: `pullbackTolerancePct`, `maCrossoverLookback`, `breakoutVolumeMult`, `btMinTrades`, `btMinWinRate` — used identically in Tasks 7, 8, 9.
- Backend field names: `pullback_tolerance_pct`, `ma_crossover_lookback`, `breakout_volume_mult` — snake_case in Python schema (Task 3), camelCase in TypeScript store (Task 7), snake_case in `api.ts` (Task 8).
- `fetch_quotes` returns `dict[str, dict]` with `{"last": float, "prevclose": float}` — Task 4 extracts `quote["last"]` explicitly.
- `_SIGNAL_KWARGS` lambdas use `r.pullback_tolerance_pct`, `r.breakout_volume_mult`, `r.ma_crossover_lookback` — matches Task 3 field names exactly.
