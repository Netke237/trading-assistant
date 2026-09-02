# Session handoff #6 — four specs written, GitHub state audited, nothing merged

**Date:** 2026-09-02
**Branch:** `claude/bamendjou-stop-model-piece-3-9mh03d` (pushed, docs only, no code)
**`main`:** `89eeb535`, unchanged this session. All three CI checks green.
**Code written this session:** none, still. Four specifications and one branch/PR audit.

Read `2026-09-02-stop-model-handoff-round-5.md` first — the design session (Q1–Q11) and the three
code findings that changed the plan. This file covers what happened after: four full specs, two
follow-up decisions, and a verified audit of every branch and PR touched in the last two days.

---

## 1. Documents produced this session

| Document | Covers |
|---|---|
| `2026-09-02-barrier-race-spec.md` | Updated: R:R/edge computed backend-side with every term **printed** on the card (Kenneth: *"show the arithmetic"*), not relocated to a TypeScript pricer. Card layout made self-contained. |
| `2026-09-02-gate-basis-spec.md` | **New.** Q3/Q7 — Black-Scholes at today's date, thresholds 0.80/0.70/0.60. Solves the "stop that moves" problem: the endpoints that produce a stop also return its cost. |
| `2026-09-02-piece-4-per-position-premium-stop-spec.md` | **New.** Nullable per-position premium stop, all three alert paths, both send paths, the auto-trader, creation-time not update-only. |
| `2026-09-02-piece-6-stocks-arithmetic-plan-spec.md` | **New.** The options exit plan with every premium-dependent step stripped. **Closes Q-A.** |
| Trade Card Schematic (artifact) | Updated to match the per-target barrier race. Reference only — do not treat as authoritative where the specs differ. |

All four specs are independently buildable — no spec depends on another shipping first, though the
recommended order (below) shares a payload field between two of them.

---

## 2. Decisions made this session

| # | Decision |
|---|---|
| **R:R/edge computation** | **Backend, disclosed via printed arithmetic — not client-side.** The frontend has no option-pricing maths at all today (no Black-Scholes, no normal CDF, not one `Math.exp` in `frontend/lib/`). Moving it client-side would permanently duplicate Python's pricer in TypeScript for a number that can never update live anyway (moving a barrier invalidates the simulation, which must be re-run). Kenneth's call, applied. |
| **Q-A → CLOSED** | **There is no stocks gate.** Kenneth: *"for stock … strip away everything regarding options / premium."* The gate measures what share of the *premium* a stop costs — a question that only exists because of an option's nonlinearity. A stock's stop cost is exact (distance × shares) and position sizing already covers it. Piece 6 is unblocked. |

**Also confirmed, not re-decided:** the 0.80/0.70/0.60 gate thresholds stand as proposed (Kenneth: "yes take"), not measured against a real scan universe — revisit only if the observed flag rate looks wrong in practice.

---

## 3. GitHub state — audited and verified this session, not assumed

**Zero open PRs.** Confirmed via `list_pull_requests` (state=all) — every PR in the repo's history is
closed, and the two from this window (#19, #20) are confirmed **merged** (not just closed) with their
merge commits verified as ancestors of `main` via `git merge-base --is-ancestor`.

**Every branch with commits in the last two days was diffed file-by-file against `main`**, not just
checked by name:

| Branch | Verdict | How verified |
|---|---|---|
| `claude/fix-playwright-e2e-suite` (PR #20 head) | Fully merged, ancestor of `main` | `git merge-base --is-ancestor` |
| `claude/spawn-2-agents-impl-d3i2ml` ("Piece 2" source) | Fully merged, ancestor of `main` | same |
| `claude/volume-profile-indicator-bug-01w0cn` | Fully merged, ancestor of `main` | same |
| `claude/executing-vs-auditing-7rnjeo` (PR #19 head) | **One commit ahead**, `4f10f414` | `git rev-list --left-right --count` |
| `claude/tradecard-setstate-render-wo6eru` | **Confirmed empty of value**, still carries the venv dump | Diffed all 10 unique commits, file by file |
| `claude/bamendjou-stop-model-piece-3-9mh03d` | Ours. Docs only. | — |

### 3.1 `claude/executing-vs-auditing-7rnjeo` — one unmerged commit, harmless

`4f10f414`, docs-only, corrects handoff round 4's A1 wording to match the correction that already
supersedes it. **Redundant, not wrong** — round 5 already states the corrected version. Not merged
this session; recommend either merging it for a clean history or letting the branch be deleted since
round 5 supersedes it.

### 3.2 `claude/tradecard-setstate-render-wo6eru` — re-verified, not taken on faith

Round 4 flagged this "do not merge" with an estimated "~129 KB" venv dump. This session actually
diffed it:

- **The dump is far larger than estimated**: 1,063 files, 304,084 lines — the entire `setuptools`
  package tree under `backend/.venv-check/`.
- **Every real code file is either byte-identical to `main` or strictly older.** `risk.ts`,
  `stopPremiumThresholdsStore.ts`, `horizonPresets.ts`, `api.ts`, `config.py` — zero diff. The two
  files that do differ (`TradeCard.tsx`, `test_config_score_thresholds.py`) diverge in exactly the
  **pre-D8 three-state gate** (`reject_fraction`/`caution_fraction`) shape that round 4 already
  root-caused as a real CI failure and fixed on `main`.

**Confirmed: nothing on this branch is recoverable. Safe to delete**, this time backed by a
line-by-line diff rather than a repeated note.

### 3.3 Not yet done — needs Kenneth's go-ahead before acting

Branch deletion is a remote, not-trivially-reversible action and was not requested outright, so
**nothing was deleted this session.** Recommended, pending confirmation:

1. Merge `4f10f414` from `claude/executing-vs-auditing-7rnjeo` into `main` (or skip — harmless either
   way since round 5 supersedes it).
2. Delete `claude/fix-playwright-e2e-suite`, `claude/spawn-2-agents-impl-d3i2ml`,
   `claude/volume-profile-indicator-bug-01w0cn`, `claude/tradecard-setstate-render-wo6eru`.

---

## 4. Coverage check — is every requirement specified?

**No — one gap, named, not hidden.**

| Requirement | Status |
|---|---|
| Elegant, robust options R:R | **Spec'd** — barrier race |
| Both stop types measured | **Spec'd** — barrier race races them; piece 4 makes the premium side per-trade |
| Gate accuracy | **Spec'd** — gate basis spec |
| Heston verdict | **Decided** (fix calibration, don't drop) — not yet spec'd in implementation detail |
| Stocks, minus the options overhead | **Spec'd** — piece 6 |
| **The per-trade method pick (D4/D5, piece 5)** | **Not spec'd.** Every decision behind it is already made (D4/D5); what's missing is a TradeCard→page channel that doesn't exist and persistence so the choice survives step navigation. No open question — just unwritten, and intentionally last in the build order. |

The Heston calibration fix (Q8) is a decided paragraph, not a written spec, same as piece 5. Flagging
both rather than letting "four specs exist" read as "everything is specified."

---

## 5. Recommended build order (unchanged from round 5, now with specs to follow)

1. **Barrier race + reprice-horizon YAML** — `2026-09-02-barrier-race-spec.md`. Start with the numpy
   attribution and its 9 backend tests; get the four path shares summing to 1.0 before touching the
   frontend.
2. **Gate basis + thresholds** — `2026-09-02-gate-basis-spec.md`. Shares the new `iv` scan field with
   piece 3; sequencing after the race avoids touching that payload twice.
3. **Piece 3** — scan-time `finalStop` (round 4 §6, still the reference for its five parts).
4. **Piece 4** — `2026-09-02-piece-4-per-position-premium-stop-spec.md`. Independent; can run in
   parallel with any of the above.
5. **Piece 6** — `2026-09-02-piece-6-stocks-arithmetic-plan-spec.md`. Unblocked, mostly assembly.
6. **Heston calibration fix** (Q8) — needs its own spec before building; not written yet.
7. **Piece 5** — the per-trade pick. Largest, last, needs 1–4 landed first. Not spec'd yet.

## 6. Open questions

None block the next build step. For the record:

- Whether 0.80/0.70/0.60 hold up on a real universe — taken as proposed, one YAML edit to revisit.
- Q23–Q27 — Claude's reversible assumptions from the original plan, never revisited, low risk.

## 7. Traps carried forward

Everything in round 5 §8, unchanged and still live for the barrier race build. Add:

- **Don't treat "four specs exist" as "fully specified."** Piece 5 and the Heston fix are decided,
  not written. Check §4 of this file before assuming coverage.
- **Branch deletion needs a yes.** Two are ready to go (§3.3) — confirmed by diff, not by trusting a
  prior note — but nothing was deleted without being asked.
- **When re-verifying a "don't merge" flag from a prior handoff, diff it, don't repeat it.** The venv
  dump's size was wrong by more than 2000x in the original note (129 KB vs 304,084 lines/~30 MB+
  class of change). Re-checking caught that; repeating it would not have.
