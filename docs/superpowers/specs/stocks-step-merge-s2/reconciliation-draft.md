# S2 reconciliation — user approved, pending final independent review

Prepared 2026-10-05 from planning branch de30a40a; current main is 4b06656a. Original spec, mockup and audit files remain unchanged as historical evidence. This addendum supersedes their GitHub-only preflight and sequencing assumptions for the proposed continuation. It does not extend their audit-clean status to this changed scope.

## Authorized decisions

The user authorized repository Markdown tickets while GitHub is blocked and explicitly accepted recording GitHub issues/assignments as unverified. The user approved preparing/reconciling plan and ticket drafts now while initially waiting for C4; the latest user authorization now removes that sequencing dependency. These artifacts are drafts, not published/ready build tickets. The latest user authorization approves the remaining artifacts and beginning S2 workflow implementation after a clean qualifying plan review. No main merge is authorized.

## Latest user decision (Q3)

Unsupported or awaiting-validation bearish strategies remain visible for research with a clear Unvalidated label; automatic arming is disabled. This is a user-approved design decision, not implemented behavior. User Q4 additionally authorizes research/analysis but blocks manual broker sending for Unvalidated bearish strategies until strategy validation requirements are met. This is separate from the automatic-arming prohibition. Save-for-research is not blocked by this decision; no permission to send can be inferred from a saved research record.

## Current-main reconciliation

Main changes since the audited baseline 6b1ee21d are documentation/state decisions (ee924a97 and 448626ca) and the handoff (4b06656a), not implementation of C4. PROJECT_STATE.json decision C4-ROUND1-2026-10-05 is authoritative:

- Score 0–100 is a filter, not evidence that higher scores imply better edge; C4 owns the corresponding copy and future ranking policy.
- C4 replaces per-symbol Stocks backtest gating with pooled strategy × direction net-CI verdicts; per-symbol evidence remains an enough-data check. Verdicts await C4 round 2.
- Options R/R thresholds stay 2.0 PASS / 1.5 CAUTION on the full-premium basis; outside S2.
- Earnings veto is max(reject_days, hold_max) per horizon; C4 owns that policy.
- Bearish auto-arm is disabled pending qualifying per-strategy evidence. S2 must not reintroduce it through after-scan continuation.
- Shared scan/evidence exclusions cover CTVA until adjusted, AVB/confirmed-delisted names and flagged evidence symbols; C4 owns the authoritative list and scope.

S2 remains workflow wiring only. Original preservation requirements apply to arithmetic, model inputs, method picks, scan identity, save-before-send, server account/risk authority and durable mutation bookkeeping. Current per-symbol gate labels/thresholds and PASS eligibility are not frozen future invariants. After C4 decisions and interface review, S2 consumes the authoritative gate/provenance/eligibility contracts on its implementation baseline; it never fabricates pooled verdicts, exclusions or bearish permissions.

## Deferred C4 integration

C4 round 2 must settle pooled verdicts and the detailed validation/label contract from strategy_matrix evidence. User Q3 settles visibility for research, the Unvalidated label for awaiting-validation bearish strategies and disabled automatic arming; manual broker-send policy is settled by Q4: block until validation requirements are met; research/analysis remains allowed and save-for-research is not inferred blocked. Q5 settles confidence de-overlap, minimum 20 and missing confidence as Unvalidated. Q6 applies the same research-only execution policy to bullish strategies missing required validation; the exact consuming contract still requires review. Do not request these facts from the user when evidence or a C4 plan can establish them. When C4 contracts become available, the coordinator records their exact reviewed decision/plan references before authorizing validation-dependent execution; W1 workflow implementation does not wait for those contracts.

## Review and release gates

1. User approval of the remaining scope, mockup, testing seams and W1–W4 drafts is granted, including beginning workflow implementation without waiting for C4.
2. Independently review changed plan scope/interactions under the repository audit gate, preserving the prior two plan rounds and stage cap; no reset or fourth round. If reconciliation cannot fit the existing audit allowance, stop and ask the user for an explicit remedy.
3. W1 may begin on current main after a clean final qualifying plan review, finalized tickets and phase claim. It must supply the fail-closed validation availability/eligibility boundary described below; missing C4 evidence does not block workflow implementation.
4. Only after the plan gate and approval may the coordinator finalize Markdown tickets. Recheck main/shared claims before taking the phase claim; fresh implementer per ticket, W1 → W2/W3 → W4. No application merge without explicit user authorization.
5. GitHub issues, comments, dependencies and assignments remain unverified; no local draft asserts absence of remote work. When access returns, reconcile these records with existing issues before creating duplicates or assigning work. Native dependency links may then be added; Markdown relative links provide the current explicit graph.

## Audit history

Original plan rounds 1 and 2 reviewed baseline 6b1ee21d and closed clean. No audit has reviewed this addendum or Markdown drafts. Zero code rounds. Tests are verification, not qualifying audits.

## Consolidated user decisions Q3–Q6 (draft behavior)

- Q3: awaiting-validation bearish strategies remain visible for research, clearly Unvalidated; automatic arming disabled.
- Q4: research/analysis allowed; manual broker sending for Unvalidated bearish strategies blocked until strategy validation requirements are met. This does not prohibit saving research. Automatic arming and manual broker sending are separate gates.
- Q6: bullish strategies missing required validation follow the same research-only policy as bearish: visible for analysis, clearly Unvalidated, automatic arming and manual broker sending blocked. No prohibition on research saves is inferred.
- Q5: count non-overlapping confidence samples; retain minimum 20; missing confidence is Unvalidated, never PASS. Q6 settles the execution policy symmetrically: bullish strategies missing required validation also remain research-only, with automatic arming and manual broker sends blocked.

These are approved design decisions, not implemented or independently audited behavior. Pooled strategy verdicts still require actual strategy_matrix evidence and reviewed C4 contract.

Symmetric Q6 acceptance (draft): consume the reviewed validation contract for both directions at automatic-arm and every direct/basket broker-send entry point. Missing required validation blocks execution, not research/analysis or research saves. Missing strategy_matrix evidence cannot be treated as a positive pooled verdict.

## Latest authorization: begin S2 without waiting for C4

User explicitly approves the remaining artifacts and starting S2 workflow implementation without waiting for C4 evidence. This supersedes earlier C4-first sequencing statements in these drafts. Begin only after the fresh independent third/final plan review reports zero gate findings and required phase claim succeeds. Historical two plan rounds remain counted; no fourth round or reset. Main merge remains unauthorized.

W1 implements current-main workflow wiring and a fail-closed validation availability/eligibility boundary consumed by automatic arm, direct card send and basket send entry points. Without an authoritative reviewed validation contract, research/analysis and research saves remain available; automatic arming and manual broker sending are blocked for BOTH directions. Existing per-symbol PASS is historical/current scan evidence and cannot masquerade as the new strategy validation approval. No fabricated pooled verdicts. Do not disable the research-only save path or conflate it with broker sending. An already-started mutation completes bookkeeping against its originating identity; the new eligibility boundary must not erase pending/ambiguous outcome ownership or enable retries.

S2 does not implement C4 model, confidence sampling/calculation or data-exclusion policies. Approved Q3–Q6 describe the required safety/visibility behavior; the separate C4 work supplies authoritative reviewed contracts later. Avoid freezing a proposed C4 schema: represent unavailable validation explicitly and adapt to a reviewed contract when it exists. Until then application workflow can function for research only. Preserve arithmetic, explicit method picks, server risk/account authority, save-before-send, scan ownership and durable mutation tracking. No live broker activation.

## W1 execution boundary acceptance

Deny every NEW broker request or automatic-arm mutation unless a trusted reviewed validation authority explicitly permits the execution and matches strategy, direction and the current scan/request provenance. While C4 authority is unavailable, no such permission exists: all workflow surfaces are research-only. A legacy/current per-symbol PASS, method pick, hydrated field, same-symbol prior scan or UI-enabled control is never a substitute authority. Capture and recheck eligibility at the actual request/mutation boundary, including after asynchronous prerequisites, rather than relying on rendering alone.

Cover direct-card limit/market sending, Position sends, basket initial sends and retry paths, explicit automatic arms and automatic after-scan portfolio saves when those saves arm server execution entries. Classify research saves separately: a benign research save remains available only if it does not implicitly arm or send. Restored state must not restore trusted permission or bypass request guards. Store provenance alongside validation availability without inventing/fixing a future C4 schema.

Guard new execution only. Do not block cancellation, status polling, reconciliation or finishing bookkeeping for already-started save/order mutations; preserve captured identity, durable pending/unknown/placed outcomes and retry refusal. Validate unavailable authority, forged/restored permission, strategy/direction/scan mismatch, async eligibility change and basket retries by asserting no outgoing arm/broker request; verify benign research saves and existing-order recovery still work. No live trading activation.
