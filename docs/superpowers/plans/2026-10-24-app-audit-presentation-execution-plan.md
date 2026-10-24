# APP-AUDIT-PRESENTATION-EXECUTION — Lane J2 Execution Plan

**Tracking:** board item #530 (is the phase tracking issue) · parent #358 · programme #348
**Phase id:** `APP-AUDIT-PRESENTATION-EXECUTION`
**Branch:** `board/app-audit-presentation-execution-c7c61ea2`
**Frozen application source:** `origin/main` at `4a74d186468afe0a7fc4c53e785b24b5c1f72b42` (with attribution tooling merged in PR #546 at `b98b025d`).
**Lane output directory:** `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/`

---

## 1. Goal, Deliverables, and Boundaries

### 1.1 Goal
Execute the browser presentation audit and reconciliation for Lane J (#358) using the separately audited and shipped J1 attribution tooling (`APP-AUDIT-PRESENTATION-ATTRIBUTION`, PR #546). Provide an empirical, fail-closed presentation disposition or stated blocker for every Lane A inventory row across all 45 route entries, 283 definitions, 2,269 component instances (20,421 state rows), 2,900 native instances (26,100 state rows), and all 4 supplemental capability contract levels (4 capabilities, 77 capability states, 11 route instances, and 198 route state requirements, totaling 290 supplemental rows) — bringing the grand total to exactly 52,308 inventory requirement rows.

### 1.2 Deliverables
1. **Presentation Capture Harness & Runs:** Automated browser execution driving Playwright Chromium over the supported state/viewport/theme/density matrix across all routes, collecting C1–C8 evidence (visible text, labels, zero/null/false checks, overflow, axe-core WCAG contrast, React Fiber current census, screenshots).
2. **Keyboard Traversal Suite:** Structured keyboard navigation tests (K1–K6) covering dialogs, drawers, disclosures, tabs, switches, tooltips, table rows, global shortcuts, and form controls.
3. **Triage & Defect Catalog:** `triage.json`, `defects.json` (confirmed presentation defects with reproduction commands and severity), and `handoffs.json` (numeric/persistence anomalies routed to domain lanes B–I).
4. **Reconciliation & Final Report:** `reconciliation.json` validated by `verify-coverage.cjs`, and the comprehensive Lane J audit report `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/report.md` accompanied by reproduction instructions in `README.md`.

### 1.3 Strict Boundaries (Zero Application Changes)
- **Files in scope:** Only files under `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/`, this plan, and this phase's entry in `PROJECT_STATE.json`.
- **Out of scope:** ZERO edits to `frontend/app/`, `frontend/components/`, `frontend/lib/`, `backend/`, `frontend/package.json`, or configuration files.
- No live broker orders, no live websocket connections, no real email/Telegram sends, no background processes or databases.
- When an observation shows unexpected numbers, J records them as findings/handoffs to domain lanes (B–I) without modifying scoring or calculations.

---

## 2. Infrastructure, Tooling Reuse & Provenance

### 2.1 Reused J1 Tooling
This phase executes using the verified and shipped pure library APIs from J1 (`docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/`):
- `harness/census.cjs`: Live React 19 Fiber tree current traversal (`hostRoot.stateNode.current`), unwrapping memo/forwardRef, tracking renderless components (`KeyboardShortcuts`), and recording connected DOM node ownership.
- `harness/smoke.cjs`: Isolated production build server (`npx next build --no-mangling`, `npx next start`), Playwright Chromium v1234 launcher, seed-once sessionStorage guard, and request interceptor.
- `harness/verify-coverage.cjs`: Fail-closed coverage verifier exporting pure functions `{ expandInventory, validateReconciliation, generateToolingReport }` checking SHA-256 hashes, source-derived target maps, reachability, and strict predicate compliance (`observed-verified` vs `observed-asserted`).
- `source-map.json` & `target-map.json`: Authoritative native containment, client/server classification, and definition `api.*` / store dependencies.

### 2.2 Provenance Record
Recorded in `provenance.json`:
- Source git commit SHA (`origin/main`), Node version (`v20.x`), Next.js version (`15.5.23`), React version (`19.2.5`), Playwright version (`1.51.x`), Chromium build (`151.0.7922.34`).
- Local system timezone `Europe/Berlin`, fixed clock timestamp for reproducible dates.
- SHA-256 hashes of all input fixtures, baseline maps, and harness scripts.

---

## 3. Capture Strategy and State Matrix

### 3.1 Nine State Families
Each route is exercised across the conservative 9-state matrix templates:
1. `normal`: Standard populated synthetic fixtures and seeds.
2. `expanded-nested`: Opening every disclosure, dialog, drawer, details tag, popover, tooltip, tab, and multi-row selection.
3. `empty`: Zero-candidate scan results, empty watchlist, empty portfolio, empty alert lists.
4. `loading`: Delayed/pending synthetic network responses, unhydrated paint checks.
5. `failed-cancelled`: HTTP 500 error responses, aborted requests, dismissed dialogs (Cancel/Esc).
6. `legacy-unsupported`: Pre-v1 store schemas, legacy saved report structures, unsupported mode/strategy values.
7. `zero-false-null-absent`: Field permutations verifying null does not render as 0, 0 does not render as blank, false renders proper negative label.
8. `stale-async`: Out-of-order synthetic responses across rapid symbol/mode switches, responses after component unmount.
9. `reload-restart`: Page reloads with current storage, legacy storage, and corrupted storage (verified via seed-once guard). Real backend restarts are recorded as `blocked` (owned by Lane I).

### 3.2 Viewports, Themes, and Densities
- **Viewports:**
  - Route minimum width (1200 px for Step 7 trade/position cards; 1280 px elsewhere) × 800 px.
  - Full HD: 1920 × 1080 px for `normal` and `expanded-nested`.
  - Sub-gate check: 1 px below minimum width verifying `MinWidthGate` message renders.
- **Themes:**
  - Persisted under `'bamendjou:theme'` using Zustand's `persist` JSON envelope:
    - Dark: `JSON.stringify({ state: { theme: 'dark', density: 'Comfortable' }, version: 1 })`
    - Light: `JSON.stringify({ state: { theme: 'light', density: 'Comfortable' }, version: 1 })`
  - (Setting raw strings would fail `JSON.parse` in `app/layout.tsx` pre-hydration script, preventing theme switching).
- **Densities:**
  - Comfortable (default): `density: 'Comfortable'`
  - Compact: `density: 'Compact'`

### 3.3 Routing and Parallel Slot Attribution
The 45 route entries in `inventory.json` correspond to:
- 28 navigable URLs in App Router (`/dashboard`, `/settings`, `/screener/step-1-regime`, etc.).
- 10 parallel slots under `frontend/app/(frame)/@contextRail/...`.
- 4 layout entries (Root layout, Frame layout, Screener layout, Standalone chart layout).
- 3 boundaries (`error.tsx`, `loading.tsx`, `not-found.tsx`).

Direct navigation to `@contextRail/...` returns HTTP 404 because parallel slots are mounted inside parent layouts. The capture harness navigates to each of the 28 URLs and emits distinct, correctly attributed evidence records for:
1. The page route entry (e.g. `frontend/app/(frame)/dashboard/page.tsx`),
2. The active `@contextRail` parallel slot (e.g. `frontend/app/(frame)/@contextRail/dashboard/page.tsx` or fallback `default.tsx`),
3. The layout entries enclosing that route.
This satisfies `slot-evidence-missing` and `route-mismatch` validation in `verify-coverage.cjs:541-550`.

---

## 4. Keyboard Traversal (K1–K6)

`harness/keyboard.cjs` verifies keyboard accessibility with mouse input completely disabled post-load:
- **K1 Reach:** Tab traversal from top of DOM verifying all interactive elements in `ariaSnapshot` are reachable.
- **K2 Visible Focus:** Computed `outline` / `box-shadow` changes on focus stop, inside viewport.
- **K3 Operate:** Enter/Space/Arrow keys activate controls, opening sub-states.
- **K4 Escape & Return:** Escape closes dialogs/drawers/popovers; focus returns to trigger element.
- **K5 Shortcuts:** Global shortcuts (`KeyboardShortcuts`: `1`–`7`, `g`+letter) function when idle and are properly suppressed when typing in form inputs.
- **K6 Canvas Fallback:** Verifies readable DOM alternatives, legends, or tooltips exist for chart canvas areas.

---

## 5. Triage, Reconciliation & Defect Reporting

### 5.1 Evidence Triage
- Automatically run C1–C6 detectors over all captures:
  - C1: Flags `NaN`, `undefined`, `null`, `[object Object]`, unformatted decimals, raw ISO dates.
  - C3: Mismatched null vs 0 vs false renderings.
  - C5: Layout overflow (`scrollWidth > clientWidth`) and text truncation without title/tooltip.
  - C6: WCAG 2.1 AA violations from `axe-core`.
- Triage every candidate into `finding` or `not-a-finding` with justification in `triage.json`.

### 5.2 Defect Catalog
- Confirmed defects recorded in `defects.json` with ID `J-NNN`, title, affected routes, state/theme/viewport, reproduction command, severity (`blocks-use`, `misleading`, `degraded`, `cosmetic`), and proposed owning remediation lane.
- File GitHub issues under parent #358 for confirmed presentation defects.
- Numeric/persistence anomalies recorded in `handoffs.json` and assigned to domain lanes B–I.

### 5.3 Row-Level Reconciliation and Fail-Closed Predicates
Lane J2 authors its own reconciliation runner script under `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/harness/reconcile.cjs` that imports `{ expandInventory, validateReconciliation, generateToolingReport }` from `APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/verify-coverage.cjs`. It maps all evidence into `reconciliation.json` and executes `validateReconciliation` with `evidenceRoot: 'docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION'`.

**Strict Predicate Rules (Enforced by `verify-coverage.cjs`):**
1. **`observed-verified` Criteria:**
   - Only `normal` state rows for route entries and client component definitions can earn `observed-verified`.
   - Requires unique route reachability per `source-map.json` and confirmed presence in the React Fiber current census.
2. **`observed-asserted` Criteria:**
   - Non-normal states (`empty`, `loading`, `failed-cancelled`, `legacy-unsupported`, `zero-false-null-absent`, `stale-async`, `reload-restart`): per `verify-coverage.cjs:586-590`, these throw `unsupported-state-predicate` if claimed as `observed-verified`. When observed in evidence, they are dispositioned as `observed-asserted` with positive artifact citation, explanation, and matching `state_key`.
   - Native instances and native states: all 979 definitions in `source-map.json` have `host_marker.eligible !== true` (unreviewed native markers). Per `verify-coverage.cjs:607`, natives throw `unproven-native-host-marker` if claimed as `observed-verified`. They are dispositioned as `observed-asserted` with DOM tag and component ancestry evidence.
   - Server-only components: 11 definitions without reviewed marker adapters throw `unproven-server-marker` if claimed verified; they are dispositioned as `observed-asserted`.
   - Supplemental states and supplemental route states: per `verify-coverage.cjs:592-594`, throw `unsupported-state-predicate` if claimed verified; they are dispositioned as `observed-asserted` when observed.
3. **Other Dispositions:**
   - `observed-ambiguous`: collisions across definitions or unverified duplicate native signatures.
   - `rendered-untargeted`: rendered without targeting evidence.
   - `not-triggered`: route executed but condition not met.
   - `not-run`: state or sub-case not executed.
   - `blocked`: production-gated `/dev/components`, private routes, live broker/websocket dependencies.
   - `na`: demonstrably non-applicable states with source-backed proof.

---

## 6. Implementation Units (Tickets)

The work is organized into 3 sequential build tickets (sub-issues of #530):

- **Unit 1: Full Browser Capture Suite (T1-T2)**
  - Execute automated browser runs across all 28 navigable URLs, generating distinct evidence for all 45 route entries (including `@contextRail` slots and layouts) across the 9 state families using the isolated smoke harness.
  - Collect C1–C8 evidence, axe-core scans, and Fiber current census outputs.
  - Output structured JSON evidence per route/state/viewport in `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/evidence/`.

- **Unit 2: Keyboard Traversal & Specialized States (T3-T4)**
  - Implement and run `keyboard.cjs` executing K1–K6 across all interaction families.
  - Execute edge cases: sub-gate viewports, reload-restart storage permutations, and stale-async mock responses.

- **Unit 3: Triage, Defect Filing, Reconciliation & Final Audit Report (T5)**
  - Generate `triage.json`, `defects.json`, and `handoffs.json`.
  - Implement `reconcile.cjs` importing `verify-coverage.cjs` to validate all 52,308 inventory requirements and produce `reconciliation.json`.
  - Author comprehensive Lane J audit report `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/report.md` and `README.md`.
  - File confirmed defect issues as sub-issues of #358.

---

## 7. Audit and Shipping Gate

- **Plan Audit Gate:** Fresh independent subagent applying `bmad-review-adversarial-general` against this plan and the codebase it references.
  - Gate criteria: Report correctness (wrong coverage number/verdict, crediting unobserved rows, reporting asserted as verified, claiming unrun checks) or exposure of paths modifying application source / persisted data.
  - Capped at 3 rounds.
- **Code Audit Gate:** After Unit 3 completion and merging `origin/main`, fresh independent subagent reviews diff `origin/main..HEAD` against this plan.
  - Same gate criteria, capped at 3 rounds.
- **Milestones:**
  - 10%: Plan drafted
  - 20%: Plan audit clean
  - 50%: Unit 1 & Unit 2 evidence captured
  - 70%: Unit 3 complete (triage, defects, reconciliation, report.md)
  - 85%: Code audit clean
  - 100%: PR merged and verified on main
