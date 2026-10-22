# Adversarial Audit Report: Context Rail Destination Parity Plan (#395)

**Target Document:** `docs/superpowers/plans/2026-10-21-app-audit-rail-destination-parity-plan.md`  
**Phase ID:** `APP-AUDIT-RAIL-DESTINATION-PARITY`  
**Reviewer:** Independent Adversarial Subagent (`1d2ca41c-1ab0-4c5d-8e87-238aa1cd6a09`, applying `bmad-review-adversarial-general`)  
**Gate Standard:** Numerical / Persistence / Mechanism Truth Gate (AUDIT-RULE-V2)  
**Date:** 2026-10-21  

---

## 1. Scope & Verification Checklist

I performed an independent adversarial audit of the plan against the real codebase, inventory audit evidence, and state tracker:
1. **Frame Shell Architecture (`frontend/app/(frame)/layout.tsx`):**
   - Verified that `FrameLayout` hosts `<ContextRail>{contextRail}</ContextRail>` mapped parallel to the persistent frame shell.
   - Confirmed `@contextRail` is the only parallel route slot defined in the application.
2. **Current Root & Segment Default Rails:**
   - Inspected `frontend/app/(frame)/@contextRail/default.tsx`: explicitly renders `<RailQuickLook />` as root fallback for unmatched routes.
   - Inspected `frontend/app/(frame)/@contextRail/alerts/default.tsx` and `frontend/app/(frame)/@contextRail/screener/default.tsx`: both explicitly render `<RailQuickLook />`.
3. **Dedicated Route Rails:**
   - Inspected `frontend/app/(frame)/@contextRail/portfolio/page.tsx`: renders portfolio totals (`Deployed`, `Open P&L`, `Positions`) and `AGGREGATE GREEKS` (`Δ Delta`, `Θ Theta / day`).
   - Inspected `frontend/app/(frame)/@contextRail/watchlist/page.tsx`: renders `STATUS BREAKDOWN` (`PASS`, `CAUTION`, `REJECT`) and `FLAGS` (`Events ≤ 7d`).
   - Inspected `analysis`, `chart`, `dashboard`, and `screener/step-7-trade-card`: verified they are the only other dedicated custom rails.
4. **Target Fallback Route Destinations:**
   - Checked filesystem under `frontend/app/(frame)/`: exactly 12 top-level route segments exist (`alerts`, `analysis`, `calendar`, `chart`, `dashboard`, `journal`, `portfolio`, `screener`, `settings`, `strategy-watch`, `validation`, `watchlist`).
   - Confirmed that `calendar`, `settings`, `journal`, `strategy-watch`, and `validation` completely lack directories under `frontend/app/(frame)/@contextRail/`.
   - Confirmed that `alerts` contains only `default.tsx` and lacks `page.tsx`.
5. **Audit Evidence & Defect Reproduction:**
   - Cross-checked `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/findings.json` (items `A-UI-RAIL-CALENDAR` and `A-UI-RAIL-SETTINGS`) and `slot-history.json`.
   - Verified the recorded failure: navigating `/portfolio` → `/calendar` retains Portfolio totals and Greeks (`slots:soft:/calendar`), whereas hard reload replaces it with QuickLook (`slots:hard:/calendar`); navigating `/watchlist` → `/settings` retains Watchlist status breakdown and flags (`slots:soft:/settings`), whereas hard reload replaces it with QuickLook (`slots:hard:/settings`).
6. **State Tracking & Verification Probes:**
   - Inspected `docs/superpowers/PROJECT_STATE.json` (`APP-AUDIT-RAIL-DESTINATION-PARITY`): verified phase registration, branch `board/app-audit-rail-destination-parity-630d7589`, and the verify probe pinning `pattern: "CalendarDefaultRail"` in `frontend/app/(frame)/@contextRail/calendar/default.tsx`.
   - Verified `scripts/state.py` passes clean with zero state drift on the current branch.

---

## 2. Gate-Level Analysis & Findings Evaluation

### A. Number Presentation & Order Accuracy
- **Pre-change state:** The pre-change bug displayed stale numerical totals (e.g. Portfolio Greeks, open P&L, deployed capital, or Watchlist event flag counts) on unrelated pages (Calendar, Settings) after soft navigation.
- **Proposed remediation:** Providing explicit slot `page.tsx` and `default.tsx` files for `calendar`, `settings`, `journal`, `strategy-watch`, `validation`, and `alerts` mounting `<RailQuickLook />` guarantees that client-side transitions immediately unmount stale page-specific rails and mount the shared QuickLook.
- `<RailQuickLook />` reads live user portfolio positions from `portfolioStore` (`openTotals`) and live watchlist data from `api.getWatchlist()`. It does not calculate order sizing or submit broker orders. No wrong numbers are displayed or sent to brokers.

### B. Persistence Integrity
- None of the added files (`default.tsx`, `page.tsx`) perform store writes, localStorage mutations, or database updates.
- No persisted data is modified or corrupted.

### C. Mechanism & Behavioral Truth
- The plan correctly describes Next.js App Router parallel route semantics: Next.js preserves the active state of an unmatched slot on client-side soft navigation unless a matching directory/page exists in the slot hierarchy.
- The plan's implementation pattern (`export default function <Name>DefaultRail() { return <RailQuickLook />; }` in `default.tsx` and `export { default } from './default';` in `page.tsx`) mirrors established repo conventions (e.g. `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/default.tsx`) and satisfies both soft navigation (`page.tsx`) and hard reload / sub-route fallbacks (`default.tsx`).
- The plan names all 5 missing slot folders (`calendar`, `settings`, `journal`, `strategy-watch`, `validation`) plus `alerts/page.tsx`, achieving 100% route coverage across all routes in `frontend/app/(frame)/`.

---

GATE FINDINGS: 0

**Basis for zero gate findings:**
1. Verified that the plan's proposed slot additions completely cover every fallback destination route in the persistent frame without omitting any destination.
2. Verified that the mechanism of Next.js parallel route slot retention and resolution is accurately stated and correctly addressed via symmetric `page.tsx` and `default.tsx` definitions.
3. Verified that the plan satisfies the verify probe in `docs/superpowers/PROJECT_STATE.json` (`CalendarDefaultRail` in `frontend/app/(frame)/@contextRail/calendar/default.tsx`).
4. Verified that no wrong numbers can be placed before a user or on a broker order, and no persisted data can be corrupted by the planned changes.
