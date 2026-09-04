# Session handoff #13 — live verification, state tracking, and the stop-cost notation

**Date:** 2026-09-04
**Branch:** `claude/dev-state-reconstruction-hzmzbi` — HEAD `c70d0b9e`, pushed.
**`main`:** `dc051a58`. **Untouched.** No PR opened, none asked for.
**Tests:** backend **1983 passed, 1 skipped** · frontend **1109 passed** · typecheck clean.

Direct continuation of handoff #12 — read that first for the reconstruction and Piece 4.
**But read `PROJECT_STATE.json` before either.** It is now the single source of truth and this
file deliberately does not restate it.

---

## 0. The most important change: state is now tracked and enforced

**`docs/superpowers/PROJECT_STATE.json`** is the single source of truth for phase status, audit
status, decisions, open questions and traps. **Nothing else restates it** — handoffs describe what
happened in a session, the state file describes where the project is.

**`scripts/state.py`** renders it *and verifies every claim against the code*. Each phase carries a
`verify` probe; the script exits non-zero when a declared status and the codebase disagree.
**`.claude/hooks/session-start.sh`** runs it on every session start and also installs
`backend/.venv` and `frontend/node_modules` when missing (both had to be rebuilt by hand in #12
before a single test could run).

Full explanation: `docs/superpowers/STATE_TRACKING.md`.

**Two things worth knowing about how it was built:**

- Its **first run caught a modelling error in the state file I had just written**. Phase F's probe
  tested that `v0_grid` exists — which says nothing about whether the Heston calibration was fixed.
  That forced a third probe kind, `defect_marker`, where finding the pattern proves the work is
  still *outstanding*. Drift detection was then verified by injecting a false status and confirming
  exit 1 and a byte-identical restore.
- The first commit **silently dropped the hook**: `.gitignore` had `.claude/*` with only `skills/`
  excepted, so it existed only in this container and every other session would never have seen the
  state check. Narrowed the ignore with a comment saying why.

---

## 1. The Barrier Race is live-verified — the item carried since handoff #9

Kenneth ran it on his machine and posted the card. **Verified from his real numbers:**

- All three rows sum to exactly 100% (66/32/2/0, 58/38/4/0, 51/42/7/0).
- All three edge figures reproduce from the printed inputs: −$51.18/−$51, +$9.22/+$9,
  +$39.51/+$40.

**Why he could not find the card:** it renders **nothing** until *Run Monte Carlo Estimate* is
clicked (`BarrierRaceCard/index.tsx:119`, `if (!race || !isFresh) return null`). The card was
correct; the button was unclicked. An invisible card reads as an unshipped one — say this in any
future walkthrough.

**A trading observation from his live card, worth carrying:** on a long-dated Δ0.54 call the
**stock stop fires first 32–42%** of the time and the premium stop only 2–7% — the *opposite* of
the schematic's reference contract (premium stop 68%). The contract holds value, so price reaches
the level before the option bleeds 59%. His edge also went **−$51 → +$9 → +$40** across the three
targets, i.e. only the 50% target is clearly positive. The race is discriminating exactly as
designed.

---

## 2. The stop-cost notation, rebuilt (`c70d0b9e`)

Kenneth asked where to see his maximum loss against premium and could not find it. **It was on
screen the whole time** — the STOP COST badge — but named for the mechanism rather than the
question, given only as a percentage and a per-share figure, and sitting beside a Barrier Race
number for the same stop that differs by six points with nothing saying why.

**Then he checked the arithmetic by hand and it did not add up.** The card printed
`$15.41 away × Δ0.54 = $8.24`, and `15.41 × 0.54 = 8.32`. Delta is really **0.5347**, rounded for
display while the loss used full precision. On a card whose entire premise is showing arithmetic a
non-coder can verify, an equation that does not multiply out is the feature failing.

**Shipped:**

| Before | After |
|---|---|
| `STOP COST` | `MAX LOSS IF THE STOP IS HIT` |
| percentage + per-share only | leads with `$824 per contract — of the $1,890 you paid, $1,066 left` |
| `Δ0.54` (does not reconcile) | `Δ0.535` (multiplies out to the printed loss) |
| no basis named | `· delta-linear, priced today` |
| two cards silently disagree | race card cross-references it and says why both are right |

New `formatStopLossHeadline` in `risk.ts`. Two new tests: one **parses the rendered equation and
asserts the printed factors produce the printed loss** — the bug itself, not a proxy for it — and
one reproduces Kenneth's contract exactly. Copy and formatting only; **no computed value changed.**

**Why three risk numbers legitimately exist** (a future session will hit this confusion again):

| Where | Number | Method | When |
|---|---|---|---|
| Contract Details `CAR` | $1,890 | the whole premium — the ceiling | n/a |
| Arithmetic card | $824 (44%) | delta straight line | today, no decay |
| Barrier Race | $879 (45.9%) | full repricing | at the median day to the barrier |

---

## 3. Decisions settled this session

All four are recorded in `PROJECT_STATE.json → decisions`; the reasoning is here.

| # | Decision |
|---|---|
| **Gate basis (Q1)** | **APPROVED** — Black-Scholes at today's date replaces the delta-linear ruler. Kenneth had thought it was already decided; **it was**, in round 5 as Q3. It had simply never been built — the gap between "decided" and "built" is what the whole reconstruction was about. |
| **Premium stop derivation** | **APPROVED and SHIPPED** (`846fc792`). Derived server-side so a live fill cannot move the dollar amount the user typed. |
| **Stock Barrier Race** | **YES** — piece 6 (Phase E) carries the two-barrier version. |
| **Stop-cost notation** | **APPROVED and SHIPPED** (`c70d0b9e`), §2 above. |
| **"Does the gate move server-side?"** | **Not open — I overstated it.** The gate-basis spec §2 already chose server-side and explicitly rejected a client-side pricer. A real prerequisite, but a decided one. |

---

## 4. Deferred, and still owed a decision

**Waiting on Kenneth** (both flagged in the schematic as "your call", both readout-only — the
stored fields stay load-bearing):

- **Invalidation row** on the Monte Carlo card (`TradeCard:2057`) — a *move* to the race, not a
  deletion. Round 7 already reverted one over-eager attempt at this.
- **Projected R/R (+8%)** on the Fixed % Ladder (`TradeCard:2075`).

**Not built:** Phases A, B, C, E. **Needs a spec first:** F (Heston), G (piece 5).

**Open questions** (live in the state file, repeated here only for context):
Q7 thresholds never measured on a real universe; whether provider IV can displace a solver for
Phase A; and **`ivRank` conflation**, which is a *live scoring and hard-reject defect*, not a
tidy-up — raw IV×100 is written into a field named for a percentile and then compared against
`iv_rank_pass_max: 34` and `hard_reject.max_iv_rank: 70`.

---

## 5. What has NOT been audited — the rule is not satisfied

> **Nothing is done until an adversarial round comes back clean.**

| Work | Rounds | State |
|---|---|---|
| **Phase D (Piece 4)** | **0 completed** | Two agents launched across two sessions; **neither reported.** |
| **Stop-cost notation** (`c70d0b9e`) | 0 | Shipped this session, unaudited. |
| `bs_iv` findings document | 2 | **Neither clean.** Amendment B addresses round 2 but has itself never been audited. |

`scripts/state.py` prints Phase D under UNAUDITED WORK every session until this is fixed. **The
notation change should be added to that list** — it is in `already_shipped` with
`audit_clean: false`, but the script only walks `phases`, so it does not currently surface. Either
extend the script or promote the entry.

---

## 6. Recommended next steps

1. **Audit Phase D.** Zero completed rounds on shipped code that touches alert thresholds and
   auto-trader sizing. Use `K-adversarial-audit-loop`. Nothing else should merge ahead of it.
2. **Fix the state-script gap in §5** — a tracker that silently omits a category of unaudited work
   is the failure it exists to prevent.
3. **Phase A**, in its revised (much smaller) shape: source `iv` from the provider on the **async**
   chain path (`market.py:1260/1277/1291/1308`), reuse `market.py:928 _compute_iv_bs` rather than
   writing a solver, fix the Newton seed. **Not** "build a bracketed solver" — that was my
   recommendation twice and it was wrong both times.
4. **Then Phase B**, now green-lit and specified.
5. **Decide the two removals** in §4 — they are cheap and blocked only on a yes.

---

## 7. Traps

The state file's `traps` array is authoritative. The two that cost time this session:

- **`.gitignore` can silently swallow tooling.** Check `git ls-tree` after committing anything
  under a broadly-ignored directory.
- **A stale status line in a handoff is worse than no line.** #12 said "NOT FIXED" in one section
  while its own addendum said fixed. That is why status now lives in one machine-checked file.

And the standing one, unchanged: **do not trust an audit finding without a file:line you have
checked yourself.** #12 accepted a round-1 finding uncritically and committed its errors; round 2
found four of nine corrections did not survive contact with the code.
