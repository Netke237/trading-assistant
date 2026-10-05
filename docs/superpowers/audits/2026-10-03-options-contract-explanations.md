# Contracts explanation implementation audit

Verdict: implemented on a feature branch, but not audit-clean or ready to merge. Four confirmed numeric defects remain. No application source was changed, merged or pushed during this audit.

GitHub branch: `feat/options-contract-explanations`.
Exact reviewed commit: `ac39b8416bb4f778eb85cb3f53baeb49c0579cfd`.
Base: `1c8b94ffb9bd177f68d9383423aaa10e7e2065df`.

Reviewed implementation on GitHub: https://github.com/Netke237/trading-assistant/commit/ac39b8416bb4f778eb85cb3f53baeb49c0579cfd

This publication includes the audit report only. Files under `/workspace` mentioned below are local execution evidence and are not included in this GitHub commit. The findings, triggering inputs, reviewed revision and validation outcomes are recorded here so another agent can reproduce them without those local files. Check the exact reviewed commit when interpreting line numbers; later revisions may differ.
`main` still points to the base and contains the plans only. The implementation appeared in a later fetch; this supersedes the earlier broad claim that no published implementation could be found. It implements Contracts Step 6, not the separate Volatility & Events Step 5 plan.

Reviewed all changed application files, published plan and measurement/test artifacts. Fresh independent reviewers `/root/crosscheck_pasted_claims` and `/root/backend_explanation_audit` applied the repository's K-adversarial-audit-loop/bmad-review-adversarial-general instructions and numeric/persistence gate. Their reports are in `/workspace/pasted-claims-independent-crosscheck.md` and `/workspace/backend-explanation-audit.md`. This is a user-requested verification of the published code; existing plan/code counters were preserved.

## Confirmed blocking findings

1. **IV weight falsely shown as zero.** `frontend/app/(frame)/screener/step-6-contracts/page.tsx:118` reads `weights.iv`, while the scorer sends `weights.iv_rank`. A normal 15% IV weight becomes “IV 0%” in Rules applied. Read the actual authoritative key and refuse missing weights rather than fabricating zero.
2. **Wide spreads understated 100-fold.** `frontend/lib/contractExplanation.ts:71` guesses percent scaling from magnitude. For bid .10/ask .90, the scorer supplies fraction 1.6, meaning 160%; the panel renders “1.6%”. Format using the known metric unit/basis, multiplying spread ratios by 100 throughout their valid range.
3. **Fractional preferred ceiling changes meaning.** `frontend/components/molecules/ContractScoreExplanation/index.tsx:170` rounds the preferred spread ceiling to an integer percent. Override .0555 means 5.55%; observed .056 correctly receives a zero spread sub-score, but the panel shows “5.6% (≤6%)”, placing it inside the displayed acceptable range. Preserve meaningful boundary precision with accessible exact values. Delta and weight formatting also warrant the same precision review.
4. **A blocker displays a false inequality.** `backend/app/scoring/contract_validator.py:556` rounds the observed spread operand before sending it. Bid 2.05/ask 2.15 gives .04761904761904767, which correctly exceeds an allowed effective hard ceiling .04761. The structured explanation rounds this to .0476 and the UI renders “0.0476 > 0.04761”, which is false. Preserve the actual guard operands in the wire model and format comparisons without reversing their meaning.

All four were independently reviewed and reproduced by the primary agent. Real production Chromium rendering with scorer-generated, Pydantic-validated payloads is captured in `/workspace/options-ui-probe.log`; repeatable helpers are `/workspace/options-ui-probe.cjs` and `/workspace/options-wire-probes.json`. No assertion or application behavior was changed to obtain these reproductions.

## Completed validation of this implementation

Source was extracted with `git archive` into `/workspace/audit-options` for testing, without creating a Git worktree or changing the main checkout. Runtime: Node 20.20.2, Python 3.11.16, installed Playwright Chromium. Browser checks used this commit's production build on port 3002.

- Frontend: **187 suites, 4,511 tests passed**; typecheck and production build passed.
- Primary focused backend selection: **121 passed** (explanation, validator, route/scoring, Step 6 rules, watched grading).
- Independent backend selection including DTE: **107 passed**. These overlap the primary selection and must not be summed.
- Independent exact old/new scorer comparison: **10,000 deterministic fixtures** preserved score/status/reasons/flags/breakdown/detail after excluding the newly added explanation.
- Published explanation layout, performance and IV rendering browser suites: **11 passed**. This is separate from the earlier 21-smoke-test run against main.
- Current production performance test: toggle p95 100ms, sort 46ms, pick 114ms; no reported interaction long tasks >100ms; ten detail regions open. These are the harness's measurements, not acceptance of the full planned performance workload.
- Main checkout remains clean. No feature merge, publication or fresh-task restoration was performed.

Logs: `/workspace/options-jest.log`, `/workspace/options-backend-tests.log`, `/workspace/options-build.log`, `/workspace/options-typecheck-final.log`, `/workspace/options-browser.log`.

## Requirements still unmet or unsupported

- The supplied Stage C report uses development mode and asserts production will be faster. The plan requires a matched production baseline/after trace and ≤20% regression. A fast production rerun does not supply the missing baseline.
- The stress harness loads 200 contracts but opens only one group and ten explanations. It does not exercise all twenty groups with 0/1/200 panels as required.
- Initial requests are asserted only as ≥20. The production rerun logged 39 requests; the test does not compare exact initial/rescue counts with a matched baseline. No redundant-request defect is concluded without that comparison.
- The original report records Python 3.12 despite mandatory 3.11. This audit's executed backend checks use 3.11; it does not retroactively validate the earlier runtime claim.
- The claimed clean code audit records no reviewer, exact reviewed diff, findings/fixes ledger or qualifying independent verdict in its cited measurement report. The state says one clean round and four fixes. That metadata alone cannot substantiate the required audit gate; this verification found four actual defects.
- Version/identity/nested-number validation is incomplete. `validateExplanation` accepts unknown versions and never matches explanation contract_id to the row. No present normal-server identity mismatch was reproduced, so this is a required defensive coverage gap rather than an invented current-path bug.
- The server snapshot lacks nonblocking hard bounds and separate raw-presence fields for normalized missing volume/OI/delta. The rounding test calls Python round directly rather than producing the specified scorer tie fixtures. These are plan coverage gaps, separate from the four reproduced numerical failures.
- Layout tests do not establish all planned long-label/bear-call/zoom/clipping cases. Some internal overflow metrics are collected but not asserted; document-level non-overflow alone cannot certify absence of clipped contents.

## Required next steps

Correct the four numerical defects and add independent boundary assertions that fail on these actual reproductions. Complete the missing snapshot/defensive and layout/performance acceptance coverage. Obtain a fresh qualifying independent review of the fixes and their interactions within the repository's recorded stage cap; preserve the audit ledger and distinguish verified results from claims. Until then, the feature branch's shipped/clean labels are unsupported. No clean audit or merge authorization is claimed here.
