# APP-AUDIT-PRESENTATION-ATTRIBUTION — J1 tooling plan

**Phase id:** `APP-AUDIT-PRESENTATION-ATTRIBUTION` · parent #358 `APP-AUDIT-PRESENTATION` (Lane J).
**Decision:** the untagged recommendation-A answer on #358, accepted after its `needs-kenneth` label was cleared: separate attribution tooling J1 from presentation execution J2.
**Status:** draft; no build tickets or implementation until a fresh independent plan round is clean.
**Estimate:** L (8–16 engineer-hours), complexity 4. This phase proves a conservative attribution/verifier contract on a few routes, not whole-app usability.

## 1. Scope and inherited history

Build the source maps, production-browser census and reconciliation verifier that J2 can use without claiming coverage that the observations do not establish. The old `2026-10-22-app-audit-presentation-plan.md` remains historical context. Its plan rounds (6, 5, 2 gate findings) remain capped at three and not clean. J1 is the explicitly approved new tooling phase with its own plan/code stages (maximum three each); it does not turn the old round-3 fixes into audited work. J2 needs its own plan and reviews after J1. #358 remains open until J2 acceptance is met.

Write only:

- this plan;
- `docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/**` (abbreviated `J1/` below);
- the coordinator's own J1 state/audit record in `PROJECT_STATE.json`.

No application code, dependencies/lockfiles, shared Lane A inventory, frontend e2e fixtures, backend, live data, settings or database changes. J1 runs a local production frontend with synthetic responses and isolated browser storage. It does not certify UI values, keyboard accessibility, contrast, any complete route/state matrix, or arithmetic/persistence. Samples carry `purpose: tooling-self-test`, never a J2 coverage result.

## 2. Freeze source and deterministic inputs

Application baseline: `4a74d186468afe0a7fc4c53e785b24b5c1f72b42` (current merged main when drafting this split). Source analysis reads that commit using `git show`, not whatever files happen to be in a dirty checkout. For browser smoke, export a fresh isolated tree with `git archive <frozen-SHA>` into a new temporary directory, then build and serve only its `frontend/`. Do not copy source/config files or build output from the working checkout. Link only the installed `frontend/node_modules` dependency directory after checking the exported lockfile matches the dependency source lockfile; record that dependency reuse. Verify the exported source tree against the frozen file manifest before building. Extra source/config files (including ignored or untracked files) are forbidden; only generated Next build outputs and the explicit dependency link are allowed. A mismatch stops the run. The harness must never serve the working checkout or a previous build. A shadow-module regression creates an untracked higher-precedence `components/KeyboardShortcuts/index.ts` in a synthetic working tree and proves it cannot enter the exported build tree or alter the frozen resolver result. Record the source SHA, actual Node/Next/React/Playwright/Chromium versions and executable, build command/flags, lockfile hash, per-input SHA-256, fixture hashes and timezone `Europe/Berlin` in `provenance.json`. Record Python 3.11 availability for programme provenance; do not run backend code.

Inventory inputs from that SHA:

- `APP-AUDIT-INVENTORY/inventory.json`;
- `APP-AUDIT-INVENTORY/supplemental-capability-contracts.json`;
- `frontend/tsconfig.json`, relevant TS/TSX sources and `frontend/lib/api.ts`.

The inventory was generated at `00b4ab54…`; it is not silently regenerated against newer code. Preserve its IDs. For every used source span, resolve the named declaration/native in current frozen source and store its current location plus hash. Missing, changed or ambiguous resolution becomes `unresolved-source`, with no verified credit. Generate a separate list of current route-entry files absent from inventory; do not invent historical inventory IDs. An inventory source hash mismatch alone does not make a current span valid: the resolver must find the declaration/signature uniquely or mark it unresolved.

Use the already installed TypeScript compiler API through the frontend package resolution path. No additional dependencies. Repeated generation with identical frozen inputs must produce byte-identical JSON (sorted keys/arrays, no wall-clock timestamps in generated maps).

## 3. Minimal tooling and data contract

`J1/harness/` contains CommonJS scripts and Node built-in `node:test` tests; frontend TypeScript/Playwright are loaded by explicit paths under `frontend/node_modules`.

### A. Source classification and authorship (`source-map.cjs`)

Read the frozen TS program, respecting aliases/re-exports. Type-only imports are not runtime edges. An unresolved runtime edge is recorded, never treated as proof that a module is server-only. The client-module set starts at parsed directive prologues containing `use client`, then follows resolved runtime imports/re-exports. Compute a server traversal from route entries, stopping when it crosses an explicit client boundary. Keep both classifications: being client-importable does not prove a particular JSX invocation ran on the client.

Emit `source-map.json` with input hashes and, for every inventory definition/route instance/native:

- resolved source declaration/span, or an explicit resolution failure;
- module-set membership and supporting import edges;
- JSX callsites and their execution-environment candidates (`client`, `server`, `mixed-or-unresolved`), including source-backed reasons; arbitrary prop/children data flow is unresolved;
- native authoring definition from lexical AST containment, ordered ancestor custom-component callsites, literal tag/attributes/text signature and dynamic/conditional attributes;
- signature collision groups within a route (never disambiguated by DOM order or count).

This is a candidate map, not a runtime result. For mixed modules such as `ContextRail`, retain per-callsite treatment. Its server-rendered `<aside>` must not be reported missing just because no fiber exists. A host marker is eligible only with a source-backed selector/signature unique within the relevant rendered route and visible/connected evidence. Generic `aside`, `section` or text shared with another definition is insufficient. Unproven markers remain unresolved/asserted.

Lexical ownership is not a DOM ownership proof. A native passed through `TableRow`/`SectionCard`/`RailSection` children is tagged `children-slot`; a descendant's own JSX is tagged with that descendant. J1 does not reconstruct arbitrary React prop flow. Such cases can be `observed-asserted` with source/DOM evidence; they cannot become verified merely because a matching node is inside the nearest ancestor fiber. Each observed DOM node can credit at most one native. Duplicate inventory signatures stay `observed-ambiguous`, even when multiple matching nodes render.

### B. Target candidates (`target-map.cjs`)

Emit `target-map.json`, per resolved definition (not all definitions in the same file), with AST source spans for direct API member calls and store reads. Resolve `api` bindings to literal HTTP method/path definitions in `frontend/lib/api.ts`; retain parameterized paths as patterns with their argument expression. Resolve direct imported store hooks/getState calls to their persisted `name`, including resolvable string constants. Shadowing, computed members, aliases that cannot be followed unambiguously, calls in unrelated nested definitions, parent-supplied props, and dynamic storage names are explicit unsupported entries. Never infer a direct call from a transitive module import.

This map establishes potential input association only. A request or seed occurring is not proof that a component entered `empty`, `loading`, `failed`, `legacy` or another state. A verified state needs the additional predicate below. Unsupported targets remain asserted/not-run; generation does not fail merely because the application contains unsupported syntax.

### C. Live census and small capture (`census.cjs`, `smoke.cjs`)

Build with the supported production `next build --no-mangling` command and start a local Next server on a recorded unused loopback port. Verify the flag exists before running; unavailable tooling is a blocker, not a substituted dev build. Use Playwright Chromium, block service workers, close every WebSocket before connecting. Route all requests: only same-origin frontend asset/document GET/HEAD traffic continues; matched API fixtures are fulfilled locally with recorded bytes; everything else (including unsafe methods) aborts and is logged. Routes are installed before navigation. Do not reuse a user's browser/profile/storage.

Capture `/dashboard` and `/settings` at 1280×800, dark theme, normal state only, plus one existing dialog open/close sequence reachable with synthetic data. Use fixtures under `J1/fixtures/` only. No keyboard/contrast/full audit acceptance is implied. Each sample records final URL, route entry, source/input hashes, fixture response log, storage seeds/readback, visible text/DOM references, census and a fixed `purpose: tooling-self-test`. A same-tab reload smoke proves seed-once behavior: initial seed, overwrite by page test code, reload, read back overwritten value. `sessionStorage` guard prevents reseeding.

Census: reach a host root from a connected node, then traverse `HostRoot.stateNode.current`, not the stale alternate reached from that node. Walk child/sibling links including renderless components. Record only connected host nodes, with stable per-observation opaque node IDs. Names unwrap memo/forwardRef where available; missing/lazy/unresolved names are recorded as unresolved. Do not serialize function props, tokens, arbitrary React state or full storage unrelated to these synthetic seeds. Match names only against route candidates; collisions remain ambiguous. Unsupported React internals fail the census explicitly and cannot yield a clean sample.

Tests must prove renderless `KeyboardShortcuts` is present on dashboard; opening then closing the chosen dialog removes its mounted definition from the current-tree census; a disconnected node and a stale alternate cannot credit a native. Synthetic fiber unit fixtures cover current/alternate selection, memo/forwardRef, no-DOM components and duplicate names. The real-browser check is required in addition to these fixtures.

### D. Expansion and fail-closed verifier (`verify-coverage.cjs`)

Export reusable pure expansion/validation functions and a CLI. Recompute route-entry/definition/component-instance/component-state/native-instance/native-state IDs from inventory joins and the exact state template. Read supplemental capability/state/route-state IDs from their own tables; preserve their distinct ID syntax and keys outside the nine. Reject duplicate or missing source IDs, invalid joins, inconsistent recorded counts and duplicate/unknown/missing reconciliation rows. Never paste the historical counts into implementation as expected constants. Unit tests use an independent small hand-written inventory with explicitly enumerated expected IDs; a full-input test cross-checks the real input's declared counts.

Every row has exactly one base disposition: `observed-verified`, `observed-asserted`, `observed-ambiguous`, `rendered-untargeted`, `not-triggered`, `not-run`, `na` or `blocked`. Findings are attached IDs with an underlying disposition, never a second row that double-counts coverage. Unexecuted rows default to `not-run` with a reason. `not-triggered` requires proof that the exact route/state scenario actually ran; `na` needs a source-backed reason. J1's smoke report lists these counts as **tooling samples only**, with zero whole-app coverage claim.

For any positive disposition, verify referenced artifacts exist, their hashes match, and source SHA, inventory hash, exact route entry (including slot/boundary identity), scenario, state key and row identity agree. A URL alone cannot identify a parallel-slot or error/loading entry; without explicit entry evidence those rows remain unverified. Reject unknown evidence reference fields/disposition values and malformed IDs; resolve only paths within the supplied evidence root (no absolute or traversal paths).

For `observed-verified`, additionally require a unique source/runtime identity tie and a registered, independently tested predicate. Initial predicate support is deliberately small:

1. `normal` client definition: unique route-reachable name in the current census, with a source-backed runtime identity adapter (module/export mapping or a uniquely tested host/output signature; bare name equality is insufficient), proves **mounted**, not “correct UI.” Host/native presence additionally needs visible connected DOM and an unambiguous authored signature with no unresolved children-slot attribution.
2. `normal` server definition: a reviewed source marker adapter with exact source span and unique visible host evidence; no census requirement. If no such adapter is proven, downgrade to asserted, never absence.
3. All non-normal and supplemental state predicates are initially unsupported for verified credit. Any attempt to mark them verified fails with `unsupported-state-predicate`. They may be asserted with actual scenario/action/target evidence and nonempty explanation, or remain not-run. J2 can add a narrowly specified predicate only with tests and independent review before using it. Presence plus a matching request/seed is explicitly insufficient.

Assertion validation checks actual evidence references, route/scenario/state match and a nonempty source/DOM explanation; it does not certify the assertion's truth. Ambiguity can be manually described as asserted, never upgraded to verified by prose. Summary output always separates verified ties, assertions, ambiguities and all non-covered rows. It prints no “all checked”, pass rate or presentation verdict. Full J2 presentation acceptance still requires actual observations and triage, not successful JSON validation.

## 4. Build units (cut child tickets only after clean plan audit)

All implementers read the gate and this plan, change only their listed J1 files, write meaningful tests first, and report RED/GREEN. The coordinator owns state, issues, claims and audits. No ticket is an independent audit target.

1. **Source maps:** `source-map.cjs`, `target-map.cjs`, their Node tests and small synthetic TS fixtures. Prove directive parsing through comments; alias/barrel and type-only handling; mixed server/client ContextRail callsites; lexical children ownership; duplicate native signatures; per-definition direct calls and unresolved dynamic API/store cases. Generate maps reproducibly against frozen real inputs. Unsupported cases are explicit output, not omissions.
2. **Census and smoke:** `census.cjs`, `smoke.cjs`, synthetic response/seed fixtures, Node tests and small browser self-test records. Acceptance: the two routes and dialog lifecycle checks above; no request to a backend/non-local host; unmatched HTTP and WebSocket abort tests; seed-once reload proof; provenance/input verification and untracked shadow-module exclusion test. Missing browser/build capability blocks this unit.
3. **Verifier and handoff:** `verify-coverage.cjs`, tests, `README.md`, `tooling-report.json`/`.md` and generated maps. Mutation tests remove/duplicate/add IDs, forge route/state/hash/source, reuse a node for two natives, claim a colliding/children-slot native verified, forge server absence, assert unsupported verified state, cite another scenario/slot, and corrupt artifact paths. Each must fail. Valid verified/ asserted/ambiguous examples remain distinctly counted. A complete all-not-run reconciliation is valid but reports zero verified/checked UI results. Document exact commands and unsupported cases for J2.

Sequence 1 → 2 → 3; each uses a fresh implementer. Tests should expose false attribution/false coverage, not merely mirror implementation functions. Full frontend typecheck and Jest suite run per repository ticket contract; backend tests are N/A because no backend source executes or changes. No application numerical pins are regenerated. Changes noticed outside scope are reported, not fixed.

## 5. Independent gates and completion

Apply `.claude/skills/K-adversarial-audit-loop/SKILL.md`; every round uses a fresh independent auditor applying `.claude/skills/bmad-review-adversarial-general/SKILL.md`. In addition to the repository numeric/persistence gate, this evidence tooling's concrete gate is a wrong coverage number/verdict: crediting an unobserved row, wrong route/state/source attribution, reporting asserted as verified, claiming an unrun check, or exposing a path to modifying shared/persisted application data. Style/wording is not a gate. Record exact scope/head, reviewer, findings, fixes and unresolved items.

Plan stage: full J1 plan round 1, then previous fixes/interactions only; at most three. Code stage: after all units, merge current main, rerun J1 tests/browser smoke, frontend typecheck/Jest and state check; full integrated diff round 1, then fixes/interactions only; at most three. A nonclean cap stops work and leaves `audit_clean: false`. Old parent rounds remain intact. Changes to the frozen application baseline or verifier predicates require new affected evidence and appropriate remaining independent review, never silent relabeling.

Milestones: 10% draft; 20% independently approved plan; 50% maps plus actual smoke evidence; 70% all tooling checks and handoff; 85% independent code audit clean; 95% exact PR head CI green/mergeable; 100% merged under board self-merge conditions. Tooling completion unblocks preparation/execution of J2; it never closes #358 or #359. J2 must freeze its own source, reconcile any inventory drift, retain unsupported cases honestly and perform the presentation audit under its separate approved plan.
