# How project state is tracked

Kenneth works across **two Claude accounts and many sessions**. Every session that
re-derives "where are we" from prose gets it subtly wrong, and the errors
compound: handoff #12 found a session that believed pieces were unbuilt which
were, and built which were not, and a `main` whose history had been re-created
without anyone noticing.

This is the fix. It has three parts and one rule.

## The single source of truth

**`docs/superpowers/PROJECT_STATE.json`.** Phase status, audit status, decisions,
open questions, what is waiting on Kenneth, the authoritative document list, and
the traps.

**Do not restate any of this in prose anywhere else.** A second copy is exactly
how drift starts. Handoffs describe *what happened in a session*; the state file
describes *where the project is*. When they would overlap, the handoff points
here instead.

## The enforcer

**`scripts/state.py`** renders the file as a table **and checks it against the
code.** Every phase carries a `verify` probe — a regex whose presence or absence
in a real source file is checked against the declared status.

**A probe pins that a symbol still EXISTS, never that it still BEHAVES as
described.** It is a presence test, so it catches a phase marked shipped whose
code was deleted, and it cannot catch code that drifted away from what the state
file says it does. Round 7 found the schematic asserting the opposite of shipped
`formatStopLossBadge` output under a green "No drift", and round 9 found two doc
blocks doing the same; a passing `state.py` is evidence the symbols are there,
not that the descriptions are true. Read the code for that.

```
python3 scripts/state.py           # render + check, exit 1 on drift
python3 scripts/state.py --quiet   # check only, silent when clean
```

Three probe kinds:

| kind | meaning |
|---|---|
| `present` | pattern found → the work is built |
| `absent` | pattern found → the work is built (declared not-built means it must be missing) |
| `defect_marker` | pattern found → the work is **not** built; the pattern *is* the unfixed defect |

`defect_marker` exists because Phase F needed it: `v0_grid` merely *existing* in
`heston_cache.py` says nothing about whether the calibration was fixed. The
hardcoded `[0.04]` literal is what says it was not. The first run of this script
caught that modelling error in its own state file — which is the point.

It walks **both** lists: `phases` and `already_shipped`. That is not a detail —
`already_shipped` means *the code is done*, never *the work is done*, and for one
round the script read only `phases`, so the stop-cost notation rework sat in
`already_shipped` with `audit_clean: false`, rendered as shipped, and was named
in no session's audit target list. A `verify` probe is optional on an
`already_shipped` entry (several predate the state file) but is checked exactly
as a phase's is wherever one is given.

Stdlib only, so it runs before any venv exists.

### The audit-bookkeeping probe

`verify` probes test code symbols. One more check tests the **bookkeeping
itself** — `audit_rounds` / `audit_clean` — against the only evidence git holds
that a round ran: a commit. (`audit_bookkeeping_drift` in `scripts/state.py`.)
It exists because three Phase A rounds once ran while the file said one, under
a green "No drift".

- **What it reads.** The highest round number in this branch's commit
  **subjects**, in any notation the repo uses — `round 3`, `round-3`,
  `rounds 6-7`, `r3`, `r1..r4`, `r2+r3` (lower-case `r` only; `R1` is a
  requirement id) — never bodies, which are full of legitimate backward references
  ("round 12's follow-ups"). Name rounds in subjects only for this branch's own
  piece, merge subjects included.
- **Against what base.** Asked of git, not the state file: `origin/main` or
  local `main`, whichever is tighter. Commits the base already carries are out
  of range, so merged work goes quiet on its own.
- **Scoped to the active target.** `active_phase` names the phase (or
  `already_shipped` entry) being audited. The span starts at the commit that
  **introduced that entry** — found by its parents (the entry is in it and in
  none of them), not by date, so merging a sibling cannot move it — and a
  branch carrying two pieces does not answer for the earlier one's round
  numbers. The pointer's value scopes nothing; if it resolves to no entry, the
  whole branch counts.
- **Known open hole (G3, not fixed).** Narrowing drops every round before the
  active entry's introducing commit, and nothing else checks them: committing
  a new entry and pointing `active_phase` at it silences the previous piece's
  undercount and its hard cap. Two attempted fixes (STATE-PROBE-FIXES rounds 3
  and 4) each failed review, so it was taken back out; see the
  STATE-PROBE-TARGET-SCOPING record in PROJECT_STATE.json. Until it is fixed,
  record a piece's rounds BEFORE opening the next one on the same branch.
- **Round notation also read:** `clean after 7 rounds` (number before the
  plural word), `rounds 1, 2 and 3`, `round #3`, `audit_r3`.
- **The tiers.**
  - Rounds in the subjects with **no target** counting them: **warn** below
    round 3, **drift** at 3.
  - A target that declares **fewer** rounds than the subjects reach: **drift**
    (a round ran and was never written down). Declaring more is not flagged —
    rounds can run without a commit.
  - **The hard cap:** the subjects reach round 3+ and the target's
    `audit_clean` is not the JSON value `true` (the string `"false"` is not
    clean): **drift** — *stop auditing and tell Kenneth*. It counts
    rounds continuously across a phase's stages and units, so a multi-unit
    package keeps `audit_clean` true while its latest round was clean.
  - **Per stage, once the plan stage is closed** (audit_rule counts the cap
    per stage, `AUDIT-CAP-PER-STAGE-2026-09-25`). Add to the target's record
    `"plan_stage": {"rounds": N, "closed_by": "<decision id>"}` (or
    `"closed_by": "clean"` when a clean plan round closed it). The cap then
    reads the **code** stage's round and still fires at code round 3 not
    clean. A round `M` with no stage word of its own is read from its
    subject: continuous only when it is written side by side with a
    `code round K` as one round — nothing but spaces, `(`, `[` or `=` between
    them — and `M - N == K` (`round 4 (code round 1)`, `code round 2 =
    round 5`); otherwise any `code` in the subject makes it code round `M`
    (`round 3 (code)`, `code audit r3`, `code round 2 fixed; round 3 not
    clean`, whatever `N` is); otherwise any `plan` makes it a
    plan round; otherwise it is continuous (`round M` → `M - N`). The field
    is **ignored** (cap counts from round 1, and the output says why) unless
    `N` is a whole number 1–3, `N` ≤ `audit_rounds`, `closed_by` is an id in
    `decisions[]` whose text names the target **or** `"clean"` with a subject
    on the branch in the canonical shape `plan round N clean` ("clean" right
    after the number; no `not` / `no` / `n't` / `never` / `none` / `without`
    / `yet` anywhere in that subject), and no plan round above `N` is on the
    branch. A subject with no `code` in it that numbers a code round from 1
    reads too low — name the stage (`docs(state): <ID> code round K`). The
    undercount check is unchanged.
  - It **clears** by going clean or by merging, never by an acknowledgement
    flag.
- **When it cannot look, it says so.** No resolvable base, no git, or a
  `git log` that fails prints **warn** "COULD NOT RUN" — an unchecked bill, not
  a clean one (exit 0). A whole-number `audit_rounds` is read in any spelling
  (`3`, `3.0`, `"3"`; decimal digits only, so `"²"` is not a number); anything else is a warn instead of a crash — except that
  the hard cap still fires as **drift**, since it never reads the count.
- **The accepted hole** (Kenneth, `BACKLOG-DECISIONS-2026-09-25` Q3 — accepted
  and documented, not patched). The entry's name and presence are still
  hand-written in the audited file, so **renaming** an `already_shipped` entry,
  **moving** an entry between `phases` and `already_shipped`, or **dropping and
  restoring** it makes every older commit read as absent and resets the
  scoping boundary to that commit — rounds before it stop counting. Don't do
  any of the three to a piece whose rounds are still running.

## The trigger

**`.claude/hooks/session-start.sh`**, registered in `.claude/settings.json`. On
every session start it installs `backend/.venv` and `frontend/node_modules` when
they are missing (remote only), then prints the state table. Drift is printed
loudly and never swallowed.

## The rule

> **Nothing is done until an adversarial round comes back clean.**

`audit_rounds` counts rounds **run**. `audit_clean` is true **only** when a round
found nothing. A phase with `status: shipped_unaudited` renders as `SHIPPED*` and
is listed under UNAUDITED WORK every single session until someone audits it — and
so does any `already_shipped` entry with `audit_clean: false`. Shipping is not
the finish line in either list.

Use the `K-adversarial-audit-loop` skill; it is what the rule is written against.

## What every session must do

1. **Start:** read the state table the hook printed. If it reports drift, fix
   that before anything else — every other claim in the file is suspect.
2. **During:** when you build, fix, or audit something, update
   `PROJECT_STATE.json` in the *same commit* as the change. Bump `audit_rounds`
   when a round runs; set `audit_clean` only when one comes back genuinely clean.
3. **End:** set `updated` and `updated_by`, run `python3 scripts/state.py` to
   confirm no drift, and commit.

## What this deliberately does not do

It does not track *how* something was built — that is what the plans and specs in
`docs/superpowers/` are for, and the state file links to them. It tracks only
what exists, what is audited, and what is still owed a decision.
