# Implementation Plan: Context Rail Destination Parity (#395)

**Target Issue:** #395 (`APP-AUDIT-RAIL-DESTINATION-PARITY: Calendar and Settings retain the previous context rail`)  
**Phase ID:** `APP-AUDIT-RAIL-DESTINATION-PARITY`  
**Parent Audit:** #348 / #349 (`APP-AUDIT-INVENTORY`, Findings `A-UI-RAIL-CALENDAR` and `A-UI-RAIL-SETTINGS`)  
**Branch:** `board/app-audit-rail-destination-parity-630d7589`  
**Date:** 2026-10-21  

---

## 1. Problem Statement & Audit Evidence

### Defect Mechanism
In Next.js App Router, the persistent frame shell (`frontend/app/(frame)/layout.tsx`) renders the primary workspace (`children`) alongside the parallel route slot `contextRail`:
```tsx
export default function FrameLayout({
  children,
  contextRail,
}: {
  children: React.ReactNode;
  contextRail: React.ReactNode;
}) {
  return (
    <div className={styles.frame}>
      <InitStores />
      <TopBar />
      <ConfigHealthBanner />
      <NavRail />
      <main id="workspace" className={styles.workspace} tabIndex={-1}>{children}</main>
      <ContextRail>{contextRail}</ContextRail>
      <KeyboardShortcuts />
    </div>
  );
}
```

The right-rail slot `@contextRail` is mapped parallel to `(frame)`.
Per Next.js App Router parallel route semantics:
1. **Hard Navigation (Initial Load / Full Page Reload):** If a parallel slot segment does not have a matching `page.tsx`, Next.js resolves `default.tsx` within the slot hierarchy (falling back to `frontend/app/(frame)/@contextRail/default.tsx`, which renders `<RailQuickLook />`).
2. **Soft Navigation (Client-Side Link Click):** When navigating via client-side router transition (e.g. clicking links in `NavRail`), if a destination segment lacks an explicit directory in `@contextRail`, Next.js **preserves the active slot component from the previous route**.

### Audit Reproduction & Evidence
In the whole-app inventory audit (`APP-AUDIT-INVENTORY`, commit `738d3abdec6c7359c361853268fc3b4fd74491d3`), deterministic browser testing captured in `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/findings.json` and `slot-history.json` proved:
1. **A-UI-RAIL-CALENDAR:**
   - User navigates: `Dashboard` → `Portfolio` → `Calendar`.
   - Soft navigation to `/calendar` retains `/portfolio`'s rail: `TOTALS` (Deployed, Open P&L, Positions) and `AGGREGATE GREEKS` (Δ Delta, Θ Theta / day).
   - Hard reload on `/calendar` abruptly replaces the stale Portfolio rail with the root default QuickLook (`WATCHLIST · TOP 5`, `PORTFOLIO`).
2. **A-UI-RAIL-SETTINGS:**
   - User navigates: `Dashboard` → `Watchlist` → `Settings`.
   - Soft navigation to `/settings` retains `/watchlist`'s rail: `STATUS BREAKDOWN` (PASS, CAUTION, REJECT) and `FLAGS` (Events ≤ 7d).
   - Hard reload on `/settings` replaces the stale Watchlist rail with the root default QuickLook.

### Scope of Missing Slot Segments
An audit of all route folders in `frontend/app/(frame)/` reveals which routes currently have explicit `@contextRail` slots:
- **Dedicated Route Rails:**
  - `analysis`: `frontend/app/(frame)/@contextRail/analysis/page.tsx`
  - `chart`: `frontend/app/(frame)/@contextRail/chart/page.tsx`
  - `dashboard`: `frontend/app/(frame)/@contextRail/dashboard/page.tsx`
  - `portfolio`: `frontend/app/(frame)/@contextRail/portfolio/page.tsx`
  - `watchlist`: `frontend/app/(frame)/@contextRail/watchlist/page.tsx`
  - `screener/step-7-trade-card`: `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`
- **Fallback / QuickLook Slots:**
  - `alerts`: `frontend/app/(frame)/@contextRail/alerts/default.tsx`
  - `screener`: `frontend/app/(frame)/@contextRail/screener/default.tsx`
- **MISSING Slot Folders (Affected Fallback Destination Family):**
  - `calendar` (`frontend/app/(frame)/calendar/page.tsx`)
  - `settings` (`frontend/app/(frame)/settings/page.tsx`)
  - `journal` (`frontend/app/(frame)/journal/page.tsx`)
  - `strategy-watch` (`frontend/app/(frame)/strategy-watch/page.tsx`)
  - `validation` (`frontend/app/(frame)/validation/page.tsx`)

Because these five route destinations lack `@contextRail/<segment>/` definitions, any client-side navigation to them leaves the previous screen's rail mounted, showing stale numbers (such as Portfolio Greeks/P&L or Watchlist flags) on unrelated pages.

---

## 2. Remediation Strategy

To achieve complete destination parity across soft navigation, hard reloads, and history traversal:

1. **Add Explicit Slots for All Fallback Destinations:**
   For each route in the fallback destination family (`calendar`, `settings`, `journal`, `strategy-watch`, `validation`), provide:
   - `page.tsx`: Explicitly renders `<RailQuickLook />` for client-side navigation matching the route.
   - `default.tsx`: Re-exports or renders `<RailQuickLook />` for hard reloads and sub-route fallbacks.
   Also add `page.tsx` to `alerts` (which currently has only `default.tsx`) to guarantee symmetric coverage.

2. **Explicit Implementation Pattern:**
   In `frontend/app/(frame)/@contextRail/calendar/default.tsx`:
   ```tsx
   import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';

   export default function CalendarDefaultRail() {
     return <RailQuickLook />;
   }
   ```
   In `frontend/app/(frame)/@contextRail/calendar/page.tsx`:
   ```tsx
   export { default } from './default';
   ```
   Apply the same uniform pattern across:
   - `@contextRail/calendar/`
   - `@contextRail/settings/`
   - `@contextRail/journal/`
   - `@contextRail/strategy-watch/`
   - `@contextRail/validation/`
   - `@contextRail/alerts/` (add `page.tsx` exporting from `./default`)

3. **Preserve Dedicated Page Rails:**
   - Dedicated page rails (`analysis`, `chart`, `dashboard`, `portfolio`, `watchlist`, `screener/step-7-trade-card`) remain untouched and continue to render their custom components.
   - The root fallback `frontend/app/(frame)/@contextRail/default.tsx` remains in place as the ultimate safety net for unmatched or 404 routes.

---

## 3. Detailed File Changes

### A. New Slot Files
1. `frontend/app/(frame)/@contextRail/calendar/default.tsx`:
   - Exports `CalendarDefaultRail` returning `<RailQuickLook />`.
2. `frontend/app/(frame)/@contextRail/calendar/page.tsx`:
   - Re-exports `default` from `./default`.
3. `frontend/app/(frame)/@contextRail/settings/default.tsx`:
   - Exports `SettingsDefaultRail` returning `<RailQuickLook />`.
4. `frontend/app/(frame)/@contextRail/settings/page.tsx`:
   - Re-exports `default` from `./default`.
5. `frontend/app/(frame)/@contextRail/journal/default.tsx`:
   - Exports `JournalDefaultRail` returning `<RailQuickLook />`.
6. `frontend/app/(frame)/@contextRail/journal/page.tsx`:
   - Re-exports `default` from `./default`.
7. `frontend/app/(frame)/@contextRail/strategy-watch/default.tsx`:
   - Exports `StrategyWatchDefaultRail` returning `<RailQuickLook />`.
8. `frontend/app/(frame)/@contextRail/strategy-watch/page.tsx`:
   - Re-exports `default` from `./default`.
9. `frontend/app/(frame)/@contextRail/validation/default.tsx`:
   - Exports `ValidationDefaultRail` returning `<RailQuickLook />`.
10. `frontend/app/(frame)/@contextRail/validation/page.tsx`:
    - Re-exports `default` from `./default`.
11. `frontend/app/(frame)/@contextRail/alerts/page.tsx`:
    - Re-exports `default` from `./default`.

### B. Unit & Integration Regression Test
1. Create `frontend/app/(frame)/@contextRail/__tests__/destinationParity.test.tsx`:
   - Verifies that `calendar`, `settings`, `journal`, `strategy-watch`, `validation`, and `alerts` slots all export components rendering `<RailQuickLook />`.
   - Verifies that dedicated rails (`portfolio`, `watchlist`, `dashboard`, `analysis`, `chart`) export their custom components.
   - Tests navigation transitions (simulating soft navigation vs hard navigation slot resolution) to prove that navigating from Portfolio or Watchlist to Calendar or Settings resolves the destination's default rail rather than retaining the prior rail.

---

## 4. Verification & Testing Plan

1. **Unit Testing (`npm run test`):**
   - Run `destinationParity.test.tsx` and all existing context rail test suites (`page.test.tsx` under portfolio, watchlist, chart, analysis, trade-card, etc.).
   - Verify 100% pass rate.
2. **Typecheck (`npm run typecheck`):**
   - Run `npm run typecheck` to confirm zero TypeScript errors.
3. **State Tracking (`scripts/state.py`):**
   - Ensure zero state drift before and after implementation.
4. **Independent Audits:**
   - Plan audit (Round 1) by an independent subagent under the adversarial audit skill.
   - Code audit (Round 1) by an independent subagent once implementation is complete.

---

## 5. Sub-Issues & Build Sequence

- **Ticket 1:** Create explicit slot definitions (`default.tsx` + `page.tsx`) across `calendar`, `settings`, `journal`, `strategy-watch`, `validation`, and `alerts`.
- **Ticket 2:** Add unit and integration regression test suite verifying destination parity for all fallback slots and preservation of dedicated rails.
- **Ticket 3:** Verification, typecheck, code audit, PR, and self-merge.
