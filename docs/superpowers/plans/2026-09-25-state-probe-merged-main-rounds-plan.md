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
honest count of 3. The drift cleared only once the branch reached main.

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

**Residuals** (round 1; the helper's docstring states them too):

- **SILENT, ACCEPTED by Kenneth** (decision STATE-PROBE-SILENT-SIBLING-ROUND-ACCEPTED-2026-09-25). Suppose a sibling branch was cut from main
  before this piece opened. It carries a round of *this* piece, and it reaches
  main before the branch merges main. The fix drops that round.
  - In git's graph it looks exactly like another piece's merged round, so git
    cannot tell the two apart.
  - It is the unnarrowed span's existing rule (merged rounds are out of range)
    applied to the narrowed span.
  - Pinned by T5.
- **LOUD: a sibling's rounds for another piece.** If they have not reached
  main, they still count against this one.
- **LOUD: only the resolved tightest ref is excluded.** If that ref lacks the
  merged main commits, their rounds still count. Excluding every candidate ref
  would fix this, but only by widening the silent case above.
- **LOUD: merge subjects.** This branch's own "Merge origin/main (X round N)"
  subject still counts.
- **Pre-existing, unchanged.** Suppose a sibling cut from the feature *after*
  the introducing commit reaches main. Then main contains the introducing
  commit, no narrowing happens, and that round is out of range.

## 3. Tests (backend/tests/test_state_audit_bookkeeping.py)

| Test | What it pins |
|---|---|
| T1 `test_rounds_merged_in_from_main_are_not_this_pieces` | A decision commit, then the piece opens and runs round 1. Main gains "round 4" and the branch merges it. The piece records 1, clean. Result: None. It fails on the old code. |
| T2 `test_merging_main_does_not_hide_this_pieces_own_undercount` | After the same main merge, round 2 on the branch with 1 declared is still drift. |
| T3 `test_a_rounds_arriving_by_a_sibling_merge_still_count` | A round-3 subject arriving through a sibling-branch merge is still drift. This separates `^merged_ref` from `--first-parent`. |
| T4 `test_the_merged_main_entrys_verify_probe_tracks_the_exclusion` | The entry's presence probe dies when either half is reverted: the `^merged_ref` append, or the call-site argument. |
| T5 `test_this_pieces_round_that_reached_main_first_is_dropped` | Pins the silent residual. |
| T6 `test_the_excluded_ref_is_the_resolved_base_not_a_fixed_name` | With a stale local main and an advanced origin/main, the exclusion is origin/main. |
| T7 `test_a_malformed_merged_ref_degrades_to_no_evidence` | `HEAD~1` is refused by the shape guard (M4). |

Mutations, all killed:
- M1: `--first-parent` instead of `^merged_ref` (T3, T4).
- M2: the call site drops `base_ref` (T1, T4).
- M0: the whole fix reverted (T1).
- M4: the `merged_ref` guard removed (T7).
- M6: a hardcoded `^main` (T4, T6, T7).

## 4. State

- A new `already_shipped` entry, STATE-PROBE-MERGED-MAIN-ROUNDS, with a
  presence probe over both halves.
- `active_phase` points at the new entry.
- The decision is recorded.
- The count is recorded per audit. Commit subjects name a round only once the
  file declares it.

## Audit rounds

**Round 1: plan and code together, fresh subagent. NOT CLEAN.**

The plan was built before its audit, so this round audited the plan and the code
together.

- **Blocking (1).** The silent residual above was undocumented. It is now
  documented, pinned by T5, and put to Kenneth.
- **Non-blocking, all taken:**
  - The loud residuals and the pre-existing case are documented.
  - The guard is tested, by T7.
  - The resolved-base test, T6, is added.
  - The misquoted count (1) is corrected to 3.
  - The `updated_by` chain is restored.
  - The build-before-audit order is recorded.
- **Noted:** the probe pattern depends on the helper appearing before the call
  site in the file.

**Kenneth's call (2026-09-25):** accept the silent residual as documented and pinned (T5). Round 2 next.
