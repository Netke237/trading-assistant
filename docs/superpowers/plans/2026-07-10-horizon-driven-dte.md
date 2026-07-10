# Horizon-Driven DTE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the holding horizon actually determine which option expiries the screener surfaces, via one uniform rule (`DTE = holding × 2`) across all seven presets, computed and enforced on the backend — including the option-chain fetch itself, not just the post-fetch filter.

**Architecture:** A pure function `dte_window()` derives `(min_dte, max_dte)` from a holding period. `scan.py` computes it once per scan and threads it through three places: (1) the option-chain fetch, so the correct expiration is requested in the first place; (2) `validate_contract()`'s hard-reject gate; (3) `validate_contract()`'s soft-rank preferred band. The window is echoed back in `ScanResult.dte_window` so the scan log shows what was actually enforced. The frontend stops regex-parsing a display string and sends structured hold days instead, while keeping a derived `horizon` display string for backward compatibility with ~19 unrelated read sites (including stock-mode).

**Tech Stack:** FastAPI + Pydantic v2 + pytest (backend); Next.js 15 + TypeScript + Zustand + Jest (frontend).

**Spec:** `docs/superpowers/specs/2026-07-10-horizon-driven-dte-design.md` (see the "Addendum — findings from adversarial review" section for the D6–D9 decisions this plan implements)

**Revision note:** This plan was rewritten after a BMAD adversarial audit of the first draft found it would not work. The audit's most important finding: `backend/app/data/market.py`'s option-chain fetch does not fetch a range of expiries — it always picks the single nearest expiration ≥21 days, hardcoded, regardless of any override passed to `validate_contract()`. Filtering candidates after the fact (the first draft's entire approach) cannot fix this; the fetch itself must be corrected. That is now Task 4, and it is the load-bearing task in this plan.

---

## File Structure

**Backend**

| File | Responsibility |
|---|---|
| `backend/app/scoring/dte_window.py` | **New.** Pure derivation of the DTE window from a holding period. No I/O. |
| `backend/tests/test_dte_window.py` | **New.** Unit tests for the pure function. |
| `backend/tests/test_horizon_dte.py` | **New.** Config, schema, validator-override, and expiration-selection tests. |
| `backend/config/contract_rules.yaml` | Adds `dte_holding_multiplier`. |
| `backend/app/scoring/contract_validator.py` | Adds `dte_holding_multiplier()` reader; adds `preferred_dte_min`/`preferred_dte_max` to the override handling (D7). |
| `backend/app/data/market.py` | Adds a shared `_nearest_expiration_in_window()` helper; adds `dte_bounds` to `fetch_option_chain()` and `fetch_option_chain_async()` (D8). |
| `backend/app/schemas/__init__.py` | `DteWindow` model; `ScanRequest` hold days + ordering validator (D9); `ScanResult.dte_window`. |
| `backend/app/routers/scan.py` | Computes the window once; threads it through the chain fetch, `_build_spreads()`, and `validate_contract()`; attaches it to the result. |

**Frontend**

| File | Responsibility |
|---|---|
| `frontend/lib/horizonPresets.ts` | **New.** Single source of truth for the 7 presets + legacy migration + display-only DTE preview. |
| `frontend/lib/__tests__/horizonPresets.test.ts` | **New.** Preset table + migration tests. |
| `frontend/types/domain.ts` | `DteWindow` type (shared, imported by `scanStore.ts`). |
| `frontend/lib/api.ts` | `postScan` accepts hold days; return type includes `dte_window`. |
| `frontend/lib/scanStore.ts` | `ScanContext` gains structured fields alongside the existing `horizon` string (D6 — `horizon` is kept, derived, not removed); `ScanResult` gains `dte_window`; persist v9 → v10 migration. |
| `frontend/components/organisms/RunScanButton/index.tsx` | Sends hold days; deletes the regex string parsing that caused the original bug. |
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | 7 preset buttons; read-only DTE rows; log renders returned window; min-range input clamp (D9). |

`horizonPresets.ts` exists so `page.tsx` and `RunScanButton` share one preset table instead of duplicating it — that duplication is what let the UI and the request diverge in the original bug.

**Why `ScanContext.horizon` is not deleted (D6):** the first plan draft deleted it and relied on `npm run typecheck` to find every consumer. An audit found 19 read sites, several in stock-mode code this feature must not touch, and one (`lib/stockScan.ts`) that would send an invalid `Horizon` value to a backend endpoint with a strict 3-value schema, breaking Stocks-mode scans. Keeping a derived `horizon` string (`` `${scoringHorizon} (${holdMin}–${holdMax}d)` ``) means none of those 19 sites change.

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

Leave `hard_reject.min_dte: 21`, `hard_reject.max_dte: 90`, and `soft_rank.preferred_dte_min/max` untouched here. They remain the fallback used when a request carries no holding period. (`preferred_dte_min/max` gets an override path in Task 3 — the fallback values themselves don't change.)

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

- [ ] **Step 6: Commit**

```bash
git add backend/config/contract_rules.yaml backend/app/scoring/contract_validator.py backend/tests/test_horizon_dte.py
git commit -m "feat(scan): add dte_holding_multiplier config"
```

---

## Task 3: Soft-rank preferred-DTE band follows the same window (D7)

Without this, every Intraday and every long-dated contract scores a flat 25 and picks up a `dte_outside_preferred` soft flag against the still-fixed 21–60 default — three such flags trigger `too_many_soft_failures`, hard-rejecting exactly the contracts the new presets exist to surface.

**Files:**
- Modify: `backend/app/scoring/contract_validator.py:207-219` (override loop)
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


def test_preferred_dte_override_centres_the_soft_score():
    """A 365-DTE contract scores poorly against the fixed 21-60 default preferred
    band, but should score near-perfectly once the preferred band is overridden
    to match a 330-400 DTE Annual window (centre 365)."""
    contract = _make_contract(days=365)
    card_default   = validate_contract(contract, 70)
    card_annual_ov = validate_contract(
        contract, 70,
        overrides={"min_dte": 330, "max_dte": 400, "preferred_dte_min": 330, "preferred_dte_max": 400},
    )
    assert "dte_outside_preferred" in card_default.soft_flags
    assert "dte_outside_preferred" not in card_annual_ov.soft_flags
    assert card_annual_ov.breakdown.dte_score > card_default.breakdown.dte_score


def test_preferred_dte_override_does_not_affect_hard_reject_alone():
    """Setting only preferred_dte_* (no min_dte/max_dte) must not change hard-reject
    behaviour — it only affects the soft score."""
    contract = _make_contract(days=10)  # below default hard min_dte=21
    card = validate_contract(contract, 70, overrides={"preferred_dte_min": 5, "preferred_dte_max": 15})
    assert "dte_too_short" in card.reject_reasons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_horizon_dte.py -k preferred_dte -v`
Expected: FAIL — the second assertion in the first test fails (`dte_outside_preferred` is still present; overrides are silently ignored for `soft_rank` keys today).

- [ ] **Step 3: Extend the override loop**

In `backend/app/scoring/contract_validator.py`, in `validate_contract()`, the current override block reads:

```python
    ov = overrides or {}
    if ov:
        hr = cfg["hard_reject"]
        for key, val in ov.items():
            if key == "max_bid_ask_spread_pct": hr["max_bid_ask_spread_pct"] = float(val)
            elif key == "max_delta":            hr["max_delta"]              = float(val)
            elif key == "min_delta":            hr["min_delta"]              = float(val)
            elif key == "min_volume":           hr["min_volume"]             = int(val)
            elif key == "min_open_interest":    hr["min_open_interest"]      = int(val)
            elif key == "min_dte":              hr["min_dte"]                = int(val)
            elif key == "max_dte":              hr["max_dte"]                = int(val)
            elif key == "max_iv_rank":          hr["max_iv_rank"]            = float(val)
```

Replace it with:

```python
    ov = overrides or {}
    if ov:
        hr = cfg["hard_reject"]
        sr = cfg["soft_rank"]
        for key, val in ov.items():
            if key == "max_bid_ask_spread_pct": hr["max_bid_ask_spread_pct"] = float(val)
            elif key == "max_delta":            hr["max_delta"]              = float(val)
            elif key == "min_delta":            hr["min_delta"]              = float(val)
            elif key == "min_volume":           hr["min_volume"]             = int(val)
            elif key == "min_open_interest":    hr["min_open_interest"]      = int(val)
            elif key == "min_dte":              hr["min_dte"]                = int(val)
            elif key == "max_dte":              hr["max_dte"]                = int(val)
            elif key == "max_iv_rank":          hr["max_iv_rank"]            = float(val)
            elif key == "preferred_dte_min":    sr["preferred_dte_min"]      = int(val)
            elif key == "preferred_dte_max":    sr["preferred_dte_max"]      = int(val)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_horizon_dte.py -k preferred_dte -v`
Expected: PASS — 2 passed

- [ ] **Step 5: Verify no existing contract test regressed**

Run: `cd backend && pytest tests/test_overrides.py tests/test_contracts_scoring.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scoring/contract_validator.py backend/tests/test_horizon_dte.py
git commit -m "feat(contracts): preferred_dte override keys — soft band follows the hard window"
```

---

## Task 4: Option-chain fetch respects the DTE window (D8 — the load-bearing fix)

Today, `fetch_option_chain()` and `fetch_option_chain_async()` in `backend/app/data/market.py` do not fetch a range of expiries. Each calls Tradier's `/options/expirations`, then picks exactly **one** date: the first one `>= 21 days` out, hardcoded. `validate_contract()`'s DTE gate — however it's configured — can only filter the single expiration that was already fetched. Tasks 1–3 are necessary but cannot produce correct results without this task: an Annual scan (330–400 DTE) would still fetch the same near-21-day chain it fetches today, then hard-reject every contract in it.

**Files:**
- Modify: `backend/app/data/market.py:442-474` (`fetch_option_chain`), `:1070-1102` (`fetch_option_chain_async`)
- Test: `backend/tests/test_market_data_fixes.py` or a new focused test file — see Step 1

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_option_chain_expiry_selection.py`:

```python
from datetime import date, timedelta

from app.data.market import _nearest_expiration_in_window


def _d(days_out: int) -> str:
    return (date.today() + timedelta(days=days_out)).isoformat()


def test_picks_the_date_closest_to_window_centre():
    today = date.today()
    dates = [_d(10), _d(35), _d(60), _d(95), _d(200)]
    # window 30-90, centre 60 -> exact match at index 2
    result = _nearest_expiration_in_window(dates, (30, 90), today)
    assert result == dates[2]


def test_excludes_dates_outside_the_window():
    today = date.today()
    dates = [_d(10), _d(200)]
    # neither date is inside 30-90
    assert _nearest_expiration_in_window(dates, (30, 90), today) is None


def test_annual_window_finds_a_far_dated_expiry():
    today = date.today()
    dates = [_d(30), _d(90), _d(180), _d(365), _d(500)]
    # window 330-400, centre 365 -> exact match
    result = _nearest_expiration_in_window(dates, (330, 400), today)
    assert result == dates[3]


def test_empty_dates_returns_none():
    assert _nearest_expiration_in_window([], (30, 90), date.today()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_option_chain_expiry_selection.py -v`
Expected: FAIL — `ImportError: cannot import name '_nearest_expiration_in_window'`

- [ ] **Step 3: Add the shared selection helper**

In `backend/app/data/market.py`, immediately before `def fetch_option_chain(` (currently line 442), add:

```python
def _nearest_expiration_in_window(
    dates: list[str], bounds: tuple[int, int], today: date,
) -> Optional[str]:
    """Return the expiration date closest to the centre of [min_dte, max_dte].

    Returns None if no available expiration falls inside the window.
    """
    lo, hi = bounds
    centre = (lo + hi) / 2
    in_window = [d for d in dates if lo <= (date.fromisoformat(d) - today).days <= hi]
    if not in_window:
        return None
    return min(in_window, key=lambda d: abs((date.fromisoformat(d) - today).days - centre))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_option_chain_expiry_selection.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Wire the helper into `fetch_option_chain` (sync)**

In `backend/app/data/market.py`, change the signature (line 442):

```python
def fetch_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
) -> list[dict]:
```

to:

```python
def fetch_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
    dte_bounds: Optional[tuple[int, int]] = None,
) -> list[dict]:
```

Replace the expiry-selection block (lines 464-473):

```python
        _today = date.today()
        if expiry and expiry in dates:
            target_exp = expiry
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
                None,
            )
            if target_exp is None:
                return []
```

with:

```python
        _today = date.today()
        if expiry and expiry in dates:
            target_exp = expiry
        elif dte_bounds is not None:
            target_exp = _nearest_expiration_in_window(dates, dte_bounds, _today)
            if target_exp is None:
                return []
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
                None,
            )
            if target_exp is None:
                return []
```

- [ ] **Step 6: Wire the helper into `fetch_option_chain_async`**

Apply the identical change to `fetch_option_chain_async` (signature at line 1070, expiry-selection block at lines 1093-1102):

```python
async def fetch_option_chain_async(
    client: httpx.AsyncClient,
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
    dte_bounds: Optional[tuple[int, int]] = None,
) -> list[dict]:
```

```python
        _today = date.today()
        if expiry and expiry in dates:
            target_exp = expiry
        elif dte_bounds is not None:
            target_exp = _nearest_expiration_in_window(dates, dte_bounds, _today)
            if target_exp is None:
                return []
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
                None,
            )
            if target_exp is None:
                return []
```

- [ ] **Step 7: Confirm existing callers are unaffected**

`dte_bounds` defaults to `None` everywhere, so every existing call site (which doesn't pass it) keeps today's exact behaviour — the `>= 21 days` fallback. This is verified in Task 5, which is the only place callers start passing bounds.

Run: `cd backend && pytest tests/test_market_data_fixes.py tests/test_intraday_fetch.py -v`
Expected: all PASS — no existing test passes `dte_bounds`, so none of their assertions change.

- [ ] **Step 8: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_option_chain_expiry_selection.py
git commit -m "fix(data): option-chain fetch selects an expiry within a DTE window, not always nearest-21d"
```

---

## Task 5: Schemas — hold days in, validated; DTE window out

**Files:**
- Modify: `backend/app/schemas/__init__.py:442-496`
- Test: `backend/tests/test_horizon_dte.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_horizon_dte.py`:

```python
import pytest
from pydantic import ValidationError

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


def test_scan_request_rejects_inverted_hold_range():
    """D9: an inverted range must be a clean validation error, not a 500 later
    when dte_window() raises."""
    with pytest.raises(ValidationError):
        ScanRequest.model_validate({
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Position",
            "hold_min_days": 100, "hold_max_days": 15,
        })


def test_scan_request_rejects_negative_hold_days():
    with pytest.raises(ValidationError):
        ScanRequest.model_validate({
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Position",
            "hold_min_days": -5, "hold_max_days": 15,
        })


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

Run: `cd backend && pytest tests/test_horizon_dte.py -k "hold_days or dte_window_defaults or scan_result_carries" -v`
Expected: FAIL — `ImportError: cannot import name 'DteWindow'`

- [ ] **Step 3: Add the `model_validator` import**

In `backend/app/schemas/__init__.py`, change:

```python
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
```

to:

```python
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
```

- [ ] **Step 4: Add `hold_min_days` / `hold_max_days` and the ordering validator to `ScanRequest`**

Inside `class ScanRequest` (starts line 442), add after the `max_cap_usd` line (line 451):

```python
    # Holding horizon (calendar days). The backend derives the contract DTE window
    # from these: dte = hold * dte_holding_multiplier. When absent, contract_rules.yaml
    # hard_reject.min_dte/max_dte apply as a fallback.
    hold_min_days: Optional[int] = None
    hold_max_days: Optional[int] = None
```

At the end of the `ScanRequest` class body (after its last field, before the blank line that precedes `class OptionsPipeline`), add:

```python

    @model_validator(mode="after")
    def _validate_hold_days(self) -> "ScanRequest":
        if self.hold_min_days is not None and self.hold_max_days is not None:
            if self.hold_min_days < 0 or self.hold_max_days < 0:
                raise ValueError("hold_min_days and hold_max_days must be non-negative")
            if self.hold_max_days < self.hold_min_days:
                raise ValueError("hold_max_days must be >= hold_min_days")
        return self
```

- [ ] **Step 5: Add the `DteWindow` model**

In the same file, insert immediately before `class ScanResult(BaseModel):` (line 485):

```python
class DteWindow(BaseModel):
    """The contract expiry window actually enforced for a scan."""
    min_dte:    int
    max_dte:    int
    multiplier: float


```

- [ ] **Step 6: Add `dte_window` to `ScanResult`**

In `class ScanResult`, add after the `direction_banner` line (line 496):

```python
    dte_window: Optional[DteWindow] = None
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && pytest tests/test_horizon_dte.py -v`
Expected: PASS — all tests in the file, including the ones from Tasks 2 and 3.

- [ ] **Step 8: Verify the schemas import cleanly**

Run: `cd backend && python -c "from app.schemas import ScanRequest, ScanResult, DteWindow; print('ok')"`
Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/__init__.py backend/tests/test_horizon_dte.py
git commit -m "feat(scan): ScanRequest hold days + ordering validation, ScanResult.dte_window"
```

---

## Task 6: Wire the window through `scan.py`

Threads the computed `(min_dte, max_dte)` into three places: the chain fetch (Task 4), `_build_spreads()` (so bearish spread construction lands on the same expiration as the primary contract), and `validate_contract()` (hard + soft, Task 3). The DTE keys must reach `validate_contract()` but must **not** be merged into the `overrides` dict shared with `score_stock()` — kept as a separate dict for clarity (see spec addendum: this is hygiene, not a correctness requirement — `score_stock()`'s override handling is an allow-list that already ignores unknown keys).

**Files:**
- Modify: `backend/app/routers/scan.py` — imports; `_build_spreads` signature (`:182-220`) and its two `fetch_option_chain_async` calls (`:206-208`); `_process_symbol` signature (`:262-286`) and its chain-fetch call (`:417`) and `_build_spreads` call (`:637-641`) and `validate_contract` call (`:480`); `run_scan` (`:862` insertion point, `:872-890` task dispatch, `:997-1009` result construction)
- Test: `backend/tests/test_horizon_dte.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_horizon_dte.py` (reuses `_make_contract` and `_expiry_str` from Task 3):

```python
from app.scoring.dte_window import dte_window


def test_position_hold_rejects_the_reported_22_dte_contract():
    """The 31.07.2026 case: a 22-DTE contract must not survive a 15-45 day hold."""
    min_dte, max_dte = dte_window(15, 45, 2.0)
    card = validate_contract(_make_contract(days=22), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte,
                                        "preferred_dte_min": min_dte, "preferred_dte_max": max_dte})
    assert "dte_too_short" in card.reject_reasons


def test_position_hold_accepts_a_60_dte_contract():
    min_dte, max_dte = dte_window(15, 45, 2.0)
    card = validate_contract(_make_contract(days=60), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte,
                                        "preferred_dte_min": min_dte, "preferred_dte_max": max_dte})
    assert "dte_too_short" not in card.reject_reasons
    assert "dte_too_long" not in card.reject_reasons


def test_annual_hold_accepts_a_365_dte_contract_and_scores_it_cleanly():
    min_dte, max_dte = dte_window(165, 200, 2.0)
    card = validate_contract(_make_contract(days=365), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte,
                                        "preferred_dte_min": min_dte, "preferred_dte_max": max_dte})
    assert "dte_too_short" not in card.reject_reasons
    assert "dte_too_long" not in card.reject_reasons
    assert "dte_outside_preferred" not in card.soft_flags
```

This test exercises exactly the combined override dict `scan.py` will build in Step 3 below — it is a unit-level stand-in for the full `run_scan` integration, which requires live Tradier data and is exercised manually in Task 12.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_horizon_dte.py -k "22_dte or 60_dte or 365_dte" -v`
Expected: The 22-DTE test FAILS (`dte_too_short` absent — the fixed default `min_dte=21` lets 22 through). This is the reported bug, reproduced at the unit level.

- [ ] **Step 3: Add `dte_bounds` to `_process_symbol` and merge it into a separate contract-overrides dict**

In `backend/app/routers/scan.py`, in the `_process_symbol` signature, add after `overrides: dict | None = None,` (line 274):

```python
    dte_bounds: tuple[int, int] | None = None,
```

Replace line 480:

```python
    scored = [(validate_contract(c, card.score, overrides=overrides), c) for c in augmented]
```

with:

```python
    # DTE bounds are derived from the holding horizon and apply to contracts only,
    # via a separate dict — kept apart from `overrides` for clarity, not because
    # score_stock() would misinterpret these keys (its override handling is an
    # allow-list that already ignores unrecognised keys).
    contract_overrides = dict(overrides or {})
    if dte_bounds is not None:
        lo, hi = dte_bounds
        contract_overrides["min_dte"] = lo
        contract_overrides["max_dte"] = hi
        contract_overrides["preferred_dte_min"] = lo
        contract_overrides["preferred_dte_max"] = hi
    scored = [(validate_contract(c, card.score, overrides=contract_overrides or None), c)
              for c in augmented]
```

- [ ] **Step 4: Pass `dte_bounds` into the primary chain fetch**

Change line 417:

```python
        chain = await fetch_option_chain_async(client, symbol, option_type=option_type)
```

to:

```python
        chain = await fetch_option_chain_async(client, symbol, option_type=option_type, dte_bounds=dte_bounds)
```

- [ ] **Step 5: Thread `dte_bounds` through `_build_spreads`**

In `backend/app/routers/scan.py`, change the `_build_spreads` signature (lines 182-195) to add a `dte_bounds` keyword parameter:

```python
async def _build_spreads(
    symbol: str,
    direction: str,
    contract: dict,
    iv_rank: float | None,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    dte_bounds: tuple[int, int] | None = None,
    spread_width: float = 5.0,
    short_leg_delta: float = 0.30,
    iv_rank_threshold: float = 50.0,
    min_credit: float = 0.50,
    max_debit_pct: float = 40.0,
):
```

Change its internal chain fetch (lines 206-208):

```python
            _puts_chain, _calls_chain = await asyncio.gather(
                fetch_option_chain_async(client, symbol, option_type="P"),
                fetch_option_chain_async(client, symbol, option_type="C"),
            )
```

to:

```python
            _puts_chain, _calls_chain = await asyncio.gather(
                fetch_option_chain_async(client, symbol, option_type="P", dte_bounds=dte_bounds),
                fetch_option_chain_async(client, symbol, option_type="C", dte_bounds=dte_bounds),
            )
```

Update its call site (lines 637-641) to pass the bound through:

```python
    _primary_sp, _alt_sp = await _build_spreads(
        symbol, direction, contract, iv_rank, client, sem,
        dte_bounds=dte_bounds,
        spread_width=spread_width,
        short_leg_delta=short_leg_delta,
        iv_rank_threshold=iv_rank_threshold,
```

(leave the remaining existing kwargs on the following lines unchanged).

- [ ] **Step 6: Compute the window once per scan**

Add to the imports near the other `app.scoring`/`app.schemas` imports in `scan.py`:

```python
from app.scoring.contract_validator import dte_holding_multiplier
from app.scoring.dte_window import dte_window
```

and add `DteWindow` to the existing `from app.schemas import (...)` import list.

In `run_scan`, immediately before `semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)` (line 862), insert:

```python
    # ── DTE window from the holding horizon ───────────────────────────────────
    # Absent hold days (e.g. an older client), the fetch/validator defaults apply.
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

`ScanRequest`'s `_validate_hold_days` model validator (Task 5) guarantees that if both fields are present here, `hold_min_days <= hold_max_days` and both are non-negative — `dte_window()` cannot raise at this call site.

- [ ] **Step 7: Pass the bounds into each task**

In the `_process_symbol(...)` call inside `tasks = [` (line 873), add after `overrides=dict(req.overrides) if req.overrides else None,` (line 879):

```python
                dte_bounds=_dte_bounds,
```

- [ ] **Step 8: Attach the window to the response**

In the `result = ScanResult(` construction (line 997), add after `direction_banner=_direction_banner,` (line 1008):

```python
            dte_window=_dte_win,
```

Leave the `_compute_deltas(ScanResult(...))` call on line 993 unchanged — it is a throwaway comparison object.

- [ ] **Step 9: Run the tests**

Run: `cd backend && pytest tests/test_horizon_dte.py tests/test_dte_window.py tests/test_option_chain_expiry_selection.py -v`
Expected: all PASS, including the 22-DTE rejection and the 365-DTE clean-score test.

- [ ] **Step 10: Verify nothing else regressed**

Run: `cd backend && pytest -q`
Expected: no new failures versus the pre-change baseline.

- [ ] **Step 11: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_horizon_dte.py
git commit -m "feat(scan): enforce holding-horizon DTE window end to end — fetch, spreads, validator"
```

---

## Task 7: Frontend preset module

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
 * derivation (and the expiry selection) and returns the enforced window in
 * ScanResult.dte_window — the preview below is for display only, before a scan
 * has run.
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

/** Kept in sync with backend/config/contract_rules.yaml: dte_holding_multiplier.
 *  Display-only — the backend is authoritative and echoes the enforced window
 *  back in ScanResult.dte_window. If the two ever drift, only the preview text
 *  shown before a scan runs is affected, not enforcement. */
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

/**
 * The derived display string kept on ScanContext.horizon for backward
 * compatibility with the ~19 read sites (including stock-mode) that expect a
 * string starting with one of 'Intraday' | 'Swing' | 'Position'.
 */
export function horizonDisplayString(scoringHorizon: ScoringHorizon, holdMin: number, holdMax: number): string {
  return `${scoringHorizon} (${holdMin}–${holdMax}d)`;
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

## Task 8: `DteWindow` type + `postScan` hold days

**Files:**
- Modify: `frontend/types/domain.ts`
- Modify: `frontend/lib/api.ts:328-348`

- [ ] **Step 1: Add the `DteWindow` type**

In `frontend/types/domain.ts`, add:

```ts
export interface DteWindow {
  min_dte:    number;
  max_dte:    number;
  multiplier: number;
}
```

Note: `ScanResult` itself is declared in `frontend/lib/scanStore.ts:34-41`, not in `types/domain.ts` — do not add `dte_window` here. `DteWindow` lives in `domain.ts` because it's a shared shape; Task 9 imports it into `scanStore.ts`.

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

Find the function's return type (the generic argument to whatever `post<...>()` call it wraps) and add `dte_window?: DteWindow` to it, importing `DteWindow` from `@/types/domain`. Without this, `result.dte_window` in `RunScanButton`'s `.then((result) => …)` callback would not typecheck even though the runtime value from the (already-updated) store `ScanResult` type carries it.

- [ ] **Step 3: Locate every existing `postScan` call and mock**

Run: `cd frontend && grep -rln "postScan" --include=*.ts --include=*.tsx .`
Expected output includes at minimum: `lib/api.ts`, `components/organisms/RunScanButton/index.tsx`, and the test files under `components/organisms/RunScanButton/__tests__/`. There is no `frontend/__mocks__/api.ts` — `postScan` is mocked inline via `jest.mock('@/lib/api', …)` inside the test files themselves; update the mock signatures there (Task 10 updates the call site; this step is just reconnaissance so Task 10 doesn't get surprised).

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: errors ONLY at the `api.postScan(...)` call site in `RunScanButton/index.tsx` (fixed in Task 10).

- [ ] **Step 5: Commit**

```bash
git add frontend/types/domain.ts frontend/lib/api.ts
git commit -m "feat(api): postScan sends hold days; DteWindow type"
```

---

## Task 9: Structured `ScanContext` + persist migration (D6 — `horizon` string kept, derived)

**Files:**
- Modify: `frontend/lib/scanStore.ts:12-16` (interface), `:34-41` (`ScanResult`), `:194-206` (migrate)

- [ ] **Step 1: Extend `ScanContext` — add fields, keep `horizon`**

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
  /**
   * Derived display string, e.g. "Position (90–105d)" — kept for the ~15
   * existing consumers (TopBar, dashboard, ScanLog, stock-mode scan/analyze
   * requests) that parse or display this directly. Always starts with one of
   * 'Intraday' | 'Swing' | 'Position' (the scoring horizon), even for the
   * Position-scored long-dated presets — see horizonDisplayString().
   */
  horizon:       string;
  horizonPreset: HorizonKey;  // 'Swing' | 'Quarterly' | 'Custom' | ...
  holdMin:       number;      // calendar days
  holdMax:       number;      // calendar days
}
```

- [ ] **Step 2: Add `dte_window` to the store's `ScanResult`**

At `frontend/lib/scanStore.ts:34-41`, add the import and field:

```ts
import type { DteWindow } from '@/types/domain';

export interface ScanResult {
  // ...existing fields unchanged...
  dte_window?: DteWindow;
}
```

(Insert the field into the existing interface body rather than redeclaring it — read the current lines 34-41 first to place it correctly among the existing fields.)

- [ ] **Step 3: Bump the persist version and add the migration branch**

Change `version: 9,` (line 194) to `version: 10,`.

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
                  horizon:   ctx.horizon   ?? 'Swing (5–15d)',
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

- [ ] **Step 4: Write a test that exercises the real `migrate` callback**

Create `frontend/lib/__tests__/scanStoreHorizonMigration.test.ts`. This must call the store's actual persisted `migrate` function, not just `migrateLegacyHorizon` in isolation (that's already covered by Task 7's tests) — the risk is in how `migrate` assembles the full state object, not in the parsing helper alone.

```ts
import { useScanStore } from '../scanStore';

// Reach into the store's persist config to get the real migrate() callback.
// zustand's `persist` middleware exposes it via the store's persist API.
const migrate = (useScanStore as unknown as {
  persist: { getOptions: () => { migrate: (state: unknown, version: number) => unknown } };
}).persist.getOptions().migrate;

describe('scanStore persisted migrate(): v9 -> v10', () => {
  it('preserves the typed custom range that v9 discarded', () => {
    const v9State = {
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Custom (60–185d)' },
    };
    const migrated = migrate(v9State, 9) as { context: Record<string, unknown> };
    expect(migrated.context).toEqual({
      universe: 'SP500',
      direction: 'Bullish',
      horizon: 'Custom (60–185d)',
      horizonPreset: 'Custom',
      holdMin: 60,
      holdMax: 185,
    });
  });

  it('handles a null context without throwing', () => {
    const v9State = { context: null };
    const migrated = migrate(v9State, 9) as { context: unknown };
    expect(migrated.context).toBeNull();
  });

  it('handles a missing context key without throwing', () => {
    const migrated = migrate({}, 9) as { context: unknown };
    expect(migrated.context).toBeNull();
  });
});
```

If `useScanStore.persist.getOptions()` is not the correct accessor for this project's zustand version, run `cd frontend && grep -n "\"zustand\"" package.json` to check the version and adjust to that version's documented API for reading the `migrate` option off a `persist`-wrapped store — do not fall back to re-testing only `migrateLegacyHorizon`, since that duplicates Task 7's coverage and leaves the actual `migrate` assembly logic (the thing that broke the original Custom range) untested.

- [ ] **Step 5: Run it**

Run: `cd frontend && npm run test -- --testPathPattern=scanStoreHorizonMigration`
Expected: PASS — 3 passed

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean. Because `horizon` was kept (not removed), none of the ~19 external read sites should produce new errors. If any do appear, they are a signal that some other part of the store shape changed unexpectedly — investigate before proceeding, do not silently patch call sites.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/scanStore.ts frontend/lib/__tests__/scanStoreHorizonMigration.test.ts
git commit -m "feat(scanStore): structured horizon fields alongside derived horizon string, persist v10"
```

---

## Task 10: `RunScanButton` sends hold days

This deletes the regex string-parsing that is the root cause of the original bug.

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/index.tsx:101-110` and `:167-173`
- Test: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`, following the existing inline `jest.mock('@/lib/api', …)` pattern already used in that file for `api.postScan`:

```ts
it('sends hold days and the scoring horizon, never min_dte/max_dte overrides', async () => {
  // arrange: scanStore context = { universe: 'SP500', direction: 'Bullish',
  //   horizon: 'Position (120–370d)', horizonPreset: 'Custom', holdMin: 60, holdMax: 185 }
  // act: click Run Scan
  const [, , horizon, hold, , overrides] = (api.postScan as jest.Mock).mock.calls[0];
  expect(horizon).toBe('Position');                    // scoringHorizonForHold(185) === 'Position'
  expect(hold).toEqual({ hold_min_days: 60, hold_max_days: 185 });
  expect(overrides).not.toHaveProperty('min_dte');
  expect(overrides).not.toHaveProperty('max_dte');
});
```

- [ ] **Step 2: Run it**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: FAIL — `postScan` is still called with the old argument order and the old string-derived horizon.

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
    // and Custom map onto one of those for scoring; the DTE window itself comes
    // from the hold days, computed backend-side.
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
Expected: PASS. If `regimeGate.test.tsx` (which sets `context: { direction, horizon: 'Swing (5–15d)' }` per the existing fixture) fails to typecheck because it's missing the new required `ScanContext` fields, update that fixture to the full structured shape:
`{ universe: 'SP500', direction, horizon: 'Swing (5–15d)', horizonPreset: 'Swing', holdMin: 5, holdMax: 15 }`.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/organisms/RunScanButton/index.tsx frontend/components/organisms/RunScanButton/__tests__/
git commit -m "fix(screener): send hold days, drop display-string regex parsing"
```

---

## Task 11: Step 3 page — 7 buttons, read-only DTE, real log, clamped range input

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`

- [ ] **Step 1: Delete the local preset table and horizon helpers**

Remove the local `HorizonKey` type (line 140), `HORIZON_PRESETS` (lines 142-147), `horizonLabel()` (727-732), `parseHorizonKey()` (734-741), and `parseCustomDays()` (743-747).

Import from the shared module instead:

```ts
import {
  HORIZON_PRESETS, presetByKey, previewDteWindow, scoringHorizonForHold, horizonDisplayString,
  type HorizonKey,
} from '@/lib/horizonPresets';
```

- [ ] **Step 2: Hoist the Position param block, add the three new preset param blocks (D1)**

`PARAM_DEFAULTS_PER_HORIZON` (line 327) is keyed by `HorizonKey` and now needs 7 keys. Per design decision D1, the new long-dated presets reuse Position's stock-scoring parameters exactly.

First, hoist the existing Position object (currently the `Position: { … }` literal inside the map, lines ~374-396) to a named const above the map:

```ts
const PARAM_DEFAULTS_POSITION: ParamDefaults = {
  // the existing Position block, moved verbatim, unchanged
};
```

Then reference it in the map and spread it for the three new keys:

```ts
const PARAM_DEFAULTS_PER_HORIZON: Record<HorizonKey, ParamDefaults> = {
  Intraday:   { /* existing, unchanged */ },
  Swing:      { /* existing, unchanged */ },
  Position:   PARAM_DEFAULTS_POSITION,
  Quarterly:  { ...PARAM_DEFAULTS_POSITION },
  SemiAnnual: { ...PARAM_DEFAULTS_POSITION },
  Annual:     { ...PARAM_DEFAULTS_POSITION },
  Custom:     { /* existing, unchanged */ },
};
```

- [ ] **Step 3: Make `min_dte` / `max_dte` read-only, driven by the derived preview**

In `PARAM_DEFS` (lines 273-276), change the two Contract rows from `type: 'number'` to `type: 'display'`:

```ts
  { key: 'min_dte', label: 'Min DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
  { key: 'max_dte', label: 'Max DTE', type: 'display', section: 'options', subGroup: 'Contract', unit: 'days',
    hint: 'Derived from the holding horizon (hold × 2). Change the horizon to change this.' },
```

Remove `min_dte` and `max_dte` from all seven blocks of `PARAM_DEFAULTS_PER_HORIZON` (including `PARAM_DEFAULTS_POSITION`, which the three new presets spread — since the key is deleted there, it is absent from all four Position-derived blocks automatically).

In the component body, compute the preview and build a display-only defaults object used only for these two rows:

```ts
  const [previewMinDte, previewMaxDte] = previewDteWindow(holdMin, holdMax);
  const displayDefaults: ParamDefaults = { ...defaults, min_dte: previewMinDte, max_dte: previewMaxDte };
```

Use `displayDefaults[def.key] ?? null` instead of `defaults[def.key] ?? null` at the two `ParamRow` render sites (currently lines 987 and 1021) — both the STOCKS and OPTIONS section loops pass `defaultVal={defaults[def.key] ?? null}`; change both to `displayDefaults[def.key] ?? null`.

- [ ] **Step 4: Rename state to hold-based names, bind to the store**

Replace the local `hz` / `minDays` / `maxDays` state initialisers (lines 762-764):

```ts
  const [hz,      setHz]      = useState<HorizonKey>(() => context?.horizonPreset ?? 'Swing');
  const [holdMin, setHoldMin] = useState<number>(() => context?.holdMin ?? presetByKey('Swing').holdMin);
  const [holdMax, setHoldMax] = useState<number>(() => context?.holdMax ?? presetByKey('Swing').holdMax);
```

Rewrite `syncToStore` (lines 787-793) to compute and store the derived display string (D6):

```ts
  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    const scoringHz = newHz === 'Custom' ? scoringHorizonForHold(newMax) : presetByKey(newHz).scoringHorizon;
    setContext({
      universe:      context?.universe ?? 'SP500',
      direction:     newDir,
      horizon:       horizonDisplayString(scoringHz, newMin, newMax),
      horizonPreset: newHz,
      holdMin:       newMin,
      holdMax:       newMax,
    });
  }
```

In `handleHzChange` (line 800), snap the hold days to the preset's fixed band when the preset is not `Custom` (Custom keeps whatever the user last typed):

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
    useScanStore.getState().setScanOverrides({
      // the existing trend-param spread block (ma_type, fast_ema, slow_ema, trend_method,
      // additive_*, rs_*) — unchanged from the current implementation, just reading `hd`
      // from the now-7-key map. Copy it verbatim from the current handleHzChange body.
    });
  };
```

- [ ] **Step 5: Clamp the Custom range inputs both directions (D9)**

Replace `handleMinChange` / `handleMaxChange` (lines 824-832):

```ts
  const handleMinChange = (v: number) => {
    const clamped = Math.min(v, holdMax);
    setHoldMin(clamped);
    syncToStore(dir, hz, clamped, holdMax);
  };
  const handleMaxChange = (v: number) => {
    const clamped = Math.max(holdMin, v);
    setHoldMax(clamped);
    syncToStore(dir, hz, holdMin, clamped);
  };
```

Update the two `<input>` elements (lines 918-939) to use `holdMin`/`holdMax` instead of `minDays`/`maxDays`, and relabel the row from "Range (days)" to "Holding period (days)". Add a helper line beneath it:

```tsx
<Text size={11} tone="dim">
  Contracts will expire in {previewMinDte}–{previewMaxDte} days (hold × 2).
</Text>
```

- [ ] **Step 6: Render the enforced window in the scan log**

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

Delete the now-unused `horizonKey` derivation at lines 844-846 (it read `context?.horizon`, which is fine to keep reading, but `hz`/`scoringHorizonForHold` is now more direct) and pass the scoring horizon to `ScanLogSection` instead — `HORIZON_WEIGHTS` (line 25) has only 3 keys, so:

```ts
  const weightsKey = hz === 'Custom' ? scoringHorizonForHold(holdMax) : presetByKey(hz).scoringHorizon;
```

and pass `horizonKey={weightsKey}` where `ScanLogSection` is rendered.

- [ ] **Step 7: Render all 7 buttons**

The existing `HORIZON_PRESETS.map((h) => …)` button-rendering block (lines 900-912) requires no structural change — it already maps over `HORIZON_PRESETS`, which now has 7 entries via Task 7's shared module. Verify visually in Task 12 that all 7 render and wrap sensibly at 1200px min-width.

- [ ] **Step 8: Typecheck and test**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: both clean.

- [ ] **Step 9: Commit**

```bash
git add "frontend/app/(frame)/screener/step-3-direction/page.tsx"
git commit -m "feat(screener): 7 holding-horizon presets, derived read-only DTE, real log window, clamped range"
```

---

## Task 12: End-to-end verification

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest -q`
Expected: no failures.

- [ ] **Step 2: Frontend suite + typecheck**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: both clean.

- [ ] **Step 3: Drive the real app — Position (regression check)**

Start the backend, then `cd frontend && npm run dev`. In the Options screener, Step 3 → select **Position** (the default/existing preset). Run a scan.
Expected: scan log DTE readout shows `30–90d`; every returned contract expires 30–90 days out. This must match today's real-world behaviour — no regression.

- [ ] **Step 4: Drive the real app — the reported defect (Custom)**

Select **Custom**, type **60** to **185**. The helper line under the range input must read "Contracts will expire in 120–370 days". Run a scan.
Expected: log shows `120–370d`; every contract expires in that window. This is the original bug report — confirm it no longer reproduces.

- [ ] **Step 5: Drive the real app — a new long-dated preset (the D8 fix)**

Select **Annual**. Run a scan on a liquid, widely-optioned symbol (e.g. SPY or AAPL) known to list LEAPS.
Expected: log shows `330–400d`; at least some candidates are returned with contracts in that window. If zero candidates return for every symbol, check backend logs for `SCAN … dte_window: 330-400d` to confirm the window was computed, then check whether `_nearest_expiration_in_window` found no date in range — this would mean the tested symbol's chain genuinely has no LEAPS that far out; retry with a different symbol before treating it as a defect.

- [ ] **Step 6: Confirm the read-only DTE fields**

Open Execution Parameters → OPTIONS → Contract. `Min DTE` / `Max DTE` must be read-only (no input box) and show the numbers matching the scan log.

- [ ] **Step 7: Confirm input validation (D9)**

In Custom, attempt to type a minimum above the current maximum. The minimum input must clamp rather than produce an invalid state. Separately, confirm no scan request can leave the browser with an inverted range — the clamp prevents this at the source, so this should be unreachable via the UI.

- [ ] **Step 8: Confirm the persisted-store migration**

With a v9 store in `localStorage` (key prefix `bamendjou:`) containing a `Custom (60–185d)` context, reload the app. Step 3 must show **Custom** selected with **60** and **185** in the range inputs — not silently reset to Swing's 5–15.

- [ ] **Step 9: Confirm stock-mode is unaffected**

Switch to the Stocks tab (still on Step 3). Select **Position**, then **Custom** with a typed range. Proceed to Step 4 (stocks) and run a stock scan.
Expected: no 422 or console error from `stockScan.ts` — this validates D6's fix (the derived `horizon` string always starts with a valid `Intraday`/`Swing`/`Position` word).

- [ ] **Step 10: Commit any fixes**

```bash
git add -A
git commit -m "test: verify horizon-driven DTE end to end, including stock-mode regression"
```

---

## Self-Review Notes

**Spec coverage.** D1 → Task 11 Step 2. D2 → Task 7 (7 presets) + Task 11 Step 7. D3 → Task 1 (`dte_window`). D4 → Task 1 `test_custom_range_is_doubled` + Task 10. D5 → Task 1 `test_intraday_clamps_zero_to_one`. D6 (kept `horizon` string) → Task 9 Step 1, Task 11 Step 4, Task 12 Step 9. D7 (soft-rank band) → Task 3. D8 (chain-fetch selection — the load-bearing fix) → Task 4, wired in Task 6. D9 (input validation) → Task 5 Step 4 (backend), Task 11 Step 5 (frontend), Task 12 Step 7. Backend-as-source-of-truth → Tasks 5, 6. Override isolation reframed as hygiene, not correctness → Task 6 intro. Log shows enforced window → Task 11 Step 6. Unwire DTE params → Task 11 Step 3.

**Type consistency.** `dte_window(hold_min, hold_max, multiplier) -> tuple[int, int]` is used identically in Tasks 1 and 6. `DteWindow` fields `min_dte` / `max_dte` / `multiplier` are identical in Task 5 (Pydantic), Task 8 (TS, in `domain.ts`), and Task 9 (imported into `scanStore.ts`'s `ScanResult`) — corrected from the first draft, which pointed at `domain.ts` for a type that actually lives in `scanStore.ts`. `previewDteWindow` mirrors `dte_window` and is asserted against the same seven bands in both suites. `_nearest_expiration_in_window(dates, bounds, today) -> Optional[str]` is defined once in `market.py` and used identically by both the sync and async chain-fetch functions.

**Corrections applied after the first adversarial audit pass:** kept `ScanContext.horizon` instead of deleting it (D6); added the soft-rank preferred-DTE override (D7); added the option-chain expiry-selection fix, which the first draft omitted entirely and without which the feature does not work (D8); added hold-day input validation on both ends (D9); corrected `DteWindow`/`ScanResult` file targeting; corrected the `__mocks__` reference to the actual inline `jest.mock` pattern; replaced the hollow migration test with one that exercises the real `migrate()` callback; re-captioned the override-isolation rationale as hygiene rather than a correctness fix.

**Known behaviour changes** (accepted in the spec): Intraday 1–7 → 1–4 DTE; Swing 14–45 → 10–30 DTE. Position is unchanged (30–90 DTE) and Task 12 Step 3 verifies this explicitly as a regression gate.
