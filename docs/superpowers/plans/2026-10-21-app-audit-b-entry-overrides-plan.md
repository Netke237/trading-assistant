# Implementation Plan: APP-AUDIT-B-ENTRY-OVERRIDES (Issue #384)

**Target:** Issue #384 (`Entry Quality controls reach requests but do not affect the trade plan`)  
**Defect Reference:** Finding C6 in `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md`  
**Phase ID:** `APP-AUDIT-B-ENTRY-OVERRIDES`  
**Date:** 2026-10-21  

---

## 1. Problem Statement and Defect Specification

In Step 3 Execution Parameters and Search Profiles, users can configure three Entry Quality controls:
1. `entry_spread_tolerance_pct` (Spread tolerance: max bid-ask spread as fraction of mid at entry; default 0.10)
2. `entry_max_slippage_pct` (Max slippage: expected slippage fraction; default 0.03)
3. `entry_min_premium` (Min premium: minimum option premium per contract in dollars; default $0.10)

`frontend/lib/resolveOptionsScanRequest.ts` correctly preserves these controls in `ScanRequest.overrides`. However, on the backend:
1. `backend/app/scoring/trade_plan.py`: `build_trade_plan()` line 155 calls `assess_entry(bid=entry_bid, ask=entry_ask, mid=entry_mid, quote_live=quote_live)` without passing a `config: EntryConfig`. `build_trade_plan` takes no entry configuration parameter, so `assess_entry` always instantiates `EntryConfig()` with hardcoded defaults from `scoring_rules.yaml`.
2. `backend/app/routers/scan.py`: `_process_symbol()` calls `build_trade_plan()` without resolving or forwarding entry overrides from `overrides`, so trade cards produced by the scan use default entry rules.
3. `backend/app/routers/scan.py`: `run_scan()` does not validate entry quality overrides upfront (unlike `_merge_rr_cfg(req.overrides)`), allowing malformed values (non-finite or negative) to either fail late or get ignored.
4. `backend/app/routers/contracts.py`: `RecomputePlanRequest` lacks entry override fields, and `recompute_plan()` passes no entry configuration to `build_trade_plan()`, causing contract overrides in Steps 6 and 7 to silently revert to default entry quality numbers.
5. `backend/app/schemas/__init__.py`: `ScanResult` does not record `entry_overrides` (unlike `rr_overrides`), leaving no persistent record for Step 7 recomputes to read.
6. `frontend/lib/tradeCardOverride.ts`: Step 7's `recomputePlan` does not extract or forward entry overrides from `ScanResult` or `scanOverrides`.

### Concrete Impact Under the Audit Gate
- **Wrong Numbers in UI & Broker Orders:**
  - A user sets `entry_max_slippage_pct: 0` (expecting zero slippage fill limit = mid, e.g. \$1.00). The trade plan calculates `max_fill: 1.03` using the default 0.03 slippage. The user and broker order previews see a 3% higher max fill price than configured.
- **Wrong Final Verdict:**
  - A user sets `entry_min_premium: 5.0` (expecting options under \$5 to be rejected). A contract with premium \$1.00 is assessed as PASS instead of REJECT because `assess_entry` compares against default 0.10. `TradeCardData.finalStatus` becomes PASS and allows order generation on a rejected contract.
  - A user sets `entry_spread_tolerance_pct: 0`. Any non-zero spread should trigger REJECT / CAUTION. Under default 0.10, spreads up to 10% pass without penalty.

---

## 2. Proposed Architecture & Solution Design

### 2.1 Backend Config & Helper Layer (`backend/app/services/config_loader.py`)
1. Define mapping for the Step 3 Entry Quality parameters:
   ```python
   _ENTRY_OVERRIDE_KEY_MAP = {
       "entry_spread_tolerance_pct": "spread_tolerance_pct",
       "entry_max_slippage_pct": "max_slippage_pct",
       "entry_min_premium": "min_premium",
   }
   _ENTRY_OVERRIDE_CAPS = {
       "entry_spread_tolerance_pct": 1.0,
       "entry_max_slippage_pct": 1.0,
       "entry_min_premium": 100.0,
   }
   ```
2. Implement `resolve_entry_config(overrides: dict | None) -> EntryConfig`:
   - Checks `overrides` for each key in `_ENTRY_OVERRIDE_KEY_MAP` (and direct config keys `spread_tolerance_pct`, `max_slippage_pct`, `min_premium` for direct callers).
   - Validates that present values are finite numbers, `>= 0`, and `<= cap`.
   - **Crucial:** Zero (`0` or `0.0`) is a valid override value. Checks `val is not None` so `0.0` is never treated as falsy or dropped.
   - Raises `ValueError` with clear message on invalid, non-finite, negative, or above-cap values.
   - Returns `EntryConfig(spread_tolerance_pct=..., max_slippage_pct=..., min_premium=...)`, where omitted/None fields fall back to `scoring_rules.yaml` via `EntryConfig.__post_init__`.
3. Implement `effective_entry_overrides(overrides: dict | None) -> dict[str, float]`:
   - Returns a dict of the validated `entry_*` keys present in `overrides` with their float values (or empty dict if none).

### 2.2 Shared Trade Plan Builder (`backend/app/scoring/trade_plan.py`)
1. Extend `build_trade_plan()` signature:
   ```python
   def build_trade_plan(
       *,
       direction: str,
       stock_price: float,
       strike: float,
       dte: int,
       premium: float,
       entry_bid: float,
       entry_ask: float,
       entry_mid: float,
       rr_cfg: dict,
       final_stop_price: float,
       target_price: float,
       stop_cost_fraction: float | None,
       target_source: str = "arithmetic",
       heston_params: HestonParams | None = None,
       horizon_preset: str | None = None,
       hold_min: float | None = None,
       hold_max: float | None = None,
       reprice_cfg: dict | None = None,
       quote_live: bool | None = None,
       entry_cfg: EntryConfig | dict | None = None,
   ) -> TradePlan:
   ```
2. If `entry_cfg` is a `dict`, resolve it via `resolve_entry_config(entry_cfg)`. If `entry_cfg` is `None`, pass `None` to `assess_entry()`, which constructs default `EntryConfig()`.
3. Pass resolved `config=entry_cfg` to `assess_entry(bid=entry_bid, ask=entry_ask, mid=entry_mid, config=entry_cfg, quote_live=quote_live)`.

### 2.3 Options Scan Router (`backend/app/routers/scan.py`)
1. Upfront validation in `run_scan()` / `_execute_scan_core`:
   ```python
   try:
       _merge_rr_cfg(req.overrides)
       resolve_target_r_multiple(req.overrides)
       _entry_config = resolve_entry_config(req.overrides)
   except ValueError as e:
       raise HTTPException(status_code=422, detail=str(e))
   ```
2. Worker task dispatch in `_execute_scan_core`:
   Pass `entry_cfg=_entry_config` explicitly into each `_process_symbol` worker invocation:
   ```python
   tasks = [
       _process_symbol(
           symbol, req.direction, req.horizon, client, semaphore, scan_id,
           min_price=req.min_price, max_price=req.max_price,
           min_cap_usd=req.min_cap_usd, max_cap_usd=req.max_cap_usd,
           overrides=req.overrides,
           dte_bounds=_dte_bounds,
           hold_min_days=req.hold_min_days, hold_max_days=req.hold_max_days,
           veto_days=_veto_days,
           horizon_preset=req.horizon_preset,
           gate=gate,
           atr_mult_target=req.confidence_atr_mult_target,
           atr_mult_stop=req.confidence_atr_mult_stop,
           regime_headwind_caution_pct=req.regime_headwind_caution_pct,
           regime_headwind_reject_pct=req.regime_headwind_reject_pct,
           price_map=price_map, bars_map=bars_map, fund_map=fund_map,
           fund_gate=fund_gate,
           spread_width=req.spread_width, short_leg_delta=req.short_leg_delta,
           iv_rank_threshold=req.iv_rank_threshold, iv_abs_threshold=req.iv_abs_threshold,
           direction_conviction_min_trend=_conviction_min_trend,
           rs_benchmark_bars=_rs_benchmark_bars,
           entry_cfg=_entry_config,
       )
       for symbol in symbols
   ]
   ```
3. In `_process_symbol()`:
   Accept `entry_cfg: EntryConfig | None = None`. Add defensive resolution so test fixtures and direct callers passing `overrides` without constructing an `EntryConfig` also receive applied overrides:
   ```python
   _entry_cfg = entry_cfg if entry_cfg is not None else (
       resolve_entry_config(overrides) if overrides else None
   )
   ```
   Pass `entry_cfg=_entry_cfg` to `build_trade_plan(..., entry_cfg=_entry_cfg)`.
4. In `run_scan()` / `_execute_scan_core`:
   Compute `_entry_overrides = effective_entry_overrides(req.overrides)` and record it on `ScanResult`:
   ```python
   result = ScanResult(
       ...
       contract_rules=_contract_rules,
       rr_overrides=_rr_overrides,
       entry_overrides=_entry_overrides,
       request_context=_request_context,
   )
   ```

### 2.4 Contracts Recompute Endpoint (`backend/app/routers/contracts.py`)
1. Extend `RecomputePlanRequest`:
   ```python
   entry_spread_tolerance_pct: float | None = Field(default=None, ge=0, le=1.0, allow_inf_nan=False)
   entry_max_slippage_pct: float | None = Field(default=None, ge=0, le=1.0, allow_inf_nan=False)
   entry_min_premium: float | None = Field(default=None, ge=0, le=100.0, allow_inf_nan=False)
   ```
2. In `recompute_plan()`:
   ```python
   _entry_overrides = {
       k: v for k, v in {
           "entry_spread_tolerance_pct": req.entry_spread_tolerance_pct,
           "entry_max_slippage_pct": req.entry_max_slippage_pct,
           "entry_min_premium": req.entry_min_premium,
       }.items() if v is not None
   }
   _entry_cfg = resolve_entry_config(_entry_overrides) if _entry_overrides else None
   plan = build_trade_plan(
       ...
       entry_cfg=_entry_cfg,
   )
   ```

### 2.5 Schemas (`backend/app/schemas/__init__.py`)
1. Add `entry_overrides: Optional[dict[str, float]] = None` to `ScanResult`.

### 2.6 Frontend Overrides & Recompute Pipeline
1. `frontend/lib/scanStore.ts`:
   Add `entry_overrides?: Record<string, number> | null;` to `interface ScanResult`.
2. `frontend/lib/tradeCardOverride.ts`:
   Define:
   ```typescript
   export const ENTRY_OVERRIDE_KEYS = [
     'entry_spread_tolerance_pct',
     'entry_max_slippage_pct',
     'entry_min_premium',
   ] as const;

   export function entryOverridesFrom(
     scanOverrides: Record<string, number | boolean | string>,
   ): Partial<Record<typeof ENTRY_OVERRIDE_KEYS[number], number>> {
     const out: Partial<Record<typeof ENTRY_OVERRIDE_KEYS[number], number>> = {};
     for (const key of ENTRY_OVERRIDE_KEYS) {
       const v = scanOverrides[key];
       if (typeof v === 'number' && Number.isFinite(v)) out[key] = v;
     }
     return out;
   }

   export function entryOverridesForPlan(
     scanResult: { entry_overrides?: Record<string, number> | null } | null | undefined,
     scanOverrides: Record<string, number | boolean | string>,
   ): Partial<Record<typeof ENTRY_OVERRIDE_KEYS[number], number>> {
     const recorded = scanResult?.entry_overrides;
     return entryOverridesFrom(recorded != null ? recorded : scanOverrides);
   }
   ```
3. `frontend/lib/api.ts`:
   Add optional fields `entry_spread_tolerance_pct?: number; entry_max_slippage_pct?: number; entry_min_premium?: number;` to `recomputePlan` request typing.
4. `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`:
   Forward entry overrides in both `api.recomputePlan` invocations:
   ```typescript
   ...rrOverridesForPlan(useScanStore.getState().scanResult, useScanStore.getState().scanOverrides),
   ...entryOverridesForPlan(useScanStore.getState().scanResult, useScanStore.getState().scanOverrides),
   ```

---

## 3. Test Strategy & Verification Plan

### 3.1 Backend Tests
1. `backend/tests/test_entry_quality.py`:
   - `test_resolve_entry_config_defaults`: None/empty overrides yields defaults matching `scoring_rules.yaml`.
   - `test_resolve_entry_config_custom_values`: Custom `entry_min_premium`, `entry_max_slippage_pct`, `entry_spread_tolerance_pct` are correctly parsed and populated.
   - `test_resolve_entry_config_zero_values_preserved`: Overrides with `0` or `0.0` are explicitly preserved and not dropped or defaulted.
   - `test_resolve_entry_config_validation_errors`: Negative, non-finite, and above-cap values raise `ValueError`.
   - `test_effective_entry_overrides`: Extracts only present, valid `entry_*` keys as floats.
2. `backend/tests/test_trade_plan.py`:
   - `test_build_trade_plan_applies_entry_config`: Verifies `max_fill` and `quality_status` respond to `entry_cfg` (e.g. 0 slippage yields `max_fill == mid`; min premium 5.0 with mid 1.0 yields `quality_status == "REJECT"`).
   - `test_recompute_endpoint_applies_entry_overrides`: POST to `/api/contracts/recompute-plan` with `entry_max_slippage_pct: 0` verifies `entry.maxFill == premium`.
   - `test_recompute_endpoint_rejects_invalid_entry_overrides`: 422 returned on negative or non-finite entry overrides.
3. `backend/tests/test_scan_endpoint.py`:
   - Scan with `entry_min_premium: 5.0` rejects low-premium contracts, and `ScanResult.entry_overrides` contains `{"entry_min_premium": 5.0}`.
   - Malformed entry override (e.g. `entry_spread_tolerance_pct: -0.1`) returns 422 upfront.

### 3.2 Frontend Tests
1. `frontend/lib/__tests__/tradeCardOverride.entryOverrides.test.ts`:
   - Unit tests for `entryOverridesFrom` and `entryOverridesForPlan` ensuring correct extraction, fallback to scan overrides when unrecorded, and preservation of 0.
2. `frontend/app/(frame)/screener/step-7-trade-card/__tests__/entry-overrides-from-scan.test.tsx`:
   - Mock `api.recomputePlan` and verify that `entryOverridesForPlan` forwards the scan's entry overrides into `recomputePlan` calls on contract override.

### 3.3 Presence Probe & State Check
- `scripts/state.py` presence probe:
  - File: `backend/app/services/config_loader.py`
  - Pattern: `def resolve_entry_config`
  - Verify 0 drift with `python scripts/state.py`.

---

## 4. Acceptance Criteria

1. **Finding C6 Fully Resolved:**
   - Setting `entry_min_premium: 5.0`, `entry_max_slippage_pct: 0`, and `entry_spread_tolerance_pct: 0` propagates to `build_trade_plan`.
   - For bid .99/ask 1.01/mid 1.0, `plan.entry.quality_status` evaluates to `REJECT` and `max_fill` evaluates to `1.00`.
2. **Scan Endpoint & Upfront 422:**
   - Options scan executes with entry quality overrides and records `entry_overrides` on `ScanResult`.
   - Malformed entry overrides fail upfront with 422 before dispatching per-symbol worker tasks.
3. **Recompute Plan Parity:**
   - Overriding a contract in Step 7 calls `/api/contracts/recompute-plan` with `entry_overrides`, computing consistent `maxFill` and entry evaluation.
4. **Zero & Default Invariants:**
   - Zero values (`0` / `0.0`) are preserved across all layers.
   - Omitted or cleared fields cleanly default to `scoring_rules.yaml`.
5. **No Regressions:**
   - All backend tests (`pytest backend/tests/test_trade_plan.py backend/tests/test_entry_quality.py`) pass on Python 3.11.
   - `npm run typecheck` and Jest frontend tests green.
   - Independent adversarial audit clean under the AUDIT-RULE-V2 gate.
