# STOCKS-STEP-MERGE-S2 — approval draft

Baseline: origin/main `6b1ee21d7d692b691760cb23882a229c58b1a40c`, fetched 2026-10-05. Review against the source snapshot in `/tmp/stocks-s2-baseline`. This is a review artifact, not a local issue tracker. No tickets, phase claim, application edits, or merge are authorized by this draft.

## Preflight and blockers

- Stage 1 PR #42 is merged at `e4d4d80e`; main records S1 as shipped/audit-clean. Keep its six Stocks steps, Step 4 strategy picker and Step 5 redirect. No S2 phase or S2 plan was found in current main. The shared claims ledger reported no active claims at inspection; re-fetch and recheck before publishing/claiming.
- GitHub issue API is denied by the environment proxy. Relevant issues, comments, assignments and possible S2 work cannot yet be checked. This remains a blocking preflight item, not proof that S2 is unimplemented/unclaimed everywhere. No implementation or ticket publication until authenticated issue access works and the duplicate/claim check passes.
- Subsequent main includes server account/risk wiring and daily-risk changes, Phase C PR #55 (bar basis, net backtest/WFO, DAY limits, setup windows, confidence invalidation, PASS-only after-scan execution), PR #68 (options R/R full-premium basis), and PR #69 (Phase C hygiene, including generation-safe backtest-cache invalidation). Preserve the entire current main baseline, not only S1. Backend calculations/API contracts are outside this package.
- User waived the unavailable custom coordinator skill. Use Matt Pocock ask-matt → to-spec → to-tickets with repository ticket-orchestration/audit rules. Existing repository tracker configuration selects GitHub. Grill-with-docs is reserved for genuinely unresolved decisions. Existing decisions Q8–Q12 and this user's preservation list govern this draft; proposed seams and mockup interactions are part of the approval request.

## Problem statement

Stocks currently exposes two results tables and two Position/order implementations. Card edits and after-scan arms live on Strategy and disappear when leaving it. Basket sends use original scan levels even when the trader has edited the full card. This makes the workflow harder to follow and can display a different execution plan from the one saved or sent.

## Solution

Keep Strategy as the merged strategy/scan step. A successful manual scan advances to Backtest; failure stays with the existing readable error. Backtest contains one results table with the union of existing information and optional full-card expansion. Position contains candidate navigation and the same full StockPositionCard. Both expose the same basket. Shared session state carries execution edits and valid evidence across those surfaces, while each new scan clears stale execution evidence. No visual redesign or Pre-Breakout handoff.

## User stories

1. As a trader, I want the same strategy selection, explanations, parameters, reset and pre-warm controls so that scanning remains familiar.
2. As a trader, I want a successful scan to show Backtest and a failed scan to stay on Strategy with its reason.
3. As a trader, I want one table showing watch status, portfolio marker, scores/deltas, health, backtest and confidence information.
4. As a trader, I want the existing event filter and hidden-row accounting, pipeline, direction warning, rejected reasons and over-cap reasons.
5. As a trader, I want to expand a candidate's full card or open it on Position without losing my edits or valid analytics.
6. As a trader, I want entry, stop, share count, target prices and exit allocations to mean the same thing on every execution surface.
7. As a trader, I want explicit method selection and its refusal/cleared-pick explanation before manual save or send.
8. As a trader, I want each analytics result invalidated only when its inputs change and late cancelled results ignored.
9. As a trader, I want a replacement scan, including the same symbol and prices, to start with fresh evidence.
10. As a trader, I want after-scan arm intent to survive navigation within this session and fire only on a next-scan PASS result.
11. As a trader, I want basket sending on Backtest and Position with matching summaries, saved snapshots, levels, quantities and picked fields.
12. As a trader, I want queued, refused, resized, placed and unknown outcomes to remain visible and safe to revisit.
13. As a trader, I want legacy saved basket rows to remain usable without silently adopting another scan's edits.
14. As a trader, I want server account sizing, exposure/daily-risk refusal and save-before-send to remain authoritative.

## Implementation decisions and invariants

### Shared session state (W1 contract)

Use the existing scan store with a new **non-persisted** stock execution slice and stable selectors. Execution identity is the current stock result's scan identity (scan_id; use the established timestamp fallback for legacy results), plus symbol. With neither identity present, do not accept execution edits/evidence. Include a local replacement generation so clearing/replacing a result invalidates outstanding writes even if a recovered result reuses its scan_id. Setter/request-attachment operations that keep the same result must not accidentally erase valid edits.

The slice holds committed overlay (entry, stop, shares, T1–T3, sharesT1–T3), successful estimate/arithmetic/structural evidence and its exact dependency key/revision, and execution feedback required to survive navigation. Preserve defaultOverlay ladder fallback, rounding and allocation scaling/clamping exactly. Uncommitted input text may stay local. Original scan candidates remain immutable. Do not store AbortControllers in persisted state.

Keep existing stamped method-pick APIs and their established persistence policy separate: W1 does not silently change the persisted picks decision. Newly shared overlay/evidence/after-scan fields are excluded from partialize and explicitly reset/ignored in hydration merge (including a same-version forged blob); no schema migration for unrelated fields. A restored pick is not permission to use missing/stale evidence or mismatched ladder prices: reconcile against currently displayed method rows before enabling any manual action. No automatic pick or fallback method.

| Change | Estimate | Arithmetic | Structural | Explicit pick |
| --- | --- | --- | --- | --- |
| Entry | invalidate/abort | invalidate/abort | invalidate/abort | clear if its selected row is invalid/unavailable |
| Stop or T1/T2/T3 | invalidate/abort | keep | keep | Monte Carlo clears; Ladder clears if picked row no longer matches; Arithmetic stays if valid |
| Shares/exit allocations | keep | keep | keep | keep if selected method row remains valid |
| Candidate navigation | keep completed evidence per identity | keep | keep | keep only with matching evidence/row |
| New scan or result replacement | clear | clear | clear | old stamp is unreadable; replacement generation also retires picks for replaced evidence |

Preserve all existing estimate/plan inputs (direction, strategy, horizon, score, entry/stop/targets and model assumptions), formulas and freshness gates. Cache only successful evidence; dependency keys include the actual request inputs. Navigation/unmount aborts in-flight analytics; every success/error/finally write also verifies captured identity, generation and dependency revision. Completed, still-valid evidence survives navigation. A late response must not recreate invalidated evidence or put old loading/error state on another candidate.

After-scan arms are session-only intent keyed by symbol, separate from scan-stamped numeric evidence. This intent intentionally survives starting a new scan because it means “fire on the next scan”; new result evidence/edits do not. Snapshot eligible arm intent when a manual run begins. Execute only fresh PASS candidates using that run's pristine levels/shares, keeping the existing method-pick exemption and paper-portfolio behavior. Do not introduce broker auto-send. Failures/queued saves/resizing/non-PASS skips retain their explanations. After-scan notices move with the user to Backtest. All manual scan entry points must use the same successful-run continuation exactly once; scan failure must not navigate. A scan may succeed even if an after-scan save fails: advance, display the separate save failure.

Allocate a monotonically increasing manual-run token before clearing/starting a scan. Guard **every asynchronous shared scan write** with that token: result plus paired request, COMPLETED/FAILED status, error, per-run metadata/feedback and completion processing. Current runStockScan installs result/request and terminal state unconditionally; W1 must change that boundary, not just guard routing. A superseded success/failure returns an explicit obsolete outcome and never installs candidates or changes the current run's state, error, notices or navigation. Recheck ownership before each after-scan save begins, and before emitting notices/navigation after awaits. Once a portfolio save has actually started, finish its bookkeeping against its captured originating run even if superseded; do not falsely retry or pretend it was cancelled. Existing separately sequenced last-run metadata refreshes must remain coherent and must not regress the visible current run. Verify deferred run A resolving or failing after newer run B, B still scanning and B already complete, and a B start during A's after-scan save loop.

### One results surface (W2)

Strategy keeps its picker, strategy descriptions, regime fit, parameter hydration/reset, multi-signal conditions, Run, last-scan timestamp and HistoryPrefetchRow. Retain a link to existing results when present, but remove its duplicate table/card after moving them to Backtest. Preserve readable scan failures and loading state. Shared scan runner remains UI-agnostic; page/floating manual triggers coordinate navigation only for their own still-current successful run.

Backtest union columns: WatchStar, symbol + portfolio marker, summary, stock score, score/rank delta, win %, trades, return %, max drawdown, fundamental health, VS SPX (preserve current sector_rs_pct mapping), event, confidence, backtest gate. Keep health sort's desc/asc/off cycle, badges, tooltips, missing-data dashes and original field formatting. Keep stock status visible independently of backtest gate. Positive win-rate tone uses the existing 0.50 reference and a caution floor based on the threshold used by this scan, not a subsequently edited setting; reject below its floor. Gate explanations likewise use paired scan-request thresholds. For a legacy result without a paired request, show threshold provenance unavailable instead of claiming current settings governed that scan.

Event filter remains an explicit display filter (avoid: unknown or >7d; pre-event-only: known <=21d; all: all). Preserve hidden-row note/count; do not rewrite the funnel counts or reinterpret over-cap as gate failures. Table expand control opens the full existing card; a separate “Open Position” action selects the symbol and navigates. Watch/pin/expand controls must not accidentally navigate or fire each other. Preserve pipeline details, direction banner, rejected/over-cap sections, last-scan timestamp and durable DirectSendNotesPanel. No independent second table is rendered.

### Position (W3)

Resolve selection by symbol within current passing candidates; choose the first valid candidate if absent, and show the existing no-candidate recovery when empty. Navigation includes Prev/Next and the existing candidate symbol choices, with selection synced to scanStore. Show the full existing StockPositionCard (sizing grid, editable ladder and allocations, estimate inputs/results/explanations, structural stop, arithmetic plan/sizing/concentration flag/Apply, method selector, Add to Portfolio, basket pin, broker choices, limit/market orders, result/errors, auto-trade arms). Port the old Position “Now” quote/loading display into the shared card without changing analytics inputs; cancel/ignore stale quote responses on identity change. Preserve company/direction/strategy, confidence/status, win rate, risk/size/R:R figures and tooltips. Retire Position's submit/build/order logic; shared card delegates to existing save-first helpers.

Successful/unknown/pending direct-send state is keyed to the originating execution identity and survives card remount/navigation. An in-flight save/send remains owned by its originating identity even when viewed elsewhere: a real saved position or order must finish bookkeeping; do not abort a broker mutation because the card unmounts. Disable repeated sends across card and basket for an in-flight, placed or ambiguous outcome. Preserve DirectSendNotesPanel recovery actions and refusal/status semantics. New scan evidence reset must not erase unresolved send tracking or make ambiguous orders retryable; keep durable notes/position ownership authoritative.

### Basket and effective values (W4)

Keep persisted stockBasket's legacy PositionCardData[] shape and symbol replacement/removal behavior. Add non-persisted provenance for new pins. An active basket row may borrow shared edits/evidence/picks only when its recorded source execution identity matches that candidate's current identity; same symbol alone is insufficient. Older/restored rows with no source metadata keep pristine saved levels and existing empty-target fallback, and are labelled as saved basket values. They never borrow new-scan edits or evidence. Retain manual method selection gating; if provenance/evidence cannot support a pick, tell the trader to open/refresh that candidate and choose a method, rather than bypassing the gate.

One effective execution resolver feeds card summary, basket display/totals, portfolio snapshot/levels, order limit and picked fields. With no shared edit for a matching row, use the same original values/default card ladder behavior as existing card; for legacy baskets preserve pristine ladder/fallback behavior. With matching edits, include full target allocations and applicable structural stop. Direction-aware risk is a nonnegative magnitude; preserve all model calculations. Dialog quantity changes commit through the same shared overlay/allocation logic for matching rows (no divergent private quantity); legacy rows may retain dialog-local quantity and existing legacy allocation rules. Display the quantity actually saved/sent after server resizing.

Read effective values and valid method picks at each submit attempt and freeze a per-row submission snapshot. Block sends while scan identity is changing or the row is stale/invalid; capture identity for all async outcomes. Do not let closing/reopening the dialog or switching Backtest/Position reset placed, queued, unknown or in-flight outcomes into retryable rows. Retry only confirmed failed rows, preserving pending/warning tracking. Keep recommendation/manual branches, broker configuration checks, stockDirectSend save-first sequence, server-approved actual quantity, daily-risk/exposure refusal and all existing status/refusal notes. No client override of server account value, new broker endpoint or backend sizing math.

## Proposed testing seams

Prefer existing store actions/selectors and mounted page/card/dialog user behavior with mocked APIs. Verify outgoing save/order payloads, UI values and persistence together, not helper implementation alone. Reuse existing stock scan, card exits/arithmetic/pick/refusal/pending, basket pending/pick, scan-store persistence and stockDirectSend tests. Add adversarial same-symbol replacement, route remount, cancelled deferred-response and basket provenance cases. Numerical literal pins remain unchanged. No new backend numerical implementation.

## Ticket breakdown (draft only)

### W1 — Shared stock execution session and after-scan continuation

Blocked by: authenticated GitHub preflight, clean plan audit, approval, issue publication and phase claim.

Ownership: scanStore and stock execution helper/type modules; StockPositionCard shared-state adoption; shared manual scan continuation and its trigger wiring; Strategy after-scan state wiring; existing/new tests for these seams. Define/export continuation and card/effective-state interfaces before W2/W3. W1 may change Strategy/floating trigger handlers now so W2 does not need to touch shared scan helper/trigger files later.

Acceptance:
- Committed edits and valid completed analytics survive unmount/remount for the same scan/symbol; no cross-symbol leaks.
- New scan start and replacement clear stale overlays/evidence/picks, including same-symbol equal-price replacements and late responses; hydration cannot restore new ephemeral fields.
- Exact existing overlay allocation math, arithmetic/MC/model inputs and dependency-specific cancellation are preserved.
- After-scan intent survives navigation/re-scan in memory, captures a run once, uses fresh PASS-only pristine candidates, and carries failures/queued/resized/skipped notices.
- All manual scan triggers have one still-current continuation contract. Failures remain readable; no older success/failure may overwrite a newer run's result/request, state, error or feedback, advance navigation or initiate another after-scan save. Started saves finish bookkeeping for their originating identity. Deferred A-after-B and supersession mid-arm-loop tests assert store values and outgoing save counts, not only the route.
- Direct-send in-flight/placed/unknown identity and bookkeeping survive navigation; controls cannot duplicate a live/ambiguous order.
- Typecheck and relevant store/card/scan/send regression suites pass; confirm unrelated persistence/method picks are preserved.

### W2 — Unified Backtest results and successful-scan routing

Blocked by: W1.

Ownership: Strategy and Backtest page/CSS modules, Backtest-specific table components and their tests. W2 owns the removal/move of results from Strategy and navigation consumption of W1's contract. Do not edit W1 shared-state/card/scan modules or Position files.

Acceptance:
- Exactly one union table, all columns/actions/information listed above; expanded full card plus separate Position action.
- Successful scan advances to Backtest including zero-candidate scans; failures stay on their initiating workflow with original reasons; after-scan save failure appears on Backtest.
- Strategy picker/reset/hydration/multi-signal/pre-warm remain; Step 5 redirect and six-step navigation remain.
- Health sort, threshold provenance, event filter/hidden counts, funnel/direction/rejection/over-cap explanations, status/deltas/portfolio/watch controls and direct-send notes remain correct.
- Meaningful page interaction tests and typecheck pass.

### W3 — Position navigation around the full existing card

Blocked by: W1. May run alongside W2 only after W1 is verified and file ownership is disjoint.

Ownership: Position page/CSS and Position navigation component/tests only. Shared card quote parity must already be supplied by W1; W3 does not edit StockPositionCard or W2 pages.

Acceptance:
- Selected symbol from Backtest is honored; Prev/Next and candidate buttons remain synchronized and recover from removal/replacement/empty results.
- Full shared card, all old Position figures/broker controls/Now quote and durable notes remain available.
- Old Position order implementation is removed; all manual sends use the full card's effective values, explicit pick and save-first path.
- Remount/switch navigation preserves edits/evidence and order safety from W1; page integration/payload checks and typecheck pass.

### W4 — Shared basket, integrated verification and phase code audit

Blocked by: W2 and W3.

Ownership: StockSendDialog/effective execution resolver/basket provenance integration, Backtest and Position basket controls, integrated tests. Coordinator alone owns PROJECT_STATE, tracking issue and audit bookkeeping; a fresh implementer performs W4 code work.

Acceptance:
- Basket opens from both pages, same shared current edits, correct totals/limits/levels/allocations/snapshots/picked fields and server-approved quantity.
- Legacy basket rows survive with pristine saved values and no same-symbol cross-scan overlay/pick adoption; stale sends fail closed with actionable explanation.
- Pending/placed/ambiguous/in-flight outcomes survive surface changes/reopening and cannot be duplicated; retries process failed rows only.
- Regression suites cover save-first, backend refusal, daily-risk/exposure sizing, all configured broker modes/statuses, numerical pins, persistence/hydration, late analytics and replacement scans.
- Frontend typecheck/full Jest and state check complete; diagnose inherited locale failure separately. Backend Python 3.11 relevant risk/order/scan regression checks plus CI as required by final touched surface. No numerical pins regenerated for runtime differences.
- Independently audited integrated phase diff is clean under repository gate and stage cap; tests/per-ticket checks are not audit rounds. Draft PR is reviewable; no merge without explicit authorization.

## Audit and publication sequence

Plan audit: fresh independent reviewer applying repository bmad adversarial skill, full spec/breakdown and mockup checked against exact baseline. Report only defects that can put a wrong number before a user/on an order or corrupt persisted data (including mechanism comments leading to such changes); undecidable is not gate-level. Max 3 plan rounds. Later rounds review only preceding fixes/interactions. Record reviewer, exact artifact hashes/scope, findings/fixes/outstanding. Clean plan does not mean implemented code is clean.

Then present mockups, proposed seams, W1–W4 acceptance/ownership/dependencies and blockers; wait for user's approval. Only when authenticated GitHub preflight passes: publish one S2 tracking issue with four child tickets and native sub-issue/blocked-by links where supported (otherwise issue-body links with explicit fallback record). W1→W2/W3→W4. Recheck main/claims; claim S2 only after approval/publication, before any application code. Fresh implementer per ticket, coordinator verification per ticket, push/checkpoint according to repository rules. W2/W3 parallel only if W1 interface is frozen and ownership stays disjoint; coordinate amendments rather than concurrent shared edits.

Code audit: after build tickets are verified, one integrated phase target, exact freshly fetched origin/main..phase branch range. Fresh independent reviewer per round, separate 3-round code-stage cap. Fix only gate findings with fresh implementers; log below-gate issues against main. Coordinator records evidence/state, keeps built-but-unmerged status honest and creates reviewable PR. No automatic merge.

## Out of scope

Visual redesign; new strategy/model/backtest calculations; Pre-Breakout handoff; options workflow or options picks/persistence changes; new account-value authority, daily-risk policy, broker adapters, backend cache/sizing rewrites; live broker activation. Existing issues are read/reconciled when API access is restored rather than invented or moved into a local tracker.
