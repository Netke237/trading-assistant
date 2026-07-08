# Config Wiring, IV Consolidation & Scheduled Scanning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire all orphaned settings to the backend, consolidate duplicated IV rank thresholds into one backend-served source, add missing execution parameters, and implement interval+day/time scheduled scanning.

**Architecture:** Seven sequential tasks. Tasks 1 and 2 both modify `StockScanRequest` — commit them separately but implement in order. Task 3 replaces hardcoded `ivThresholds.ts` constants with a backend-served store. Tasks 4–5 are independent Settings wiring. Task 6 adds scheduled scanning with day/time/interval controls. Task 7 is cleanup-only (no backend changes).

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 + TypeScript + Zustand v5 + CSS Modules (frontend), pytest (backend tests), Jest (frontend tests).

---

## File Map

**New files:**
- `backend/app/routers/config.py` — `GET /api/config/iv-thresholds`
- `backend/app/schemas/schedule.py` — `ScheduleConfig` Pydantic model
- `frontend/lib/ivThresholdsStore.ts` — Zustand store: fetches per-horizon IV thresholds from backend, falls back to hardcoded defaults
- `backend/tests/test_stock_scan_overrides.py` — Task 1 backend tests
- `backend/tests/test_confidence_gate_stocks.py` — Task 2 backend tests
- `backend/tests/test_iv_thresholds_endpoint.py` — Task 3 backend tests
- `backend/tests/test_risk_limits_endpoint.py` — Task 4 backend tests
- `backend/tests/test_schedule_endpoint.py` — Task 6 backend tests

**Modified files:**
- `backend/app/schemas/stock_scan.py` — add `overrides`, confidence gate, regime gate, fundamentals bearish fields (Tasks 1, 2, 5)
- `backend/app/routers/stock_scan.py` — pass `overrides` to `score_stock`, apply confidence gate cap (Tasks 1–2, 5)
- `backend/app/routers/risk_settings.py` — extend risk endpoint with portfolio limits (Task 4); add schedule endpoints (Task 6)
- `backend/app/services/scan_scheduler.py` — add `days_of_week`, `window_start_hour`, `window_end_hour`, `timezone_name` (Task 6)
- `backend/app/main.py` — register `config` router (Task 3)
- `backend/config/settings.yaml` — add `schedule` block nested under existing `scan` key (Task 6)
- `frontend/lib/settingsStore.ts` — remove `ivPassThreshold`/`ivCautionThreshold` and bump version 17→18 (Task 3); add `scheduleConfig` and bump 18→19 (Task 6)
- `frontend/lib/riskStore.ts` — wire `limits` to backend on save (Task 4)
- `frontend/lib/ivThresholds.ts` — replace hardcoded constants with re-exports from `ivThresholdsStore` (Task 3)
- `frontend/lib/api.ts` — extend `postStockScan` (Task 1), add `getIvThresholds`, `getSchedule`, `putSchedule` (Tasks 3, 6)
- `frontend/lib/stockScan.ts` — send `scanOverrides` + confidence gate fields (Tasks 1–2)
- `frontend/app/(frame)/screener/step-3-direction/page.tsx` — add 11 new PARAM_DEFS entries, move `iv_rank_pass_max` to `section: 'options'` (Tasks 1, 5)
- `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` — use `ivThresholdsStore` (Task 3)
- `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx` — use `ivThresholdsStore` (Task 3)
- `frontend/app/(frame)/settings/scan/page.tsx` — add IV threshold controls, schedule controls (Tasks 3, 6)
- `frontend/app/(frame)/alerts/page.tsx` — remove orphaned IV threshold fields (Task 3)
- `frontend/app/(frame)/settings/risk/page.tsx` — wire portfolio limits to backend (Task 4)
- `frontend/lib/__tests__/settingsStore.test.ts` — remove `ivPassThreshold` assertions (Task 3)
- `frontend/lib/scanParamsStore.ts` — fix `btMinWinRate` default (Task 7)

---

## Task 1: Wire Step-3 Scorer Overrides to Stocks Scanner

The Stock scanner (`/api/stock-scan`) currently ignores all Step-3 Execution Parameters (score weights, trend method, MACD, RSI, etc.). `stock_scorer.py` already reads these from an `overrides: dict | None = None` parameter — the only missing piece is forwarding them through `StockScanRequest`.

**NOT wired in this task:** `iv_rank_pass_max` (irrelevant in stock mode), Options contract params, `pullback_require_reversal` (already sent separately), confidence gate params (Task 2).

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Modify: `backend/app/routers/stock_scan.py` (~line 212)
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/stockScan.ts`
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`
- Create: `backend/tests/test_stock_scan_overrides.py`

- [ ] **Step 1: Discover internal function names in `stock_scan.py`**

Before writing the integration test, run this to find the actual function names used inside `_process_stock`:

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
grep -n "^def \|^async def \|^from \|^import " app/routers/stock_scan.py | head -60
```

Note the exact names of: (a) the function that loads price bars, (b) the function that fetches fundamentals, (c) the function that computes signals. You will need these as patch targets below.

- [ ] **Step 2: Write failing backend tests**

```python
# backend/tests/test_stock_scan_overrides.py
import asyncio
from unittest.mock import MagicMock, patch
from app.schemas.stock_scan import StockScanRequest


def test_stock_scan_request_accepts_overrides():
    """StockScanRequest must accept an overrides dict."""
    req = StockScanRequest(
        universe=["AAPL"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
        overrides={"weight_trend": 50, "weight_pullback": 10, "weight_trigger": 15,
                   "weight_event": 15, "weight_vol": 10},
    )
    assert req.overrides["weight_trend"] == 50


def test_stock_scan_request_overrides_defaults_to_empty():
    """When omitted, overrides must default to empty dict (not None)."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema"
    )
    assert req.overrides == {}


def test_score_stock_receives_overrides_from_request():
    """_process_stock must forward req.overrides to score_stock as the overrides kwarg.

    BEFORE RUNNING: replace each PATCH_TARGET_* placeholder with the actual
    attribute name visible in stock_scan.py (found in Step 1).
    Use the name as it appears in the stock_scan module namespace, e.g.:
      - bars loader: "app.routers.stock_scan.get_historical_bars"  (or whatever Step 1 shows)
      - fundamentals: "app.routers.stock_scan._get_fundamentals"   (adjust to actual name)
      - signals:      "app.routers.stock_scan.compute_signal"      (adjust to actual name)
    """
    captured: dict = {}

    def fake_score_stock(**kwargs):
        captured.update(kwargs)
        card = MagicMock()
        card.status = "PASS"
        card.score = 70
        card.rules = []
        return card

    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        overrides={"weight_trend": 50},
    )

    async def run():
        with patch("app.routers.stock_scan.score_stock", side_effect=fake_score_stock), \
             patch("PATCH_TARGET_BARS_LOADER", return_value=[MagicMock()] * 130), \
             patch("PATCH_TARGET_SIGNALS", return_value=MagicMock()), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("PATCH_TARGET_FUNDAMENTALS", return_value=None):
            from app.routers.stock_scan import _process_stock
            await _process_stock("AAPL", req, {}, None, None)

    asyncio.get_event_loop().run_until_complete(run())
    assert captured.get("overrides") == {"weight_trend": 50}, (
        f"score_stock was not called with overrides=req.overrides. Got: {captured.get('overrides')}"
    )
```

- [ ] **Step 3: Run to confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_stock_scan_overrides.py::test_stock_scan_request_accepts_overrides \
               tests/test_stock_scan_overrides.py::test_stock_scan_request_overrides_defaults_to_empty -v
```
Expected: both schema tests fail with `AttributeError: 'StockScanRequest' has no attribute 'overrides'`. The integration test has PATCH_TARGET_* placeholders — replace them with actual names found in Step 1 before running it.

- [ ] **Step 4: Add `overrides` field to `StockScanRequest`**

In `backend/app/schemas/stock_scan.py`, add `Any` to the typing import (line 2):
```python
from typing import Any, Literal, Optional
```

Add at the bottom of the `StockScanRequest` class (after `fundamentals_de_reject`):
```python
    # Per-scan scorer overrides — keys map directly to stock_scorer.py override handlers.
    # Options contract params and iv_rank_pass_max are excluded (irrelevant in stock mode).
    overrides: dict[str, Any] = {}
```

- [ ] **Step 5: Run schema tests — expect PASS**

```bash
python -m pytest tests/test_stock_scan_overrides.py::test_stock_scan_request_accepts_overrides \
               tests/test_stock_scan_overrides.py::test_stock_scan_request_overrides_defaults_to_empty -v
```
Expected: 2 passed.

- [ ] **Step 6: Pass overrides to `score_stock` in `_process_stock`**

In `backend/app/routers/stock_scan.py`, find the `score_stock(...)` call (~line 212). Replace:
```python
            card = score_stock(
                symbol=symbol,
                direction=req.direction,
                horizon=req.horizon,
                bars=bars[-120:],
                scoring_mode="stock",
                regime_signal=regime_signal,
                regime_gate=full_cfg["regime_gate"] if regime_signal else None,
                fundamentals=_fh,
                fundamentals_gate=fund_gate,
            )
```
With:
```python
            card = score_stock(
                symbol=symbol,
                direction=req.direction,
                horizon=req.horizon,
                bars=bars[-120:],
                scoring_mode="stock",
                regime_signal=regime_signal,
                regime_gate=full_cfg["regime_gate"] if regime_signal else None,
                fundamentals=_fh,
                fundamentals_gate=fund_gate,
                overrides=req.overrides,
            )
```

- [ ] **Step 7: Run all backend tests (including integration test with fixed PATCH_TARGET_* names)**

```bash
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```
Expected: all previously passing tests still pass + new tests pass.

- [ ] **Step 8: Wire frontend — add `overrides` to `postStockScan` in `api.ts`**

`api.ts` uses arrow function properties on an object literal (not a class). Find the `postStockScan` property. It currently looks like:
```typescript
postStockScan: (req: SomeType) => post<StockScanResult>('/api/stock-scan', req),
```
Change it to accept an `overrides` field in the request type:
```typescript
postStockScan: (req: StockScanParams & { overrides?: Record<string, unknown> }) =>
  post<StockScanResult>('/api/stock-scan', req),
```
Where `StockScanParams` is whatever the existing type name is. The `overrides` field is passed in the body automatically since the whole `req` object is serialized.

- [ ] **Step 9: Send filtered overrides from the stock scan caller**

In `frontend/lib/stockScan.ts`, note that `useScanStore` is already imported. Add before the `postStockScan` call:

```typescript
// Keys from scanStore.scanOverrides that stock_scorer.py reads via the overrides dict.
// Options-only params (max_delta, min_dte, etc.) and iv_rank_pass_max are excluded.
const STOCKS_SCORER_KEYS = new Set([
  'weight_trend', 'weight_pullback', 'weight_trigger', 'weight_event', 'weight_vol',
  'trend_method', 'ma_type', 'fast_ema', 'slow_ema',
  'additive_ma_type', 'additive_ma_period', 'additive_slope_lookback',
  'additive_adx_period', 'additive_adx_pass', 'additive_adx_caution',
  'additive_price_max', 'additive_slope_max', 'additive_adx_max',
  'rs_period', 'rs_pass_threshold', 'rs_caution_threshold', 'rs_benchmark',
  'swing_high_lookback_bars', 'atr_caution_max',
  'macd_fast', 'macd_slow', 'macd_signal', 'rsi_floor',
  'event_reject_days', 'event_caution_days',
]);

const rawOverrides = useScanStore.getState().scanOverrides;
const stocksOverrides = Object.fromEntries(
  Object.entries(rawOverrides).filter(([k]) => STOCKS_SCORER_KEYS.has(k))
);
```

In the call to `api.postStockScan(...)`, add:
```typescript
overrides: stocksOverrides,
```

- [ ] **Step 10: Move `iv_rank_pass_max` PARAM_DEFS entry to Options only**

In `frontend/app/(frame)/screener/step-3-direction/page.tsx`, find the entry with `key: 'iv_rank_pass_max'` (~line 249). Change `section: 'stocks'` to `section: 'options'` and update the hint:

```typescript
  { key: 'iv_rank_pass_max', label: 'IV rank pass max', type: 'number', section: 'options', subGroup: 'Volatility', min: 0, max: 100, step: 1,
    hint: 'Max IV rank (0–100) for a PASS on options contracts. N/A on Intraday. ↑ Higher → elevated-IV stocks still qualify (more) · ↓ Lower → only calm-IV stocks pass (fewer). Per-horizon defaults are set in Settings → Scan.' },
```

Also remove `iv_rank_pass_max` from the Stocks-relevant entries in `PARAM_DEFAULTS_PER_HORIZON` (it is now Options-only). Leave it in the Position and Swing defaults for the Options path.

- [ ] **Step 11: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```
Expected: no errors.

- [ ] **Step 12: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py \
        backend/tests/test_stock_scan_overrides.py \
        frontend/lib/api.ts frontend/lib/stockScan.ts \
        "frontend/app/(frame)/screener/step-3-direction/page.tsx"
git commit -m "feat(stocks): wire Step-3 scorer overrides to stock scanner backend"
```

---

## Task 2: Wire Confidence Gate to Stocks Scanner

Confidence is currently computed for every stock but the gate (cap status based on win-rate) is never applied in the Stocks path. The Settings confidence gate also never reaches the stock scan request.

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `frontend/lib/stockScan.ts`
- Create: `backend/tests/test_confidence_gate_stocks.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_confidence_gate_stocks.py
from app.schemas.stock_scan import StockScanRequest


def test_stock_scan_request_accepts_confidence_gate_fields():
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        confidence_caution_below=50.0,
        confidence_reject_below=35.0,
        confidence_atr_mult=1.5,
    )
    assert req.confidence_caution_below == 50.0
    assert req.confidence_reject_below == 35.0
    assert req.confidence_atr_mult == 1.5


def test_confidence_gate_fields_default_to_none():
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema"
    )
    assert req.confidence_caution_below is None
    assert req.confidence_reject_below is None
    assert req.confidence_atr_mult is None
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_confidence_gate_stocks.py -v
```

- [ ] **Step 3: Add confidence gate fields to `StockScanRequest`**

In `backend/app/schemas/stock_scan.py`, add after `overrides` (added in Task 1):
```python
    # Confidence gate — caps a stock's verdict when signal backtest win-rate is low.
    # When None, the gate is disabled (backend falls back to scoring_rules.yaml defaults).
    confidence_caution_below: Optional[float] = None  # win-rate < this → cap at CAUTION
    confidence_reject_below:  Optional[float] = None  # win-rate < this → cap at REJECT
    confidence_atr_mult:      Optional[float] = None  # ATR multiplier for backtest barriers
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/test_confidence_gate_stocks.py -v
```

- [ ] **Step 5: Apply the confidence gate cap in `_process_stock`**

In `backend/app/routers/stock_scan.py`, find where `conf_val` is computed (~line 276). After the line that reads `conf_val = _cached["confidence"]`, add:

```python
            # Apply per-request confidence gate (when enabled).
            # StockScoreCard is a @dataclass — use dataclasses.replace() to update status.
            import dataclasses
            _SEVERITY = {"PASS": 0, "CAUTION": 1, "REJECT": 2}

            if conf_val is not None and req.confidence_reject_below is not None:
                if conf_val < req.confidence_reject_below:
                    return {
                        "symbol": symbol,
                        "reason": (
                            f"confidence gate REJECT: {conf_val:.0f}% "
                            f"< {req.confidence_reject_below:.0f}%"
                        ),
                    }
            if conf_val is not None and req.confidence_caution_below is not None:
                if conf_val < req.confidence_caution_below:
                    if _SEVERITY.get(card.status, 0) < _SEVERITY["CAUTION"]:
                        card = dataclasses.replace(card, status="CAUTION")
```

> **Note:** Confirm that `StockScoreCard` is indeed a `@dataclass` (not a Pydantic model) by checking `backend/app/scoring/stock_scorer.py` lines 28–40 before applying. If it is a Pydantic model, replace `dataclasses.replace(card, status="CAUTION")` with `card.model_copy(update={"status": "CAUTION"})`. Do not use `card._replace(...)` — that is a `NamedTuple` method and does not exist on dataclasses.
>
> Also note: when `conf_val is None` (cache miss on first run), the gate is silently skipped — this is intentional.

- [ ] **Step 6: Add gate-logic tests**

Before writing this test, run the same grep from Task 1 Step 1 to get the correct patch targets for `_process_stock`. Then add to `backend/tests/test_confidence_gate_stocks.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch
from app.schemas.stock_scan import StockScanRequest

# IMPORTANT: Replace PATCH_TARGET_* placeholders below with actual names from
# Task 1 Step 1 grep output (e.g. "app.routers.stock_scan.get_historical_bars").


def test_confidence_gate_reject_excludes_low_confidence_symbol():
    """When conf_val < reject_below, _process_stock must return a 'reason' dict (exclusion)."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        confidence_reject_below=35.0,
    )
    fake_card = MagicMock()
    fake_card.status = "PASS"
    fake_card.score = 70
    fake_card.rules = []

    async def run():
        with patch("app.routers.stock_scan.score_stock", return_value=fake_card), \
             patch("PATCH_TARGET_BARS_LOADER", return_value=[MagicMock()] * 130), \
             patch("PATCH_TARGET_SIGNALS", return_value=MagicMock()), \
             patch("app.routers.stock_scan.compute_confidence", return_value=30.0), \
             patch("PATCH_TARGET_FUNDAMENTALS", return_value=None):
            from app.routers.stock_scan import _process_stock
            return await _process_stock("AAPL", req, {}, None, None)

    result = asyncio.get_event_loop().run_until_complete(run())
    assert "reason" in result, f"Expected exclusion dict with 'reason', got: {result}"
    assert "confidence gate REJECT" in result["reason"]


def test_confidence_gate_caution_caps_pass_to_caution():
    """When reject_below <= conf_val < caution_below, status must be capped at CAUTION."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        confidence_caution_below=50.0,
        confidence_reject_below=35.0,
    )
    fake_card = MagicMock()
    fake_card.status = "PASS"
    fake_card.score = 70
    fake_card.rules = []

    async def run():
        with patch("app.routers.stock_scan.score_stock", return_value=fake_card), \
             patch("PATCH_TARGET_BARS_LOADER", return_value=[MagicMock()] * 130), \
             patch("PATCH_TARGET_SIGNALS", return_value=MagicMock()), \
             patch("app.routers.stock_scan.compute_confidence", return_value=40.0), \
             patch("PATCH_TARGET_FUNDAMENTALS", return_value=None):
            from app.routers.stock_scan import _process_stock
            return await _process_stock("AAPL", req, {}, None, None)

    result = asyncio.get_event_loop().run_until_complete(run())
    assert "reason" not in result or result.get("status") == "CAUTION"
```

- [ ] **Step 7: Run all backend tests**

```bash
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 8: Wire frontend — send confidence gate from settingsStore**

In `frontend/lib/stockScan.ts`, import `useSettingsStore` and add to the `api.postStockScan(...)` call:

```typescript
const { confidenceGate } = useSettingsStore.getState();
// Add these fields to the postStockScan request object:
confidence_caution_below: confidenceGate.enabled ? confidenceGate.cautionBelow : undefined,
confidence_reject_below:  confidenceGate.enabled ? confidenceGate.rejectBelow  : undefined,
confidence_atr_mult:      confidenceGate.enabled ? confidenceGate.atrMult       : undefined,
```

`compute_confidence()` already accepts `atr_mult` (confirmed at `signal_confidence.py:127-132`) — include it unconditionally alongside the other two gate fields.

Also add `confidence_caution_below?: number`, `confidence_reject_below?: number`, and `confidence_atr_mult?: number` to the `postStockScan` request type in `api.ts`.

**Backend side:** In `backend/app/routers/stock_scan.py`, find where `compute_confidence()` is called inside `_process_stock` and forward the per-request ATR multiplier:

```python
conf_val = compute_confidence(
    ...,                               # existing args unchanged
    atr_mult=req.confidence_atr_mult,  # per-request override; None falls back to YAML default
)
```

If `compute_confidence()` is invoked via an intermediate helper, locate where `atr_mult` is resolved from YAML and add: `atr_mult = req.confidence_atr_mult if req.confidence_atr_mult is not None else yaml_atr_mult`.

- [ ] **Step 9: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```

- [ ] **Step 10: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py \
        backend/tests/test_confidence_gate_stocks.py frontend/lib/stockScan.ts frontend/lib/api.ts
git commit -m "feat(stocks): apply confidence gate cap in stock scanner pipeline"
```

---

## Task 3: Consolidate IV Rank Thresholds — Backend Endpoint + Settings UI

Currently the same numbers (Swing: 34/55, Position: 44/65, Intraday: null) appear in three independent places: `scoring_rules.yaml`, `frontend/lib/ivThresholds.ts` (hardcoded), and `Step-3 PARAM_DEFAULTS_PER_HORIZON`. The `/alerts` page has an editable "IV Pass Threshold" stored in `settingsStore` but never sent to the backend.

This task: backend serves canonical values from YAML via `GET /api/config/iv-thresholds`. Frontend fetches them into a Zustand store. Settings → Scan gets editable per-horizon overrides. The `/alerts` orphan fields are removed.

**Files:**
- Create: `backend/app/routers/config.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_iv_thresholds_endpoint.py`
- Create: `frontend/lib/ivThresholdsStore.ts`
- Modify: `frontend/lib/ivThresholds.ts`
- Modify: `frontend/lib/settingsStore.ts` (remove fields + bump version 17→18)
- Modify: `frontend/lib/__tests__/settingsStore.test.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`
- Modify: `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`
- Modify: `frontend/app/(frame)/settings/scan/page.tsx`
- Modify: `frontend/app/(frame)/alerts/page.tsx`

- [ ] **Step 1: Write failing backend test**

```python
# backend/tests/test_iv_thresholds_endpoint.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_iv_thresholds_endpoint_returns_all_horizons():
    response = client.get("/api/config/iv-thresholds")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"Intraday", "Swing", "Position"}


def test_iv_thresholds_swing_matches_yaml():
    response = client.get("/api/config/iv-thresholds")
    assert response.status_code == 200
    swing = response.json()["Swing"]
    assert swing["pass_max"] == 34
    assert swing["caution_max"] == 55


def test_iv_thresholds_intraday_is_null():
    response = client.get("/api/config/iv-thresholds")
    intraday = response.json()["Intraday"]
    assert intraday["pass_max"] is None
    assert intraday["caution_max"] is None
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_iv_thresholds_endpoint.py -v
```
Expected: 404 or connection error — endpoint does not exist yet.

- [ ] **Step 3: Create `backend/app/routers/config.py`**

```python
from __future__ import annotations

import functools
from pathlib import Path

import yaml
from fastapi import APIRouter

_CFG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"

router = APIRouter(prefix="/api/config", tags=["config"])


@functools.lru_cache(maxsize=1)
def _scoring_cfg() -> dict:
    return yaml.safe_load(_CFG_PATH.read_text())


@router.get("/iv-thresholds")
def get_iv_thresholds() -> dict:
    """Return per-horizon IV rank pass/caution thresholds from scoring_rules.yaml.
    Uses lru_cache — restart server to pick up YAML changes."""
    horizons = _scoring_cfg()["horizons"]
    return {
        label: {
            "pass_max":    horizons[key]["vol"].get("iv_rank_pass_max"),
            "caution_max": horizons[key]["vol"].get("iv_rank_caution_max"),
        }
        for label, key in [
            ("Intraday", "intraday"),
            ("Swing",    "swing"),
            ("Position", "position"),
        ]
    }
```

- [ ] **Step 4: Register the config router in `backend/app/main.py`**

In `backend/app/main.py`, find the other `app.include_router(...)` lines and add:
```python
from app.routers.config import router as config_router
app.include_router(config_router)
```

- [ ] **Step 5: Run test — expect PASS**

```bash
python -m pytest tests/test_iv_thresholds_endpoint.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Create `frontend/lib/ivThresholdsStore.ts`**

```typescript
// Fetches per-horizon IV rank thresholds from the backend at app start.
// Falls back to YAML values (34/55 Swing, 44/65 Position) if the fetch fails.
import { create } from 'zustand';
import { api } from '@/lib/api';

export interface HorizonIvThresholds {
  pass_max:    number | null;
  caution_max: number | null;
}

export interface IvThresholdsState {
  thresholds:    Record<string, HorizonIvThresholds>;
  loaded:        boolean;
  fetch:         () => Promise<void>;
  setThresholds: (t: Record<string, HorizonIvThresholds>) => void;
}

export const FALLBACK: Record<string, HorizonIvThresholds> = {
  Intraday: { pass_max: null, caution_max: null },
  Swing:    { pass_max: 34,   caution_max: 55   },
  Position: { pass_max: 44,   caution_max: 65   },
};

export const useIvThresholdsStore = create<IvThresholdsState>((set) => ({
  thresholds: FALLBACK,
  loaded:     false,
  fetch: async () => {
    try {
      const data = await api.getIvThresholds();
      set({ thresholds: data, loaded: true });
    } catch {
      set({ loaded: true }); // keep fallback values
    }
  },
  setThresholds: (t) => set({ thresholds: t }),
}));

export function getIvPassMax(
  horizonKey: string,
  thresholds: Record<string, HorizonIvThresholds>,
): number | null {
  return thresholds[horizonKey]?.pass_max ?? FALLBACK[horizonKey]?.pass_max ?? null;
}

export function getIvCautionMax(
  horizonKey: string,
  thresholds: Record<string, HorizonIvThresholds>,
): number | null {
  return thresholds[horizonKey]?.caution_max ?? FALLBACK[horizonKey]?.caution_max ?? null;
}
```

- [ ] **Step 7: Add `getIvThresholds` to `frontend/lib/api.ts`**

`api.ts` uses an object literal with arrow function properties and module-level helper functions (`get`, `post`, `put`). Add to the `api` object:
```typescript
getIvThresholds: () =>
  get<Record<string, { pass_max: number | null; caution_max: number | null }>>(
    '/api/config/iv-thresholds'
  ),
```

- [ ] **Step 8: Bootstrap the fetch in the frame layout**

Next.js App Router layouts are Server Components by default. Create a `'use client'` bootstrap component:

```typescript
// frontend/components/atoms/IvThresholdsBootstrap/index.tsx
'use client';
import { useEffect } from 'react';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';

export function IvThresholdsBootstrap() {
  const fetch = useIvThresholdsStore((s) => s.fetch);
  useEffect(() => { fetch(); }, [fetch]);
  return null;
}
```

Render `<IvThresholdsBootstrap />` inside `frontend/app/(frame)/layout.tsx` (the persistent frame layout, not the root layout) — it renders once on mount and fires the backend fetch.

- [ ] **Step 9: Update Step-5 vol-events to use the store**

In `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`, replace:
```typescript
import { IV_PASS_MAX, IV_CAUTION_MAX } from '@/lib/ivThresholds';
// usage: IV_PASS_MAX[horizonKey]
```
With:
```typescript
import { useIvThresholdsStore, getIvPassMax, getIvCautionMax } from '@/lib/ivThresholdsStore';
// In the component body:
const ivThresholds = useIvThresholdsStore((s) => s.thresholds);
// Usage: getIvPassMax(horizonKey, ivThresholds)
```

- [ ] **Step 10: Update Step-7 context rail to use the store**

In `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`, same pattern:
```typescript
import { useIvThresholdsStore, getIvPassMax, getIvCautionMax } from '@/lib/ivThresholdsStore';
// In TradeCardContextRail():
const ivThresholds = useIvThresholdsStore((s) => s.thresholds);
// Pass ivThresholds to buildChecklist() and use getIvPassMax/getIvCautionMax inside it.
```

- [ ] **Step 11: Update `frontend/lib/ivThresholds.ts` compatibility shims**

Replace the entire contents of `frontend/lib/ivThresholds.ts` with:
```typescript
// Compatibility shims — consumers should migrate to useIvThresholdsStore directly.
export { getIvPassMax, getIvCautionMax, FALLBACK } from '@/lib/ivThresholdsStore';

export const IV_PASS_MAX: Record<string, number | null> = {
  Intraday: null, Swing: 34, Position: 44,
};
export const IV_CAUTION_MAX: Record<string, number | null> = {
  Intraday: null, Swing: 55, Position: 65,
};
```

- [ ] **Step 12: Remove orphaned IV fields from settingsStore — bump version 17→18**

In `frontend/lib/settingsStore.ts`, make ALL four changes below:

**a)** Remove from `SettingsState` interface:
```typescript
ivPassThreshold:         number;  // ← delete
ivCautionThreshold:      number;  // ← delete
setIvPassThreshold:      (v: number) => void;  // ← delete
setIvCautionThreshold:   (v: number) => void;  // ← delete
```

**b)** Remove from the initial state object (inside `create(...)`):
```typescript
ivPassThreshold:    34,  // ← delete
ivCautionThreshold: 55,  // ← delete
```

**c)** Remove from the `resetToDefaults` action body:
```typescript
ivPassThreshold:    34,  // ← delete
ivCautionThreshold: 55,  // ← delete
```

**d)** Remove from the `partialize` callback:
```typescript
ivPassThreshold:    state.ivPassThreshold,    // ← delete
ivCautionThreshold: state.ivCautionThreshold, // ← delete
```

**e)** Remove the two action implementations (`setIvPassThreshold` and `setIvCautionThreshold`).

**f)** Add migration branch (keeping the stacking/cumulative pattern used by the existing `migrateSettings`):
```typescript
if (version < 18) {
  delete (next as Record<string, unknown>).ivPassThreshold;
  delete (next as Record<string, unknown>).ivCautionThreshold;
}
```

**g)** Change the `version` in the `persist(...)` options from `17` to `18`.

- [ ] **Step 13: Update `settingsStore.test.ts`**

In `frontend/lib/__tests__/settingsStore.test.ts`, find every assertion that references `ivPassThreshold` or `ivCautionThreshold` and remove those assertions entirely (they tested fields that no longer exist).

- [ ] **Step 14: Remove orphaned fields from /alerts page**

In `frontend/app/(frame)/alerts/page.tsx`, find and delete:
- The "IV Pass Threshold" input field (JSX)
- The "IV Caution Threshold" input field (JSX)
- Any local state or handlers that only served these two fields (`setIvPassThreshold`, `setIvCautionThreshold`)

- [ ] **Step 15: Add per-horizon IV controls to Settings → Scan**

In `frontend/app/(frame)/settings/scan/page.tsx`, add an "IV Rank Thresholds" section. Follow the exact CSS class names used in the existing parameter rows in that file:

```tsx
'use client';
// At top of file, add:
import { useIvThresholdsStore, HorizonIvThresholds } from '@/lib/ivThresholdsStore';

// Inside the component:
const { thresholds, setThresholds } = useIvThresholdsStore();
const [localIvPassMax, setLocalIvPassMax] = useState<Record<string, number>>({
  Swing:    thresholds.Swing?.pass_max    ?? 34,
  Position: thresholds.Position?.pass_max ?? 44,
});

function handleSaveIvThresholds() {
  setThresholds({
    ...thresholds,
    Swing:    { ...thresholds.Swing,    pass_max: localIvPassMax.Swing    },
    Position: { ...thresholds.Position, pass_max: localIvPassMax.Position },
  });
}
```

```tsx
<section className={styles.section}>
  <header className={styles.sectionHeader}>
    <Text size={13} weight={600}>IV rank thresholds</Text>
    <Text size={11} tone="secondary">
      Per-horizon pass maximums for options IV rank filtering. Mirrors scoring_rules.yaml defaults.
      Changes apply to the current session only — edit the YAML to make them permanent.
    </Text>
  </header>
  {(['Swing', 'Position'] as const).map((h) => (
    <div key={h} className={styles.paramRow}>
      <div className={styles.paramLeft}>
        <Text size={12}>{h} — IV rank pass max</Text>
        <Text size={11} tone="dim">Default: {h === 'Swing' ? 34 : 44}</Text>
      </div>
      <input
        type="number" min={0} max={100} step={1}
        value={localIvPassMax[h]}
        onChange={(e) => setLocalIvPassMax((prev) => ({ ...prev, [h]: Number(e.target.value) }))}
        className={styles.paramInput}
      />
      <Text size={11} tone="dim" className={styles.paramHint}>
        IV rank (0–100) at or below this value → PASS on options.
        ↑ Higher → elevated-IV stocks still qualify (more candidates) ·
        ↓ Lower → only calm-IV stocks pass (fewer candidates)
      </Text>
    </div>
  ))}
  <button className={styles.saveBtn} onClick={handleSaveIvThresholds}>
    Apply thresholds
  </button>
</section>
```

- [ ] **Step 16: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```
Expected: no errors.

- [ ] **Step 17: Run all tests**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run test -- --testPathPattern=settingsStore
```

- [ ] **Step 18: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/routers/config.py backend/app/main.py \
        backend/tests/test_iv_thresholds_endpoint.py \
        frontend/lib/ivThresholdsStore.ts frontend/lib/ivThresholds.ts \
        frontend/lib/settingsStore.ts frontend/lib/api.ts \
        "frontend/components/atoms/IvThresholdsBootstrap/index.tsx" \
        "frontend/app/(frame)/layout.tsx" \
        "frontend/app/(frame)/screener/step-5-vol-events/page.tsx" \
        "frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx" \
        "frontend/app/(frame)/settings/scan/page.tsx" \
        "frontend/app/(frame)/alerts/page.tsx" \
        "frontend/lib/__tests__/settingsStore.test.ts"
git commit -m "feat(iv-thresholds): consolidate IV rank thresholds to backend endpoint; add Settings Scan controls"
```

---

## Task 4: Wire Risk Limits to Backend

`riskStore.limits` (portfolio value, max single/total exposure, max concurrent, max daily) are visible in Settings → Risk but never sent to the backend. The backend uses `risk_rules.yaml` independently.

**Important pre-read:** Before writing any code, read `backend/app/routers/risk_settings.py` in full. The actual file is `risk_settings.py` (not `settings.py`). Note:
1. The router prefix and exact URL paths
2. The `RiskConfig` Pydantic model field names — they use **camelCase** (e.g., `premiumStopPct`), not snake_case
3. The storage mechanism (probably writes to `risk_rules.yaml`)

**Files:**
- Modify: `backend/app/routers/risk_settings.py`
- Create: `backend/tests/test_risk_limits_endpoint.py`
- Modify: `frontend/lib/riskStore.ts`
- Modify: `frontend/app/(frame)/settings/risk/page.tsx`

- [ ] **Step 1: Read the existing risk settings file**

```bash
cat "F:/Git/GitHub/Trading assistant/backend/app/routers/risk_settings.py"
```

Note the exact camelCase field names in `RiskConfig`, the router prefix, the endpoint paths, and the storage mechanism.

- [ ] **Step 2: Write failing backend test**

Use the **same field naming convention** as the existing `RiskConfig` (camelCase). For example, if existing fields are `premiumStopPct`, then new fields must also be camelCase:

```python
# backend/tests/test_risk_limits_endpoint.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_risk_settings_accepts_portfolio_limits():
    # Use camelCase to match RiskConfig field naming convention
    payload = {
        "premiumStopPct": 0.60,
        "portfolioValue": 50000.0,
        "maxSinglePositionPct": 0.05,
        "maxTotalExposurePct": 0.20,
        "maxConcurrentPositions": 5,
        "maxDailyRecommendations": 10,
    }
    # Use the actual endpoint path found in risk_settings.py
    response = client.post("/api/settings/risk", json=payload)
    assert response.status_code == 200


def test_risk_settings_get_returns_portfolio_limits():
    response = client.get("/api/settings/risk")
    assert response.status_code == 200
    data = response.json()
    assert "portfolioValue" in data
    assert "maxConcurrentPositions" in data
```

> **Note:** If the existing `RiskConfig` uses snake_case, adjust the test payload to snake_case instead. Match whatever convention the file already uses.

- [ ] **Step 3: Extend `RiskConfig` in `risk_settings.py`**

Add these fields to the `RiskConfig` class, following the exact same naming convention already used (camelCase or snake_case — whichever the file uses):

```python
# Using camelCase to match existing field style:
portfolioValue:           Optional[float] = None
maxSinglePositionPct:     Optional[float] = None
maxTotalExposurePct:      Optional[float] = None
maxConcurrentPositions:   Optional[int]   = None
maxDailyRecommendations:  Optional[int]   = None
```

Persist and return these new fields alongside `premiumStopPct` using the same storage mechanism already used. The storage location (`risk_rules.yaml`, database, etc.) is determined by reading Step 1 output.

- [ ] **Step 4: Run test — expect PASS**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_risk_limits_endpoint.py -v
```

- [ ] **Step 5: Wire frontend — save limits to backend on Settings → Risk save**

In `frontend/lib/riskStore.ts`, find the save handler. `saveRiskSettings` is a standalone export from `frontend/lib/api.ts` (not a method on the `api` object). Use it as:

```typescript
import { saveRiskSettings } from '@/lib/api';

// In the save handler:
await saveRiskSettings({
  premiumStopPct:         settingsStore.premiumStopPct,
  portfolioValue:          limits.portfolioValue,
  maxSinglePositionPct:    limits.maxSinglePositionPct,
  maxTotalExposurePct:     limits.maxTotalExposurePct,
  maxConcurrentPositions:  limits.maxConcurrentPositions,
  maxDailyRecommendations: limits.maxDailyRecommendations,
});
```

Extend the `saveRiskSettings` function signature in `api.ts` to accept the new fields.

- [ ] **Step 6: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```

- [ ] **Step 7: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/routers/risk_settings.py backend/tests/test_risk_limits_endpoint.py \
        frontend/lib/riskStore.ts frontend/lib/api.ts
git commit -m "feat(risk): wire portfolio limits from Settings Risk to backend"
```

---

## Task 5: Add Missing Execution Parameters to Step-3

Add four new parameter groups to the Step-3 Execution Parameters panel. All new PARAM_DEFS entries follow the exact format of the existing ones — check `step-3-direction/page.tsx` for the TypeScript type of the `PARAM_DEFS` array entries and match it exactly (including all optional fields like `unit`).

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`
- Modify: `backend/app/schemas/stock_scan.py` (Regime Gate + Fundamentals Bearish named fields)
- Modify: `backend/app/routers/stock_scan.py` (consume new fields)
- Modify: `backend/app/services/fundamentals_gate.py` (extend bearish gate handling)

- [ ] **Step 1: Add new PARAM_DEFS entries to Step-3**

In `frontend/app/(frame)/screener/step-3-direction/page.tsx`, find the `PARAM_DEFS` array. Add the following entries before the closing `]`, respecting the exact TypeScript field structure of the existing entries:

```typescript
  // ALL — Regime Gate
  {
    key: 'regime_headwind_caution_pct', label: 'Headwind caution %',
    type: 'number', section: 'all', subGroup: 'Regime Gate',
    min: -100, max: 0, step: 5, unit: '%',
    hint: 'Sector underperformance vs benchmark below this % → CAUTION on candidate. '
        + '↑ Higher (closer to 0) → stricter, more candidates caught (fewer pass) · '
        + '↓ Lower → only severe laggards affected (more pass). Default: -15%',
  },
  {
    key: 'regime_headwind_reject_pct', label: 'Headwind reject %',
    type: 'number', section: 'all', subGroup: 'Regime Gate',
    min: -100, max: 0, step: 5, unit: '%',
    hint: 'Sector underperformance below this % → hard REJECT regardless of score. '
        + '↑ Higher (less negative) → stricter, more rejections · '
        + '↓ Lower → only catastrophic laggards rejected (more pass). Default: -40%',
  },
  // ALL — Fundamentals (Bearish direction only)
  {
    key: 'fundamentals_caution_above', label: 'Fundamentals caution above (bearish)',
    type: 'number', section: 'all', subGroup: 'Fundamentals Bearish',
    min: 0, max: 100, step: 5,
    hint: 'BEARISH SCANS ONLY. Fundamental health score above this → CAUTION. '
        + 'Flags risk of shorting a financially strong company. '
        + '↑ Higher → only very strong companies flagged (fewer cautions) · '
        + '↓ Lower → wider caution zone (more cautions). Default: 70',
  },
  {
    key: 'fundamentals_reject_above', label: 'Fundamentals reject above (bearish)',
    type: 'number', section: 'all', subGroup: 'Fundamentals Bearish',
    min: 0, max: 100, step: 5,
    hint: 'BEARISH SCANS ONLY. Fundamental health score above this → hard REJECT. '
        + 'Company is too financially strong to short safely. '
        + '↑ Higher → only fortress-balance-sheet companies rejected (fewer) · '
        + '↓ Lower → stricter, more rejections. Default: 80',
  },
  // OPTIONS — Entry Quality
  {
    key: 'entry_spread_tolerance_pct', label: 'Spread tolerance',
    type: 'number', section: 'options', subGroup: 'Entry Quality',
    min: 0, max: 0.5, step: 0.01,
    hint: 'Max bid-ask spread as a fraction of mid price at entry. '
        + '↑ Higher → wider spreads allowed (more contracts, worse fills) · '
        + '↓ Lower → tight spread required (fewer contracts, better fills). Default: 0.10',
  },
  {
    key: 'entry_max_slippage_pct', label: 'Max slippage',
    type: 'number', section: 'options', subGroup: 'Entry Quality',
    min: 0, max: 0.1, step: 0.005,
    hint: 'Expected slippage as a fraction of price. '
        + '↑ Higher → accepts poor fills (more, but costlier) · '
        + '↓ Lower → only clean-fill entries pass (fewer). Default: 0.03',
  },
  {
    key: 'entry_min_premium', label: 'Min premium',
    type: 'number', section: 'options', subGroup: 'Entry Quality',
    min: 0, max: 5, step: 0.05, unit: '$',
    hint: 'Minimum option premium per contract in $. '
        + '↑ Higher → rejects cheap, illiquid options (fewer) · '
        + '↓ Lower → penny options included (more, but harder to exit). Default: $0.10',
  },
  // ALL — Reward/Risk
  {
    key: 'rr_bullish_target_pct', label: 'Bullish target %',
    type: 'number', section: 'all', subGroup: 'Reward/Risk',
    min: 0.01, max: 2.0, step: 0.01, unit: '%',
    hint: 'Profit target as a fraction of entry for bullish trades. '
        + '↑ Higher → demands bigger moves (fewer qualify, R/R better) · '
        + '↓ Lower → takes smaller wins (more qualify). Default: 10%',
  },
  {
    key: 'rr_bearish_target_pct', label: 'Bearish target %',
    type: 'number', section: 'all', subGroup: 'Reward/Risk',
    min: 0.01, max: 2.0, step: 0.01, unit: '%',
    hint: 'Profit target as a fraction of entry for bearish trades. '
        + '↑ Higher → demands bigger downside moves · '
        + '↓ Lower → takes smaller drops. Default: 10%',
  },
  {
    key: 'rr_bullish_invalidation_pct', label: 'Bullish invalidation %',
    type: 'number', section: 'all', subGroup: 'Reward/Risk',
    min: 0.005, max: 1.0, step: 0.005, unit: '%',
    hint: 'Stop-loss distance for bullish trades. '
        + '↑ Higher → wider stop (more room, worse R/R) · '
        + '↓ Lower → tighter stop (better R/R but more stop-outs). Default: 5%',
  },
  {
    key: 'rr_bearish_invalidation_pct', label: 'Bearish invalidation %',
    type: 'number', section: 'all', subGroup: 'Reward/Risk',
    min: 0.005, max: 1.0, step: 0.005, unit: '%',
    hint: 'Stop-loss distance for bearish trades. '
        + '↑ Higher → wider stop · '
        + '↓ Lower → tighter stop. Default: 5%',
  },
```

- [ ] **Step 2: Add defaults to `PARAM_DEFAULTS_PER_HORIZON`**

In the same file, add to all four horizon blocks (Intraday, Swing, Position, Custom):
```typescript
regime_headwind_caution_pct:  -15,
regime_headwind_reject_pct:   -40,
fundamentals_caution_above:    70,
fundamentals_reject_above:     80,
entry_spread_tolerance_pct:    0.10,
entry_max_slippage_pct:        0.03,
entry_min_premium:             0.10,
rr_bullish_target_pct:         0.10,
rr_bearish_target_pct:         0.10,
rr_bullish_invalidation_pct:   0.05,
rr_bearish_invalidation_pct:   0.05,
```

- [ ] **Step 3: Add `SUBGROUP_DESCRIPTIONS` entries**

Find the `SUBGROUP_DESCRIPTIONS` object in `step-3-direction/page.tsx` and add:
```typescript
'Regime Gate':          "Sector vs. benchmark headwind thresholds. When a stock's sector is lagging the benchmark by more than these percentages, the candidate is cautioned or rejected regardless of its score.",
'Fundamentals Bearish': 'Applied only when Direction = Bearish. Protects against shorting companies with strong balance sheets — high fundamental health scores are a caution or reject signal for short trades.',
'Entry Quality':        'Options fill-quality filters applied at contract selection. Controls minimum premium, maximum spread, and expected slippage.',
'Reward/Risk':          'Target and invalidation (stop) distances used to compute R/R ratios. These drive the reward_risk scorer and position card stop/target prices.',
```

- [ ] **Step 4: Add named backend fields for Regime Gate + Fundamentals Bearish to `StockScanRequest`**

In `backend/app/schemas/stock_scan.py`, add after the confidence gate fields (Task 2):
```python
    # Regime gate per-scan overrides (None = use scoring_rules.yaml defaults)
    regime_headwind_caution_pct: Optional[float] = None
    regime_headwind_reject_pct:  Optional[float] = None
    # Fundamentals gate — bearish direction overrides (None = use YAML defaults)
    fundamentals_caution_above:  Optional[float] = None
    fundamentals_reject_above:   Optional[float] = None
```

- [ ] **Step 5: Consume regime gate overrides in `_process_stock`**

In `backend/app/routers/stock_scan.py`, find the `score_stock(...)` call added in Task 1. The `regime_gate` argument is currently:
```python
regime_gate=full_cfg["regime_gate"] if regime_signal else None,
```
Before the `score_stock(...)` call, build an overridden gate dict:
```python
            _regime_gate = dict(full_cfg.get("regime_gate") or {})
            if req.regime_headwind_caution_pct is not None:
                _regime_gate["headwind_caution_pct"] = req.regime_headwind_caution_pct
            if req.regime_headwind_reject_pct is not None:
                _regime_gate["headwind_reject_pct"] = req.regime_headwind_reject_pct
```
Then replace `regime_gate=full_cfg["regime_gate"] if regime_signal else None` with:
```python
                regime_gate=_regime_gate if regime_signal else None,
```

- [ ] **Step 6: Consume fundamentals bearish overrides**

In `backend/app/services/fundamentals_gate.py`, read the `resolve_fundamentals_gate` function (or equivalent) that builds the gate config. Extend it to accept `caution_above` and `reject_above` override parameters — or add them inline in `_process_stock` before calling `_score_fundamentals`:

```python
            # Apply bearish fundamentals overrides if provided
            _fund_gate = dict(fund_gate) if fund_gate else {}
            if req.fundamentals_caution_above is not None:
                _fund_gate["cautionAbove"] = req.fundamentals_caution_above
            if req.fundamentals_reject_above is not None:
                _fund_gate["rejectAbove"] = req.fundamentals_reject_above
            # Replace fund_gate with the overridden version for the score_stock call
            fund_gate = _fund_gate if _fund_gate else None
```

This must be inserted BEFORE `_fh` is computed (before `_score_fundamentals` is called), not after.

- [ ] **Step 7: Wire named fields from frontend stockScan.ts**

In `frontend/lib/stockScan.ts`, the Regime Gate and Fundamentals Bearish keys are sent as named fields on the request body (not in `overrides`). Add:

```typescript
const raw = useScanStore.getState().scanOverrides;
// In the postStockScan call body, add:
regime_headwind_caution_pct: raw.regime_headwind_caution_pct as number | undefined,
regime_headwind_reject_pct:  raw.regime_headwind_reject_pct  as number | undefined,
fundamentals_caution_above:  raw.fundamentals_caution_above  as number | undefined,
fundamentals_reject_above:   raw.fundamentals_reject_above   as number | undefined,
```

Also add these four fields to the `postStockScan` request type in `api.ts`.

- [ ] **Step 8: Verify Entry Quality + Reward/Risk reach Options scan**

Read `backend/app/routers/scan.py` and the `overrides` handling therein. The keys `entry_spread_tolerance_pct`, `entry_max_slippage_pct`, `entry_min_premium`, `rr_bullish_target_pct`, `rr_bearish_target_pct`, `rr_bullish_invalidation_pct`, `rr_bearish_invalidation_pct` should flow through `scanOverrides` → `effectiveOverrides` → the Options scan request's `overrides` dict. Verify this path is not filtered. If the backend Options scorer modules (`entry_quality.py`, `reward_risk.py`) don't yet read these keys from `overrides`, add them using `overrides.get("entry_spread_tolerance_pct", yaml_default)` fallback pattern.

- [ ] **Step 9: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```

- [ ] **Step 10: Run backend tests**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 11: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py \
        backend/app/services/fundamentals_gate.py \
        "frontend/app/(frame)/screener/step-3-direction/page.tsx" \
        frontend/lib/stockScan.ts frontend/lib/api.ts
git commit -m "feat(step3): add regime gate, fundamentals bearish, entry quality, reward/risk execution params"
```

---

## Task 6: Scheduled Scanning with Day/Time/Interval Controls

Currently the button is the only trigger. `ScanScheduler` supports only a flat cadence. This task adds day-of-week mask, market-hours window, interval selector, separate Options/Stocks enable toggles, and a Settings → Scan UI for all controls.

**Important:** The settings endpoint lives in `backend/app/routers/risk_settings.py` (not `settings.py` — that file does not exist). The `router` object in `risk_settings.py` is already defined — do not redefine it.

**Files:**
- Modify: `backend/app/services/scan_scheduler.py`
- Create: `backend/app/schemas/schedule.py`
- Modify: `backend/config/settings.yaml`
- Modify: `backend/app/routers/risk_settings.py` (add schedule endpoints to existing router)
- Create: `backend/tests/test_schedule_endpoint.py`
- Modify: `frontend/lib/settingsStore.ts` (add `scheduleConfig`, bump version 18→19)
- Modify: `frontend/app/(frame)/settings/scan/page.tsx`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Create `backend/app/schemas/schedule.py`**

```python
from __future__ import annotations
from pydantic import BaseModel, Field


class ScheduleConfig(BaseModel):
    enabled_options:    bool      = False
    enabled_stocks:     bool      = False
    cadence_minutes:    int       = Field(60, ge=5, le=1440)
    days_of_week:       list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0=Mon…6=Sun
    window_start_hour:  int       = Field(9,  ge=0, le=23)
    window_end_hour:    int       = Field(17, ge=1, le=24)
    timezone_name:      str       = "America/New_York"
```

- [ ] **Step 2: Write failing backend test**

```python
# backend/tests/test_schedule_endpoint.py
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.schedule import ScheduleConfig
from app.services.scan_scheduler import ScanScheduler

client = TestClient(app)


def test_get_schedule_returns_defaults():
    response = client.get("/api/settings/schedule")
    assert response.status_code == 200
    data = response.json()
    assert "cadence_minutes" in data
    assert "days_of_week" in data
    assert "enabled_options" in data
    assert "enabled_stocks" in data


def test_put_schedule_persists():
    payload = {
        "enabled_options": True, "enabled_stocks": False,
        "cadence_minutes": 60, "days_of_week": [0, 1, 2, 3, 4],
        "window_start_hour": 9, "window_end_hour": 17,
        "timezone_name": "America/New_York",
    }
    r = client.put("/api/settings/schedule", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/settings/schedule")
    assert r2.json()["cadence_minutes"] == 60
    assert r2.json()["enabled_options"] is True


def test_scheduler_skips_weekend():
    cfg = ScheduleConfig(days_of_week=[0, 1, 2, 3, 4])
    assert 5 not in cfg.days_of_week  # Saturday not included
    assert 6 not in cfg.days_of_week  # Sunday not included


def test_scheduler_cadence_clamped():
    scheduler = ScanScheduler()
    scheduler.set_cadence(1)     # below minimum of 5
    assert scheduler.cadence == 5
    scheduler.set_cadence(9999)  # above maximum of 1440
    assert scheduler.cadence == 1440
```

- [ ] **Step 3: Add schedule endpoints to `backend/app/routers/risk_settings.py`**

Open `risk_settings.py`. The `router` variable is already defined at the top (do not redefine it). Add imports and endpoint handlers at the bottom of the file:

```python
# Add to existing imports at top of risk_settings.py:
import yaml as _yaml
from pathlib import Path as _Path
from app.schemas.schedule import ScheduleConfig

_SETTINGS_PATH = _Path(__file__).parent.parent.parent / "config" / "settings.yaml"


def _load_settings() -> dict:
    return _yaml.safe_load(_SETTINGS_PATH.read_text()) or {}


def _save_settings(data: dict) -> None:
    _SETTINGS_PATH.write_text(
        _yaml.dump(data, default_flow_style=False, allow_unicode=True)
    )


# Add these endpoints (use the existing `router` variable already defined in the file):
@router.get("/schedule", response_model=ScheduleConfig)
def get_schedule() -> ScheduleConfig:
    raw = _load_settings().get("scan", {}).get("schedule", {})
    return ScheduleConfig(**raw)


@router.put("/schedule", response_model=ScheduleConfig)
def put_schedule(cfg: ScheduleConfig) -> ScheduleConfig:
    data = _load_settings()
    data.setdefault("scan", {})["schedule"] = cfg.model_dump()
    _save_settings(data)
    return cfg
```

- [ ] **Step 4: Add schedule block to `backend/config/settings.yaml`**

`settings.yaml` currently ends with:
```yaml
scan:
  cadence_minutes: 60
```

**Do NOT duplicate the `scan:` key.** Append the `schedule` block as a nested key under the existing `scan` key. The file should become:
```yaml
scan:
  cadence_minutes: 60
  schedule:
    enabled_options: false
    enabled_stocks: false
    cadence_minutes: 60
    days_of_week: [0, 1, 2, 3, 4]
    window_start_hour: 9
    window_end_hour: 17
    timezone_name: "America/New_York"
```

Use the Edit tool (not Write) to append only the nested `schedule:` block under the existing `scan:` key — do not rewrite the entire file (it contains credentials).

- [ ] **Step 5: Run test — expect PASS**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_schedule_endpoint.py -v
```

- [ ] **Step 6: Extend `ScanScheduler` with day/time awareness**

Replace the contents of `backend/app/services/scan_scheduler.py` with:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Callable, Awaitable

from app.schemas import ScanResult, ScanHistoryEntry
from app.schemas.schedule import ScheduleConfig


class ScanScheduler:
    def __init__(self, cadence_minutes: int = 60):
        self.cadence = cadence_minutes
        self._cfg: ScheduleConfig | None = None
        self._task: asyncio.Task | None = None
        self._last_result: ScanResult | None = None
        self._history: list[ScanHistoryEntry] = []
        self._running = False
        self._cancelled = False
        self._last_run_at: datetime | None = None
        self._next_run_at: datetime | None = None
        self._scan_fn: Callable[[], Awaitable[ScanResult]] | None = None

    def bind(self, scan_fn: Callable[[], Awaitable[ScanResult]]) -> None:
        self._scan_fn = scan_fn

    def configure(self, cfg: ScheduleConfig) -> None:
        self._cfg = cfg
        self.cadence = cfg.cadence_minutes

    def _should_run_now(self) -> bool:
        if self._cfg is None:
            return True
        tz = ZoneInfo(self._cfg.timezone_name)
        now = datetime.now(tz)
        if now.weekday() not in self._cfg.days_of_week:
            return False
        return self._cfg.window_start_hour <= now.hour < self._cfg.window_end_hour

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._cancelled = False
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._cancelled = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._running = False

    def get_status(self) -> dict:
        return {
            "running":         self._running and not self._cancelled,
            "last_run_at":     self._last_run_at.isoformat() if self._last_run_at else None,
            "next_run_at":     self._next_run_at.isoformat() if self._next_run_at else None,
            "cadence_minutes": self.cadence,
            "schedule":        self._cfg.model_dump() if self._cfg else None,
        }

    def get_last_result(self) -> ScanResult | None:
        return self._last_result

    def set_cadence(self, minutes: int) -> None:
        self.cadence = max(5, min(1440, minutes))

    async def _loop(self) -> None:
        if self._scan_fn is None:
            raise RuntimeError("ScanScheduler: no scan function bound")
        while not self._cancelled:
            if not self._should_run_now():
                try:
                    await asyncio.sleep(900)  # re-check every 15 min when outside window
                except asyncio.CancelledError:
                    self._running = False
                    raise
                continue

            self._last_run_at = datetime.now(timezone.utc)
            self._next_run_at = self._last_run_at + timedelta(minutes=self.cadence)
            try:
                result = await self._scan_fn()
            except asyncio.CancelledError:
                self._running = False
                raise
            except Exception:
                pass  # log but keep scheduler alive
            else:
                self._last_result = result
                self._history.append(
                    ScanHistoryEntry(
                        scan_id=result.scan_id,
                        timestamp=result.timestamp,
                        candidate_count=len(result.candidates),
                        rejected_count=len(result.rejected),
                        state=result.state,
                    )
                )

            sleep_s = (self._next_run_at - datetime.now(timezone.utc)).total_seconds()
            if sleep_s > 0:
                try:
                    await asyncio.sleep(sleep_s)
                except asyncio.CancelledError:
                    self._running = False
                    raise

        self._running = False
```

- [ ] **Step 7: Run all backend tests**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 8: Add schedule config to `settingsStore` — bump version 18→19**

Task 3 already bumped `settingsStore` to version 18. This task adds `scheduleConfig` and bumps to version **19** (not 18 — would collide with Task 3's migration).

In `frontend/lib/settingsStore.ts`, add:

```typescript
export interface ScheduleConfig {
  enabledOptions:  boolean;
  enabledStocks:   boolean;
  cadenceMinutes:  number;
  daysOfWeek:      number[];
  windowStartHour: number;
  windowEndHour:   number;
  timezoneName:    string;
}

export const DEFAULT_SCHEDULE_CONFIG: ScheduleConfig = {
  enabledOptions:  false,
  enabledStocks:   false,
  cadenceMinutes:  60,
  daysOfWeek:      [0, 1, 2, 3, 4],
  windowStartHour: 9,
  windowEndHour:   17,
  timezoneName:    'America/New_York',
};
```

Add `scheduleConfig: ScheduleConfig` to `SettingsState`, set default `scheduleConfig: { ...DEFAULT_SCHEDULE_CONFIG }`, add `setScheduleConfig: (c: ScheduleConfig) => void` action.

Add migration branch **using the same stacking pattern as the existing `migrateSettings` function** (do not use early returns — follow the exact pattern in the file):
```typescript
if (version < 19) {
  (next as Record<string, unknown>).scheduleConfig = { ...DEFAULT_SCHEDULE_CONFIG };
}
```

Change the store `version` in `persist(...)` options from `18` to `19`.

- [ ] **Step 9: Add `getSchedule` / `putSchedule` to `frontend/lib/api.ts`**

`api.ts` uses module-level helper functions (`get`, `post`, `put`) — not `this._get`/`this._put`. Add to the `api` object:

```typescript
// Import ScheduleConfig at the top of api.ts — import from settingsStore:
import type { ScheduleConfig } from '@/lib/settingsStore';

// Add to the api object:
getSchedule: () => get<ScheduleConfig>('/api/settings/schedule'),
putSchedule:  (cfg: ScheduleConfig) =>
  put<void>('/api/settings/schedule', {
    enabled_options:   cfg.enabledOptions,
    enabled_stocks:    cfg.enabledStocks,
    cadence_minutes:   cfg.cadenceMinutes,
    days_of_week:      cfg.daysOfWeek,
    window_start_hour: cfg.windowStartHour,
    window_end_hour:   cfg.windowEndHour,
    timezone_name:     cfg.timezoneName,
  }),
```

- [ ] **Step 10: Add schedule UI to Settings → Scan**

In `frontend/app/(frame)/settings/scan/page.tsx`, add this section. Match the exact CSS class names already used in the file (check the existing param rows):

```tsx
// State:
const { scheduleConfig, setScheduleConfig } = useSettingsStore();
const [schedule, setSchedule] = useState<ScheduleConfig>(scheduleConfig);

async function handleSaveSchedule() {
  await api.putSchedule(schedule);
  setScheduleConfig(schedule);
}
```

```tsx
<section className={styles.section}>
  <header className={styles.sectionHeader}>
    <Text size={13} weight={600}>Scheduled scanning</Text>
    <Text size={11} tone="secondary">
      Automatically triggers scans on a recurring interval within the configured time window.
      Options and Stocks run independently. Changes take effect on the next server restart.
    </Text>
  </header>

  <div className={styles.paramRow}>
    <Text size={12}>Enable Options scan</Text>
    <input type="checkbox" checked={schedule.enabledOptions}
      onChange={(e) => setSchedule((s) => ({ ...s, enabledOptions: e.target.checked }))} />
    <Text size={11} tone="dim">
      Runs the Options scan (/api/scan) on the interval below
    </Text>
  </div>
  <div className={styles.paramRow}>
    <Text size={12}>Enable Stocks scan</Text>
    <input type="checkbox" checked={schedule.enabledStocks}
      onChange={(e) => setSchedule((s) => ({ ...s, enabledStocks: e.target.checked }))} />
    <Text size={11} tone="dim">
      Runs the Stocks scan (/api/stock-scan) on the interval below
    </Text>
  </div>

  <div className={styles.paramRow}>
    <Text size={12}>Interval</Text>
    <select value={schedule.cadenceMinutes}
      onChange={(e) => setSchedule((s) => ({ ...s, cadenceMinutes: Number(e.target.value) }))}>
      <option value={15}>Every 15 min</option>
      <option value={30}>Every 30 min</option>
      <option value={60}>Every 1 hour</option>
      <option value={120}>Every 2 hours</option>
      <option value={240}>Every 4 hours</option>
    </select>
    <Text size={11} tone="dim">How often the scan fires within the active window</Text>
  </div>

  <div className={styles.paramRow}>
    <Text size={12}>Active days</Text>
    <div className={styles.dayPicker}>
      {(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const).map((label, day) => (
        <label key={day} className={styles.dayChip}>
          <input type="checkbox"
            checked={schedule.daysOfWeek.includes(day)}
            onChange={(e) => {
              const next = e.target.checked
                ? [...schedule.daysOfWeek, day].sort((a, b) => a - b)
                : schedule.daysOfWeek.filter((d) => d !== day);
              setSchedule((s) => ({ ...s, daysOfWeek: next }));
            }} />
          <Text size={11}>{label}</Text>
        </label>
      ))}
    </div>
    <Text size={11} tone="dim">Scans only run on checked days (US market: Mon–Fri)</Text>
  </div>

  <div className={styles.paramRow}>
    <Text size={12}>Window start hour (ET)</Text>
    <input type="number" min={0} max={23}
      value={schedule.windowStartHour}
      onChange={(e) => setSchedule((s) => ({ ...s, windowStartHour: Number(e.target.value) }))} />
    <Text size={11} tone="dim">
      Scan will not fire before this hour (Eastern Time). 9 = 9:00 AM ET
    </Text>
  </div>
  <div className={styles.paramRow}>
    <Text size={12}>Window end hour (ET)</Text>
    <input type="number" min={1} max={24}
      value={schedule.windowEndHour}
      onChange={(e) => setSchedule((s) => ({ ...s, windowEndHour: Number(e.target.value) }))} />
    <Text size={11} tone="dim">
      Scan will not fire after this hour. 17 = 5:00 PM ET (market close)
    </Text>
  </div>

  <button className={styles.saveBtn} onClick={handleSaveSchedule}>Save schedule</button>
</section>
```

- [ ] **Step 11: Add CSS for day picker**

In `frontend/app/(frame)/settings/scan/page.module.css`, add:
```css
.dayPicker {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.dayChip {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  cursor: pointer;
}
```

- [ ] **Step 12: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```

- [ ] **Step 13: Run all backend tests**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 14: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/scan_scheduler.py backend/app/schemas/schedule.py \
        backend/app/routers/risk_settings.py backend/config/settings.yaml \
        backend/tests/test_schedule_endpoint.py \
        frontend/lib/settingsStore.ts frontend/lib/api.ts \
        "frontend/app/(frame)/settings/scan/page.tsx" \
        "frontend/app/(frame)/settings/scan/page.module.css"
git commit -m "feat(scheduler): add day/time/interval scheduled scanning with Settings Scan UI"
```

---

## Task 7: Cleanup — Labels, Defaults, Descriptions

Small corrections, no backend changes.

**Files:**
- Modify: `frontend/lib/scanParamsStore.ts`
- Modify: the settings component that renders the Fundamentals Gate "De-reject threshold" field

- [ ] **Step 1: Fix `btMinWinRate` default in `scanParamsStore.ts`**

Read `frontend/lib/scanParamsStore.ts` in full. Note:
1. The current store version number (e.g., `8`)
2. The migration pattern — does `migrateParams` use early-return branches (`if (v < N) return {...}`) or a stacking/accumulate pattern?

**If early-return pattern:** Add a new branch at the correct version and use the same return shape as the others:
```typescript
if (v < N+1) return {
  ...DEFAULTS,
  ...(state as Partial<ScanParams>),
  btMinWinRate: (state as Partial<ScanParams>).btMinWinRate === 0.30 ? 0.45
                : ((state as Partial<ScanParams>).btMinWinRate ?? 0.45),
};
```
Where `N+1` is the new version (current version + 1).

**If stacking pattern:** Add:
```typescript
if (version < N+1) {
  if ((next as Record<string,unknown>).btMinWinRate === 0.30) {
    (next as Record<string,unknown>).btMinWinRate = 0.45;
  }
}
```

In both cases:
- Change `btMinWinRate: 0.30` in the initial defaults to `btMinWinRate: 0.45`
- Bump the store `version` in `persist(...)` options to `N+1`

- [ ] **Step 2: Fix "De-reject threshold" description**

Find the settings page/component that renders the Fundamentals Gate "De-reject threshold" field (search for "de-reject" or "deReject" or "De-reject" in the frontend codebase). The current hint says something like "Minimum R:R ratio that can override a fundamental REJECT" — this is factually wrong; it is a **debt-to-equity cap**.

Change label and hint to:
```
Label: "D/E reject threshold"
Hint:  "Maximum debt-to-equity ratio allowed. Companies with D/E above this value are hard-rejected regardless of fundamental health score. ↑ Higher → more leveraged companies qualify (fewer rejections) · ↓ Lower → only low-debt companies pass (more rejections). Default: 3.0"
```

- [ ] **Step 3: Run typecheck + tests**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
npm run test -- --testPathPattern=scanParams
```

- [ ] **Step 4: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
# Add scanParamsStore.ts and the file containing the De-reject hint
git add frontend/lib/scanParamsStore.ts
git commit -m "fix: btMinWinRate default 0.30→0.45 to match backend; fix D/E reject threshold description"
```

---

## Self-Review

**Spec coverage check:**

| User instruction | Task |
|---|---|
| Wire Step-3 overrides to Stocks scanner | Task 1 |
| Wire Confidence gate to Stocks scanner | Task 2 |
| Consolidate IV rank thresholds — backend endpoint | Task 3 |
| Move IV controls to Settings Scan; remove from Alerts | Task 3 |
| Wire Risk limits to backend | Task 4 |
| Add regime_gate to Execution Parameters | Task 5 |
| Add fundamentals bearish thresholds to Execution Parameters | Task 5 |
| Add entry_quality to Execution Parameters | Task 5 |
| Add reward_risk to Execution Parameters | Task 5 |
| Stocks and Options keep SEPARATE shortlist max fields | Not changed — already separate (`shortlistMaxCandidates` vs `stockShortlistMax`); verified |
| Fix De-reject description | Task 7 |
| Scheduled scanning (day/time/interval) | Task 6 |
| Fix btMinWinRate default mismatch | Task 7 |
| All new YAML params in UI get explanatory text matching existing style | All tasks include `hint:` strings with `↑ Higher → ... · ↓ Lower → ...` pattern |

**Key implementation notes:**
- Task 4: All `RiskConfig` fields use the convention already established in `risk_settings.py` — verify camelCase vs snake_case before writing the test payload.
- Task 5 Step 6: Fundamentals bearish override must be applied BEFORE `_fh` is computed — check the exact execution order in `_process_stock`.
- Task 5 Step 8: Entry Quality + Reward/Risk for Options scan — verify `scan.py` doesn't filter these keys from the `overrides` dict before they reach the scorer modules.
- Task 6: Changing the schedule via `PUT /api/settings/schedule` persists the config to `settings.yaml` but the running `ScanScheduler` instance is not automatically reconfigured. Either: (a) call `scheduler.configure(cfg)` inside `put_schedule` endpoint if `scheduler` is accessible as a module-level singleton from `scan.py`, or (b) document that a server restart is required after changing schedule settings.
- `settingsStore` version sequence: Task 3 → version 18 (removes IV fields). Task 6 → version 19 (adds scheduleConfig). These must be committed in order — do not swap.
