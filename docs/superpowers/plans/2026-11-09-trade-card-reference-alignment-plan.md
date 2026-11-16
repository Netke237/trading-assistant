# TRADE-CARD-REFERENCE-ALIGNMENT

Parent #603, branch board/trade-card-reference-alignment-86fd081f. Frozen presentation reference d8245e6695b301dae35a476f170e6cdf4cc0d7b0 in PR602; production numerical authority main86982b58. User initially selected #604; subsequent explicit chat instruction is to keep going through the board. Resume #605–610 in order on the same phase branch and draft PR611. All remain in authorized scope; do not stop after a single build ticket. #609 retains native prerequisite #591; resolve that prerequisite through its own board phase if still open before #609.

## Historical review
The seven-ticket publication manifest was independently reviewed by amendment_ticket_plan_audit, zero gate findings (plan round1). This elaboration retains that review and undergoes plan round2; it adds implementation detail, not new numerical behavior. Phase code audit remains after all build tickets, per orchestration rules.

## Task1 / #604 — page order, identity, qualifications (M, complexity3)

Read the frozen README and IMPLEMENTATION-GAPS D01–D03 in /workspace/trade-card-design-review/docs/superpowers/specs/2026-11-09-trade-card-reference, and reconcile with actual TradeCard/page before changes.

Allowed application files: frontend/components/organisms/TradeCard/index.tsx and TradeCard.module.css; frontend/components/molecules/MethodCompareSelector/index.tsx and its module CSS if required. Allowed tests: existing TradeCard and MethodCompareSelector tests and page identity-market-context/integrated-flows/a8-rail-and-structural-cache tests, plus new TradeCard page-order tests. Scope clarification during regression: page calculation-flow tests must explicitly open Arithmetic/Ladder through comparison before their existing calculation scenarios; retain all numerical assertions. This is the same reviewed default-visibility adaptation, no application behavior expansion. Coordinator owns this plan/state and acceptance evidence. Do not touch submissionDraft, broker/direct-send handlers, calculation formulas, stores or backend.

First write meaningful failing tests for initial MC-only visibility, MC-first ordering when comparing, separated collapsed Stock Qualification directly beneath visible Contract Details, preserved Contract Qualification evidence and reading order Exit Plan before methods before entry/size before decision. Ensure method visibility never calls compute or changes selected target/settings. Update obsolete default-all-method expectations by explicitly opening methods when those tests exercise their content. Prove red before implementation.

Implementation: retain existing parent Market Sentiment then Fundamental Health (all badges/colors/explanations), chart jump/inline chart, candidate/mode navigation, basket, spreads and alternatives. Enlarge strike/right (~30px) and full expiry (~25px) with responsive wrapping and existing tokens. Split the current combined score disclosure into distinct Stock Qualification (immediately after Contract Details, default closed) and Contract Qualification (distinct reachable disclosure, default closed); retain both ScoreCardPanel components and every explanation. Keep selected Contract Details visible.

Reorder existing actual Exit Plan into a single section before method results, preserving all existing editable controls, helpers, alerts and data sources exactly once. Place Order Entry and loss budget/sizing after methods, before existing decision/actions. Keep structure evidence reachable without compacting/removing its content (#605 owns that change). Prefer moving existing JSX or extracting local render fragments over rebuilding data. Preserve original event handlers and conditional mounts. The standalone Barrier Race remains unchanged until #606. Default comparedMethods becomes ['monte_carlo']; selector and visible card DOM order MC, Arithmetic, Ladder. Browsing only changes visibility; all calculations remain explicitly triggered and cached/restored results unchanged.

Run focused tests, typecheck and full Jest; no backend changes. Commit `fix(trade-card): restore page hierarchy and contract identity` with repo attribution. Do not push, edit state, close issues or claim independent audit. Report red/green results and any deviations to coordinator.

## Acceptance evidence
Coordinator checks initial/restored real shell at desktop and narrow widths in dark/light themes using isolated route fixtures (no real writes), records page order, identity wrapping, closed disclosures and no lost actions; preserves screenshots/check data in repository. Reconcile affected entries from existing final-register.md; no loss of text or duplicated execution settings. No declaration that #605–610 are complete. Phase integrated code audit and merge remain pending all tickets.

## Remaining approved tasks — execution details

These tasks transcribe the independently approved publication acceptance (plan round1) with implementation scopes. Round3 reviews added execution details/interactions with Tasks1–7; counters remain continuous. The frozen README/D01–D12 and real numerical source remain controlling. Each fresh implementer reads its entire live issue, listed source, and repo brief, writes meaningful expected-red tests first, preserves all numerical/transport/persistence logic, runs typecheck and full Jest (two workers acceptable), and commits only allowed application/test files with Codex attribution. Coordinator owns plan/state/evidence, pushes and ticket closures. When a full run reveals only obsolete presentation-test expectations, correct and rerun all affected suites; report combined unchanged full-run coverage accurately. Do not repeat broad tests once failure is resolved without new concern. Do not add tests that merely mirror JSX. Preserve every existing conditional notice and handler; presentation rewrites may update obsolete container/visibility assertions while retaining numerical/safety checks.

Keep model-specific full detail mounted/reachable via native default-closed details or existing CollapsibleSection keepMounted; no changing freshness, calculations, request timing, stop precedence, selected target, broker safeguards or inherited edits. Missing stays unavailable. Do not copy illustrative reference numbers or scripts.

## Task2 / #605 — TC-ALIGN-02 — Compact actual Exit Plan and fold structure evidence into closed disclosures

Allowed scope and implementation: TradeCard/index.tsx, TradeCard.module.css, existing/new TradeCard tests and page presentation assertions only. Move existing Structure & Stops JSX intact into an Exit Plan default-closed structure-evidence disclosure; remove its stand-alone main-path wrapper. Keep unique stop-cost/ATR/raw-structure results and Check structure available, with explicit separate pricing bases. Put loss percentage plus remaining value/loss per contract beside the three existing exit controls in responsive columns; detailed quantity/basis/time prose default closed. Keep invalid stop/small-premium actionable notices visible. Reuse exitPremium strings and TIME_STOP_DTE; no new formulas. Commit: fix(trade-card): compact exit plan and preserve structure evidence.

Approved acceptance:

- [ ] Keep one editable actual Exit Plan: invalidation, premium-loss amount, loss percentage, concise remaining option value and loss per contract, plus readable time-exit threshold.
- [ ] Move verbose basis, quantity breakdown, ATR/structure and time explanation into a default-closed disclosure; keep actionable missing/invalid warnings visible.
- [ ] Remove the separate full-width Structure & Stops block from the main reading path, relocating every unique result, source, explanation and Check structure action to the appropriate context/disclosure.
- [ ] Preserve edit/revert/inheritance rules, restored overrides, valid bounds and small-premium read-only behavior. Use existing consistent tinted editable affordances and clearly distinct readouts.
- [ ] Keep stock stop versus premium-loss amount versus remaining option-price threshold units explicit. Three days to expiry is an alert at ≤3 DTE, not three days after entry or an automatic close.
- [ ] Keep all quantity totals tied to the same applicable premium/quantity basis; missing estimates remain unavailable. Do not apply calculated stops automatically or change formulas/alert rules.
- [ ] Verify edited, inherited, missing, restored and changed-contract states alongside the reference.


## Task3 / #606 — TC-ALIGN-03 — Show Monte Carlo essentials with its nested graphical Barrier Race

Allowed scope and implementation: TradeCard/index.tsx, TradeCard.module.css, BarrierRaceCard/index.tsx and module CSS, associated TradeCard/BarrierRace tests and page presentation assertions. Existing controls, source/time qualifiers and all MC targets become concise table rows with consistently ordered columns; long provenance/formulas/settings default closed. Nest existing BarrierRaceCard under MC in a default-closed details, retaining mounted state and every existing chart/table/control/risk explanation. Main stop consequences must come from the currently valid race outcome with explicit corresponding target/time basis if target-dependent; never from Arithmetic or stale saved race. Reuse existing target association/selection rather than inventing an unlabeled first outcome. If no valid consequence exists, say unavailable. Keep stale/error/fallback warnings outside relevant closures, and replace repeated actual-exit readouts with a concise source/difference link. Commit: fix(trade-card): focus Monte Carlo essentials and nest barrier race.

Approved acceptance:

- [ ] Show existing percentage inputs and explicit Run action, then actual stock/premium barrier inputs, barrier-time option value at stock stop and corresponding loss, with concise source/time labels.
- [ ] Use a compact target table: target, stock price, option value, existing independent target-touch probability and conditional time. All existing target rows stay visible.
- [ ] Move full formulas, model/provenance text and extra settings into method disclosures; keep caveats that materially qualify visible figures and stale/error/fallback-volatility states visible.
- [ ] Nest the existing graphical Barrier Race under Monte Carlo in a default-closed expansion. Preserve bars, numeric shares, target-selection controls, conditional medians, R:R, edge and deeper explanations; bar/table weights remain identical.
- [ ] Remove duplicated actual Exit Plan readouts from the method card; retain a concise source difference/link when the simulation input differs. Never substitute current-time Arithmetic pricing for barrier-time race values.
- [ ] Preserve calculation input precedence, current freshness and restore rules, on-demand performance and all existing guards; do not introduce new simulated stops or pricing.
- [ ] Verify unrun, fresh, restored, stale and rerun states; no new live broker/provider/notification calls during tests.


## Task4 / #607 — TC-ALIGN-04 — Align Arithmetic and Ladder target tables and two/three-method comparison

Allowed scope and implementation: TradeCard/index.tsx, TradeCard.module.css, MethodCompareSelector display components if required, associated TradeCard/comparison/page presentation tests. Harmonize actual current targets into semantic compact tables matching MC column order. Preserve Arithmetic resolved-versus-original target and pricing geometry details, and Ladder EditableTargetRow handlers and all full-position/rung outcomes. Preserve inherited stops with explicit source; no inventing Ladder probability/time/valuation. Ensure subgrid or another pure layout approach aligns cards, stop slots and table headers at each comparison row; 2 or3 methods, wrapping without clipping. Allow extra matching-height blank space for short Arithmetic table. No model calculation/target selection on viewing. Commit: fix(trade-card): align method targets and comparison tables.

Approved acceptance:

- [ ] Use the same stop context and target-column order as Monte Carlo. Arithmetic shows its current-time stop-cost valuation and resolved target used for option valuation/probability; original arithmetic target/snap geometry/model detail expands.
- [ ] Ladder shows shared actual stock invalidation and premium-derived option threshold with source; only genuinely absent Ladder-specific stock-stop valuation says not calculated. Probability/time say Not supplied.
- [ ] Preserve editable Ladder targets, quantities, full-position outcomes, rung allocations/unavailable states, capped/quality warnings and full-premium R:R. Do not add alternative exits together.
- [ ] Open comparison in the same results area. Support two or all three methods, equal outer card heights and aligned stop/target slots/table headers; additional cards may wrap without clipping essential columns.
- [ ] Keep all calculation/structure/pricing/geometry explanations and actions reachable; default-close specifics, retain material warnings with affected values.
- [ ] Verify fresh/stale/restored/edited/spread contexts and both themes inside the real app shell; preserve sources, formulas, persistence and selection behavior.


## Task5 / #608 — TC-ALIGN-05 — Group method/target selection and one compact selected-target review

Allowed scope and implementation: TradeCard/index.tsx, TradeCard.module.css, page.tsx and page CSS at step-7-trade-card, MethodPickSelector/SelectedTargetReview or other existing display components only if their existing logic is reused, associated tests. Inspect existing method/row/basis draft resolution first. Group those existing controls with one selected-target review and destination actions; use current selected values/probability/time/quantity/outcome as available, not independently derived transport. Remove only duplicate latest/all-target recommendation summary after relocating every unique context. Keep final status in identity; retain all four method choices, optional rows, clear/fallback/ambiguous behavior, Judged on semantics and existing source validation. A selection never applies model stops into actual settings. Preserve non-disabled alert channels, send/basket/auto-trade/export actions and portals. Commit: fix(trade-card): group decisions and selected target review.

Approved acceptance:

- [ ] Bring method choices, target-row choices, Judged on basis and compact selected-target evidence together with destination actions.
- [ ] Show selected TP stock/option values, existing probability/time, applicable quantity and estimated gross full-position outcome where supplied. Distinguish estimates from submitted settings and unavailable values.
- [ ] Remove the Final Recommendation latest/all-target duplicate summary; preserve its unique evidence at the originating method or the single selected-target review and keep final status in identity.
- [ ] Preserve all four existing recorded method choices including Barrier Race, optional target rows, clear/unavailable behavior, target matching, fallback alert basis and Judged on semantics. Choosing a basis must not disable either existing stop alert.
- [ ] Reuse the actual authoritative draft/resolution values already implemented. Do not rebuild independent transport values from display strings, copy model stops into actual settings, or undo server-backed review.
- [ ] Keep one actual editable Exit Plan, linked from decision review; show differences without another permanent duplicated actual-exit panel.
- [ ] Verify method/row changes, absent/unreachable/ambiguous targets, quantity edits and stale results cannot leave a misleading selected review.


## Task6 / #609 — TC-ALIGN-06 — Make basket and broker destination reviews concise without weakening safeguards

Allowed scope and implementation: Only after #608 and native #591 prerequisite complete. SubmissionReview/index.tsx and CSS, existing destination-review display components (SendToBrokerDialog and Step7 page JSX/CSS if needed), associated tests. Preserve current server preview/fingerprint/authoritative draft and submit values unchanged. Put destination, exact contract/expiry, quantity, requested/effective order-entry basis, actual exits and target-alert basis first; fold technical generation/transport/attached-plan/provenance in native details. Keep provisional/unknown-fill/server-change/review-invalid warnings, conditional controls and feedback visible. No submissionDraft/directOrder/store/backend modifications for this presentation ticket; prerequisite expiry fix belongs separate phase. Test mocked basket/broker payload parity and changed-review refusal, pending/partial/retry outcomes. Commit: fix(trade-card): simplify destination reviews without changing safeguards.

Approved acceptance:

- [ ] Before confirmation, show destination, contract/expiry, quantity, order type/limit or tracked-entry basis, actual stock/premium settings and effective target-alert basis prominently.
- [ ] Move draft generation, technical transport metadata, full attached-plan/provenance strings and long resolution explanations into secondary disclosure; preserve all information and conditional controls.
- [ ] Keep requested versus server-resolved/estimated values explicit, with visible changes requiring re-review, unavailable fill information, warnings and result/pending/rejection feedback.
- [ ] Retain existing authoritative draft, server preview/fingerprint, normalization and changed-value rejection. Submission must consume the reviewed values; UI reorganization must not replace those checks with prototype math.
- [ ] Pin remains symbol selection, not a frozen snapshot or order. Portfolio tracking creates no broker order. Broker confirmation names the destination and must not imply in-app stops/TP are broker protective orders.
- [ ] Keep unknown market fills separate from requested values and reconcile saved/fill adjustments through existing outcomes. Preserve limits, earnings gates, retries, spreads, duplicate guards and auto-trade capabilities.
- [ ] Verify basket and mocked broker request/store parity, changed settings, server adjustments, pending sync, partial failures and unavailable fills without real orders or notifications.


## Task7 / #610 — TC-ALIGN-07 — Visually accept the amended page against the permanent reference

Allowed scope and implementation: Coordinator-owned docs/superpowers/plans/trade-card-reference-alignment/ evidence, guarded browser harness and acceptance/information-register docs; associated presentation/flow verification tests only. Implementer prepares full625-item location/retention reconciliation against final source, D01–D12 matrix and repeatable guarded browser verification for all accepted states and widths/themes. Do not blindly count matching strings as proof of conditional runtime behavior. Use controlled comparable fixture inputs and existing pure calculations; no real orders/providers/notifications. Register gaps become concrete authorized acceptance fixes before final phase audit. Independent fresh visual reviewer must explicitly assess real app-shell captures against frozen reference, separate from numeric gate audit. Coordinator merges current main, runs required checks, closes build tickets, then independent phase code audit on integrated diff; no original575 counters reset. Reserve final-acceptance.md marker TRADE-CARD-REFERENCE-ALIGNMENT-FINAL-VERIFIED only once all implementation and integrated acceptance actually exist, and retain audit_clean false until formal fresh code review clean. Commit: test(trade-card): verify visual alignment and preserve information.

Approved acceptance:

- [ ] Reconcile all twelve amendment IDs with source changes and before/after evidence or an explicit user-approved exception. Validate the latest Stock Qualification placement.
- [ ] Account for every item in the current 625-item preservation register, including conditional warnings, actions, tooltips, colors and explanations; the historical 132-entry appendix is not a replacement.
- [ ] Capture initial, calculated, restored, stale/rerun, edited/reverted, two/three-method and both destination-review states in both themes at supported app-shell widths, including 1200,1366,1920.
- [ ] Use controlled, comparable sample inputs when judging numerical equality; source/stop-time differences remain labeled. Do not use mock quotes/probabilities as production golden values.
- [ ] Verify readable target columns, equal-height/aligned compared cards, default-closed disclosures, editability and no lost navigation/chart/qualification/alternative/spread/auto-trade functionality.
- [ ] Run appropriate checks plus existing mocked tracking/broker parity regression tests and record network/write guards. No real trading or notifications.
- [ ] Complete the new phase independent plan/code audits with fresh reviewers, shrinking fix scopes and the three-round-per-stage cap. Do not reset/reopen original phase575 audit counters.
- [ ] Obtain explicit visual acceptance against the reference; a clean numeric/persistence gate or item count alone is not proof of design conformity.

