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

### Explicitly authorized additional plan stages

The additive `plan_stages` field supports another plan stage only when an
existing recorded decision explicitly authorizes it. Targets without this field
keep the existing behavior, including singular `plan_stage` validation, warnings,
subject inference and accepted holes above. Do not add both fields: plural
metadata never falls back to the singular path when invalid.

`plan_stages` is a nonempty ordered array of objects. Each `rounds` is the
number actually run in that stage: an integer 1–3, excluding booleans, floats
and numeric strings. The cumulative sum defines continuous endpoints and must
not exceed valid `audit_rounds`. Do not record zero-round future stages or edit
old counts to buy headroom. For example, stages of three and two rounds cover
plan rounds 1–3 and 4–5; the authorized second interval remains 4–6.

Every stage after the first needs `opened_by`, the unique ID of a root
`decisions[]` entry naming the target as a whole token. Its answer `a` must
contain exactly one affirmative, unnegated, bounded declaration in this order:
`open`/`opens`/`opened`, `new plan stage`, `plan rounds START-END`. Hyphen and
en dash ranges are accepted, case-insensitively. START must be the preceding
cumulative endpoint plus one; END must be START+2. Canonical future wording is
`Open one new plan stage: plan rounds START-END`, with the target named in the
decision. A question in `q`, conditional or interrogative wording, mere target
mention, duplicate ID, negated declaration or wrong range cannot authorize it.
This recognizer checks recorded authorization; it cannot grant permission.

All earlier stages must close with `closed_by: "clean"` or the verified
`opened_by` decision of the immediately following stage. Clean closure requires
positive canonical branch-subject proof `plan round CONTINUOUS-END clean`,
using the cumulative endpoint, with no subject-wide clean negation. Contradictory
negative clean evidence at that endpoint invalidates closure. A local stage
number or extra clean boolean is insufficient. The final stage may remain open
by omitting `closed_by`, or close clean; an unpaired decision acknowledgment
cannot close it. An open final stage trips the cap at its third non-clean round,
even if overall `audit_clean` is true.

After every plan stage closes, code starts after their sum. For six plan rounds,
`round 7 (code round 1)` and `code round 1` identify code round 1; untagged
continuous `round 7` also subtracts six. Existing stage-word and paired-number
inference still applies. Code round 3 requires overall `audit_clean` to be the
JSON value `true`; code round 4 is always drift in the plural path. While the
final plan stage is open, explicit code evidence and untagged continuous rounds
beyond its endpoint are invalid. Explicit plan rounds outside the recorded
intervals are invalid, rather than being reclassified as code.

Malformed plural metadata, missing authorization, invalid closure and cap
breaches produce visible drift (CLI exit 1), never a convenient legacy fallback.
Undercount, target ownership, introduction boundary and base resolution remain
unchanged. This validation runs when the resolved target has branch round
evidence; no evidence does not certify metadata, and unavailable git/base still
reports `COULD NOT RUN`. It does not certify independent reviewer verdicts or
repair the accepted identity/scoping holes above.

#### Historical decision and normalized example

The following is the immutable recorded TRADIER opening decision, followed by a
normalized **example** for six actual plan rounds whose final subject is
`docs(state): TRADIER-GOVERNOR plan round 6 clean`. It illustrates the schema;
it does not change the historical target, decision, audit status or shipping
status. Preserve the original decision text and recorded rounds.

```json
{
  "id": "TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10",
  "q": "TRADIER-GOVERNOR's plan stage hit its 3-round cap without a clean round (R3-G1: a deadline-bound fire-path regime fetch can miss its rate-limit slot during a stock scan, fall back to yfinance and size the order differently). Q1 open a new plan stage for the overdraft redesign? Q2 if not, shrink to bulk traffic only? Q3 accept a short burst above the limit while the overdraft is used (at most 15 extra requests, then repaid)?",
  "a": "Kenneth, 2026-10-10 (chat): 'i agree' to the coordinator's recommendation -- Q1 YES: open ONE new plan stage (up to 3 rounds, plan rounds 4-6 overall) for the overdraft redesign: deadline-bound auto-trade fire-path Tradier calls (regime fetch incl. intraday, earnings veto, market-open price check) never wait and never fail on the limiter -- they take a slot if free, otherwise go anyway and book an overdraft (bucket negative, floored at -capacity 15); bulk traffic (scans, prewarm, monitors, probes) waits until it is repaid, so the average stays 120/min; the stock scan's earnings lookup waits for its slot BEFORE its 5 s deadline starts. Q3 YES: a burst of at most 15 extra requests is accepted. Q2 not needed. No counter reset: plan rounds 1-3 stay recorded; the scan-slowdown merge question stays pre-accepted ('ok Go ahead', 2026-10-10). Not a merge approval.",
  "by": "Kenneth 2026-10-10 (chat)"
}
```

```json
{
  "id": "TRADIER-GOVERNOR",
  "audit_rounds": 6,
  "audit_clean": false,
  "plan_stages": [
    {"rounds": 3, "closed_by": "TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10"},
    {"rounds": 3, "opened_by": "TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10", "closed_by": "clean"}
  ]
}
```

The clean plan close moves this example to code round zero. It does not assert
a clean integrated code audit. If only plan rounds 4 and 5 have run, the second
object instead has `rounds: 2` and omits `closed_by`; keep the total truthful.

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
