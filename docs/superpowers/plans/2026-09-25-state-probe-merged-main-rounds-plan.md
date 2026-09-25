# STATE-PROBE-MERGED-MAIN-ROUNDS — plan (2026-09-25)

Decision: STATE-PROBE-MERGED-MAIN-ROUNDS-2026-09-25 (Kenneth: "Agree. Go!").
Deferred from the MANUAL-IBKR-CONFIRM-AS-ERROR handoff.

## 1. The defect

`audit_bookkeeping_drift` reads the highest `round N` in commit subjects over
`_target_scoped_base(base_ref, state)..HEAD`. When the active entry was introduced
on the branch, the scoped base is that introducing sha. `sha..HEAD` excludes only
the ancestors of `sha`. So once the branch merges `origin/main`, the span takes in
every main commit that landed after `sha`, including other pieces' already-merged
round subjects.

Seen live: A5c's "round 4" subject raised drift on MANUAL-IBKR-CONFIRM-AS-ERROR's
honest count of 1. The drift cleared only once the branch reached main.

The unnarrowed path (`base_ref..HEAD`) never had this problem, because main's
commits are ancestors of `base_ref`. The boundary walk in `_target_scoped_base`
already reads `base_ref..HEAD -- <state file>`, so it never sees main's commits
either.

## 2. Change (scripts/state.py only)

- `_round_numbers_in_branch_subjects(base_ref, merged_ref=None)`:
  - When `merged_ref` is set and differs from `base_ref`, it runs
    `git log --format=%s <base_ref>..HEAD ^<merged_ref>`.
  - `merged_ref` passes the same ref-shape guard, or the function returns None.
    This is the same degrade as today's guard.
- The call in `audit_bookkeeping_drift` passes `base_ref`, the resolved tightest
  of origin/main and main, as `merged_ref`.

**Why not `--first-parent`.** It would also drop this branch's own commits that
arrive through a sibling-branch merge. MANUAL-IBKR-CONFIRM-AS-ERROR's decision
commit came in exactly that way, from claude/jolly-thompson-0q7paq. Those are the
rounds an undercount can hide in. `^merged_ref` drops only what main already
carries, which is the scope the unnarrowed path already uses.

**Unchanged:**
- The one-directional rule.
- The hard cap.
- The unphased banner.
- The introducing-commit boundary.
- Base-ref resolution.

**Accepted residual.** A sibling branch's rounds for a *different* piece still
count against this one. This is a false alarm: it is visible, and it clears when
the count is recorded or the work is merged. It has not been seen in practice.

## 3. Tests (backend/tests/test_state_audit_bookkeeping.py)

| Test | What it pins |
|---|---|
| T1 `test_rounds_merged_in_from_main_are_not_this_pieces` | A decision commit, then the piece opens and runs round 1. Main gains "round 4" and the branch merges it. The piece records 1, clean. Result: None. It fails on the old code. |
| T2 `test_merging_main_does_not_hide_this_pieces_own_undercount` | After the same main merge, round 2 on the branch with 1 declared is still drift. |
| T3 `test_a_rounds_arriving_by_a_sibling_merge_still_count` | A round-3 subject arriving through a sibling-branch merge is still drift. This separates `^merged_ref` from `--first-parent`. |
| T4 `test_the_merged_main_entrys_verify_probe_tracks_the_exclusion` | The entry's presence probe dies when either half is reverted: the `^merged_ref` append, or the call-site argument. |

Mutations, all killed:
- M1: `--first-parent` instead of `^merged_ref` (T3, T4).
- M2: the call site drops `base_ref` (T1, T4).
- M0: the whole fix reverted (T1).

## 4. State

- A new `already_shipped` entry, STATE-PROBE-MERGED-MAIN-ROUNDS, with a
  presence probe over both halves.
- `active_phase` points at the new entry.
- The decision is recorded.
- The count is recorded per audit. Commit subjects name a round only once the
  file declares it.

## Audit rounds

(none yet)
