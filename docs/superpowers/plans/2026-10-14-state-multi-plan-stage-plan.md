# STATE-MULTI-PLAN-STAGE — explicit additional plan stages

Board item #214. Scope: `scripts/state.py`, state checker tests and `docs/superpowers/STATE_TRACKING.md`. No application, broker, model, YAML-loader or other agent's phase changes. Python 3.11 for backend tests. Every plan/code stage retains its existing three-round cap; target totals and subject round numbers remain continuous.

## Problem and source facts

`_plan_stage` accepts only one plan boundary 1..3, while the user authorized TRADIER-GOVERNOR's second stage (continuous plan rounds 4..6) with `TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10`. `_staged_hits` distinguishes explicit plan, local code and paired continuous/code numbers. `_stage_round_max` then subtracts the single plan boundary from continuous subjects. Current tests use real temporary git repositories to prove subjects and target-introduction scope are actually read. Preserve those paths and the accepted limitations: editable identity resets, subject-only evidence, and the fact the checker cannot independently certify a reviewer verdict.

## Additive record contract

Legacy `plan_stage` records and missing stage metadata keep their existing behavior byte-for-byte, including warnings, permissive decision-target closure rules and stage-subject inference. Implement the new path only when `plan_stages` is present. Do not silently fall back to legacy metadata if new metadata is malformed. Both singular and plural fields on one target are ambiguous: reject plural metadata visibly rather than choose the convenient boundary.

`plan_stages` is a nonempty ordered array of stage objects:

```json
[
  {"rounds": 3, "closed_by": "TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10"},
  {"rounds": 3, "opened_by": "TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10", "closed_by": "clean"}
]
```

`rounds` is a local integer 1..3, excluding booleans, floats and numeric strings. Continuous endpoints are derived by cumulative sum, never editable offsets. Sum cannot exceed a valid declared `audit_rounds`. All stages before the last must be closed. The final stage may be open (absent `closed_by`) so a newly authorized stage can run its first and second rounds without inheriting the previous cap; it still escalates at its own third round without clean closure. Empty/zero-round future stages are not allowed; record a stage when its first audit runs, not to buy unused headroom. No extra clean boolean grants permission or closure.

Every stage after the first requires `opened_by` identifying a unique decision in root `decisions[]`, naming this target as a whole token, and explicitly authorizing this NEXT plan interval. Mere existence or mention of the target is insufficient. The preceding stage must close either clean or by that same opening decision; a different unrelated decision cannot bridge a capped stage into a new one. Do not edit existing decision text or invent an authorization.

Opening proof is deliberately strict: decision `a` must contain an affirmative unnegated opening declaration with an explicit `plan rounds START-END` range (hyphen or en dash), where START is the prior cumulative endpoint plus one and END is START+2. Match a bounded declaration containing `open`/`opens`/`opened` then `new plan stage` then `plan rounds START-END`, allowing the existing TRADIER phrasing `open ONE new plan stage (up to 3 rounds, plan rounds 4-6 overall)`. Case-insensitive. Reject locally negated opening declarations (`not`, `never`, `no`, `don't`, `cannot`, `decline`, `reject`, etc.) and ambiguous/multiple matching declarations; decision IDs must be unique. A question in `q` is not an affirmative answer. The target token can be in the decision object (as in the existing record's `q`), but the affirmative opening/range must be in `a`. Future decisions should use the documented canonical wording `Open one new plan stage: plan rounds START-END`. This is a conservative recognizer of recorded authorization, not natural-language inference or a permission source.

Closure `clean` needs canonical positive `plan round CONTINUOUS-END clean` branch-subject proof using existing clean/negation matching, not a local stage number or an arbitrary clean field. Closure by decision is valid ONLY for an earlier stage immediately followed by the next stage, and must be that next stage's verified opening decision naming the exact target. The final stage must remain open or close through verified clean evidence; an unpaired decision closure is invalid even if the decision mentions the target or acknowledges its findings. Historical stage counts >3 are always invalid; a later clean verdict or authorization must not hide a fourth round in the same stage. No global `audit_clean` value overrides invalid plural metadata.

## Evidence and cap handling

Retain target identity/base resolution, ownership filtering, subject extraction and the existing undercount check before stage handling. Under-counted totals are still drift. Parse explicit plan numbers continuously and locate them in cumulative stage intervals. Explicit plan numbers greater than the last declared endpoint contradict the record; do not treat them as code. Opening range proof prevents deleting/shortening an exhausted stage to shift later evidence into a new one. Closed-stage clean proof binds each endpoint; reject contradictory negative clean proof at that same endpoint conservatively. Require a capped non-clean earlier stage to close through the verified next-stage authorization, not generic acknowledgement.

If the final plan stage is open, known explicit code-stage evidence is premature and invalid, not a means of suppressing its cap. Continuous untagged subjects beyond the final recorded plan endpoint must not gain a speculative code offset while that stage is open. Infer explicit/stage-word forms with existing `_staged_hits` rules and preserve ambiguity conservatively rather than reset counts.

After ALL recorded plan stages close, code begins after their sum. Reuse `_staged_hits(subject, TOTAL_PLAN_ROUNDS)` and `_stage_round_max(subjects, TOTAL_PLAN_ROUNDS)`: explicit local code round K remains K, paired continuous M/code K recognizes M-TOTAL=K, and untagged continuous rounds subtract total. The code stage at 3 without overall `audit_clean is True` remains drift; fourth code round in the plural path is always drift, even if overall clean is true. Explicit plan evidence outside recorded intervals, an invalid record or authorization always produces drift with a precise reason; no fallback that can render 'No drift'. Missing git evidence/base keeps existing 'could not run' behavior; metadata validation runs when the resolved target has round evidence, as today.

Keep historical same-stage cap semantics: an open plan stage at its third non-clean round escalates; a recorded verified clean plan close moves to code round zero; explicitly authorized next stage moves to that stage's first actual round. Do not let a fourth round be relabeled by an authorization whose stated interval does not match.

## Build tasks (fresh implementer per task; cut after clean plan audit)

### T1 — Checker and real-git regressions

Allowed files: `scripts/state.py`, new `backend/tests/test_state_multi_plan_stage.py`; existing state test files only if a shared fixture must be imported without changing baseline assertions. Keep diff around 500 lines or less. Add helpers with stable narrow contracts; leave the legacy `_plan_stage` implementation intact. The completed-target presence marker is `def _plan_stages`.

Tests first and confirm RED on actual current false-positive: three non-clean plan subjects, authorized opening, plan rounds 4/5 and positive clean 6, optional code round 7 (code 1); truthful total and plural record yields no drift. Test real TRADIER decision text loaded from main's state, no hard-coded approval based on its ID. Do not mutate that historical phase on main or its branch.

GREEN matrix: second stage open local round 1/2 passes, local round 3 unclean trips; positive final clean at continuous 6 moves to code; code rounds 1/2 pass, 3 unclean trips, 4 always trips. Every stage's fourth round trips even if global audit_clean true. Test third authorized stage, clean first stage reopening requires approval, absent/wrong-target/unrelated/duplicate decision, q-only opening, negative or ambiguous a, wrong opening numeric range, stage removal/reordering/shortening, malformed rounds/list/object, simultaneous singular/plural, missing closure, unpaired acknowledgment closure at the final cap (with and without following code evidence), missing/negated/mismatched clean evidence, explicit later plan, premature code, untagged evidence while open, count under-report, already_shipped target and canonical ownership filtering. Run all three existing state test modules to ensure legacy inference/caps/ownership still pass. Preserve numeric total/clean reporting without silently rewriting persisted audit history.

Full frontend typecheck/tests required by implementer brief; Python 3.11 focused state suites and full backend. Environment-only Telegram settings may be scoped out for test process, not changed in repository. If full checks expose an unrelated failure, isolate and document rather than alter other agents' packages.

Commit: `feat(state): validate explicitly authorized multiple plan stages`.

### T2 — Documentation and end-to-end verification

Allowed files: `docs/superpowers/STATE_TRACKING.md`, new `docs/superpowers/plans/2026-10-14-state-multi-plan-stage-validation.md`, tests from T1 only for missing externally observable coverage. Fresh implementer documents exact record schema, cumulative numbering, opening decision proof/canonical wording, legacy compatibility and conservative invalid-metadata failure behavior. Show the actual TRADIER decision + normalized record as an EXAMPLE, without altering that phase or claiming another phase now audited/shipped.

Verify subprocess exit statuses on synthetic real-git states with probe files so valid two-stage state returns 0 and cap/missing authorization returns 1; ensure this tests `main`, not only helper methods. Document focused/full results and actual numeric conditions without resetting any other counters. Shared `PROJECT_STATE.json` is coordinator-owned only, merged with current main before integrated code audit. Commit: `docs(state): explain explicit plan stage reopening`.

## Audit and shipping

This phase starts plan/code rounds at zero; existing historical phases stay unchanged. Fresh independent gate auditor reviews plan round 1 against sources. Maximum three per stage, follow-ups only fixes/interactions. Child tickets only after clean plan. Fresh implementers; integrated target `origin/main..HEAD` after merging main, with conflicts/tests reconciled. Gate only wrong displayed/order numbers, persisted-data corruption or mechanism claims that induce wrong change; checker integer counters/boundaries and persistent audit history qualify. Do not fix accepted unrelated historical gaps. Record reviewer/exact diff/findings/fixes/outstanding in coordinator state, and ship only through exact-head audited CI self-merge rules. Documentation follow-up records verified merge, never anticipated success.
