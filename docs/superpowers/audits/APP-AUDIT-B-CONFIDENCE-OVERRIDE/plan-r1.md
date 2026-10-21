# Adversarial Plan Audit: APP-AUDIT-B-CONFIDENCE-OVERRIDE (#383)

- **Plan reviewed:** `docs/superpowers/plans/2026-10-20-app-audit-b-confidence-override-plan.md`  
- **Reviewer:** Independent Adversarial Auditor (`68607bdc-c740-47a2-9b4a-03d9b27985e8`)
- **Standard applied:** `bmad-review-adversarial-general` with numeric/persistence gate (AUDIT-RULE-V2)

---

### Scope & Checked Artifacts
Cross-checked the plan against the real codebase and named artifacts:
1. `frontend/lib/resolveStockScanRequest.ts` (lines 17–29, 120–193)
2. `frontend/lib/resolveOptionsScanRequest.ts` (lines 105–140)
3. `frontend/lib/scanScheduleResolve.ts` (lines 70–137)
4. `frontend/lib/stockScan.ts` (lines 330–360)
5. `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/controls/findings.md` (Finding C5)
6. `docs/superpowers/PROJECT_STATE.json` (`APP-AUDIT-B-CONFIDENCE-OVERRIDE` phase, verify probe)
7. Backend request schema and gate handlers (`backend/app/schemas/stock_scan.py`, `backend/app/routers/stock_scan.py`, `backend/app/scoring/signal_confidence.py`)

---

### Verification Details

1. **Defect Identification & Mechanism Parity**
   - In `resolveStockScanRequest.ts`, lines 174–175 currently hardcode `confidenceGate.cautionBelow` and `confidenceGate.rejectBelow` from `ctx.confidenceGate`, completely ignoring `ctx.scanOverrides.confidence_caution_below` and `ctx.scanOverrides.confidence_reject_below`.
   - In contrast, Options scan resolution (`resolveOptionsScanRequest.ts:124–133`) extracts `confidence_caution_below` and `confidence_reject_below` from `scanOverrides` and respects numeric overrides.
   - The plan's proposed fix correctly checks `typeof ... === 'number' && Number.isFinite(...)`, ensuring explicit `0` is preserved (not dropped via falsy coalescing).

2. **Edge Cases & Invariants**
   - **Explicit Zero**: Tested `0` through the proposed ternary expression: `typeof 0 === 'number' && Number.isFinite(0)` evaluates to `true`, resolving directly to `0`. Backend `StockScanRequest` accepts float `0.0`, and `stock_scan.py:1679` / `1689` evaluates `conf_val < 0.0`, effectively disabling threshold triggering.
   - **Gate Disabled**: When `confidenceGate.enabled === false`, `confidence_caution_below` and `confidence_reject_below` evaluate to `undefined`. On the wire, `undefined` becomes `None` on `StockScanRequest`. In `backend/app/routers/stock_scan.py:1678` / `1688`, `req.confidence_reject_below is not None` evaluates to `False`, skipping the gate entirely. This matches `backend/tests/test_confidence_gate_stocks.py:test_confidence_gate_disabled_preserves_pass_status` and `frontend/lib/__tests__/stockScanRequestPins.test.ts:116–123`.
   - **One Override Present, One Absent**: Each threshold ternary is independent; an override on one falls back to the Settings store value for the other.
   - **Scope Isolation**: `STOCKS_SCORER_KEYS` is untouched; the fields remain top-level request properties and are not forwarded into the `overrides` dict.

3. **Consumer Integration**
   - `frontend/lib/stockScan.ts:346–347` passes live `scanOverrides` and `confidenceGate` to `buildStockScanRequestBody`.
   - `frontend/lib/scanScheduleResolve.ts:129–130` passes `profile.scanOverrides` and `profile.scanSettings.confidenceGate` to `buildStockScanRequestBody`.
   - `frontend/lib/analysisStore.ts:57–58` passes `scanOverrides` and `confidenceGate` to `buildStockScanRequestBody`.
   All consumers route through `buildStockScanRequestBody`, ensuring immediate and consistent application of the fix across manual scans, scheduled scans, and single-stock analysis.

4. **Project State & Probe Consistency**
   - `PROJECT_STATE.json` defines a `defect_marker` probe matching `confidence_caution_below: confidenceGate\\.enabled \\? confidenceGate\\.cautionBelow : undefined` in `frontend/lib/resolveStockScanRequest.ts`.
   - The proposed replacement removes this exact pattern, satisfying `scripts/state.py`'s `defect_marker` probe when the phase is marked `built`.
   - `python scripts/state.py` currently passes with zero drift.

---

### Gate Findings
No findings meet the numeric/persistence gate. No arithmetic distortion, broker order sizing error, data corruption, or mechanism misstatement was found.

GATE FINDINGS: 0
