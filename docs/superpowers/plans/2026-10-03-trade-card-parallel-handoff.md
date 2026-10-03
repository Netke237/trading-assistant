# Trade card presentation — new-session parallel handoff

Read `docs/superpowers/PROJECT_STATE.json` → `trade_card_presentation` and the matching `task_backlog.items` entries for canonical status, dependencies, ownership and audit results. This document defines work boundaries, not a second status ledger. Implementation is requested for new sessions; this documentation session does not implement the application.

## Read first in every new session

1. `AGENTS.md`; run `python3 scripts/state.py` and `python3 scripts/claim.py`.
2. Canonical `trade_card_presentation` entry and your task ID under `task_backlog.items` in PROJECT_STATE.json. The live claims ledger is the authority for active workers; a backlog entry saying not_started is not permission to ignore an active claim.
3. `2026-10-03-trade-card-presentation-plan.md` and its plan audit record. Original seven-slice implementation requirements remain binding. This parallel handoff changes work scheduling/file ownership only. This newer handoff supersedes the older plan's blanket sequential instruction for the explicitly disjoint tasks below; all shared-file integration remains serial.
4. Approved preview and 520-entry information mapping under `docs/superpowers/specs/2026-10-03-trade-card-presentation/`. The preview is a design reference, not production code. Its fabricated sample state / reference values / local demo callbacks must never be copied into calculations, persisted data or broker actions.
5. Claim exactly your implementation task ID via `python3 scripts/claim.py take TASK-ID -m '...'` on your isolated feature branch. Never take --force or change another task's ownership. Check dependencies have actually landed in your checkout, code-audited clean; a remote claim disappearing or a plan audit does not prove code completion. Renew before expiry and release when done.

If a dependency is not available, or a shared-file change is required outside your allowance, stop the dependent edit, record the concrete blocker and coordinate with the owning session. Continue independent scoped work where possible. Do not expand ownership silently. No automatic deployment, main merge or broker actions.

## Disjoint workstreams and external ownership clearance

### TRADE-CARD-UI-CORE — main card presentation

Before starting, clear the overlapping live TRADING-REVIEW-FIXES claim: its plan edits Step-7 page and related guards. Verify its relevant audited changes have landed in your checkout and the owner released the overlap, or obtain an explicit documented disjoint boundary/ownership transfer. The existing TRADING-REVIEW-FIXES-A shipped flag is not sufficient: its note records an open unmerged PR. CORE can run alongside the two leaf tasks after this gate is satisfied, not automatically today.

Own only:
- `frontend/components/organisms/TradeCard/**` including its CSS/tests.
- `frontend/app/(frame)/screener/step-7-trade-card/**` including page/direct-order tests; presentation edits only, no directOrder behaviour change.
- New task-specific presentation components under `frontend/components/molecules/TradeCardPresentation/**` if needed.

Build handling hierarchy, latest-result display, method cards and dedicated probability/time column spacing; expose the existing MaxLossOverrideEditor directly. Work in small audited checkpoints corresponding to original slices 3, 4 and the local parts of 2/7. Preserve all TradeCard hooks, refs, state, units, callbacks, request guards, touched/edited overlays, lastRunMethod/methodPick distinction and every send/auto-trade behaviour.

Do not modify MarketSentiment, FundamentalHealthCard, BarrierRaceCard, ScoreCardPanel, MethodPickSelector, shared types/helpers, backend or the parallel context route. Until other task interfaces land, leave the current component calls intact and do not pass nonexistent compact/selection/evidence props. Top placement, leaf composition, side-panel wiring and new race shortcut are final integration work. This task may retain temporarily old leaf layout; no claim that the whole redesign is finished.

### TRADE-CARD-CONTEXT-CARDS — compact market and fundamentals

Own only `frontend/components/molecules/MarketSentiment/**` and `frontend/components/molecules/FundamentalHealthCard/**`, including focused tests in those directories.

Provide an optional `compact?: boolean` prop, default false, preserving all existing shared callers. Compact mode uses slim wrapping layout, with every original value, interpretation, tooltip/definition, statistics and safety flag reachable. Active safety flags stay visible. Use existing theme tokens; no new numeric scoring or API fetching. A disclosure is presentational and does not suppress no-data states or warnings.

Do not relocate cards in page/TradeCard or change source data. Final integrator passes compact and performs placement: Market Sentiment immediately beneath How this page works; Fundamental Health immediately beneath stock/option identity. API contract is the same optional boolean on both components; if impossible without further shared edits, coordinate rather than inventing a different interface.

### TRADE-CARD-BARRIER-PRESENTATION — standalone race table

Own only `frontend/components/organisms/BarrierRaceCard/**` including CSS/tests.

Reorganise existing outputs so probability shares, conditional target time, stock R:R and edge/contract appear together. Keep original formatter helpers and all current props/early-return guards, allocated weights, independent invalidation statistic, full arithmetic and warnings. Other medians and long explanations expand inline. The table is bounded by the actual available card width; essential outcomes/actions must not be clipped.

Do not modify TradeCard, MethodPickSelector, lib/barrierRace, shared types, prices, calculations or status logic. Keep the current component API unchanged for this independently landable task; no selectable shortcut yet. The final integrator can add an optional controlled selection callback in a separately audited diff, wired to the same existing methodPickOptions and guarded availability path.

## Dependent tasks — do not launch competing evidence implementations

### TRADE-CARD-SCORE-EVIDENCE

Before editing, coordinate with `OPTIONS-CONTRACT-EXPLANATIONS`, whose active implementation owns contract_validator, schemas/__init__, routers/contracts, domain.ts, contractExplanation helper/molecule and potentially statusTooltips. Also inspect OPTIONS-VOL-EVENTS-EXPLANATIONS for shared threshold/status files. The live claim is not permission for this task to bypass that owner.

Also clear the overlapping TRADING-REVIEW-FIXES owner on stock_scorer, scan and schemas; verify relevant landed changes or a documented ownership transfer. Start this task only after the contract explanation implementation has landed code-audited clean and its contract/types are available in the checkout, or after an explicit documented ownership transfer. Reuse its authoritative contract explanation metadata; do not invent a second structure or scorer. Then add only missing stock scan evidence and necessary Step-7 propagation/legacy absence handling from original Slice 1. Baseline numbers and gate outputs must remain unchanged.

Owned after dependency clearance: `backend/app/scoring/stock_scorer.py`, `backend/app/routers/scan.py`, `backend/app/schemas/__init__.py`, `frontend/types/domain.ts`, `frontend/lib/tradeCardOverride.ts`, `frontend/lib/scanStore.ts`, and named score/scan/override tests. Extensions into contract_validator or routers/contracts require explicit coordination with the existing task owner and an amended audited scope; they are not automatically allowed. Do not edit TradeCard render code.

Missing optional evidence on old cards is honest not-captured state, not guessed default weights. Stock/contract rule metadata must stay paired with their own authoritative results through overrides, persistence and recompute. Contract changes must not inherit the prior contract evidence. Keep numerical parity, server rounding, rejection/caps and fill/order paths unchanged. Python 3.11 for backend checks.

### TRADE-CARD-QUALIFICATION-PRESENTATION

Requires TRADE-CARD-SCORE-EVIDENCE landed code-audited clean. Own only `frontend/components/molecules/ScoreCardPanel/**`, new `frontend/components/molecules/TradeCardQualification/**`, and task-specific pure presentation helpers/tests under `frontend/lib/tradeCardQualification*`.

Build an optional presentation variant/controlled display of the evidence contract actually delivered by the prior task, preserving default shared callers. Preserve existing factor observations, factor/status colours, total, numeric confidence, badge tooltip and confidenceText. Add Backtested setup confidence wording with visible historical/payoff explanation; retain sample counts/no-history when supplied. Read authoritative evidence rather than recomputing scores or substituting YAML defaults. Missing evidence is explicit and no new gate is added.

No edits to TradeCard, page, domain.ts, statusTooltips, existing ContractScoreExplanation, backend or context route. Final integrator wires the controlled presentation; this task must typecheck without nonexistent caller changes.

### TRADE-CARD-PRESENTATION-INTEGRATION

Requires all five internal implementation tasks plus the external contract explanation dependency landed code-audited clean in the integration checkout, all task claims released/transferred, and dependency interface verification. Sole owner of final composition across those files; ownership starts only after prior workers finish. Original slices 2/5/6/7 integration obligations still apply.

Place compact top cards once, complete stock/option identity, wire exact score evidence/qualification, compose one method selector and one execution panel, add the optional race-selection shortcut without changing price spaces or stop semantics. Preserve parallel checklist's existing evaluator and provider, statuses and independent warnings; do not duplicate comparator code or create two TradeCard/control instances for desktop/laptop. Integrate leaf task APIs only after reading their audited diffs. No shared store/API/scorer rewrites for layout.

Do complete source/state-based reconciliation of 520 information entries, correcting inventory errors where found. All information and controls retained, active refusals visible, broker/tracking/arm/save payloads baseline-equivalent, direction/gate colours unchanged. Check light/dark and actual frame widths at 1200/1366/1440/1920, expiry/refusal, legacy, contract switches, race stock/premium-only changes, overrides, spread and alternatives. Full frontend/typecheck/build and relevant backend parity once after integration; independent code audit before shipping readiness.

## State updates and concurrency rules

The JSON entry declares dependencies, allowlists, excluded shared owners and original slice mapping. Do not change globally unrelated active_phase, main history, existing audit counters or external task states to make this target appear active/completed.

PROJECT_STATE.json and this handoff are shared coordination files, never free parallel write targets. Every state edit for these tasks takes a short-lived `TRADE-CARD-PRESENTATION-STATE` claim, fetches latest canonical documentation branch/merged main, applies only its own entry delta, checks for intervening updates and verifies state. If another session owns the lock, report completion evidence to it; do not push a full stale state snapshot. Branch state edits must be reconciled by the final integrator against current canonical JSON, not accepted wholesale. The claims lock governs participating trade-card sessions; unrelated owners may also modify state, so a lock alone does not eliminate the need to rebase/reconcile.

During implementation report exact commit, allowlist diff, meaningful checks and independent code-review evidence in your task-specific work log under `docs/superpowers/plans/trade-card-worklogs/TASK-ID.md`. This is session event evidence, not a second canonical status. No status/audit-clean claim without reviewer/diff evidence. Plan audit is not code audit. Keep maximum three rounds per stage; zero findings closes that stage.

Original implementation plan was independently audited by Bernoulli. This changed concurrency/ownership handoff and its JSON entries require their own independent review before declaring parallel handoff ready. Original audit counters remain separate; do not reuse them for this new scope.

## New-session launch text

Two fresh sessions can start together after the handoff audit: TRADE-CARD-CONTEXT-CARDS and TRADE-CARD-BARRIER-PRESENTATION. A third session, TRADE-CARD-UI-CORE, may join after its external trading-review ownership gate is cleared. Later task launch IDs and dependency status are in canonical JSON.

Paste this with TASK-ID replaced:

> Implement TASK-ID from docs/superpowers/PROJECT_STATE.json trade_card_presentation/task_backlog. Read AGENTS.md and docs/superpowers/plans/2026-10-03-trade-card-parallel-handoff.md, then the audited presentation plan and approved design/mapping. Fetch latest origin/main and start your own implementation branch from it; all handoff documents are published there. Check live claims and claim only this task. Work only inside its allowlist; preserve all information, calculations, units, persistence and existing gate/direction colours. Honour dependencies and shared file owners. Perform targeted checks and a fresh independent adversarial code audit within the repository cap; report exact commits and evidence. Do not deploy, merge main or place orders. Update only your own canonical task entry through the shared-state lock and reconcile latest JSON.

## Publication destination

User directed that all implementation documents be on origin/main. Start fresh sessions from latest origin/main. The earlier codex/trade-card-parallel-handoff branch is a historical publication branch, not a required launch base. Ownership, live-claim checks, external gates and audit requirements remain unchanged.
