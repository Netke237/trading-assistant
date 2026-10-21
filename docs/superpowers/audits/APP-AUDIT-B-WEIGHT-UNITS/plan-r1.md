# Plan Audit Round 1: APP-AUDIT-B-WEIGHT-UNITS

**Target:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md`  
**Auditor:** Independent subagent `d9be7b85-2225-4d50-a667-dc965320fc84`  
**Date:** 2026-10-21  
**Gate:** Numeric / Persistence Gate (0 gate findings required for clean exit)  

---

## Findings

### F-1: Redundant normalization in `scanScheduleResolve.ts` and non-idempotent mapping of `1` to `0.01`
- **Location:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md:53-72`
- **Scenario:** `resolveProfileToScanRequest` delegates to `buildOptionsScanRequestBody` / `buildStockScanRequestBody`. Double application with `val === 1 -> 0.01` causes 100% weight to be scaled to 1 and then to 0.01 (1%), a 100x weight collapse and persisted data corruption in `scan_schedule.yaml`.
- **Status:** Fixed. Normalization removed from `scanScheduleResolve.ts` (handled solely at request builder choke points). Normalization made strictly idempotent with `f > 1.0 -> f / 100.0`.

### F-2: Asymmetric interpretation of `1`
- **Location:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md:33-40` vs `64-70`
- **Scenario:** Backend treated `1` as 1.0 (100%), while frontend mapped `1` to 0.01 (1%).
- **Status:** Fixed. Both frontend and backend use idempotent `> 1.0` scaling. Legacy schedule migration in `scan_schedule_store.py` explicitly normalizes entries where `val > 1.0`.

### F-3: `ScanScheduleStore._migrate_entry` missed schema version bump and options mode
- **Location:** `docs/superpowers/plans/2026-10-21-app-audit-b-weight-units-plan.md:73-76`
- **Scenario:** `_SCHEMA_VERSION = 2` was not bumped to 3, so `migrate = version_int < _SCHEMA_VERSION` evaluated to `False` on version 2 files. Furthermore, `_migrate_entry` only inspected `mode == "stocks"`, leaving options schedules unmigrated.
- **Status:** Fixed. `_SCHEMA_VERSION` bumped to 3. `_migrate_entry` updated to migrate `resolved_request["overrides"]` for both `stocks` and `options` modes.

---

**GATE FINDINGS:** 3 (all 3 resolved in revised plan for Round 2).
