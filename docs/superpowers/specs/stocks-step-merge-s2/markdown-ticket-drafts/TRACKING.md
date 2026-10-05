# STOCKS-STEP-MERGE-S2 — Markdown tracking draft

Status: approved artifacts / blocked pending final qualifying reconciled-plan audit and phase claim. C4 is not a start blocker.
Coordinator owns this tracking record. No phase claim taken; no implementer assigned.
GitHub issue number: unknown. Existing issues/comments/assignments: unverified because API access is blocked. User explicitly authorizes Markdown fallback; do not interpret unknown as absent.

Scope and gates: [reconciliation draft](../reconciliation-draft.md), [original audited specification](../spec-and-breakdown.md), [mockup](../workflow-mockup.html), [historical audit](../plan-audit.md).

| Draft | Blocked by | Owner when released | Status |
|---|---|---|---|
| [W1](W1.md) | final qualifying reconciled-plan audit, finalized ticket and phase claim | Fresh implementer | Draft / blocked |
| [W2](W2.md) | W1 verified | Fresh implementer | Draft / blocked |
| [W3](W3.md) | W1 verified | Fresh implementer | Draft / blocked |
| [W4](W4.md) | W2 + W3 verified | Fresh implementer | Draft / blocked |

W2/W3 parallel only after W1 interfaces are frozen and ownership is disjoint. Coordinator alone owns state, tracking and independent phase audits. Every ticket is a build unit; integrated phase is the code audit target. Preserve three-round caps per stage and prior historical counters. No implementation or merge is performed by these drafts.

User has approved the remaining mockup/testing seams/breakdown and changed sequencing to start without waiting for C4. A clean final qualifying plan review and phase claim remain required. GitHub reconciliation remains explicit deferred work.

Latest user decision Q3: awaiting-validation bearish strategies remain visible for research, clearly Unvalidated, with automatic arming disabled. This is proposed behavior awaiting implementation/review. User Q4 allows research/analysis and blocks manual broker sending until strategy validation requirements are met. Automatic arming remains independently disabled. Save-for-research is not inferred blocked.

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

## Coordinator release

Independent plan round 3 returned zero gate findings; see [review record](../plan-audit-round3.md). User-approved Markdown tickets are finalized. Phase claim STOCKS-STEP-MERGE-S2 acquired on codex/stocks-s2-markdown-draft. W1 assigned next; W2/W3 blocked on verified W1; W4 blocked on W2/W3. Application work remains unaudited until integrated code review.
