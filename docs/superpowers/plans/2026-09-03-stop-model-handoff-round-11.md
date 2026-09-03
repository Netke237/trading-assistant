# Session handoff #11 — round 9 ran and came back clean, three coverage tests added

**Date:** 2026-09-03
**Branch:** `claude/barrier-race-audit-round-9-lirkv8` — HEAD is this commit, based on `0f6acbb`.
**`main`:** `0f6acbb`. Untouched — no fast-forward this session, no PR opened (none asked for).

Read handoff #10 first. This is its direct follow-on: round 9, deferred there, ran to completion.

---

## 0. The tally

**Round 9 ran to completion and found no functional defect — nine rounds, the first one clean.**
It surfaced one real test-coverage gap (not a bug), which is now closed. The count of *clean*
audit rounds is 1; the count of rounds run is 9.

Setup that made this the first attempt-per-round to both start AND finish without an infra kill:
an isolated worktree at `/home/user/worktrees/round9-audit` (detached at `0f6acbb`, `backend/.venv`
and `frontend/node_modules` symlinked from the main checkout so no reinstall was needed), the
auditor told to write each finding to disk the moment it confirmed it, and it was explicitly told
about round 8's two closed findings so it wouldn't waste effort re-discovering and re-reporting
them. Ran on Sonnet. One agent call, no crashes, ~17 minutes, 110 tool calls.

---

## 1. What round 9 covered and what it found

Scope: `git diff ab3fb46..0f6acbb` (the whole Barrier Race feature, primary) with disproportionate
hostility to `git diff 741f2db..0f6acbb` (round 8's delta — the largest single unaudited slice this
loop has carried). Specifically pointed at what round 8 did not reach: the frontend
`BarrierRaceCard` rendering, `scan.py`'s trade-card assembly, and the new `horizon_preset` plumbing
itself.

**Investigated and confirmed CLEAN** (full detail, including every mutation tried, in the
session's `round9-findings.md` — not checked into the repo, see §4):

- Every real frontend call site that must send `horizonPreset`/`holdMin`/`holdMax`: `RunScanButton`,
  `step-3-direction`'s `syncToStore`, `scanScheduleResolve.ts`, `searchProfileSnapshot.ts`,
  `TradeCard`'s `getFirstPassageEstimate`, both `recomputePlan` call sites, and the shared
  `horizonFieldsFrom` helper. One noted-but-not-reported edge: a `ScanScheduleEntry.resolved_request`
  persisted to the DB *before* commit `741f2db` would lack `horizon_preset` and silently resolve to
  Swing until the user re-saves that profile — pre-existing stored data being read by new code, not
  a defect in the reviewed diff.
- `reprice_horizon.py`'s clamp/fallback/`sim_median` precedence rules, cross-checked against
  `test_reprice_horizon_agreement.py` and `test_trade_plan.py`.
- Stage 1 (display back-solve) vs Stage 2 (stop repricing) using different call shapes — confirmed
  intentional, matching handoff #10's decision #1, not a wiring bug.
- `build_trade_plan`/`estimate_rr`/`estimate_targets` threading `reprice_years` identically into
  both call sites — no transposition, no stale copy.
- `BarrierRaceCard` rendering: `money()`/`days()`/`pctLabel()`/`weightPercents()` all propagate NaN
  visibly rather than coercing to a plausible zero; the stacked-bar segment-omission guard doesn't
  create a "looks fine" state (the `aria-label` still prints the NaN literally); the
  edge-per-contract ×100/÷100 unit conversion is a matched pair.
- The `raceIsFresh` staleness gate: mutated `raceBarriers?.contract === data.contract` to a bare
  `true`, simulating "a stale race renders as if fresh" — 2 `TradeCard` tests failed immediately.
  Reverted.

**One finding, present at three independent call sites, same root cause:** `horizon_preset`/
`hold_min`/`hold_max` are correctly forwarded on `0f6acbb` by all three FastAPI endpoints that
accept them (`/api/scan`, `/api/contracts/recompute-plan`, `/api/contracts/first-passage`) — but
none of that router-level forwarding was tested. Hardcoding `horizon_preset=None` at each of the
three forwarding lines left the entire backend suite (1944 passed, 1 skipped) unchanged, in all
three cases independently. Every existing test that exercises `horizon_preset` calls
`build_trade_plan`/`estimate_first_passage` directly as a Python function, never through the router
with a real request payload carrying a non-default value.

This is exactly the failure mode `horizon_preset` was introduced to prevent: a future edit that
drops, mis-cases, or silently defaults the field anywhere in this router-level wiring would
reintroduce the ladder/Monte-Carlo horizon mismatch — with zero CI signal. Not a live bug. A real
hole.

---

## 2. What this session closed

Three tests added, one per call site, each following the existing pattern for "an override changes
the response over the wire" (`test_scan_rr_bullish_target_pct_override_changes_target_price` and
siblings):

- `backend/tests/test_trade_plan.py::test_recompute_endpoint_horizon_preset_reaches_build_trade_plan`
  — POSTs `/api/contracts/recompute-plan` with `horizon_preset` omitted vs `"Annual"` (dte=185:
  Swing/absent → 7 fallback days, Annual → 80 clamped to 0.75×185=138.75), asserts the ladder's
  `estimatedOptionPrice`s differ, and that the `"Annual"` response matches calling
  `build_trade_plan` directly with the same preset.
- `backend/tests/test_barrier_race.py::TestEndpoint::test_horizon_preset_reaches_estimate_first_passage_over_the_wire`
  — same pattern against `/api/contracts/first-passage` (dte=30: Swing→7, Annual→80 clamped to
  22.5), asserting `targets[i].stockPrice` differs.
- `backend/tests/test_scan_endpoint.py::test_scan_horizon_preset_reaches_build_trade_plan` — same
  pattern through the full `/api/scan` pipeline (`_rr_test_chain()`'s dte=35: Swing→7, Annual→80
  clamped to 26.25), asserting a scanned candidate's `exit.targets` differ.

All three were mutation-tested against exactly the regression they exist to catch — hardcoding
`horizon_preset=None` at each forwarding line — and each failed correctly before the fix, then
passed after reverting the mutation. Files verified byte-identical to pre-mutation backups via
`diff` after every experimental edit.

**Verification, this session:**

| Check | Result |
|---|---|
| `backend && .venv/bin/python -m pytest -q` | **1947 passed, 1 skipped** (was 1944, +3) |
| `frontend && npx tsc --noEmit` | clean |

No frontend files changed this session (the finding and its fix were entirely backend-router-level),
so the frontend test suite is unchanged from handoff #10's 1089 passed and was not re-run.

---

## 3. Decisions carried forward, unchanged

Handoff #10 §0's decisions 1–5 (reprice_years wiring, `horizon_preset` as its own field, no default
on `TradePlan.reprice_years`, the round-7 caution note staying removed, Amendment A) all still hold.
Round 9 read every one of them as implemented and found no discrepancy — see §1.

---

## 4. Findings file location

The full round-9 findings file (~130 lines: the one finding in full mutation detail, plus every
clean thread with what was checked) is at
`/tmp/claude-0/-home-user-trading-assistant/2791b172-adf0-5bfd-b926-a3662e27e59d/scratchpad/round9-findings.md`
— a session-scoped scratchpad, **not checked into the repo and not guaranteed to survive past this
session's container.** If a future session needs it and it's gone, that's a loss (per the "write
findings to disk" lesson) but not a blocker — §1 and §2 above already extract everything actionable
from it. Consider checking a findings file into `docs/superpowers/` in a future round rather than a
scratchpad, now that this has happened twice.

---

## 5. Pick up here

1. **Look at the card on Kenneth's machine.** Still the top item carried from handoffs #9 and #10 —
   a full scan through Steps 1–7 against live market data. Nothing in this session changes that; if
   anything, a ninth audit round with no functional finding is one more reason the remaining risk is
   in things a credential-less container cannot exercise (real chain shapes, real IV, real
   fundamentals), not in the reviewed code paths.
2. **Round 10, if the loop continues.** Round 9 was the first clean round. Whether to keep running
   the loop past a clean round, and against what scope, is a judgment call for whoever picks this up
   — the previous eight rounds each found something, so one clean round is evidence, not proof.
3. Then handoff #6 §5's build order: gate basis → piece 3 → piece 4 → piece 6 → Heston → piece 5.

## 6. Still outstanding

- **The five dead branches**, unchanged from handoff #10 §5 — `git push --delete` still 403s in a
  remote session and the GitHub MCP server exposes no branch-delete tool.
- Everything in handoff #10 §5 not listed above.

## 7. Traps carried forward

Handoff #10 §6 in full. Nothing new this session — round 9's method (mutation-test, revert, verify
byte-identical via `diff`) held up without incident, which is itself worth noting: the worktree +
findings-to-disk combination from handoff #9/#10 has now produced two consecutive completed rounds
after three consecutive crashes before it. Keep using both.
