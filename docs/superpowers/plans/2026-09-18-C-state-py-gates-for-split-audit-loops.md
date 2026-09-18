# Piece C — how a piece crosses `state.py`'s gates when the plan and the code are audited separately

**Date:** 2026-09-18
**Status:** OPEN QUESTION — not planned, not audited, not implemented.
**Split from:** `2026-09-18-auto-trader-direction-sizing-plan.md` (Piece A) after its round 3
fired audit_rule's hard cap. This was round 3's BLOCKER, and it is a **tooling/bookkeeping**
question, not an engineering one — which is why it does not belong in a plan about position
sizing.

---

## 1. The contradiction, verified by simulation

Round 3 established this by **simulating `state.py`**, not by reasoning about it.

Piece A's §4 requires `python3 scripts/state.py` to exit 0 at the fix commit. **That is
unreachable.** Two independent gates fire:

1. **The declared/actual gate.** `state.py:625-635` computes `declared_shipped = ph["status"] in
   SHIPPED` where `SHIPPED = {"shipped", "shipped_unaudited"}` (`:65`). The probe is a regex
   presence test, so the moment the fix line lands the pattern is found, `actual_shipped`
   becomes true, and `"in_progress"` puts the phase in `drift`. Flipping `status` to `shipped`
   in the fix commit is **necessary**.
2. **The resolved-path hard cap.** It is **not sufficient.** `git_max >= 3 and not audit_clean`
   fires as well, because this branch carries a **round-3 subject** and `git_max` is read from
   branch commit subjects (`_round_numbers_in_branch_subjects`, `:157-167`, regex
   `\bround\s+(\d+)`, case-insensitive).

All four combinations were simulated at `git_max=3`. **Only `shipped` / 3 / `audit_clean=TRUE`
exits 0** — and setting that at the fix commit **would be a lie**, because at that commit the
CODE has had **zero** adversarial rounds. The three rounds audited the *plan*.

**The only reconciling value is a bookkeeping falsehood.** That is the finding.

## 2. Why this is structural, not a one-off

`git_max` counts round subjects **on the branch**, and cannot distinguish *"round 3 of the plan
audit"* from *"round 3 of the code audit"*. Whenever a piece is planned and audited to
convergence, then implemented and audited again, the second loop starts with the first loop's
round count already banked against it.

So this recurs for **every** piece that uses the plan-then-build shape — which is the shape
this project prefers for anything touching money.

## 3. The options, unweighed

None of these has been analysed; listing them is not endorsing them.

- **A fresh branch per loop.** Implement Piece A on a branch cut from `main`, so `git_max`
  resets to 0 and the code audit starts clean. Cheapest, no tooling change. Question: does the
  plan's audit history then become invisible where it matters?
- **Distinguish the subject.** Teach `_round_numbers_in_branch_subjects` to separate plan
  rounds from code rounds (e.g. a `plan round N` / `code round N` convention). Touches
  `state.py`, needs its own round.
- **Separate counters.** `plan_audit_rounds` vs `audit_rounds` in the phase entry. Most honest,
  most invasive.
- **Register the piece only when code lands.** Matches the existing note that O4 has no
  `already_shipped` entry because nothing is built — but Piece A's entry already exists and
  `active_phase` points at it.

## 4. What this blocks

Piece A **cannot satisfy its own §4** until this is settled. Piece A's engineering is converged
and implementable; what is not settled is how the repo's own instrument reports it afterwards
without someone writing a false value into `PROJECT_STATE.json`.

**Do not resolve this by editing a field to make a banner go green.** The banner is the
instrument working. `state.py` exits 1 on this branch today **by design** — `git_max` reached 3
with `audit_clean` false — and that clears by going clean or by merging, never by an edit.
