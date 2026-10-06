# STATE-AUDIT-MULTI-PHASE: explicit audit ownership

User requested this separate checker fix while P0B (#79) is paused. Tracking #89. Branch codex/state-audit-multi-phase, cut from P0A a6aa7891. This is not a retry or reset of the capped STATE-PROBE-TARGET-SCOPING G3 finding (invented target/pointer can hide prior undercounts); that limitation remains recorded and untouched.

## Problem

P0A and P0B plans were introduced on the same branch. P0A then recorded `docs(state): STOCKS-HORIZON-P0A round 3 (code round 2) clean; code stage closed`. When the branch moves to P0B, `_target_scoped_base` correctly finds P0B's introducing commit, but `_round_numbers_in_branch_subjects` counts every round subject after it. P0B honestly declares two plan rounds, and the checker incorrectly attributes P0A's third round to it. The function documents this cross-piece false alarm.

## Narrow behavior

1. Recognize ownership ONLY for canonical subjects beginning `docs(state): <FULL-PHASE-ID> round N` (also permit `plan round N` or `code round N` immediately after the ID). Match the ID as a whole token and case-sensitively against known `phases[].id` values. Other subject formats and shorthand remain unowned evidence.
2. Pass the resolved active phase identity and the known phase IDs into `_round_numbers_in_branch_subjects` through optional keyword arguments. Existing callers without them keep their current behavior. If the active pointer does not resolve to a phase, retain all evidence as today.
3. Skip a round subject only if its canonical owner is a known DIFFERENT phase and the active phase's full ID is absent as a whole token from the rest of that subject. A subject naming the active phase anywhere remains evidence, including mixed ownership/interaction subjects. Unknown, shorthand, ambiguous and unowned subjects remain evidence. Do not infer ownership from arbitrary occurrences of IDs or from commit bodies.
4. Correct the second reproduced false alarm: the historical unowned subject `docs(state): P0A plan round 1 clean; P0B plan round 1, 3 findings fixed in the plan` is currently parsed as round 3 by the numeric-list regex. In a SINGULAR `round N, K findings` match, do not count an implicit continuation number K immediately followed by the word findings (case-insensitive, singular finding also allowed). Retain the primary round N, every independently/explicitly marked round/r-number, and all numbers in explicit plural `rounds N, K` lists even if followed by findings. Other number forms stay conservative evidence. This parsing correction applies to all helper callers; only ownership filtering remains opt-in. Test real historical subject and direct/singular/plural/multiple-round edge cases. Do not skip the whole mixed/unowned subject.
5. Keep introducing-commit scope, ancestry, merged-ref exclusions, undercount/cap checks, all counters and strict audit_clean logic unchanged. Do not add editable boundary overrides, clear the pointer or increase counters to make an alarm disappear.
6. Update the function's documented cross-piece limitation to distinguish explicit ownership from residual unowned/shorthand alarms. Document canonical audit-record subjects in docs/agents/ticket-orchestration.md.

## Tests first

Add focused real-git regressions in backend/tests/test_state_audit_ownership.py using the existing state test loader/helpers pattern:
- Active P0B (two recorded rounds), explicit P0A round 3 and state-prerequisite round 1: no false undercount/cap. P0B's own round 3 still fails against declared 2.
- Higher unowned round, unknown canonical owner, shorthand owner, other prefix and mixed subject naming active ID: retain evidence and fail on a real undercount.
- Whole-token ID matching (P0B vs P0B-EXTRA); absent/unresolved active pointer retains prior warnings.
- Default helper callers retain all ownership evidence; merged-history exclusion is unchanged. The singular-round finding-count correction applies to default callers too.
- Real historical mixed subject with round 1 and 3 findings counts round 1; standalone round 3 findings and explicit continuation round/r3 still count round 3; explicit plural rounds 1, 3 findings remains conservatively round 3; later separately marked rounds are retained; unknown/ambiguous counts not naming findings still count.
- Reproduce the real P0B branch alarm before the parsing change, then run the new checker against a detached verification checkout of P0B at 0ae9f121 without changing its state, counters or branch.

Run new tests red first, then implement only scripts/state.py and the lifecycle doc. Python 3.11. Run new ownership plus existing bookkeeping/built-status tests, frontend typecheck before commit. Coordinator verifies scope and results; full P0A backend suite is already running independently. A fresh independent reviewer applies the numeric/persistence and mechanism gate to the whole code change. Plan and code each cap at three rounds, with later rounds only fixes/interactions.

## Outcome

The actual P0B branch check passes without changing P0B's two plan rounds or P0A's clean audit record. Unknown/ambiguous evidence still alarms. Open a separate PR based on the P0A branch; never merge without the user's go. P0B stays paused until this separate prerequisite is verified and its continuation is authorized.

## Plan correction after implementation check

2026-10-06: the ownership implementer reproduced the additional finding-count parse defect on the actual P0B history. It stopped before committing, with the narrow ownership patch preserved. This correction addresses only that defect and its interaction with ownership filtering; plan round 2 reviews this text diff against the real parser/history. No extra P0B audit round is claimed; P0B remains paused.
