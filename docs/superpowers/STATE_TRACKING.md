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

**`scripts/state.py`** renders the file as a table **and verifies it against the
code.** Every phase carries a `verify` probe — a pattern whose presence or
absence in a real source file proves the declared status:

```
python3 scripts/state.py           # render + verify, exit 1 on drift
python3 scripts/state.py --quiet   # verify only, silent when clean
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
