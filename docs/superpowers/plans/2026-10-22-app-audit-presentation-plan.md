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
- Store-seeded states (scan results for Steps 4–7, portfolio rows, watchlist, legacy shapes) are written to `localStorage` through `context.addInitScript` **before** the app loads, using the real persisted keys listed in `CLAUDE.md` (for example `'bamendjou-scan-store'`, `'bamendjou-portfolio-v1'`, `'bamendjou:theme'`). The seeded bytes are recorded per observation. Seeds are synthetic and live only in the isolated browser context.
- A `blocked-unmatched` request during a capture is not silently ignored: T5 lists each one and states whether it left a surface in a loading/failed state that the observation then reports as such.

## 4. What is captured

### 4.1 State families (the inventory's nine state keys)

For each URL page, rail slot and boundary, the harness runs the state families below. A family that cannot apply to a route is recorded as `N/A` with a source-backed reason (for example: `/screener/step-5-strategy` is a redirect, so it has only a redirect observation).

| Key | How it is produced |
|---|---|
| `normal` | Populated deterministic fixtures and seeds; default settings. |
| `expanded-nested` | From `normal`, open every disclosure the route offers: `<details>`, `aria-expanded` toggles, dialogs, drawers, popovers, tooltips (hover **and** keyboard focus), row selections, tabs; ≥2 distinct rows where rows repeat. Each opened state is its own observation with the action path that produced it. |
| `empty` | Fixtures returning empty collections; no seeds. |
| `loading` | Fixture handlers held unresolved until the capture completes. |
| `failed` | Fixture handlers returning HTTP 500 with a JSON error body, and separately a network abort, for the route's primary request(s). Cancelled scans where a cancel control exists. |
| `legacy` | Seeds in older persisted shapes the stores' `migrate()` accepts, and legacy saved-report records where the report inspector reads them. |
| `zero-null` | Fixtures with `0`, `null` and absent fields on displayed numeric values, to check that "unavailable" is not shown as `0` (and vice versa). |
| `stale-async` | Where a route issues a re-fetch on control change, the earlier response is released after the later one; the observation records what is shown. Routes without such a re-fetch are `N/A` with reason. Correctness of which value wins belongs to the domain lane; J records only what is presented and whether it is labelled. |
| `post-reload` | `page.reload()` after `normal` (and after `expanded-nested` where a disclosure state is persisted), recording what is restored. |

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
- **C3 Unavailable vs zero.** In `zero-null` fixtures, each field set to `null`/absent must not render as `0`, `0%` or `$0`, and each field set to `0` must not render as `—`/`n/a`. Field-by-field expected/actual pairs are recorded.
- **C4 Bounded raw data.** Raw JSON / evidence disclosures (`RawEvidence`, `LegacyReport`, `UnsavedReport`, report inspector) are explicitly opened by the user, bounded (scroll container or truncation with a stated total), and not the only place a value is readable.
- **C5 Overflow and layout.** Horizontal page scroll (`scrollWidth > clientWidth` on the scrolling element); elements whose text is clipped (`scrollWidth > clientWidth` with `overflow: hidden` or `text-overflow: ellipsis`) and have no accessible full value (`title`, `aria-label`, tooltip); interactive elements overlapping another interactive element's box; content outside the viewport horizontally.
- **C6 Contrast and accessible names.** `axe-core` (from `frontend/node_modules`) with `wcag2a`, `wcag2aa` and `wcag21aa` tags, per observation, both themes. Each violation records rule, node selector, and contrast ratio where applicable. Additionally Playwright's `ariaSnapshot()` of `body` is stored, so every interactive element's computed role and name is in the evidence.
- **C7 Fiber census.** A walk of `__reactFiber$*` from every DOM node collecting component names (`type.displayName || type.name`, unwrapping `memo`/`forwardRef`). This is how definitions are tied to observations (§5).
- **C8 Screenshot.** Full-page PNG; its SHA-256 is stored for every observation. Only screenshots cited by a finding are committed (cropped where possible), to keep the repository small; every other screenshot is reproducible from the harness and recorded by hash. Screenshots are never the only evidence for a result.

### 4.4 Keyboard-only traversal, one procedure per interaction family

Run with the mouse never used after page load. Families (source census at the frozen SHA): dialogs (`role="dialog"` in 14 files, e.g. `ConfirmDialog`, `SaveProfileDialog`, `RenameProfileDialog`, `SendToBrokerDialog`, `StockSendDialog`, `CompositeAlertDialog`, `JournalEntryForm`, `TextInputPopover`, `ChartClickPopover`); drawers (`EditDrawer`, `ClosePositionDrawer`, `PipelineInspector`, `SavedScanReportInspector`); `aria-expanded` toggles (13 files incl. `CollapsibleSection`, `ContractExplanationToggle`, `ConfigHealthChip`); `<details>` disclosures (22 files); tabs (`role="tab"`: watchlist, Step 2, `JournalEntryForm`); switches and radio groups (settings, alerts, `EditDrawer`, `MethodPickSelector`); tooltips (`Tooltip`, Step 5 contract); selectable table rows (`TableRow`, `QuickLookRow`, `JournalEntryTable`); global shortcuts (`KeyboardShortcuts`: `1`–`7`, `g`+letter, `?`; `StepNavBar` ←/→); chart canvas interactions (`ChartWorkspace`, `ChartTopBar`, `ChartRightPanel`); native form controls (`select`, checkboxes, inputs).

For each family, on at least one route where it occurs (every route where it is cheap), record:
- **K1 Reach:** Tab from the document start; the ordered list of focused elements (role, name, bounding box). Every interactive element in the ariaSnapshot must be reached, or the gap is a finding. Elements with click handlers but no keyboard route (found via fiber props `onClick` on non-interactive host elements without `tabIndex`) are listed.
- **K2 Visible focus:** for each focus stop, computed `outline`/`box-shadow` differs from the unfocused state, and the element is inside the viewport (scrolled into view).
- **K3 Operate:** Enter/Space (and arrows for tabs/radios/sliders) performs the action; the resulting state is captured as an `expanded-nested` observation.
- **K4 Escape and return:** dialogs, drawers and popovers close on Escape; focus returns to the opening control; modal dialogs keep Tab within themselves while open.
- **K5 Shortcuts:** global shortcuts do not fire while typing in inputs (the documented `isEditable` guard) and do fire otherwise.
- **K6 Chart canvas:** whether chart information has a keyboard/readable alternative; absence is recorded as a finding candidate, not assumed acceptable.

## 5. Coverage contract against the Lane A inventory

Source of rows: `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/inventory.json` (45 route entries, 283 definitions, 2,269 route-instance rows, 20,421 component state IDs) plus `supplemental-capability-contracts.json` (77 capability states, 198 route/state requirements). T5 writes `reconciliation.json` with **one disposition per row at each level**, and `verify-coverage.cjs` checks that no ID is missing, duplicated or unknown.

Disposition vocabulary (exactly one per row):
- `observed` — the definition (via C7 name match restricted to definitions reachable on that route per `route_instances`) or route entry was present in ≥1 observation of that route **and** state; lists the observation IDs and the checks that ran. Means "presented and inspected", never "numbers correct".
- `finding` — as `observed`, plus the defect ID(s) it carries.
- `not-triggered` — the route/state was executed but the definition did not render; states the condition from Lane A's semantic entry contract that the fixture did not satisfy.
- `na` — the state cannot apply (source-backed reason).
- `blocked` — cannot be executed in this lane (reason: needs a live backend/broker/websocket, private crash route, real restart, etc.), with the owning lane.

Name ambiguity: where several reachable definitions on one route share a name (inventory has `Row` ×4, `SortBtn` ×3, `CalendarIcon` ×3, …), all candidates get `observed-ambiguous`, which counts as `observed` only together with a manual source note naming the rendering caller; otherwise it is `not-triggered`. `component_files_not_reached` (4 files) and `/__test-crash` (private folder) are `blocked` with Lane A's existing disposition cited. The verifier fails if any row is uncategorised or if any `observed` row cites an observation that does not exist.

Rows added to Lane A's inventory after the frozen inventory commit are reconciled the same way before closure: T5 diffs `inventory.json` at the frozen SHA against `origin/main` at PR time and dispositions every added ID.

## 6. Findings

Each presentation defect in `defects.json` has: ID `J-NNN`, title, route(s), state/viewport/theme, reproduction (harness command + observation ID), expected, actual, affected SHA, severity class (`blocks-use` / `misleading` / `degraded` / `cosmetic`), related existing issue (searched by title/route before filing), owning remediation lane (J for presentation; domain lane for numbers), evidence paths, regression check to use on retest, retest status `unfixed`. Numbers/persistence observations go into a separate `handoffs.json` with the owning lane; J files no numeric verdicts.

Filing: the coordinator (not the implementers) files one GitHub issue per confirmed defect with the template in `docs/agents/board.md`, labels `board-item`, `priority:app-audit`, one `size:*`, one `complexity:*` with rationale (per `docs/agents/task-ratings.md`), links it as a sub-issue of #358, and records native blocked-by edges only where two fixes touch the same source file. Defects that duplicate an open issue are added as a comment on that issue instead. Filing does not add them to the Board's Queue (only Kenneth edits the Board body); the coordinator lists them in a Board comment.

## 7. Tickets (build units; sub-issues of #358)

All tickets: write only inside the lane directory; run nothing against a backend; commit with message `docs(audit): APP-AUDIT-PRESENTATION <ticket summary>`; never edit `PROJECT_STATE.json` audit fields.

**T1 — Harness and provenance.** `harness/` with: build/start/stop scripts; `run.cjs` (context, routing, WebSocket close, clock, seeding, matrix loop, per-observation capture C1–C8, axe injection from `node_modules/axe-core/axe.min.js`); `fixtures/` registry keyed by route × state family; `provenance.json`. Output layout `evidence/<route-slug>/<state>/<viewport>-<theme>[-<density>].json` plus `index.json`. **Acceptance:** a smoke run of `/dashboard` and `/settings` in `normal` at 1280 dark produces observations with non-empty C1, C6 and C7 (C7 ≥ 20 names on `/dashboard`), zero requests reaching a non-local host, and `provenance.json` complete. `node harness/self-test.cjs` checks: (a) an unmatched request is aborted and logged, (b) a WebSocket is closed, (c) a 500 fixture is served when the failed family is selected.

**T2 — Screener captures.** Fixtures and runs for `/screener` (redirect), Steps 1–3 (all three modes where the step varies by mode), Options Steps 4-ranking → 5 → 6 → 7 trade card, Stocks Steps 4-stocks → 6-backtest → 7-position-card, Pre-Breakout Step 4 with sub-modes `prebreakout` / `pullback` / `fib`, the `/screener/step-5-strategy` redirect, and the screener and Step 7 `@contextRail` slots; every state family in §4.1 and the matrix in §4.2. **Acceptance:** every screener route entry has observations or a recorded `N/A`/`blocked` per state family; expanded-nested covers every `<details>`/`aria-expanded`/dialog/drawer found on these routes by a DOM query, with ≥2 rows where rows repeat.

**T3 — Non-screener captures.** Same for `/dashboard`, `/portfolio` (incl. `EditDrawer`, `ClosePositionDrawer`), `/watchlist` (Stocks/Contracts tabs), `/alerts`, `/strategy-watch`, `/analysis`, `/chart`, `/chart/standalone`, `/calendar`, `/journal`, `/validation`, `/settings` (each of the 9 sections), `/dev/components`, the root redirect, `not-found`, the Frame `error.tsx` boundary (malformed fixture then Retry, as Lane A did) and `loading.tsx`, and the remaining rail slots and fallbacks. **Acceptance:** as T2 for these routes.

**T4 — Keyboard traversal.** `harness/keyboard.cjs` implementing K1–K6 for every family in §4.4, both themes at minimum width (focus visibility differs by theme). **Acceptance:** each family has ≥1 executed procedure with per-step records; every K-check outcome is pass, finding-candidate, or blocked-with-reason.

**T5 — Triage, reconciliation, report.** Triage every C1/C5/C6/K detector candidate into `finding` or `not-a-finding` with a one-line reason (`triage.json`); write `defects.json`, `handoffs.json`, `reconciliation.json`, `verify-coverage.cjs`, `report.md`, `README.md` (reproduction commands). Report separates **presentation verdicts** from **numbers/persistence observations**, lists every `blocked`/`N/A` with reason, and states limitations (§9). **Acceptance:** `node verify-coverage.cjs` passes; every defect has all §6 fields; report counts are produced by the verifier, not typed.

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
- Real backend/database restart belongs to Lane I; `post-reload` here is a browser reload only.
- Chart canvas pixels are not read; chart presentation is checked through its DOM controls, legends, tooltips and accessible alternatives.
