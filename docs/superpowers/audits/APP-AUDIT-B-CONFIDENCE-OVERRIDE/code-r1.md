# Adversarial Code Audit: APP-AUDIT-B-CONFIDENCE-OVERRIDE (#383)

- **Diff reviewed:** `30d0e94e722ec51cf775de52adb22dc4ab1c61d8..01a00316` (commit `01a00316`)
- **Reviewer:** Independent Adversarial Auditor (`3bd81c8f-f29e-423d-85e0-1f8b294a38a4`)
- **Plan checked:** `docs/superpowers/plans/2026-10-20-app-audit-b-confidence-override-plan.md`
- **Standard applied:** `bmad-review-adversarial-general` with numeric/persistence gate (AUDIT-RULE-V2)

---

### Scope & Checked Artifacts
1. `frontend/lib/resolveStockScanRequest.ts` (lines 170–190)
2. `frontend/lib/__tests__/resolveStockScanRequest.confidence.test.ts` (full test suite, 10 tests)
3. `docs/superpowers/plans/2026-10-20-app-audit-b-confidence-override-plan.md`
4. `docs/superpowers/PROJECT_STATE.json` (`APP-AUDIT-B-CONFIDENCE-OVERRIDE` phase entry and verify probe)
5. `docs/superpowers/audits/APP-AUDIT-B-CONFIDENCE-OVERRIDE/plan-r1.md`
6. Callers and consumers:
   - `frontend/lib/stockScan.ts` (lines 330–355)
   - `frontend/lib/scanScheduleResolve.ts` (lines 118–137)
   - `frontend/lib/analysisStore.ts` (lines 45–66)
   - `frontend/lib/currentScanReportInputs.ts` (lines 28–30)
7. Backend schemas & gate processing:
   - `backend/app/schemas/stock_scan.py` (lines 100–105)
   - `backend/app/routers/stock_scan.py` (lines 1140–1165, 1675–1695)

---

### Adversarial Verification & Gate Analysis

1. **Numeric Correctness & Override Resolution**
   - **Explicit Numeric Overrides**: When `confidenceGate.enabled === true` and `rawOverrides.confidence_caution_below` or `confidence_reject_below` is a finite number, the override value is sent directly to `StockScanRequestBody`.
   - **Zero Preservation (Finding C5)**: Checked input `0`. `typeof 0 === 'number' && Number.isFinite(0)` evaluates to `true`. Value `0` is preserved on the request. In `stock_scan.py`, `conf_val < 0.0` evaluates to `False` (for win rates ≥ 0%), effectively suppressing the threshold without disabling the gate mechanism.
   - **Non-Numeric / Non-Finite Rejection**: Checked `null`, `undefined`, `NaN`, `Infinity`, `-Infinity`, strings, and booleans. All fail `typeof ... === 'number' && Number.isFinite(...)` and cleanly fall back to `confidenceGate.cautionBelow` / `confidenceGate.rejectBelow`.
   - **Independent Thresholds**: Overriding only one threshold (e.g. caution) leaves the other to fall back to the Settings store value without cross-field interference.

2. **Gate Disabled Invariant**
   - When `confidenceGate.enabled === false`, both `confidence_caution_below` and `confidence_reject_below` evaluate to `undefined`, irrespective of overrides.
   - On JSON serialization, `undefined` properties are omitted. On the backend, `StockScanRequest` defaults both fields to `None`.
   - In `backend/app/routers/stock_scan.py:1678` & `1688`, `req.confidence_... is not None` evaluates to `False`, correctly skipping the gate and preserving pass status. Verified against `stockScanRequestPins.test.ts:116–123`.

3. **Scope Isolation & Consumer Parity**
   - `confidence_caution_below` and `confidence_reject_below` remain excluded from `STOCKS_SCORER_KEYS`, ensuring they are sent as top-level `StockScanRequest` fields and not leaked into the backend `overrides: dict[str, Any]` dictionary.
   - All consumers (`stockScan.ts`, `scanScheduleResolve.ts`, `analysisStore.ts`, `currentScanReportInputs.ts`) invoke `buildStockScanRequestBody` and inherit the identical resolution behavior.

4. **Persistence & Broker Order Impact**
   - `buildStockScanRequestBody` is a pure function with no side effects. No localStorage keys or persisted Zustand stores are mutated.
   - Broker order sizing (derived from `account_size` and `risk_pct` in `StockPositionCardData`) is completely uncoupled from the confidence gate threshold filters and is unaffected.

5. **State & Regression Probe Verification**
   - `python scripts/state.py` passes with exit code 0 (`No drift: every declared status matches the code.`). The `defect_marker` probe accurately confirms the hardcoded pattern is eliminated.
   - `npm run typecheck` passes with 0 errors.
   - `frontend/lib/__tests__/resolveStockScanRequest.confidence.test.ts` (10/10 passing).
   - `frontend/lib/__tests__/stockScanRequestPins.test.ts` (5/5 passing).
   - `frontend/lib/__tests__/a5AnalysisMirrorsScan.test.tsx` (19/19 passing).
   - Backend pytest suite `test_confidence_gate_stocks.py`, `test_a5_analysis_mirrors_scan.py`, `test_scan_schema.py` (28/28 passing).

---

### Gate Findings
No findings meet the numeric/persistence gate. No wrong numbers are displayed to users or sent to brokers, no persisted data is corrupted, and no mechanisms are misstated.

GATE FINDINGS: 0
