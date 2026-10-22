# APP-AUDIT-PRESENTATION — Lane J execution plan

**Tracking:** board item #358 (is the phase tracking issue) · programme #348
**Phase id:** `APP-AUDIT-PRESENTATION`
**Branch:** `board/app-audit-presentation-58612753`
**Frozen application source:** `origin/main` at `bf0b3b5400f1aa0e5a695a3d13139f8b893fcf09` (the branch point). Every observation records this SHA; a later `git merge origin/main` changes no observation unless a ticket re-runs it and records the new SHA.
**Lane output directory:** `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION/` (only this lane writes there).

## 1. Goal, deliverable and boundaries

Verify usability and every expanded, empty, error and legacy disclosure of the frontend in a real browser, and give **every Lane A inventory row a presentation result or a stated blocker**. Deliverables: a reproducible harness, captured evidence, a row-level reconciliation against Lane A's inventory, a report, and one separately filed GitHub issue per confirmed presentation defect.

Audit/report only. In scope for commits: files under the lane output directory, this plan, and this phase's `PROJECT_STATE.json` entry. **Out of scope:** any change under `frontend/app`, `frontend/components`, `frontend/lib`, `backend/`, `frontend/e2e/` or config; recalibration; storage-key renames; live broker orders; real notification sends; any backend process, database or scheduler. Fixes become separately claimed board phases.

Lane J owns presentation findings across the app. Domain lanes B–I own arithmetic and persistence. When a capture shows a number that looks wrong, J records it as an observation and hands it to the owning lane (the inventory's `owners.numeric` / `owners.persistence`); J does not certify or refute arithmetic.

## 2. Environment and provenance (recorded by T1 in `provenance.json`)

- Production build: `cd frontend && npx next build --no-mangling` (Next 15.5.23, React 19.2.5). `--no-mangling` is a supported `next build` flag that keeps function names so the React fiber census (§4.3) can name rendered components; the build is otherwise a normal production build. Verified feasible on 2026-10-22: the build succeeds in about 1 minute and a fiber walk on `/dashboard` resolved 56 component names, including `DashboardPage`, `RiskPanel`, `RailQuickLook`.
- Server: `npx next start -p 3031 -H 127.0.0.1` from `frontend/`, started and stopped by the harness. No `next dev`.
- Browser: Playwright `@playwright/test` 1.62.1 driving Chromium 141.0.7390.37 at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (the default headless-shell path for this Playwright version is not installed; the explicit executable is). Headless, new context per run, `serviceWorkers: 'block'`, `locale: 'en-US'`, `timezoneId: 'Europe/Berlin'` (Kenneth's operating zone, as Lane A used), fixed clock via `page.clock.setFixedTime` at a recorded instant so date labels are deterministic.
- Record: SHA, Node version, Next/React/Playwright/Chromium versions, `axe-core` version (already in `frontend/node_modules`), harness file SHA-256s, fixture file SHA-256s, `python3.11 --version` (recorded for programme provenance only; no backend runs in this lane).

## 3. Network isolation and fixtures

- The API base is `NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'` (`frontend/lib/api.ts:94`). The harness routes **every** request: same-origin non-`/api` GETs continue to the local Next server; requests matched by the active fixture set are fulfilled from synthetic JSON; **everything else is aborted** and logged as `blocked-unmatched`. Every WebSocket is closed before connecting (`context.routeWebSocket`). No request ever reaches a backend.
- Fixtures reuse `frontend/e2e/fixtures/api-mocks.ts` (`setupApiMocks`, `MOCK_OPTION_CHAIN`, `MOCK_SCAN_CANDIDATE`) by import, without editing it, and add lane-local synthetic fixtures under the lane directory. Every fixture body is SHA-256 addressed in `mock-payloads.json` and linked from the observations that used it.
- Store-seeded states (scan results for Steps 4–7, portfolio rows, watchlist, legacy shapes) are written to `localStorage` **before** the app loads, using the real persisted keys listed in `CLAUDE.md` (for example `'bamendjou-scan-store'`, `'bamendjou-portfolio-v1'`, `'bamendjou:theme'`). The seeded bytes are recorded per observation. Seeds are synthetic and live only in the isolated browser context.
- **Seed once, never on reload.** Playwright re-runs `context.addInitScript` on every navigation including `page.reload()`, which would overwrite whatever the app persisted. The init script therefore writes the seed only if the `sessionStorage` flag `__laneJ_seeded` is absent and then sets it; `sessionStorage` survives a same-tab reload, so a reload reads what the app itself wrote. Every reload observation records full `localStorage` before and after the reload. The T1 self-test proves the guard: seed key `X`, let the page overwrite it, reload, and assert the overwritten value (not the seed) is read back.
- A `blocked-unmatched` request during a capture is not silently ignored: T5 lists each one and states whether it left a surface in a loading/failed state that the observation then reports as such.

## 4. What is captured

### 4.1 State families (the inventory's nine state keys, exact names)

The keys and sub-cases are exactly those of `inventory.json` → `state_matrix_templates["conservative-nine-state-v1"]`. For each URL page, rail slot and boundary, the harness runs every **sub-case** below. Each sub-case is either executed (observation IDs recorded) or recorded per route as `not-run` with a reason; a key is never reported as executed when only some of its sub-cases ran — the per-row disposition (§5) names the sub-cases that actually entered the row's state. A key that cannot apply to a route is `na` only with a source-backed reason, and only after the inventory's stated pre-N/A checks (for example: `/screener/step-5-strategy` is a redirect, so it has only a redirect observation).

| Key | Sub-cases and how each is produced |
|---|---|
| `normal` | Populated deterministic fixtures and seeds; default settings. |
| `expanded-nested` | From `normal`, open every disclosure the route offers: `<details>`, `aria-expanded` toggles, dialogs, drawers, popovers, tooltips (hover **and** keyboard focus), row selections, tabs; ≥2 distinct rows where rows repeat. Each opened state is its own observation with the action path that produced it and the definition/native IDs that action opened. |
| `empty` | (a) fixtures returning empty collections; (b) no selected symbol/candidate; no seeds. Parent-controlled empty props are inspected before any `na`. |
| `loading` | (a) the route's requests held unresolved until capture; (b) a slow hydration capture taken before stores rehydrate (first paint after `domcontentloaded`); parent-controlled loading props inspected before any `na`. |
| `failed-cancelled` | (a) HTTP 500 with a JSON error body and (b) network abort, applied **per request path** the route issues (each path in turn, not only the primary one), each recorded with the path it failed; (c) a dialog opened and cancelled (Cancel button and Escape), distinguished from failure; (d) an interrupted request: navigation away / control change while a request is pending. No real mutation is ever sent: every unsafe method is fulfilled or aborted by the mock. |
| `legacy-unsupported` | (a) older persisted shapes the stores' `migrate()` accepts; (b) legacy saved-report records where the report inspector reads them; (c) unsupported mode / broker / strategy values seeded into the persisted stores and fixtures; (d) records with missing source provenance fields. No storage key is renamed. |
| `zero-false-null-absent` | Four distinct fixture variants on displayed fields: `0`, `false`, `null`, field omitted. Checked by C3. |
| `stale-async` | (a) two delayed responses released in reverse order across a symbol/mode/control change; (b) a response released after the consuming component unmounted (navigate away, then release); (c) parent async props released late; (d) hydration recovery (persisted state arriving after first render). `na` only for a route where none of (a)–(d) has a source path, citing the source. J records what is presented and whether staleness is labelled; which value is correct belongs to the domain lane. |
| `reload-restart` | `page.reload()` with (a) current-shape storage written by the app during the run, (b) legacy-shape storage, (c) corrupt storage (invalid JSON, wrong types) under each persisted key the route reads, (d) soft navigation away and browser back/forward versus hard reload; full `localStorage` read back before and after each. Seeds are applied once only (§3). Backend restart is not executed in this lane (owner Lane I) and is recorded `blocked` per row. |

### 4.2 Viewport, theme, density matrix

- Minimum supported width per route comes from `MinWidthGate` (`frontend/components/MinWidthGate/index.tsx`): **1200 px** on `/screener/step-7-trade-card` and `/screener/step-7-position-card`, **1280 px** elsewhere.
- Every state-family observation runs at the route's minimum width × 800 high, in **both** `dark` and `light` theme.
- `normal` and `expanded-nested` additionally run at **1920 × 1080** in both themes.
- `normal` additionally runs once in `Compact` density (the other density, `Comfortable`, is the default) at minimum width, dark theme.
- Width one pixel below the minimum: one observation per route confirms the gate message renders and is readable.
- Zoom: browser zoom changes the CSS viewport width, so 125 % / 150 % zoom on a 1600 / 1920 px window is the 1280 CSS-px case already covered; additionally one `normal` observation per route runs at 1280 × 800 with `deviceScaleFactor: 2` to check that nothing depends on device pixels. Anything below the gate is unsupported by design and reported as such, not as a defect.
- Theme and density are applied through the real persisted key `'bamendjou:theme'` (`frontend/lib/theme.ts`, read by the no-flash script in `frontend/app/layout.tsx`), so the `<html data-theme / data-density>` attributes are set by the app itself.

### 4.3 Per-observation checks (all recorded as data, not only screenshots)

Each observation stores: URL, action path, viewport/theme/density, seed bytes, network log indices, page errors, console errors, and:

- **C1 Visible text readback.** All visible text with its element's role/label. Detectors flag candidate defects: literal `NaN`, `undefined`, `null`, `Infinity`, `[object Object]`, `\u`-escapes, unrendered template markers, numbers with more than 4 decimals, raw ISO timestamps, a unit-less number next to a label that elsewhere carries a unit, the same field with different units or rounding on one screen. Candidates are triaged by a human-equivalent reading in T5; a detector hit is never by itself a finding.
- **C2 Labels and scope.** For every labelled value: the label text, the unit, and whether the surface says if it is saved, current or live (scan-frozen vs current controls; saved report vs live). Mislabelled or unlabelled scope is a presentation finding.
- **C3 Unavailable vs zero vs false.** In the `zero-false-null-absent` variants, each field set to `null` or omitted must not render as `0`, `0%`, `$0`, `No` or `false`; each field set to `0` must not render as `—`/`n/a`/blank; each boolean set to `false` must render as its negative label, not as unavailable or as the literal `false`. Field-by-field expected/actual pairs are recorded.
- **C4 Bounded raw data.** Raw JSON / evidence disclosures (`RawEvidence`, `LegacyReport`, `UnsavedReport`, report inspector) are explicitly opened by the user, bounded (scroll container or truncation with a stated total), and not the only place a value is readable.
- **C5 Overflow and layout.** Horizontal page scroll (`scrollWidth > clientWidth` on the scrolling element); elements whose text is clipped (`scrollWidth > clientWidth` with `overflow: hidden` or `text-overflow: ellipsis`) and have no accessible full value (`title`, `aria-label`, tooltip); interactive elements overlapping another interactive element's box; content outside the viewport horizontally.
- **C6 Contrast and accessible names.** `axe-core` (from `frontend/node_modules`) with `wcag2a`, `wcag2aa` and `wcag21aa` tags, per observation, both themes. Each violation records rule, node selector, and contrast ratio where applicable. Additionally Playwright's `ariaSnapshot()` of `body` is stored, so every interactive element's computed role and name is in the evidence.
- **C7 Fiber census (live tree).** From any connected element's `__reactFiber$*`, walk `return` links to the `HostRoot` fiber (tag 3), then start from `hostRoot.stateNode.current` — the FiberRoot's **current** tree (React keeps two alternates and swaps them on each commit, so the fiber reached from a DOM node or from `__reactContainer$*` may be the stale alternate). Traverse the whole current tree via `child`/`sibling`, so components that render no DOM are included; collect component names (`type.displayName || type.name`, unwrapping `memo`/`forwardRef`/`lazy`) and, per component, the host nodes it owns, counting only nodes with `isConnected === true`. Server-only components are not in this tree (§5.1). T1 self-tests: `KeyboardShortcuts` (renders `null`, mounted by the Frame layout) is in the `/dashboard` census; after opening and then closing a dialog (e.g. `ConfirmDialog`), the dialog component is absent from the census taken after close.
- **C8 Screenshot.** Full-page PNG; its SHA-256 is stored for every observation. Only screenshots cited by a finding are committed (cropped where possible), to keep the repository small; every other screenshot is reproducible from the harness and recorded by hash. Screenshots are never the only evidence for a result.

### 4.4 Keyboard-only traversal, one procedure per interaction family

Run with the mouse never used after page load. Families (source census at the frozen SHA): dialogs (`role="dialog"` in 14 files, e.g. `ConfirmDialog`, `SaveProfileDialog`, `RenameProfileDialog`, `SendToBrokerDialog`, `StockSendDialog`, `CompositeAlertDialog`, `JournalEntryForm`, `TextInputPopover`, `ChartClickPopover`); drawers (`EditDrawer`, `ClosePositionDrawer`, `PipelineInspector`, `SavedScanReportInspector`); `aria-expanded` toggles (13 files incl. `CollapsibleSection`, `ContractExplanationToggle`, `ConfigHealthChip`); `<details>` disclosures (22 files); tabs (`role="tab"`: watchlist, Step 2, `JournalEntryForm`); switches and radio groups (settings, alerts, `EditDrawer`, `MethodPickSelector`); tooltips (`Tooltip`, Step 5 contract); selectable table rows (`TableRow`, `QuickLookRow`, `JournalEntryTable`); global shortcuts (`KeyboardShortcuts`: `1`–`7`, `g`+letter, `?`; `StepNavBar` ←/→); chart canvas interactions (`ChartWorkspace`, `ChartTopBar`, `ChartRightPanel`); native form controls (`select`, checkboxes, inputs).

For each family, on at least one route where it occurs (every route where it is cheap), record:
- **K1 Reach:** Tab from the document start; the ordered list of focused elements (role, name, bounding box). Every interactive element in the ariaSnapshot must be reached, or the gap is a finding. Elements with click handlers but no keyboard route (found via fiber props `onClick` on non-interactive host elements without `tabIndex`) are listed.
- **K2 Visible focus:** for each focus stop, computed `outline`/`box-shadow` differs from the unfocused state, and the element is inside the viewport (scrolled into view).
- **K3 Operate:** Enter/Space (and arrows for tabs/radios/sliders) performs the action; the resulting state is captured as an `expanded-nested` observation.
- **K4 Escape and return:** dialogs, drawers and popovers close on Escape; focus returns to the opening control; modal dialogs keep Tab within themselves while open.
- **K5 Shortcuts:** global shortcuts do not fire while typing in inputs (the documented `isEditable` guard) and do fire otherwise. The header comment of `KeyboardShortcuts` also documents `?` (cheat sheet, "Phase 7"); K5 records whether pressing `?` does anything, and a documented-but-absent shortcut is a triage candidate, not assumed to work.
- **K6 Chart canvas:** whether chart information has a keyboard/readable alternative; absence is recorded as a finding candidate, not assumed acceptable.

## 5. Coverage contract against the Lane A inventory

Source of rows: `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/inventory.json` and `supplemental-capability-contracts.json`, expanded exactly as Lane A specifies (`state_row_expansion` and `route_instances[*].native_instance_expansion`). Five levels, every ID reconciled:

| Level | Count at the frozen inventory | ID rule |
|---|---|---|
| Route entries | 45 | `route_entries[*].id` |
| Definitions | 283 | `definitions[*].id` |
| Component route instances / their state rows | 2,269 / 20,421 | `route_instances[*].id` / `state_ids` (9 per instance) |
| Native route instances / their state rows | 2,900 / 26,100 | route-instance ID + `"::"` + `native_surfaces[*].id`; state ID = that + `"::state:"` + key |
| Supplemental capability states / route-state requirements | 77 / 198 | as listed in `supplemental-capability-contracts.json`, with their own state keys (which include keys outside the nine, e.g. `kind-FVG-visible`, `type-rsi`, `missing-invalid-explanation`) |

T5 writes `reconciliation.json` with **exactly one disposition per ID at every level**, and `verify-coverage.cjs` recomputes the expansion from Lane A's files (it does not read counts from this plan) and fails if any ID is missing, duplicated or unknown, or if the computed totals differ from `inventory.json` → `counts`.

### 5.1 Tying an observation to a definition or a native

- **Client vs server-only definitions.** T1 computes the *client module set* from source at the frozen SHA: every module whose file starts (after comments) with `'use client'`, plus every module transitively imported by one (edges from `inventory.json` → `import_graph`). A definition is *server-only* only if its module is **not** in the client module set. Shared atoms/molecules without the directive (e.g. `Data`, `Text`, `StatusBadge`) are imported by client modules, so they are client definitions and are tied by the census like any other. The generated list is committed as `server-only.json` with the import evidence for each entry.
- **Client definitions** — C7 census (§4.3) of the live tree, name-matched only against definitions reachable on that route per `route_instances`. Duplicate names on one route (`Row` ×4, `SortBtn` ×3, `CalendarIcon` ×3, …) → `observed-ambiguous` for every candidate (see §5.3).
- **Server-only definitions** never appear in the client fiber tree. They are tied only via **host evidence**: a connected DOM element or text produced literally by that definition's own JSX (recorded selector + source line) in the cited observation; otherwise `blocked` ("server-only component, not in client census, no host marker").
- **Natives** — each connected DOM node is assigned to **at most one native**, and only to a native of the **nearest** client definition that owns the node in the live fiber tree (nodes rendered by a descendant definition belong to that descendant, never to the ancestor). A node matches a native's source signature when the host tag (or, for a custom-component tag, the census component name) and every literal identifying attribute in `attributes` (e.g. `role`, `aria-label`, `title`) and its literal non-blank `text` agree. If two or more natives reachable on the same route share an identical signature (the inventory has 49 such natives in 19 groups, e.g. the two `StockPositionCard` "View Chart" links at lines 880 and 1527, the two `PortfolioPage` "Dismiss" buttons at lines 194 and 207, the per-sub-mode Pre-Breakout Run Scan buttons), every one of them is `observed-ambiguous` regardless of how many nodes matched.
- **Renderless client components** (return `null`: e.g. `KeyboardShortcuts`, `StoreHydration`, `InitStores`, supplemental `ChartOverlays`, `DrawingOverlays`) are found by the live-tree census, which includes fiber-only components. Supplemental capability rows additionally need the capability's own observable effect named in its contract (e.g. a marker/price-line label in the chart's DOM), else `not-triggered`.

### 5.2 When a state row is credited — verified vs asserted

Lane A's `entry_requirement` text is one template string per state key, shared by all definitions; it has **no per-definition map** of request paths, data keys or disclosure controls. The verifier therefore can only check what is recorded in observation files, and the report separates what is machine-verified from what is asserted:

- **`observed-verified`** (counted as verified coverage) — the cited observation is of the row's route and the row's own state key (and, for supplemental rows, the supplemental key), the definition/native is tied to it per §5.1, and:
  - for `normal`: nothing more;
  - for `expanded-nested`: the observation's recorded action path ends in activating **this native** (or a native owned by this definition), identified by native ID, and the post-action live census/DOM shows the disclosed content that native controls;
  - for any other key: the observation's `targets` entry for this row names a fixture whose request path or seed key the verifier can see in that observation's network log / seeded storage **and** that path/key is listed for this definition in the T1 *source-derived target map* — a table generated from source at the frozen SHA giving, per definition, the `api.*` functions called in its own module (resolved to request paths through `frontend/lib/api.ts`) and the persisted store keys its own module reads. A definition with no entry in the map can never reach `observed-verified` for these keys.
- **`observed-asserted`** (reported separately, **not** summed with verified coverage) — the definition/native is tied to a capture of the row's route and state, and the implementer recorded targeting evidence in prose (action path, branch condition satisfied), but the verifier cannot check it against the source-derived map. The report lists these with their evidence and calls them unverified.
- **`rendered-untargeted`** — present in a capture of that state with no targeting evidence. Not coverage.

The verifier mechanically checks every `observed-verified` row against the observation file and the target map; it checks `observed-asserted` rows only for route/state/tie presence and non-empty evidence.

### 5.3 Disposition vocabulary (exactly one per row)

- `observed-verified`, `observed-asserted`, `rendered-untargeted` — §5.2.
- `observed-ambiguous` — tied only through a shared name or shared native signature (§5.1). It is upgraded to `observed-asserted` only with a manual note naming the branch condition the fixture satisfied and the DOM evidence that distinguishes it; it is never `observed-verified`. Without the note it is reported as `observed-ambiguous` and not counted as coverage.
- `finding` — any `observed-*` disposition plus the defect ID(s); the report keeps the underlying verified/asserted/ambiguous class.
- `not-triggered` — the row's route and state key (or supplemental key) **was executed** but the definition/native did not render or its entry was not met; cites the unmet condition.
- `not-run` — the row's state key or supplemental key (or every sub-case of it) was **never executed** for that route in this lane; states why. Counted and listed by the verifier; never presented as checked. Supplemental-key rows (99 of the 198 requirements use keys outside the nine) are `not-run` unless T2/T3 records a capture for that exact supplemental key from its `fixture_contract`.
- `na` — the state cannot apply (source-backed reason, after the template's pre-N/A checks).
- `blocked` — cannot be executed in this lane, with reason and owning lane (live backend/broker/websocket; private crash route; production-gated dev route; server-only component without host marker; real backend restart).

Fixed dispositions: `component_files_not_reached` (4 files) and `/__test-crash` (private folder) are `blocked` citing Lane A's existing disposition. `/dev/components` calls `notFound()` when `NODE_ENV !== 'development'` (`frontend/app/dev/components/page.tsx:34`); in this production-build lane it is captured once to prove the 404, and the route entry and all its route instances/states are `blocked` ("production-gated; reachable only under next dev"). No `next dev` run is made.

Coverage summary: the verifier produces per-level counts of every disposition. "Every inventory row has a presentation result or stated blocker" is satisfied by every ID carrying one disposition; the report headlines `observed-verified`, shows `observed-asserted` and `observed-ambiguous` separately as unverified, and never presents `rendered-untargeted`, `not-triggered`, `not-run`, `na` or `blocked` as passes.

Source added after the inventory: Lane A's inventory was generated at `00b4ab54`; route-entry files added since (rail `page`/`default` re-exports and others) are not in `inventory.json`. T5 globs `frontend/app/**/{page,layout,default,error,loading,not-found}.tsx` at the frozen SHA, lists every file absent from `route_entries`, and dispositions each with the same vocabulary in a separate `post-inventory-additions` section. Lane A's files are never edited. Before closure T5 also checks whether `inventory.json` changed on `origin/main` and, if so, dispositions every added ID.

## 6. Findings

Each presentation defect in `defects.json` has: ID `J-NNN`, title, route(s), state/viewport/theme, reproduction (harness command + observation ID), expected, actual, affected SHA, severity class (`blocks-use` / `misleading` / `degraded` / `cosmetic`), related existing issue (searched by title/route before filing), owning remediation lane (J for presentation; domain lane for numbers), evidence paths, regression check to use on retest, retest status `unfixed`. Numbers/persistence observations go into a separate `handoffs.json` with the owning lane; J files no numeric verdicts.

Filing: the coordinator (not the implementers) files one GitHub issue per confirmed defect with the template in `docs/agents/board.md`, labels `board-item`, `priority:app-audit`, one `size:*`, one `complexity:*` with rationale (per `docs/agents/task-ratings.md`), links it as a sub-issue of #358, and records native blocked-by edges only where two fixes touch the same source file. Defects that duplicate an open issue are added as a comment on that issue instead. Filing does not add them to the Board's Queue (only Kenneth edits the Board body); the coordinator lists them in a Board comment.

## 7. Tickets (build units; sub-issues of #358)

All tickets: write only inside the lane directory; run nothing against a backend; commit with message `docs(audit): APP-AUDIT-PRESENTATION <ticket summary>`; never edit `PROJECT_STATE.json` audit fields.

**T1 — Harness and provenance.** `harness/` with: build/start/stop scripts; `run.cjs` (context, routing, WebSocket close, clock, seeding, matrix loop, per-observation capture C1–C8, axe injection from `node_modules/axe-core/axe.min.js`); `fixtures/` registry keyed by route × state family; `provenance.json`. Output layout `evidence/<route-slug>/<state>/<viewport>-<theme>[-<density>].json` plus `index.json`. **Acceptance:** a smoke run of `/dashboard` and `/settings` in `normal` at 1280 dark produces observations with non-empty C1, C6 and C7 (C7 ≥ 20 names on `/dashboard`), zero requests reaching a non-local host, and `provenance.json` complete. `node harness/self-test.cjs` checks: (a) an unmatched request is aborted and logged, (b) a WebSocket is closed, (c) a 500 fixture is served when the `failed-cancelled` family is selected, (d) the seed-once guard: a seeded key overwritten by the page survives `page.reload()` (§3), (e) the full-tree census contains `KeyboardShortcuts` on `/dashboard` (§4.3 C7), (f) `server-only.json` is generated per §5.1 (client module set from `'use client'` plus transitive imports) and each server-only entry has a host-marker selector or a `blocked` reason, (g) the live-tree census excludes a closed dialog, (h) the source-derived target map (§5.2) is generated and committed as `target-map.json` with the source line of each `api.*` call and store-key read. Every capture writes its `targets` declarations (§5) — the observation schema requires the field.

**T2 — Screener captures.** Fixtures and runs for `/screener` (redirect), Steps 1–3 (all three modes where the step varies by mode), Options Steps 4-ranking → 5 → 6 → 7 trade card, Stocks Steps 4-stocks → 6-backtest → 7-position-card, Pre-Breakout Step 4 with sub-modes `prebreakout` / `pullback` / `fib`, the `/screener/step-5-strategy` redirect, and the screener and Step 7 `@contextRail` slots; every state family in §4.1 and the matrix in §4.2. **Acceptance:** every screener route entry has, per state key and sub-case (§4.1), observations with `targets` declarations or a recorded `not-run`/`na`/`blocked` reason; expanded-nested covers every `<details>`/`aria-expanded`/dialog/drawer found on these routes by a DOM query, with ≥2 rows where rows repeat.

**T3 — Non-screener captures.** Same for `/dashboard`, `/portfolio` (incl. `EditDrawer`, `ClosePositionDrawer`), `/watchlist` (Stocks/Contracts tabs), `/alerts`, `/strategy-watch`, `/analysis`, `/chart`, `/chart/standalone`, `/calendar`, `/journal`, `/validation`, `/settings` (each of the 9 sections), `/dev/components` (one capture proving the production 404; see §5), the root redirect, `not-found`, the Frame `error.tsx` boundary (malformed fixture then Retry, as Lane A did) and `loading.tsx`, and the remaining rail slots and fallbacks. **Acceptance:** as T2 for these routes.

**T4 — Keyboard traversal.** `harness/keyboard.cjs` implementing K1–K6 for every family in §4.4, both themes at minimum width (focus visibility differs by theme). **Acceptance:** each family has ≥1 executed procedure with per-step records; every K-check outcome is pass, finding-candidate, or blocked-with-reason.

**T5 — Triage, reconciliation, report.** Triage every C1/C5/C6/K detector candidate into `finding` or `not-a-finding` with a one-line reason (`triage.json`); write `defects.json`, `handoffs.json`, `reconciliation.json`, `verify-coverage.cjs`, `report.md`, `README.md` (reproduction commands). Report separates **presentation verdicts** from **numbers/persistence observations**, lists every `blocked`/`N/A` with reason, and states limitations (§9). **Acceptance:** `node verify-coverage.cjs` passes, recomputing all five levels of §5 from Lane A's files (2,269/20,421 component and 2,900/26,100 native rows at the frozen inventory) checking every `observed-verified` row against the cited observation file and `target-map.json` per §5.2, checking `observed-asserted`/`observed-ambiguous` rows for route/state/tie presence and non-empty evidence, and reporting the verified, asserted, ambiguous and non-covered counts separately; every defect has all §6 fields; report counts are produced by the verifier, not typed.

Order: T1 → (T2, T3 in sequence; they share the harness) → T4 → T5. T2/T3 may extend the fixture registry only by adding files.

## 8. Audits, milestones, merge

- **Plan stage:** fresh independent auditor per round on this file against the real code it names; cap 3.
- **Code stage:** after T5, `git merge origin/main`, re-run `verify-coverage.cjs` and the harness self-test, then fresh independent auditor per round on `origin/main..HEAD`; cap 3. Gate for this report deliverable, briefed to the auditor: a finding blocks only if the evidence or report would put a **wrong number or wrong verdict in front of the reader** (a check claimed as run that did not run, a row claimed covered that is not, a defect misreported, a value transcribed wrongly) or if the diff **changes application code, fixtures shared with other lanes, or persisted data**. Wording and style are not reported.
- **Completion milestones for this audit-only phase** (per `task-ratings.md`): 0 % queued · 10 % this plan drafted · 20 % plan independently approved and recorded · 50 % T1–T4 evidence exists · 70 % T5 done, `verify-coverage.cjs`, harness self-test, `npm run typecheck` and `python3 scripts/state.py` pass · 85 % code-stage audit clean · 95 % PR head CI green and mergeable · 100 % merged and the verifier re-run on `main` recorded. No milestone claims any defect fixed.
- **Merge:** board self-merge conditions (`docs/agents/board.md` step 7). #358 closes with the PR; filed defects stay open as their own board items. #359 (integration) depends on this lane closing.

## 9. Known limits stated up front

- Synthetic fixtures, not real market data; real-environment checks are N/A in this lane (no backend runs) and are reported as such.
- Accessible names are checked from the browser accessibility tree and axe-core, not with a screen reader.
- One browser engine (Chromium 141). Other engines are not covered.
- Real backend/database restart belongs to Lane I; `reload-restart` here is a browser reload (current/legacy/corrupt storage) only; the backend-restart part is `blocked` per row.
- Chart canvas pixels are not read; chart presentation is checked through its DOM controls, legends, tooltips and accessible alternatives.
