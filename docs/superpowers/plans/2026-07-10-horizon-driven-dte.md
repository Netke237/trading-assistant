# Horizon-Driven DTE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the holding horizon actually determine which option expiries the screener surfaces, via one uniform rule (`DTE = holding × 2`) across all seven presets, computed and enforced on the backend.

**Architecture:** A new pure function `dte_window()` derives `(min_dte, max_dte)` from a holding period. `scan.py` calls it once per scan, feeds the result into the already-working `validate_contract(overrides={"min_dte": …, "max_dte": …})` path, and echoes the window back in `ScanResult.dte_window` so the scan log can display what was actually enforced. The frontend stops regex-parsing a display string and sends structured hold days instead.

**Tech Stack:** FastAPI + Pydantic v2 + pytest (backend); Next.js 15 + TypeScript + Zustand + Jest (frontend).

**Spec:** `docs/superpowers/specs/2026-07-10-horizon-driven-dte-design.md`

---

## File Structure

**Backend**

| File | Responsibility |
|---|---|
| `backend/app/scoring/dte_window.py` | **New.** Pure derivation of the DTE window from a holding period. No I/O. |
| `backend/tests/test_dte_window.py` | **New.** Unit tests for the pure function. |
| `backend/tests/test_horizon_dte.py` | **New.** Enforcement + schema tests. |
| `backend/config/contract_rules.yaml` | Adds `dte_holding_multiplier`. |
| `backend/app/scoring/contract_validator.py` | Adds `dte_holding_multiplier()` config reader. |
| `backend/app/schemas/__init__.py` | `DteWindow` model; `ScanRequest` hold days; `ScanResult.dte_window`. |
| `backend/app/routers/scan.py` | Computes the window, enforces it, attaches it to the result. |

**Frontend**

| File | Responsibility |
|---|---|
| `frontend/lib/horizonPresets.ts` | **New.** Single source of truth for the 7 presets + legacy migration + display-only DTE preview. |
| `frontend/lib/__tests__/horizonPresets.test.ts` | **New.** Preset table + migration tests. |
| `frontend/types/domain.ts` | `DteWindow` type. |
| `frontend/lib/api.ts` | `postScan` accepts hold days. |
| `frontend/lib/scanStore.ts` | Structured `ScanContext`; persist v9 → v10 migration. |
| `frontend/components/organisms/RunScanButton/index.tsx` | Sends hold days; deletes the regex string parsing. |
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | 7 preset buttons; read-only DTE rows; log renders returned window. |

`horizonPresets.ts` exists so `page.tsx` and `RunScanButton` share one preset table instead of duplicating it — the duplication is what let the UI and the request diverge in the first place.

---

## Task 1: The `dte_window()` pure function

**Files:**
- Create: `backend/app/scoring/dte_window.py`
- Test: `backend/tests/test_dte_window.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_dte_window.py`:

```python
import pytest

from app.scoring.dte_window import dte_window


def test_position_preset_reproduces_existing_band():
    """15-45 day hold must yield the existing 30-90 DTE band exactly."""
    assert dte_window(15, 45, 2.0) == (30, 90)


def test_intraday_clamps_zero_to_one():
    """0 * 2 = 0 is not a tradeable DTE; the bottom clamp lifts it to 1."""
    assert dte_window(0, 2, 2.0) == (1, 4)


def test_swing_preset():
    assert dte_window(5, 15, 2.0) == (10, 30)


def test_quarterly_preset():
    assert dte_window(45, 60, 2.0) == (90, 120)


def test_semi_annual_preset():
    assert dte_window(90, 105, 2.0) == (180, 210)


def test_annual_preset():
    assert dte_window(165, 200, 2.0) == (330, 400)


def test_custom_range_is_doubled():
    """The originally-reported case: typing 60-185 means expiries 120-370 days out."""
    assert dte_window(60, 185, 2.0) == (120, 370)


def test_max_below_min_is_clamped_up():
    """A degenerate 0-0 hold clamps min to 1, and max must not fall below it."""
    assert dte_window(0, 0, 2.0) == (1, 1)


def test_negative_hold_raises():
    with pytest.raises(ValueError):
        dte_window(-1, 10, 2.0)


def test_non_positive_multiplier_raises():
    with pytest.raises(ValueError):
        dte_window(5, 15, 0.0)


def test_hold_max_below_hold_min_raises():
    with pytest.raises(ValueError):
        dte_window(20, 5, 2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_dte_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.scoring.dte_window'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/scoring/dte_window.py`:

```python
"""Derive an option contract's DTE window from an intended holding period.

An option should never be held to expiry — theta decay accelerates in the final
weeks. The contract's days-to-expiry must therefore exceed the intended hold so
the position can be exited with time value remaining.

One rule, applied uniformly to every horizon preset including Custom:

    min_dte = max(1, round(hold_min * multiplier))
    max_dte = round(hold_max * multiplier)

The bottom clamp only ever engages for the Intraday preset, where a 0-day hold
would otherwise produce an untradeable 0-DTE contract.
"""


def dte_window(hold_min: int, hold_max: int, multiplier: float) -> tuple[int, int]:
    """Return the (min_dte, max_dte) contract window for a holding period.

    Args:
        hold_min:   Minimum intended holding period, in calendar days. >= 0.
        hold_max:   Maximum intended holding period, in calendar days. >= hold_min.
        multiplier: DTE-to-holding ratio. Must be > 0.

    Returns:
        (min_dte, max_dte), both >= 1, with max_dte >= min_dte.

    Raises:
        ValueError: on negative holds, a non-positive multiplier, or hold_max < hold_min.
    """
    if hold_min < 0 or hold_max < 0:
        raise ValueError(f"holding period must be non-negative, got ({hold_min}, {hold_max})")
    if hold_max < hold_min:
        raise ValueError(f"hold_max {hold_max} is below hold_min {hold_min}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier}")

    min_dte = max(1, round(hold_min * multiplier))
    max_dte = round(hold_max * multiplier)
    if max_dte < min_dte:
        max_dte = min_dte
    return min_dte, max_dte
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_dte_window.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/dte_window.py backend/tests/test_dte_window.py
git commit -m "feat(scan): add dte_window() — derive contract DTE from holding period"
```

---

## Task 2: Config multiplier + reader

**Files:**
- Modify: `backend/config/contract_rules.yaml`
- Modify: `backend/app/scoring/contract_validator.py`
- Test: `backend/tests/test_horizon_dte.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_horizon_dte.py`:

```python
from app.scoring.contract_validator import dte_holding_multiplier


def test_multiplier_loads_from_config():
    assert dte_holding_multiplier() == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_horizon_dte.py -v`
Expected: FAIL — `ImportError: cannot import name 'dte_holding_multiplier'`

- [ ] **Step 3: Add the config key**

In `backend/config/contract_rules.yaml`, insert directly below the `score_thresholds` block (after line 5, before the `# Hard-reject rules (FR-24)` comment):

```yaml
# DTE is derived from the selected holding horizon: dte = holding_days * multiplier.
# Never hold an option to expiry — this buffer leaves time value at exit.
dte_holding_multiplier: 2.0
```

Leave `hard_reject.min_dte: 21` and `hard_reject.max_dte: 90` untouched. They remain the fallback used when a request carries no holding period.

- [ ] **Step 4: Add the reader**

In `backend/app/scoring/contract_validator.py`, immediately after the `_load_config()` function (which ends at line 45), add:

```python
def dte_holding_multiplier() -> float:
    """DTE-to-holding-period ratio from contract_rules.yaml."""
    return float(_load_config().get("dte_holding_multiplier", 2.0))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_horizon_dte.py -v`
Expected: PASS — 1 passed

- [ ] **Step 6: Verify no existing contract test regressed**

Run: `cd backend && pytest tests/test_overrides.py tests/test_contracts_scoring.py -v`
Expected: all PASS. In particular `test_min_dte_override_rejects_near_expiry` still relies on the default `min_dte=21` and must stay green.

- [ ] **Step 7: Commit**

```bash
git add backend/config/contract_rules.yaml backend/app/scoring/contract_validator.py backend/tests/test_horizon_dte.py
git commit -m "feat(scan): add dte_holding_multiplier config"
```

---

## Task 3: Schemas — hold days in, DTE window out

**Files:**
- Modify: `backend/app/schemas/__init__.py:442-496`
- Test: `backend/tests/test_horizon_dte.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_horizon_dte.py`:

```python
from app.schemas import DteWindow, ScanRequest, ScanResult


def test_scan_request_accepts_hold_days():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bullish",
        "horizon": "Position",
        "hold_min_days": 15,
        "hold_max_days": 45,
    })
    assert req.hold_min_days == 15
    assert req.hold_max_days == 45


def test_scan_request_hold_days_default_none():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bullish",
        "horizon": "Position",
    })
    assert req.hold_min_days is None
    assert req.hold_max_days is None


def test_scan_result_carries_dte_window():
    result = ScanResult(
        scan_id="REC-1",
        timestamp="2026-07-10T00:00:00Z",
        candidates=[],
        rejected=[],
        dte_window=DteWindow(min_dte=30, max_dte=90, multiplier=2.0),
    )
    assert result.dte_window.min_dte == 30
    assert result.dte_window.max_dte == 90
    assert result.dte_window.multiplier == 2.0


def test_scan_result_dte_window_defaults_none():
    result = ScanResult(scan_id="REC-1", timestamp="t", candidates=[], rejected=[])
    assert result.dte_window is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_horizon_dte.py -v`
Expected: FAIL — `ImportError: cannot import name 'DteWindow'`

- [ ] **Step 3: Add `hold_min_days` / `hold_max_days` to `ScanRequest`**

In `backend/app/schemas/__init__.py`, inside `class ScanRequest` (starts line 442), add after the `max_cap_usd` line (line 451):

```python
    # Holding horizon (calendar days). The backend derives the contract DTE window
    # from these: dte = hold * dte_holding_multiplier. When absent, contract_rules.yaml
    # hard_reject.min_dte/max_dte apply as a fallback.
    hold_min_days: Optional[int] = None
    hold_max_days: Optional[int] = None
```

- [ ] **Step 4: Add the `DteWindow` model**

In the same file, insert immediately before `class ScanResult(BaseModel):` (line 485):

```python
class DteWindow(BaseModel):
    """The contract expiry window actually enforced for a scan."""
    min_dte:    int
    max_dte:    int
    multiplier: float


```

- [ ] **Step 5: Add `dte_window` to `ScanResult`**

In `class ScanResult`, add after the `direction_banner` line (line 496):

```python
    dte_window: Optional[DteWindow] = None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/test_horizon_dte.py -v`
Expected: PASS — 5 passed

- [ ] **Step 7: Verify the schemas import cleanly**

Run: `cd backend && python -c "from app.schemas import ScanRequest, ScanResult, DteWindow; print('ok')"`
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/__init__.py backend/tests/test_horizon_dte.py
git commit -m "feat(scan): ScanRequest hold days, ScanResult.dte_window"
```

---

## Task 4: Enforce the window in `scan.py`

The DTE keys must reach `validate_contract()` but **must not** reach `score_stock()`. Both currently receive the same `overrides` dict.

**Files:**
- Modify: `backend/app/routers/scan.py:262-286` (signature), `:480` (call site), `:872-890` (task dispatch), `:997-1009` (result)
- Test: `backend/tests/test_horizon_dte.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_horizon_dte.py`:

```python
from datetime import date, timedelta

from app.scoring.contract_validator import validate_contract


def _expiry_str(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def _make_contract(*, bid=1.0, ask=1.10, delta=0.45, days=40, volume=500, oi=1000) -> dict:
    return {
        "symbol": "AAPL",
        "strike": 185,
        "expiry": _expiry_str(days),
        "is_call": True,
        "bid": bid,
        "ask": ask,
        "price": (bid + ask) / 2,
        "delta": delta,
        "theta": -0.05,
        "volume": volume,
        "open_interest": oi,
        "iv_rank": 30,
        "ivRank": 30,
    }


def test_position_hold_rejects_the_reported_22_dte_contract():
    """The 31.07.2026 case: a 22-DTE contract must not survive a 15-45 day hold."""
    min_dte, max_dte = dte_window(15, 45, 2.0)
    card = validate_contract(_make_contract(days=22), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte})
    assert "dte_too_short" in card.reject_reasons


def test_position_hold_accepts_a_60_dte_contract():
    min_dte, max_dte = dte_window(15, 45, 2.0)
    card = validate_contract(_make_contract(days=60), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte})
    assert "dte_too_short" not in card.reject_reasons
    assert "dte_too_long" not in card.reject_reasons


def test_annual_hold_accepts_a_365_dte_contract():
    min_dte, max_dte = dte_window(165, 200, 2.0)
    card = validate_contract(_make_contract(days=365), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte})
    assert "dte_too_short" not in card.reject_reasons
    assert "dte_too_long" not in card.reject_reasons
```

Add `from app.scoring.dte_window import dte_window` to the imports at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_horizon_dte.py -k "22_dte or 60_dte or 365_dte" -v`
Expected: The 22-DTE test FAILS (`dte_too_short` absent — the fixed `min_dte=21` lets 22 through). This is the reported bug, reproduced.

- [ ] **Step 3: Add the `dte_bounds` parameter to `_process_symbol`**

In `backend/app/routers/scan.py`, in the `_process_symbol` signature, add after `overrides: dict | None = None,` (line 274):

```python
    dte_bounds: tuple[int, int] | None = None,
```

- [ ] **Step 4: Feed the bounds into `validate_contract` only**

Replace line 480:

```python
    scored = [(validate_contract(c, card.score, overrides=overrides), c) for c in augmented]
```

with:

```python
    # DTE bounds are derived from the holding horizon and apply to contracts only.
    # They must never reach score_stock(), which shares the same `overrides` dict.
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        contract_overrides["min_dte"], contract_overrides["max_dte"] = dte_bounds
    scored = [(validate_contract(c, card.score, overrides=contract_overrides or None), c)
              for c in augmented]
```

- [ ] **Step 5: Compute the window once per scan**

In `backend/app/routers/scan.py`, add to the imports near the other `app.scoring` imports:

```python
from app.scoring.contract_validator import dte_holding_multiplier
from app.scoring.dte_window import dte_window
```

and add `DteWindow` to the existing `from app.schemas import (...)` import list.

In `run_scan`, immediately before `semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)` (line 862), insert:

```python
    # ── DTE window from the holding horizon ───────────────────────────────────
    # Absent hold days (e.g. an older client), contract_rules.yaml defaults apply.
    _dte_bounds: tuple[int, int] | None = None
    _dte_win: DteWindow | None = None
    if req.hold_min_days is not None and req.hold_max_days is not None:
        _mult = dte_holding_multiplier()
        _dte_bounds = dte_window(req.hold_min_days, req.hold_max_days, _mult)
        _dte_win = DteWindow(min_dte=_dte_bounds[0], max_dte=_dte_bounds[1], multiplier=_mult)
        _log.info("SCAN %s dte_window: %d-%dd (hold %d-%dd x %.1f)",
                  scan_id, _dte_bounds[0], _dte_bounds[1],
                  req.hold_min_days, req.hold_max_days, _mult)
```

- [ ] **Step 6: Pass the bounds into each task**

In the `_process_symbol(...)` call inside `tasks = [` (line 873), add after `overrides=dict(req.overrides) if req.overrides else None,` (line 879):

```python
                dte_bounds=_dte_bounds,
```

- [ ] **Step 7: Attach the window to the response**

In the `result = ScanResult(` construction (line 997), add after `direction_banner=_direction_banner,` (line 1008):

```python
            dte_window=_dte_win,
```

Leave the `_compute_deltas(ScanResult(...))` call on line 993 unchanged — it is a throwaway comparison object.

- [ ] **Step 8: Run the tests**

Run: `cd backend && pytest tests/test_horizon_dte.py tests/test_dte_window.py -v`
Expected: all PASS, including the 22-DTE rejection.

- [ ] **Step 9: Verify nothing else regressed**

Run: `cd backend && pytest -q`
Expected: no new failures versus the pre-change baseline.

- [ ] **Step 10: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_horizon_dte.py
git commit -m "feat(scan): enforce holding-horizon DTE window on contracts"
```

---

## Task 5: Frontend preset module

**Files:**
- Create: `frontend/lib/horizonPresets.ts`
- Test: `frontend/lib/__tests__/horizonPresets.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/horizonPresets.test.ts`:

```ts
import {
  HORIZON_PRESETS,
  presetByKey,
  previewDteWindow,
  scoringHorizonForHold,
  migrateLegacyHorizon,
} from '../horizonPresets';

describe('HORIZON_PRESETS', () => {
  it('has seven presets', () => {
    expect(HORIZON_PRESETS).toHaveLength(7);
  });

  it('maps every long-dated preset to Position scoring', () => {
    for (const key of ['Position', 'Quarterly', 'SemiAnnual', 'Annual'] as const) {
      expect(presetByKey(key).scoringHorizon).toBe('Position');
    }
  });

  it('keeps the short presets on their own scoring horizons', () => {
    expect(presetByKey('Intraday').scoringHorizon).toBe('Intraday');
    expect(presetByKey('Swing').scoringHorizon).toBe('Swing');
  });
});

describe('previewDteWindow', () => {
  it.each([
    ['Intraday',   0,   2,   1,   4],
    ['Swing',      5,   15,  10,  30],
    ['Position',   15,  45,  30,  90],
    ['Quarterly',  45,  60,  90,  120],
    ['SemiAnnual', 90,  105, 180, 210],
    ['Annual',     165, 200, 330, 400],
  ])('%s: hold %i-%i -> dte %i-%i', (_label, hMin, hMax, dMin, dMax) => {
    expect(previewDteWindow(hMin as number, hMax as number)).toEqual([dMin, dMax]);
  });

  it('doubles a custom range', () => {
    expect(previewDteWindow(60, 185)).toEqual([120, 370]);
  });

  it('clamps a zero minimum up to 1', () => {
    expect(previewDteWindow(0, 0)).toEqual([1, 1]);
  });
});

describe('scoringHorizonForHold', () => {
  it('derives the custom scoring horizon from hold_max', () => {
    expect(scoringHorizonForHold(2)).toBe('Intraday');
    expect(scoringHorizonForHold(4)).toBe('Intraday');
    expect(scoringHorizonForHold(15)).toBe('Swing');
    expect(scoringHorizonForHold(20)).toBe('Swing');
    expect(scoringHorizonForHold(21)).toBe('Position');
    expect(scoringHorizonForHold(185)).toBe('Position');
  });
});

describe('migrateLegacyHorizon', () => {
  it('parses a legacy custom string, preserving the typed days', () => {
    expect(migrateLegacyHorizon('Custom (60–185d)')).toEqual({
      horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
    });
  });

  it('parses a legacy preset string', () => {
    expect(migrateLegacyHorizon('Swing (5–15d)')).toEqual({
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
    });
  });

  it('falls back to Swing on an unknown or missing string', () => {
    expect(migrateLegacyHorizon(undefined)).toEqual({
      horizonPreset: 'Swing', holdMin: 5, holdMax: 15,
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=horizonPresets`
Expected: FAIL — `Cannot find module '../horizonPresets'`

- [ ] **Step 3: Write the implementation**

Create `frontend/lib/horizonPresets.ts`:

```ts
/*
 * Single source of truth for the holding-horizon presets.
 *
 * The button expresses a HOLDING PERIOD. The contract DTE window is derived from
 * it as `hold * DTE_HOLDING_MULTIPLIER`. The backend performs the authoritative
 * derivation and returns the enforced window in ScanResult.dte_window — the
 * preview below is for display only, before a scan has run.
 */

export type HorizonKey =
  | 'Intraday' | 'Swing' | 'Position'
  | 'Quarterly' | 'SemiAnnual' | 'Annual'
  | 'Custom';

/** The three horizons the backend scorer understands. */
export type ScoringHorizon = 'Intraday' | 'Swing' | 'Position';

export interface HorizonPreset {
  key:            HorizonKey;
  label:          string;
  hint:           string;
  holdMin:        number;
  holdMax:        number;
  scoringHorizon: ScoringHorizon;
}

/** Kept in sync with backend/config/contract_rules.yaml: dte_holding_multiplier. */
export const DTE_HOLDING_MULTIPLIER = 2.0;

export const HORIZON_PRESETS: HorizonPreset[] = [
  { key: 'Intraday',   label: 'Intraday',    hint: '0–2 days',     holdMin: 0,   holdMax: 2,   scoringHorizon: 'Intraday' },
  { key: 'Swing',      label: 'Swing',       hint: '5–15 days',    holdMin: 5,   holdMax: 15,  scoringHorizon: 'Swing'    },
  { key: 'Position',   label: 'Position',    hint: '15–45 days',   holdMin: 15,  holdMax: 45,  scoringHorizon: 'Position' },
  { key: 'Quarterly',  label: 'Quarterly',   hint: '45–60 days',   holdMin: 45,  holdMax: 60,  scoringHorizon: 'Position' },
  { key: 'SemiAnnual', label: 'Semi-annual', hint: '90–105 days',  holdMin: 90,  holdMax: 105, scoringHorizon: 'Position' },
  { key: 'Annual',     label: 'Annual',      hint: '165–200 days', holdMin: 165, holdMax: 200, scoringHorizon: 'Position' },
  { key: 'Custom',     label: 'Custom',      hint: 'Set range',    holdMin: 5,   holdMax: 15,  scoringHorizon: 'Swing'    },
];

export function presetByKey(key: HorizonKey): HorizonPreset {
  const found = HORIZON_PRESETS.find((p) => p.key === key);
  return found ?? HORIZON_PRESETS[1];   // Swing
}

/** Custom has no fixed scoring horizon — derive it from the upper hold bound. */
export function scoringHorizonForHold(holdMax: number): ScoringHorizon {
  if (holdMax <= 4)  return 'Intraday';
  if (holdMax <= 20) return 'Swing';
  return 'Position';
}

/**
 * Display-only preview of the window the backend will enforce.
 * Mirrors backend/app/scoring/dte_window.py exactly.
 */
export function previewDteWindow(holdMin: number, holdMax: number): [number, number] {
  const lo = Math.max(1, Math.round(holdMin * DTE_HOLDING_MULTIPLIER));
  const hi = Math.max(lo, Math.round(holdMax * DTE_HOLDING_MULTIPLIER));
  return [lo, hi];
}

/** Upgrade a v9 stringly-typed horizon ("Custom (60–185d)") to structured state. */
export function migrateLegacyHorizon(horizon: string | undefined): {
  horizonPreset: HorizonKey; holdMin: number; holdMax: number;
} {
  if (horizon?.startsWith('Custom')) {
    const m = horizon.match(/(\d+)\s*[–-]\s*(\d+)/);
    if (m) return { horizonPreset: 'Custom', holdMin: Number(m[1]), holdMax: Number(m[2]) };
    return { horizonPreset: 'Custom', holdMin: 5, holdMax: 15 };
  }
  for (const p of HORIZON_PRESETS) {
    if (p.key !== 'Custom' && horizon?.startsWith(p.key)) {
      return { horizonPreset: p.key, holdMin: p.holdMin, holdMax: p.holdMax };
    }
  }
  const swing = presetByKey('Swing');
  return { horizonPreset: 'Swing', holdMin: swing.holdMin, holdMax: swing.holdMax };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=horizonPresets`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/horizonPresets.ts frontend/lib/__tests__/horizonPresets.test.ts
git commit -m "feat(screener): horizon preset module — 7 presets, hold-based"
```

---

## Task 6: `DteWindow` type + `postScan` hold days

**Files:**
- Modify: `frontend/types/domain.ts`
- Modify: `frontend/lib/api.ts:328-348`

- [ ] **Step 1: Add the `DteWindow` type**

In `frontend/types/domain.ts`, add near the other scan result types:

```ts
export interface DteWindow {
  min_dte:    number;
  max_dte:    number;
  multiplier: number;
}
```

Then find the `ScanResult` interface in the same file and add:

```ts
  dte_window?: DteWindow;
```

If `ScanResult` is not declared in `types/domain.ts`, locate it with:
`cd frontend && grep -rn "interface ScanResult" types lib` and add the field there instead.

- [ ] **Step 2: Extend `postScan`**

In `frontend/lib/api.ts`, change the `postScan` signature (line 328) to accept a `hold` argument after `horizon`:

```ts
  postScan: (
    universe: string[],
    direction: string,
    horizon: string,
    hold: { hold_min_days: number; hold_max_days: number },
    filters?: {
      min_price?: number; max_price?: number; min_cap_usd?: number; max_cap_usd?: number;
      confidence_caution_below?: number; confidence_reject_below?: number;
      fundamentals_enabled?: boolean;
      fundamentals_caution_below?: number;
      fundamentals_reject_below?: number;
      fundamentals_de_reject?: number;
    },
    overrides?: Record<string, number | boolean | string>,
    spreads?: {
      spread_width?: number;
      short_leg_delta?: number;
      iv_rank_threshold?: number;
      min_credit?: number;
      max_debit_pct?: number;
    },
  ) =>
```

In the request body this function builds, spread `...hold` alongside `universe`, `direction`, and `horizon` so `hold_min_days` and `hold_max_days` are sent as top-level fields (matching `ScanRequest`).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: errors ONLY at the `api.postScan(...)` call site in `RunScanButton/index.tsx` (fixed in Task 8) and in `frontend/__mocks__/`. Update the `postScan` mock signature in `frontend/__mocks__/` to accept the new argument.

- [ ] **Step 4: Commit**

```bash
git add frontend/types/domain.ts frontend/lib/api.ts frontend/__mocks__/
git commit -m "feat(api): postScan sends hold days; DteWindow type"
```

---

## Task 7: Structured `ScanContext` + persist migration

**Files:**
- Modify: `frontend/lib/scanStore.ts:12-16` (interface), `:194-206` (migrate)

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/scanStoreHorizonMigration.test.ts`:

```ts
import { migrateLegacyHorizon } from '../horizonPresets';

describe('scanStore v9 -> v10 context migration', () => {
  it('preserves the typed custom range that v9 discarded', () => {
    const legacy = { universe: 'SP500', direction: 'Bullish', horizon: 'Custom (60–185d)' };
    const migrated = { universe: legacy.universe, direction: legacy.direction, ...migrateLegacyHorizon(legacy.horizon) };
    expect(migrated).toEqual({
      universe: 'SP500', direction: 'Bullish',
      horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
    });
  });

  it('handles a null context', () => {
    const ctx: { horizon?: string } | null = null;
    expect(ctx).toBeNull();
  });
});
```

- [ ] **Step 2: Run it**

Run: `cd frontend && npm run test -- --testPathPattern=scanStoreHorizonMigration`
Expected: PASS (it exercises `migrateLegacyHorizon`, already built in Task 5).

- [ ] **Step 3: Restructure `ScanContext`**

In `frontend/lib/scanStore.ts`, replace the interface at lines 12-16:

```ts
export interface ScanContext {
  universe:  string;       // "SP500" | "NAS100" | ...
  direction: Direction;
  horizon:   string;       // "Swing (5–15d)"
}
```

with:

```ts
import type { HorizonKey } from './horizonPresets';

export interface ScanContext {
  universe:      string;      // "SP500" | "NAS100" | ...
  direction:     Direction;
  horizonPreset: HorizonKey;  // 'Swing' | 'Custom' | ...
  holdMin:       number;      // calendar days
  holdMax:       number;      // calendar days
}
```

- [ ] **Step 4: Bump the persist version and add the migration branch**

In the same file, change `version: 9,` (line 194) to `version: 10,`.

Add this branch after the `if (version < 9)` line (line 206):

```ts
        if (version < 10) {
          const ctx = s.context as { universe?: string; direction?: string; horizon?: string } | null | undefined;
          s = {
            ...s,
            context: ctx
              ? {
                  universe:  ctx.universe  ?? 'SP500',
                  direction: ctx.direction ?? 'Bullish',
                  ...migrateLegacyHorizon(ctx.horizon),
                }
              : null,
          };
        }
```

Add the import at the top of the file:

```ts
import { migrateLegacyHorizon } from './horizonPresets';
```

- [ ] **Step 5: Typecheck to find every consumer of `context.horizon`**

Run: `cd frontend && npm run typecheck`
Expected: errors at every site reading `context.horizon`. Enumerate them:
`cd frontend && grep -rn "context?\.horizon\|context\.horizon" app components lib`

Fix each to read `context.horizonPreset` / `context.holdMin` / `context.holdMax`. The TopBar scan-context string should render as `` `${preset.label} (${holdMin}–${holdMax}d hold)` ``.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm run test`
Expected: any failure is a test asserting the old `horizon: 'Swing (5–15d)'` shape (e.g. `RunScanButton/__tests__/regimeGate.test.tsx:19,69`). Update those fixtures to the structured shape.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/scanStore.ts frontend/lib/__tests__/scanStoreHorizonMigration.test.ts
git commit -m "refactor(scanStore): structured horizon context, persist v10"
```

---

## Task 8: `RunScanButton` sends hold days

This deletes the regex string-parsing that is the root cause of the original bug.

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/index.tsx:101-110` and `:167-173`
- Test: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx` a test asserting the payload. Follow the mocking style already used in that file for `api.postScan`; assert:

```ts
it('sends hold days and the scoring horizon, never min_dte/max_dte', async () => {
  // arrange: scanStore context = { universe: 'SP500', direction: 'Bullish',
  //                                horizonPreset: 'Custom', holdMin: 60, holdMax: 185 }
  // act: click Run Scan
  const [, , horizon, hold, , overrides] = (api.postScan as jest.Mock).mock.calls[0];
  expect(horizon).toBe('Position');                    // derived from holdMax=185
  expect(hold).toEqual({ hold_min_days: 60, hold_max_days: 185 });
  expect(overrides).not.toHaveProperty('min_dte');
  expect(overrides).not.toHaveProperty('max_dte');
});
```

- [ ] **Step 2: Run it**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: FAIL — `postScan` is still called with the old argument order.

- [ ] **Step 3: Replace the string parsing**

In `frontend/components/organisms/RunScanButton/index.tsx`, replace lines 101-110:

```ts
    const direction   = context?.direction ?? 'Bullish';
    const horizonRaw  = context?.horizon   ?? 'Swing (5–15d)';
    const horizonKey  = horizonRaw.split(' ')[0];  // "Swing (5–15d)" → "Swing"
    // "Custom" is not a valid API horizon — map to nearest preset by max-day value
    let horizon: string = horizonKey;
    if (horizonKey === 'Custom') {
      const maxMatch = horizonRaw.match(/–(\d+)d/);
      const maxDays  = maxMatch ? Number(maxMatch[1]) : 15;
      horizon = maxDays <= 4 ? 'Intraday' : maxDays <= 20 ? 'Swing' : 'Position';
    }
```

with:

```ts
    const direction = context?.direction ?? 'Bullish';
    const presetKey = context?.horizonPreset ?? 'Swing';
    const holdMin   = context?.holdMin ?? presetByKey('Swing').holdMin;
    const holdMax   = context?.holdMax ?? presetByKey('Swing').holdMax;
    // The backend scorer knows only Intraday/Swing/Position. Long-dated presets
    // and Custom map onto one of those; the DTE window comes from the hold days.
    const horizon: string = presetKey === 'Custom'
      ? scoringHorizonForHold(holdMax)
      : presetByKey(presetKey).scoringHorizon;
```

Add the import:

```ts
import { presetByKey, scoringHorizonForHold } from '@/lib/horizonPresets';
```

- [ ] **Step 4: Pass hold days to `postScan`**

Change the call at line 167 from:

```ts
    api.postScan(universe, direction, horizon, filters, effectiveOverrides, {
```

to:

```ts
    api.postScan(universe, direction, horizon,
      { hold_min_days: holdMin, hold_max_days: holdMax },
      filters, effectiveOverrides, {
```

- [ ] **Step 5: Confirm no DTE keys are sent**

Run: `cd frontend && grep -n "min_dte\|max_dte" components/organisms/RunScanButton/index.tsx`
Expected: no output. The backend now owns the window.

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/components/organisms/RunScanButton/index.tsx frontend/components/organisms/RunScanButton/__tests__/
git commit -m "fix(screener): send hold days, drop display-string regex parsing"
```

---

## Task 9: Step 3 page — 7 buttons, read-only DTE, real log

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`

- [ ] **Step 1: Delete the local preset table and horizon helpers**

Remove the local `HorizonKey` type (line 140), `HORIZON_PRESETS` (lines 142-147), `horizonLabel()` (727-732), `parseHorizonKey()` (734-741), and `parseCustomDays()` (743-747).

Import from the shared module instead:

```ts
import {
  HORIZON_PRESETS, presetByKey, previewDteWindow, scoringHorizonForHold,
  type HorizonKey,
} from '@/lib/horizonPresets';
```

- [ ] **Step 2: Add the three new preset param blocks**

`PARAM_DEFAULTS_PER_HORIZON` (line 327) is keyed by `HorizonKey` and now needs 7 keys. Per design decision D1 the new presets reuse Position's parameters exactly. After the `Position: { … }` block (ends line 396), add:

```ts
  // D1: long-dated presets reuse Position scoring; only the DTE window differs.
  Quarterly:  { ...PARAM_DEFAULTS_POSITION },
  SemiAnnual: { ...PARAM_DEFAULTS_POSITION },
  Annual:     { ...PARAM_DEFAULTS_POSITION },
```

To make that spread possible, first hoist the Position object to a named const above the map:

```ts
const PARAM_DEFAULTS_POSITION: ParamDefaults = { /* the existing Position block, moved verbatim */ };
```

and reference it as `Position: PARAM_DEFAULTS_POSITION,` inside the map.

- [ ] **Step 3: Make `min_dte` / `max_dte` read-only**

In `PARAM_DEFS` (lines 273-276), change the two Contract rows from `type: 'number'` to `type: 'display'`:

```ts
  { key: 'min_dte', label: 'Min DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
  { key: 'max_dte', label: 'Max DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
```

Remove `min_dte` and `max_dte` from all seven blocks of `PARAM_DEFAULTS_PER_HORIZON`. Instead, compute them for display in the component body:

```ts
  const [previewMinDte, previewMaxDte] = previewDteWindow(holdMin, holdMax);
```

and pass them into the `ParamRow` for those two keys via the existing `defaultVal` prop, e.g. by special-casing in the `defaults[def.key]` lookup:

```ts
  const displayDefaults: ParamDefaults = { ...defaults, min_dte: previewMinDte, max_dte: previewMaxDte };
```

then use `displayDefaults[def.key] ?? null` where `defaults[def.key] ?? null` is passed today (lines 987, 1021).

- [ ] **Step 4: Render 7 buttons and bind state to the store**

Replace the local `hz` / `minDays` / `maxDays` state initialisers (lines 762-764) to read from the structured context:

```ts
  const [hz,      setHz]      = useState<HorizonKey>(() => context?.horizonPreset ?? 'Swing');
  const [holdMin, setHoldMin] = useState<number>(() => context?.holdMin ?? presetByKey('Swing').holdMin);
  const [holdMax, setHoldMax] = useState<number>(() => context?.holdMax ?? presetByKey('Swing').holdMax);
```

Rewrite `syncToStore` (lines 787-793):

```ts
  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    setContext({
      universe:      context?.universe ?? 'SP500',
      direction:     newDir,
      horizonPreset: newHz,
      holdMin:       newMin,
      holdMax:       newMax,
    });
  }
```

In `handleHzChange` (line 800), when the preset is not `Custom`, snap the hold days to the preset's band before syncing:

```ts
  const handleHzChange = (h: HorizonKey) => {
    const p = presetByKey(h);
    const nextMin = h === 'Custom' ? holdMin : p.holdMin;
    const nextMax = h === 'Custom' ? holdMax : p.holdMax;
    setHz(h);
    setHoldMin(nextMin);
    setHoldMax(nextMax);
    syncToStore(dir, h, nextMin, nextMax);
    const hd = PARAM_DEFAULTS_PER_HORIZON[h];
    useScanStore.getState().setScanOverrides({ /* the existing trend-param block, unchanged */ });
  };
```

The `Range (days)` inputs (lines 915-940) keep their `disabled={!custom}` behaviour, now writing `holdMin` / `holdMax`. Relabel to `Holding period (days)` and add a helper line under it:

```tsx
<Text size={11} tone="dim">
  Contracts will expire in {previewMinDte}–{previewMaxDte} days (hold × 2).
</Text>
```

- [ ] **Step 5: Render the enforced window in the scan log**

Replace lines 841-842:

```ts
  const effectiveMinDte = (scanOverrides.min_dte as number | undefined) ?? (defaults.min_dte as number);
  const effectiveMaxDte = (scanOverrides.max_dte as number | undefined) ?? (defaults.max_dte as number);
```

with:

```ts
  const enforcedDte = scanResult?.dte_window;   // set by the backend on every scan
```

Replace the log DTE readout (lines 1062-1065) with:

```tsx
                <span className={formStyles.logStat}>
                  <Text size={11} tone="dim">DTE</Text>
                  <Text size={11} tone="secondary">
                    {enforcedDte ? `${enforcedDte.min_dte}–${enforcedDte.max_dte}d` : '—'}
                  </Text>
                </span>
```

Also delete the now-unused `horizonKey` derivation at lines 844-846 and pass `hz` to `ScanLogSection` instead — but note `HORIZON_WEIGHTS` (line 25) has only 3 keys, so map through the scoring horizon:

```ts
  const weightsKey = hz === 'Custom' ? scoringHorizonForHold(holdMax) : presetByKey(hz).scoringHorizon;
```

and pass `horizonKey={weightsKey}`.

- [ ] **Step 6: Typecheck and test**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add "frontend/app/(frame)/screener/step-3-direction/page.tsx"
git commit -m "feat(screener): 7 holding-horizon presets, derived read-only DTE, real log window"
```

---

## Task 10: End-to-end verification

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest -q`
Expected: no failures.

- [ ] **Step 2: Frontend suite + typecheck**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: both clean.

- [ ] **Step 3: Drive the real app**

Start the backend, then `cd frontend && npm run dev`. In the Options screener:

1. Step 3 → select **Position**. The helper line must read "Contracts will expire in 30–90 days".
2. Run a scan. The scan log DTE readout must show `30–90d`.
3. Confirm no returned contract expires sooner than 30 days from today — this is the reported 31.07.2026 defect.
4. Select **Custom**, type **60** to **185**. The helper line must read "120–370 days".
5. Run a scan. The log must show `120–370d`, and every contract must expire in that window.
6. Open Execution Parameters → OPTIONS → Contract. `Min DTE` / `Max DTE` must be read-only and show the derived numbers.

- [ ] **Step 4: Confirm the persisted-store migration**

With a v9 store in `localStorage` (key prefix `bamendjou:`), reload the app. The horizon selection must survive, and a previously-typed Custom range must reappear as hold days.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "test: verify horizon-driven DTE end to end"
```

---

## Self-Review Notes

**Spec coverage.** D1 → Task 9 Step 2. D2 → Task 5 (7 presets) + Task 9 Step 4. D3 → Task 1 (`dte_window`). D4 → Task 1 `test_custom_range_is_doubled` + Task 8. D5 → Task 1 `test_intraday_clamps_zero_to_one`. Backend-as-source-of-truth → Tasks 3, 4. Override isolation → Task 4 Step 4. Log shows enforced window → Task 9 Step 5. Unwire DTE params → Task 9 Step 3. Structural string-parsing fix → Tasks 7, 8.

**Type consistency.** `dte_window(hold_min, hold_max, multiplier) -> tuple[int, int]` is used identically in Tasks 1 and 4. `DteWindow` fields `min_dte` / `max_dte` / `multiplier` are identical in Task 3 (Pydantic), Task 6 (TS), and Task 9 (render). `previewDteWindow` mirrors `dte_window` and is asserted against the same seven bands in both suites.

**Known behaviour changes** (accepted in the spec): Intraday 1–7 → 1–4 DTE; Swing 14–45 → 10–30 DTE.
