# Code Audit Round 1: APP-AUDIT-B-PROFILE-VALIDATION (#381)

**Date**: 2026-10-21  
**Reviewer**: Fresh independent subagent `4ac802c0-7694-4031-ba52-61f76fddde76` (role: `Independent Code Auditor`)  
**Target Diff**: `origin/main` (`e5a9d269`) .. `HEAD` (`1be70ab8`)  
**Target Plan**: `docs/superpowers/plans/2026-10-21-app-audit-b-profile-validation-plan.md`  
**Target Issue**: #381 (Malformed current-version profile crashes Search Profile controls / future-version write barrier)  
**Baseline Evidence**: `controls/findings.md` (C3), `controls/source-probe.cjs:20-23`, `followup/storage/findings.md` (S3), `followup/storage/browser.cjs:104-109`  

---

## Adversarial Findings

### Finding F-1
- **File & Line**: `frontend/lib/searchProfileValidation.ts:37-104` (interaction with `searchProfileSnapshot.ts:112` and `settingsStore.ts:432`)
- **Problem**: `isValidSearchProfile` guarded fields with `obj.field !== undefined` checks, allowing profiles with missing required fields (e.g. missing `confidenceGate` or missing `direction`) to pass validation. When selected, `applySearchProfile` passed `undefined` to `setConfidenceGate(undefined)`, corrupting the persisted `bamendjou-settings` in `localStorage`, and caused scans to post `direction: undefined`, collapsing trend scores to 0.
- **Fix**: Adhere strictly to the approved plan (Section 3.A.1) by requiring `mode`, `createdAt`, `updatedAt`, `direction`, `horizonPreset`, `holdMin`, `holdMax`, `universe` (with all 4 string bounds), `scanOverrides`, and `scanSettings` (with complete `confidenceGate` and `atrMult` pairs) to be strictly mandatory non-optional schema properties.

---

GATE FINDINGS: 1
