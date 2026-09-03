# Session handoff #10 — round 8 ran, `reprice_years` is wired, the spec is amended

**Date:** 2026-09-03
**Branch:** `claude/barrier-race-audit-round-8-13dcbb` — HEAD `6f03210`, based on `741f2db`.
**`main`:** `728c59e` (PR #21, merged 2026-09-02). Untouched.
**No PR opened** — none was asked for.

Read handoff #9 first. This supersedes its §5 items 1–4, all of which are now done.

---

## 0. The tally

**Round 8 ran to completion and produced two findings. The count is eight rounds, none clean.**

Handoff #9 was right to refuse to record round 8 — it had not happened. It has now. Both of its
findings are fixed in this branch, so **round 9 has unaudited fixes in front of it**, the same
position round 8 inherited.

Two things made this round finish where three previous attempts died:

- **The auditor wrote each finding to disk the moment it confirmed it** (handoff #9 §4's "add one
  thing next time"). It paid off immediately — the findings file is a better record than the final
  report, because it also lists the ~dozen threads that found *nothing*, which is what stops the
  next round re-treading them.
- **It ran on Sonnet, in an isolated git worktree.** The worktree mattered more than expected: the
  auditor mutation-tests by editing and `git checkout`-ing files, and this session was editing the
  same files concurrently. Sharing a tree would have destroyed one or the other.

Set that up with: `git worktree add <path> <sha> --detach`, then symlink `backend/.venv` and
`frontend/node_modules` into it. The venv's absolute paths still resolve because the original
location still exists.

---

## 1. What landed

Three commits on top of `741f2db`.

### `9f77fbc` — the Fixed % Ladder back-solves at the resolved holding horizon

Handoff #9 §3's approved change. `build_trade_plan` is now the caller that `reward_risk.py`'s own
comment said did not exist; `estimate_rr` / `estimate_targets` finally receive `reprice_years`.

One function owns the horizon: **`reprice_horizon.display_reprice_years()`**, called by both
Stage 1 and `build_trade_plan` with the same arguments. It pins `sim_median=None`, which is what
makes the agreement exact rather than approximate. **The stop leg still passes the simulated median
directly and must stay that way** — do not route it through the shared helper to make things look
uniform.

`TradePlan` gained a `reprice_years` field, deliberately with **no default**: a plan that cannot say
what horizon it priced at is how the two cards drifted apart in the first place.

### `0bddb83` — the horizon payload, the note's removal, and round 8's findings

**The trap handoff #9 §3 warned about was real, and worse than it looked.** It is not that the two
paths *might* send different spellings — they structurally could not send the same one.
`ScanRequest.horizon` is `Literal['Intraday', 'Swing', 'Position']`, so Quarterly, SemiAnnual and
Annual all arrive as `"Position"`, while `/first-passage` carries the uncollapsed key. Wiring the
ladder to `req.horizon` would have repriced a 200-day hold and a 20-day hold identically (14 days)
while the card beside it used 80 — **and removed the caution note that had been admitting the
disagreement.** Strictly worse than doing nothing.

So `horizon_preset` travels as its own field, alongside the scoring horizon rather than instead of
it, on `/scan` and `/contracts/recompute-plan`. `horizonFieldsFrom()` is the single spelling used by
all three trade-card call sites.

**The caution note is gone**, removed only after both halves were demonstrated by test — equal
inputs (`repriceHorizonPayload.test.ts`) and equal horizons from equal inputs
(`test_reprice_horizon_agreement.py`). A comment marks the spot and says what to re-derive before
writing a note there again, and `TradeCard.test.tsx` asserts the prose stays absent.

Round 8's two findings, both closed:

1. **`_race_out()`'s wire mapping had no field-level coverage.** Swapping
   `daysStockStop`/`daysPremiumStop`, and separately `pTargetFirst`/`pStockStopFirst`, each survived
   the full 1845-test suite. `test_race_wire_mapping.py` now gives every source field a distinct
   sentinel and pins each wire field to its own source — and fails if the map falls behind the
   dataclass.
2. **The round-7 caution note had no coverage** — superseded by its removal, which is itself pinned.

**Plus the mutant that opened the round.** Handoff #9 §4's lead was correct and blocker-grade:
inverting `first_passage.py:599`'s `rr_stock_stop` to `risk / reward` — the card's headline ratio,
upside down — passed **1845 tests**. Every existing assertion about it was satisfied by the inverted
value: it still varied across strikes, was still `None` on non-positive risk, still not-`None`
otherwise. **None of them ever divided the two legs and compared.** Two tests now do. Verified: the
mutant fails both.

### `6f03210` — Amendment A on the barrier race spec

Appended, not merged, per handoff #9 §2. Four items: the `premium_stop_pct` seed deviation is kept
and §2.3's premise recorded as wrong; §3.2/D8's StatusBadge is dropped permanently; §2.4's guard
rationale is marked stale while the guard stays; and §2.2's "ONLY place that rule lives" is recorded
as now true.

---

## 2. The card, read against a live backend — first time

Handoff #9 §5 item 4, done as far as this environment allows, and it was worth doing.

`uvicorn app.main:app` starts fine in a remote container. **Market data does not** — yfinance and
`^VIX` fail through the proxy — but `/api/contracts/first-passage` and
`/api/contracts/recompute-plan` take the contract in the request body and returned **HTTP 200 with
real numbers**. The card was then rendered against those exact responses and read end to end.

**The two cards agree on live output, to the cent.** On AAPL 190C, 30 DTE, $5.20, Position:

| | |
|---|---|
| Shared horizon | 16.0 days remaining, sigma 0.3325 |
| Monte Carlo card | $6.24 → $191.39, $7.02 → $192.72, $7.80 → $193.97 |
| Fixed % Ladder | $199.80 → $11.98, $207.20 → $18.28, $214.60 → $25.23 |

Both legs price the same contract at the same remaining life, in opposite directions. Re-deriving
each from `bs_price` / `_solve_target_stock_price` at that horizon reproduces every figure exactly.

**The change is small on short contracts and large on long ones**, which is where Kenneth will
notice it. Same 30-DTE contract: the ladder moved $0.06–$0.15. A 365-DTE LEAP ($24.50 premium)
moved far more, and — the actual point — **now responds to the preset at all**:

| | T1 | T2 | T3 | R:R |
|---|---|---|---|---|
| Before (every preset, half-expiry is preset-blind) | $24.87 | $30.09 | $35.71 | — |
| Now, Swing | $33.65 | $38.86 | $44.37 | 0.62 |
| Now, Annual | $30.27 | $35.47 | $40.99 | 0.39 |

**Everything on the rendered card adds up.** Reward $1.04 = $6.24 − $5.20; risk $4.00 = $5.20 −
$1.20; R:R 0.26× = 1.04/4.00; premium-stop risk $3.12 = 5.20 × 0.60; `rr_premium_stop` 0.33× =
0.20/0.60; edge 0.22×1.04 − 0.02×4.00 − 0.72×3.12 + 0.04×(3.84−5.20) = −$2.15 → −$215. The four
shares sum to 100%. Removing the caution note left no gap — the "Each probability above is measured
on its own" note follows cleanly.

**What a human should still look at:** on this contract every edge is deeply negative (−$215 to
−$260) because the premium stop fires on 72–83% of paths. That is the card working as designed —
disclosure, not a defect — but it is exactly the kind of thing worth Kenneth's eye on a real scan.

**Still not done:** a full scan through Steps 1–7 against live market data. That needs credentials
this container does not have.

---

## 3. Verification — all on `6f03210`

| Check | Result |
|---|---|
| `backend && .venv/bin/python -m pytest -q` | **1944 passed, 1 skipped** (was 1845) |
| `frontend && npm run test` | **1089 passed**, 101 suites (was 1078) |
| `frontend && npx tsc --noEmit` | clean |
| `frontend && npm run build` | success |
| `npx playwright test -c <scratch> --grep @smoke` | **19 passed, 2 skipped** |
| `frontend && npm run lint` | **0 errors**, 56 warnings — all pre-existing |

Backend +99 (agreement 64, wire mapping 33, rr orientation 2); frontend +11.

Environment traps from handoff #9 §1 all still apply. One to add: **`pip install -r requirements.txt`
times out against files.pythonhosted.org on the default settings.** Use
`pip install --timeout 120 --retries 5`. The first attempt failed on a read timeout and the failure
is easy to miss if you `echo $?` after a `tail`.

---

## 4. Pick up here

1. **Round 9.** Everything in §1 is unaudited. Same prompt shape (handoff #9 §4) plus the two things
   that made round 8 work: **write findings to disk as you go**, and **run it in a git worktree** so
   it can mutate freely. Sonnet was sufficient. Give it the two closed findings as context so it
   does not re-report them, and point it at what round 8 did NOT reach: the frontend
   `BarrierRaceCard` rendering, `scan.py`'s trade-card assembly, and the new `horizon_preset`
   plumbing itself.
2. **Look at the card on Kenneth's machine**, with a real scan through Steps 1–7. §2 gets as close
   as a credential-less container can, and the numbers moved on a LEAP by real money.
3. Then handoff #6 §5's build order: gate basis → piece 3 → piece 4 → piece 6 → Heston → piece 5.

## 5. Still outstanding

- **The four dead branches.** Unchanged from handoff #9 §6 — `git push --delete` still 403s in a
  remote session and the GitHub MCP server exposes no branch-delete tool. One minute in the UI.
- Everything in handoff #9 §6 and handoff #8 §7 not listed above.

## 6. Traps carried forward

Handoff #9 §7 in full, plus:

- **A dead agent's lead can be worth more than its report.** Round 8's only salvaged fragment was
  "mutants 5 and 7 survived" with no way to know which mutants those were. Handoff #9 correctly
  refused to guess them — and instead recorded the *one* mutation known to have been left in the
  tree. That one turned out to be a live, blocker-grade coverage hole. Recording the verifiable
  scrap beat reconstructing the interesting one.
- **A test that passes on both a value and its reciprocal is not testing that value.** Every
  `rr_stock_stop` assertion in the suite was of that kind. When pinning a derived number, assert the
  derivation, not just its shape and null-handling.
- **`git checkout <file>` to revert a mutant destroyed uncommitted work in this session too**, on
  exactly the file handoff #9 §7 warns about. Commit first — and prefer `cp` to a scratch backup
  over `git checkout` when your own edits are in the tree.
- **A "silent default on a dict miss" is a design hazard, not a nicety.** `_fallback_days` returning
  Swing on an unknown preset is why the horizon mismatch would have shipped invisibly. When two
  paths must send the same value, assert the equality in a test — the code will never tell you.
