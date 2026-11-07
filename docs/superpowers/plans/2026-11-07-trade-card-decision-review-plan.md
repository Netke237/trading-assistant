# TRADE-CARD-DECISION-REVIEW — implementation plan

Tracking: #575. Build tickets: #576–#584. Source inspected: `c8f3b8a2`.
Phase size XL; complexity 4. Implement only this phase on its claimed board branch.

## Scope and authority

The parent issue and nine ticket acceptance checklists are the requirements.
The user explicitly authorized native publication wiring, clearing the hold and
starting this phase on 2026-11-07. Nine native child links and eleven dependency
links were installed and read back. This authorization does not change pricing,
alert semantics, risk gates, account configuration or protective-order behavior.

The current source already contains the earlier trade-card presentation work.
The older 520-entry mapping, preview and screenshots are design/evidence inputs,
not live numerical fixtures or proof of the trader's current build. Keep all
unique information, original status colors and controls, and preserve existing
on-demand calculation, restoration and freshness behavior.

## Baseline gate

Ticket #576 must identify the running revision and compare it with inspected
source before any dependent application implementation. The running URL/revision
has been requested in this chat and is currently unknown. A local mocked browser
run of `c8f3b8a2` proves only this checkout's behavior. It cannot close this gate.
While waiting, collect source evidence, current-build captures and the proposed
before/after register. If the actual build remains unavailable, record exactly
what is missing, leave #576 open and stop dependent implementation. Do not infer
equivalence from a historical screenshot. Any material source difference requires
updating this plan and independent review within the remaining plan-stage cap.

## Existing behavior that is load-bearing

- Step7 owns candidate/basket state, override preparation, execution, caches and
  AutoTradeArm. Preserve its component owner and readiness predicates.
- TradeCard owns local editing and calculation freshness. `methodPick` records
  a choice; it does not execute calculations or apply model stops to settings.
- `estimateIsFresh`, `raceIsShowable`, `stockStopMoved` and `raceBarriersMoved`
  protect different vintages. MC target-touch and race first-event results have
  different meanings and different validity after edits.
- Ladder R/R uses the full premium; full-position and rung outcomes differ.
  Arithmetic premiums require the existing matched calculation basis.
- The actual Exit Plan uses current execution-field resolution, including
  touched/reverted values, the pinned scan premium, live/global cases and tiny
  premiums. MC/Arithmetic premiums are separate calculation inputs.
- `position_writer.create_position` refreshes quotes, reanchors generated levels,
  applies gates/quantity normalization, resolves premium loss and effective TP,
  and commits. A frontend summary cannot predict the persisted row reliably.
- Direct orders save first. Persisted tracking quote values are not broker fills.
  Existing broker responses do not supply fill price or filled quantity.

## Build order

Run one fresh implementer per ticket. Existing tickets are reused; create no
duplicates. Dependencies: 577/578/579 after 576; 580 after 579; 581 after 578/580;
582/583 after 581; 584 after 577/582/583. Execute serially where source overlaps.
Each implementer reads its complete ticket and this plan. Tests precede behavioral
changes; documentation-only inventory work uses evidence validation rather than
artificial red tests. Push verified ticket commits before closing its issue.

### #576 — verify complete information inventory (S, complexity 3)

Files: new evidence and inventory under
`docs/superpowers/plans/trade-card-decision-review/`; read current TradeCard,
Step7, BarrierRaceCard, MethodPickSelector, context, tracking dialog, order helpers,
the earlier mapping and integration reconciliation. Do not change app code.

1. Record exact checkout SHA, source hashes, reference revisions, mocked-data
   provenance and native ticket graph. Record the actual running build separately.
2. Reconcile all 520 historical entries with current rendering regions and add
   new/changed fields, badges, tooltips, explanations, actions and conditional
   states. Record current/future location, mutability, source, units, time basis,
   applicable state and preservation check. A loop's real rows remain dynamic.
3. Capture initial, calculated, stale and restored local states with mocked APIs;
   compare actual running-build evidence when supplied. Record unresolved
   discrepancies. No order, arm, fire or position-create request is permitted.
4. Reconcile current-time stop-cost, Arithmetic stop valuation and barrier-time
   valuation explanations against their actual implementations. Keep each basis.

Close only when the running-build comparison and complete register are evidenced.
Commit: `docs(trade-card): verify information and running-build baseline`.

### #577 — identity and market context (M, complexity 3)

Files: TradeCard render/CSS and Step7 render; existing FundamentalHealthCard and
MarketSentiment only if needed, with opt-in changes for shared consumers.

Promote existing strike, right and unambiguous expiry. Keep full Contract Details,
spread legs/summary, alternatives, edited state, inline chart and separate chart
tab. Market Sentiment already precedes the card; place the existing Fundamental
Health directly beneath it without duplicating it or losing definitions, scores
or colors. Preserve its card lifetime, candidate synchronization and missing data.
Verify order, prominent identity, all context fields, both themes and widths;
update the older test whose deliberate layout expectation places scores first.
Commit: `feat(trade-card): clarify contract identity and market context`.

### #578 — actual exit settings and editable fields (M, complexity 3)

Files: TradeCard, its CSS, existing edit/target/budget components and their tests.

Render one actual Exit Plan. Preserve bounds, touched/revert state, saved-edit
precedence, absolute user stops and tiny-premium read-only behavior. Derive loss
percentage, loss and remaining value from the same execution-field premium basis
already used by `effectivePremiumStop` and its live/global/pinned/touched branches.
Show per-share, per-contract and quantity totals explicitly; invalid/missing basis
means unavailable, never zero or a borrowed model premium. Label 3 DTE as an
alert at three days or fewer until expiry, not an automatic close.

Use consistent editable styling across existing inputs and affordances. Keep
read-only max fill/time/results distinct. Collapse explanatory/ATR/structure
detail by default while retaining warnings and essential actual settings. Reuse
existing disclosure storage keys/preferences. Calculation or selection must not
mutate settings. Tests cover live/global/pinned/tiny/missing premium, quantity,
focus without typing, edits/revert and unchanged outbound values.
Commit: `feat(trade-card): clarify exit settings and editable values`.

### #579 — Monte Carlo and Barrier Race (M, complexity 4)

Files: TradeCard MC/race presentation, BarrierRaceCard/CSS and relevant tests.

Retain explicit calculation and all actual payload target rows with their own
premium/stock target, touch probability and conditional time. Keep simulation
barriers and source precedence distinct from actual settings. Preserve input,
expiry, fallback and stale warnings in their affected sections.

Fix the existing graphic mismatch: `StackedBar` currently uses raw `p*` shares;
numeric/aria rows use allocated `weight*` shares. Use the existing allocated
weights consistently for segment geometry and numeric meaning, with the same
existing helper's fallback/rounding policy. Do not change the simulation or edge
formula. Add a raw-versus-allocated fixture and verify geometry, labels and aria.
Place rich race detail in the agreed expansion; retain selection shortcuts,
medians, R/R, edge, arithmetic and all inventoried copy. Disclosure cannot bypass
freshness. Retain independently valid target-touch evidence after barrier edits.
Commit: `feat(trade-card): align Monte Carlo and Barrier Race presentation`.

### #580 — Arithmetic, Ladder and comparison (L, complexity 4)

Files: TradeCard render/CSS; controlled presentation components if extracted.

Preserve all Arithmetic target rows, matched-premium rules and model/source/time
details; preserve edited Ladder targets, local approximation and full-premium R/R.
Add display-only two/three-method comparison controls independent of `methodPick`.
Opening a card must never calculate, select a trade method or rewrite settings.
Use aligned field order and equal-height method cards at fitting widths, readable
stacking at narrow widths. Put Ladder in the same comparison layout.

Show Ladder's inherited actual Exit Plan stock/premium settings with source labels.
Only unavailable method-specific stock-stop valuation/probability/time is labeled
not calculated/supplied. Keep per-share, per-contract, full-position and rung
outcomes distinct. Test two/three-card selection, absent rows, stale/restored
results, all three quantity bases, no unintended requests and no overflow.
Commit: `feat(trade-card): compare target methods on consistent bases`.

### #581 — authoritative trade review (L, complexity 4)

Files: Step7 builders, a shared submission-draft helper, a review presentation
component, TradeCard decision display and tests. Read picked-method backend rules.

Extract actual request builders into shared immutable submission drafts rather
than reconstructing a summary in a second code path. Review and submission consume
the same request object and generation. Include contract, quantity, destination,
order type/limit, entry semantics, actual stops, raw method/row and intended target
basis. Keep model probability/time and available quantity totals separate from
execution inputs and server-resolved values.

Retain optional row behavior and all existing method choices. Judged on records a
basis; it does not disable another alert. Show effective backend TP/fallback from
the server review introduced by #582, not a duplicate TypeScript pricing/routing
rule. Before that server evidence exists, label effective values unresolved.
Contract/quantity/entry/settings/selection/recalculation changes invalidate or
refresh the draft; late async responses cannot replace a newer contract/review.
Test no-row, unreachable MC, Barrier Race, ambiguous/unmappable Arithmetic,
differing model/actual stops, spreads and stale-response races.
Commit: `feat(trade-card): review the authoritative submission draft`.

### #582 — exact basket tracking review (L, complexity 4)

Files: shared draft/review, Step7 basket, SendToBrokerDialog, portfolioStore/API;
backend portfolio schemas/router and position_writer; regression tests.

Reuse one authoritative writer-resolution path for preview and confirmation. A
preview must return the complete resolved position and differences without
`transfer_hold`, position creation/commit, broker calls or approval accounting.
Exposure locking may write guard state: rollback that preview transaction and
release its locks. Preview must never roll back unrelated work in a caller's
shared transaction; use an isolated endpoint/session boundary.

Fingerprint the immutable request and material resolved fields (entry, quantity,
stops, premium fraction, targets/allocations, method and effective TP, plan and
inherited material defaults). Exclude timestamps/IDs/diagnostics that cannot
change trading semantics. Rerun normal quote/risk/TP resolution on confirmation
under the existing booking/exposure lock. Compare before any transfer/add/commit;
a material mismatch returns review-required with no position/order/hold write.
Never freeze a preview quote or waive current risk checks to make it match.

Show requested versus effective values before confirmation and adopt the complete
authoritative saved row immediately afterward. Preserve local-only metadata.
One-off basket quantities update review/totals without mutating card quantities.
If earlier basket rows change capacity, preserve successful rows and require
re-review of changed remaining rows. Preserve hard failures and pending-sync
states; pending retries carry the original confirmation constraint and cannot
silently approve a new preview. Resolve ambiguous saves using stable recId and
matching confirmed request identity, never a same-contract 409 alone.

Test preview side-effect absence; unchanged confirmation parity; quote/capacity/
TP-default changes reject before writes; absolute user stop versus generated
reanchor; fallback premium and target semantics; partial baskets, network ambiguity
and retries; immediate adoption of actual stops/targets/TP. Tracking creates no
broker order. Commit: `feat(tracking): confirm server-resolved basket values`.

### #583 — exact broker review and outcome (L, complexity 4)

Files: Step7 direct-order orchestration/helpers/review; API/portfolioStore;
backend existing broker safeguards only if transport parity needs threading.

Keep save-first behavior and its cleanup/unknown-order safeguards. Review the
normalized intended saved row via #582, confirm it unchanged, then dispatch the
captured immutable broker request matching the reviewed contract/quantity/type/
limit/destination. A changed normalized quantity requires review before dispatch.
Use stable `attempt_id` and `saved_rec_id` through the existing backend-supported
durable attempt/prepared-row and exposure-credit paths; do not add a second broker
dispatch mechanism. No later quote/settings/broker change may rebuild the request
silently. Refresh/review instead, preserving duplicate/order guards and gates.

Name the configured broker/mode and known account context honestly. Current
responses expose order id/status/broker/deduplication, not fill price or filled
quantity. Do not infer a fill from acceptance or treat the saved quote as a fill.
Show unavailable execution fields and reconcile only facts supplied by supported
responses. Preserve rejection cleanup and persistent ambiguous/pending-save notes.
Mock all transports; verify captured request equality, stable retry identity,
saved-row link, response states and no real trading.
Commit: `feat(trading): confirm broker requests and reconcile outcomes`.

### #584 — complete verification and preservation audit (L, complexity 4)

Files: integrated tests and evidence/register; no unrelated production changes.
Reconcile every baseline item to the finished destination and state. Exercise
fresh/restored/edited/reverted contracts, all methods, comparison, stale/rerun,
spreads, unavailable values, fallbacks, quantities, normalization, partial/network
failures and mocked broker responses. Verify full information retention, existing
navigation/arm ownership, on-demand performance, editable affordances, layout and
unchanged numerical golden values. Capture widths 1200/1366/1920 in both themes.

Run frontend typecheck/full Jest, Python 3.11 full backend tests, applicable browser
checks and state probes. Record exact commands, revisions and limitations. Merge
origin/main before code audit, resolve/retest, then audit the whole phase once all
tickets are complete. Only code-clean, exact-head-green work can enter board.md's
self-merge flow. Commit: `test(trade-card): verify review and information parity`.

## Audit history and gates

The published ticket breakdown reports one independent plan round by
`ticket_breakdown_audit`, zero gate findings. Preserve it as historical round 1;
it did not audit this implementation architecture or any code. The expanded plan
requires a fresh independent plan review (round 2 of at most 3). Do not reset the
history. New plan findings are fixed and reviewed within the remaining cap.
No code rounds have run. Code-stage cap is separately three.

Every qualifying reviewer reads bmad-review-adversarial-general and the numeric/
persistence gate: report only reachable wrong user/order numbers, persisted-data
corruption, or mechanism claims that would cause a wrong change. Later rounds
review the preceding fixes and interactions. Record reviewer, exact content,
findings/fixes and outstanding items. No self-review clears a gate.

Milestones remain phase-level: 10% expanded concrete implementation plan awaiting
approval (historical breakdown 20% preserved separately); 20% exact plan approved;
50% all nine implementations exist; 70% required regressions/local checks pass;
85% exact integrated diff independently clean; 95% exact PR head CI and merge
conditions met; 100% verified merge plus required integrated retests. Do not
average ticket percentages. The missing running-build comparison prevents #576
closure and every dependent ticket regardless of plan-review outcome.
