# Session handoff #2 — stop model: branch consolidation, the piece-1/2 gap, and what to build next

**Date:** 2026-09-01
**Branch:** `claude/executing-vs-auditing-7rnjeo` — **everything now lives here.** Based on
`claude/spawn-2-agents-impl-d3i2ml` (gate + pieces 1 & 2), with the three planning documents
rescued from `claude/tradecard-setstate-render-wo6eru`.
**For:** the next session picking this up.

**Relationship to the first handoff:** this document **replaces §6 ("Where to pick up") of
`2026-09-01-stop-model-session-handoff.md` only.** Everything else in that file — the settled
decisions, the expensive codebase facts, the open questions, the traps — still stands and is still
the primary reference. Read it.

---

## 0. Read these, in this order

| # | Document | What it is |
|---|---|---|
| 1 | **this file** | Branch state, the prerequisite fix, the next build |
| 2 | `2026-09-01-stop-model-session-handoff.md` | The facts (§4), the open questions (§5), the traps (§7). Still authoritative. |
| 3 | `2026-08-31-stop-model-unification.md` | The plan. Marked **DO NOT BUILD AS ONE PIECE**. §8 is the piece split. |
| 4 | `2026-08-31-montecarlo-premium-stop-columns.md` | Rejection record with the algebraic proof. Read before proposing any R:R column. |

All four are on this branch. Before this session they were not — see §1.

---

## 1. Prerequisite: branch state (fix this first)

### What was wrong

| Branch | Carries | Merged? | PR? |
|---|---|---|---|
| `claude/tradecard-setstate-render-wo6eru` | The shipped gate **and all three planning documents** | No | No |
| `claude/spawn-2-agents-impl-d3i2ml` | main + gate (cherry-picked) + pieces 1 & 2 — **but none of the documents** | No | No |

Neither branch was merged to `main` and there were **no open pull requests on the repository at
all**. The plan, the rejection record and the first handoff — the entire record of what was decided
and why two designs were killed — existed only on the branch that was *not* carried forward. Merging
`spawn-2` and tidying up the other branch would have silently destroyed all of it.

### What this session did

- Re-based `claude/executing-vs-auditing-7rnjeo` on `claude/spawn-2-agents-impl-d3i2ml`, so the
  shipped code and the documents are on one branch.
- Copied the three documents across (file copy, not a branch merge — see the trap below).

### What still needs doing

- **Open a PR from this branch to `main` and merge it.** Three commits of shipped, tested work plus
  four documents are sitting unmerged.
- **Do not merge `claude/tradecard-setstate-render-wo6eru` wholesale.** It carries an accidental
  ~129 KB `backend/.venv-check/` virtualenv dump (a full `pip`/`setuptools` site-packages tree)
  committed by mistake. The previous session already excluded it when cherry-picking; keep excluding
  it. That branch is also behind `main` (it predates `AGENTS.md` and the `mainSeriesId` chart work).
  Everything of value on it is now on this branch. It can be abandoned.

---

## 2. Decisions that are settled — do not relitigate

Full list is D1–D12 in `2026-08-31-stop-model-unification.md` §1. The ones most likely to be
accidentally undone:

| # | Decision |
|---|---|
| **D1** | **Each method owns a stop.** Arithmetic and Monte Carlo both use structural+ATR; Ladder keeps stock ± %. The duplication is deliberate — Kenneth chose it over the simpler "one stop with one exception". |
| **D2** | **The flat −3% is not deleted.** It is reassigned from "position default" to "the Ladder method's stop". Already YAML-backed and per-run editable in Step 3. |
| **D4/D5** | **Per trade Kenneth picks:** method → one price row → stop basis (stock-price or premium). An explicit click, never "whichever method ran most recently". |
| **D6** | All three alerts stay. One armed, two advisory. The card must say which is which. |
| **D8** | **The gate warns, never blocks** — and after Kenneth's revision has only **two** states, PASS/CAUTION, and never paints red. His words: *"dont reject any contract. just show those with good profit or not."* |
| **D10** | Stop orders are not being built. All four paper adapters are `Literal["MKT","LMT"]`. Everything called a "stop" today is an in-app alert. |
| **D11** | Existing open positions: do nothing. |
| **D12** | Scope is stocks **and** options. |

### Two designs already built on paper and rejected — do not re-propose

1. **An R:R column for the Monte Carlo card.** The backend defines the target option price as
   `premium × (1 + pct)`, so `reward = premium × pct` **always, by construction**. Any denominator
   proportional to premium cancels it, leaving `R:R = pct / k` — a constant multiple of the number
   the user typed, identical for every contract. Draft 1 gave a flat 1.667×; draft 2, written to fix
   draft 1, gave 1.068× — *worse*. The proof is in `2026-08-31-montecarlo-premium-stop-columns.md`.
   **If a third design is proposed, compute its closed form first and check whether `premium`
   cancels.**
2. **Expected value on the Monte Carlo card.** Three independent defects. Worst: the loss leg used
   `(1 − p_target)` when the card carries a real stop probability one field away — on the reference
   contract that flips T20 from **+$62 to −$100**.

---

## 3. What has shipped

| Commit | Branch | What |
|---|---|---|
| `3c3754f` | (original) | Bug fix — `TradeCard`'s `patch()` called the parent's `onEditsChange` from inside `setOverlay`'s updater, firing setState mid-render. |
| `c8d3d75` | (original) | **Stop-vs-premium gate.** Flags contracts where the structural stop costs most or all of the premium. |
| `3400041` | (original) | Gate thresholds moved to `scoring_rules.yaml → horizons.<key>.stop_premium`, served by `/api/config/stop-premium-thresholds`. |
| `a095e74` | (original) | Gate reduced to two states, PASS \| CAUTION, never red. |
| `f01c69ae` | this branch | All of the above cherry-picked forward, excluding the `.venv-check` dump. |
| `76bfa362` | this branch | **Piece 1** — the Monte Carlo request sends the exit plan's structural+ATR stop as `invalidation_price` instead of the flat −3%. |
| `09e684bd` | this branch | **Piece 2** — a `sharedStop` memo so the gate and `structuralRR` read the same stop. |

Full frontend suite green (97 suites, 999 tests), `npm run typecheck` clean.

---

## 4. ~~Prerequisite~~ CLOSED: the gap between pieces 1 and 2

**Status: fixed in this session.** `components/organisms/TradeCard/index.tsx` — the Monte Carlo
request's `invalidation_price` now reads `sharedStop?.price ?? data.exit.invalidation` instead of
`exitPlan?.stop.price ?? data.exit.invalidation`. `sharedStop` was moved up in the file (declared
ahead of `estimateFirstPassage`, right after the state it depends on — `exitPlan`,
`arithmeticLiveStockPrice`, `structuralStop`, `structuralStopStockPrice` are all already in scope
there) so the memo itself didn't move logically, only its position in the file. Two new tests in
`TradeCard.test.tsx` (describe block `"TradeCard — piece 1/2 gap: cache-restored exit plan with no
fresh click this mount"`) reproduce the Next-then-Prev CandidateNav scenario — an exit plan AND a
structural stop both restored from cache, neither refreshed this mount — and assert the Monte Carlo
request, the gate, and (transitively, since both already read `sharedStop`) `structuralRR` all
resolve to the same restored structural stop rather than the restored exit-plan stop. Confirmed the
test fails against the pre-fix code (reverted the one line locally, re-ran, got the expected
185.87-vs-178.50 mismatch) before restoring the fix. Full suite green (97 suites, 1001 tests
including the two new ones), `npm run typecheck` clean.

The rest of this section is kept for the record of what the gap was and why it mattered — no action
needed here anymore.

### The gap

The two pieces were built by separate agents and made **opposite choices about a cache-restored
exit plan**:

- **Piece 1** reads `exitPlan?.stop.price` directly. `exitPlan` is seeded from `data.exit.exitPlan`,
  so it **accepts a restored plan**.
- **Piece 2**'s `sharedStop` requires `arithmeticLiveStockPrice != null`, and that is reset to
  `null` on every contract switch. It **refuses a restored plan** and falls through to the raw
  structural level.

### Why it matters — this is the ordinary path, not an edge case

`exitPlanByContract` is a parent-held cache in `step-7-trade-card/page.tsx:157`, spliced back into
`card.exit.exitPlan` by `withCachedEstimate` (`tradeCardOverride.ts:286`). So:

> Click **Next** then **Prev** in CandidateNav and come back to a card you already computed a plan
> for. The card remounts. `exitPlan` is restored; `arithmeticLiveStockPrice` is `null`. Monte Carlo
> now measures against the exit-plan stop while the gate and `structuralRR` measure against the raw
> structural level — **two different stops on the same card again.**

That is exactly the regression the plan's own test list names: *"the three stop consumers (MC
request, gate, `structuralRR`) all read the same value — the anti-regression for someone later
re-pointing one of them"* (`2026-08-31-stop-model-unification.md` §5).

### The fix

Point the Monte Carlo request's `invalidation_price` at `sharedStop` rather than at `exitPlan`
directly, so all three consumers resolve through one memo:

```ts
invalidation_price: sharedStop?.price ?? data.exit.invalidation,
```

Two things to get right:

1. `sharedStop` is declared **after** `estimateFirstPassage` in the file today. Either move the memo
   up or read it through a ref — do not reorder anything that would change the freshness semantics
   piece 2 documented at length.
2. Piece 2 chose the conservative resolution deliberately: pairing a restored final stop with a
   placeholder stock price is a mixed-vintage number. Keep that choice — make Monte Carlo match the
   gate, not the reverse. The MC request already sends `referenceStockPrice` separately, so the
   pairing concern applies there too.

Add a regression test asserting all three consumers resolve to the same price in the
restored-plan-without-a-fresh-click state.

---

## 5. Where to continue: piece 3, and why

### Pieces 1 and 2 are currently dormant in the normal path

`computeExitPlan` is called from exactly one place — the "Compute Arithmetic Plan" button
(`TradeCard/index.tsx:1316`). It is optional and user-triggered. Both shipped pieces prefer the exit
plan's stop and **fall back when there isn't one**.

So on any card where Kenneth has not clicked that button, **Monte Carlo still sends the flat −3%.**
The bug the first handoff called "the worst factual wrongness on the card" is fixed only for people
who click an optional button first.

**Piece 3 (Phase 1 — scan-time `finalStop`) is what puts the structural+ATR stop on the card before
any click.** That is the argument for doing it next, and it is stronger than "it is next in the
list": piece 3 is what makes pieces 1 and 2 actually take effect by default.

### Piece 3 scope (from the plan, Phase 1)

1. **Backend, at scan time.** Call `compute_final_stop` per **symbol** and attach `exit.finalStop`:
   `{ price, source, structuralPrice, structuralSource, atrFloorPrice, distanceDollar, atr, computedAt }`.
   `structuralSource` and `distanceDollar` are **required**, not optional — the "Bottom (final stop)"
   row reads both. Wrap in `asyncio.to_thread`; `find_structural_stop` is synchronous CPU work and
   `scan.py` already offloads every comparable computation.
2. **`stop.contractPrice` cannot exist at scan time** (it needs a contract). Specify explicitly that
   the contract-priced sub-cells and `recommendedSize` render `—` until a plan is computed.
3. **Survive a Step 6 contract override.** `mergePlan` does `exit: plan.exit` — a wholesale
   replacement — and `/contracts/recompute-plan`'s `TradeExit` has no `finalStop`, so it would be
   wiped for exactly the cards the user hand-picked a contract for. Add `finalStop` to `TradeExit`
   and echo it back, **and** splice it in `withCachedEstimate` as defence in depth.
4. **Persisted-store migration.** `scanStore` persists `scanResult` at `version: 12`. Bump to **13**
   with an explicit migration branch (CLAUDE.md requires both). Restored pre-13 sessions have no
   `finalStop`: render **"not computed — re-run the scan"**, never a blank and never a silent PASS.
5. **Ranking-table badge (D8).** `WatchlistRow` carries no `exit` and no `contractDetails`. Add
   `stopCostPct` + `stopCostStatus`, populate in `cardToRow`, add one grid track to `COLUMNS` and to
   `TableRow`, and verify against the 1200 px min-width gate. State on the badge that it describes
   the **auto-picked** contract, since a Step 6 override can later change it.

---

## 6. Deferred topics

### Deferred build pieces

| Piece | Scope | Status |
|---|---|---|
| **3** | Scan-time `finalStop` (Phase 1) | **Next.** See §5. |
| **4** | Per-position `premium_stop_pct` (Phase 4) — column + Alembic migration + three alert paths (`alertEngine.ts`, `alert_generator.py`, `EditDrawer`'s `alertFiresAgainst`) | Deferred. **Independent of piece 3** — could run in parallel. Note `auto_trader.py:254,352` sizes off the global pct and needs threading or an explicit "deliberately ignores it" note. |
| **5** | The per-trade selection (Phases 3 + 5 + 6) | Deferred. Largest piece, most unknowns. Needs a `TradeCard`→page channel that does not exist today (only `contracts` crosses that boundary) and persistence, because component state dies on step navigation and would silently disarm the choice. **Do not attempt until 1–4 have shipped.** |
| **6** | Stocks (Phase 7) | Deferred and **blocked on Q-A**. Also needs a new `POST /stocks/exit-plan` endpoint — `/contracts/exit-plan` requires `strike > 0`, `dte`, `premium > 0`, none of which a stock has. Seven `buildPaperStockPosition` call sites. |

### Deferred questions

| # | Question | State |
|---|---|---|
| **Q-A** | **The stocks gate basis.** A structural+ATR stop is ≥2 ATR by construction, so an "ATR-multiple" gate can never fire against it. Either (a) the stocks gate measures the **strategy signal's** stop, or (b) thresholds become relative to `atr_multiplier`. | **Blocks piece 6.** Kenneth's call. **New evidence this session (below).** |
| **A1** | Gate loss basis: cheap delta-linear (works from scan data, so the badge can exist in the ranking table) vs. the exit plan's Black-Scholes repriced value (more accurate, needs a click first). If the repriced basis drives the **verdict**, `dte_at_target = expiry_years × 0.5` becomes verdict-bearing rather than display-only. | Open |
| Q23–Q27 | Answered by Claude, not by Kenneth — he said "go ahead" without responding. Flagged as reversible assumptions in the plan's §1.1. | Open, low risk |

**New evidence on Q-A.** The first handoff worried that `pullback_ema`'s default `atr_stop_mult: 1.5`
might make option (a) unreachable too. That worry does not hold across the board — the strategy
signal stops span a wide range:

| Strategy | Stop | ATR multiple |
|---|---|---|
| `breakout_base` | `base_high − atr * 0.2` (`strategy_engine.py:591,601`) | **0.2** |
| (swing-based variant) | `_swing_low(bars, 10) − atr * 0.2` (`:819,827`) | **0.2** |
| `pullback_ema` / `ma_crossover` | `fast_val − atr * atr_stop_mult`, default 1.5 (`:446,462`) | **1.5** (search grid `[1.0, 1.5, 2.0]`) |
| `mean_reversion_bb` | `lower[-1] − stop_atr_mult * atr` (`:921,934`) | configurable |
| `mean_reversion_vwap` | `current − stop_atr_mult * atr` (`:1024,1035`) | configurable |

So a signal-stop-based gate **does** have real spread, unlike `compute_final_stop`'s ≥2 ATR floor.
This does not decide Q-A — that is still Kenneth's call — but it removes the reason to assume (a) is
dead on arrival.

### Deferred / known-broken, carried forward

- **Nothing protective reaches a broker** (D10). After all seven phases you have alerts, not stops.
- **Monte Carlo freshness** (Phase 2.4). Re-running Compute Arithmetic Plan *after* an estimate does
  not retroactively update the already-rendered probability — it silently goes stale. Deliberately
  left by piece 1.
- **The backend re-anchors stops on save.** `portfolio.py:198-213` does
  `adjusted_stop + (live_price − scanStockPrice)`. Defensible for a percentage-of-price level,
  **wrong for a structural stop**, which is an absolute chart level. The two send paths also
  disagree: `buildPaperPosition` sets `scanStockPrice` (so it re-anchors), `positionFromOrder` does
  not — same armed stop, two persisted values depending on which button was pressed. (Phase 6.2.)
- **Three different global premium percentages** exist — `reward_risk.premium_stop_pct`,
  `auto_trade.premium_stop_pct`, `settingsStore.premiumStopPct` — and **no per-position field at
  all**. (Piece 4.)
- **`stop.contractPrice` reprices at half time-to-expiry** (`reward_risk.py:82`) — why a 109-DTE
  contract shows a ~94% loss. Inherited, uncorrected, out of scope.
- **`dte < 1` returns `probability = 0.0` for every target** (`first_passage.py:195-205`) — a refusal
  to simulate, not a real zero. The Intraday horizon hits this routinely. The card does not say so.
- **The Monte Carlo probability is an option-value barrier** (`hit_mask = option_paths >=
  target_option`), while the *Invalidation* row's probability is a **stock** barrier. The card does
  not distinguish them.
- **D2 is only partially deliverable** — un-selected sends still carry the flat 3% (Phase 6.3).

---

## 7. Recommended order

> **Superseded by `2026-09-01-stop-model-handoff-round-3.md` §3.** PR [#19](https://github.com/Netke237/trading-assistant/pull/19) was opened and its
> backend CI came back red (`KeyError: 'reject_fraction'` — a test left behind by the D8 two-state
> revision); that is fixed. Round 3 is the current order. The rest of *this* file still stands.

1. ~~Open the PR from this branch~~ **Done** — PR #19, open, not yet merged.
2. ~~Close the piece-1/2 gap.~~ **Done** (§4).
3. **Piece 3 — scan-time `finalStop`.** Backend + `TradeExit` schema echo + `scanStore` v12→v13
   migration + the ranking badge. This is what makes pieces 1 and 2 fire by default. (§5)
4. **Piece 4 — per-position `premium_stop_pct`.** Independent of everything above.
5. Then reassess. Leave pieces 5 and 6; 6 is blocked on Q-A regardless.

---

## 8. Traps

- **Do not merge `claude/tradecard-setstate-render-wo6eru`** — it carries a committed virtualenv.
  Copy files off it if you need anything; everything of value is already here. (§1)
- **Do not propose an R:R column with a premium-proportional denominator.** Two designs died on it.
  Compute the closed form first. (§2)
- **Do not assume a value on the card is "display only".** Both audit rounds caught exactly this,
  twice each. `overlay.premiumStop` is the risk denominator in `computeEditedRR` and
  `rrContribution`; `exitPlan.stop.contractPrice` feeds a **submit-blocking** gate. Grep for
  consumers before calling anything cosmetic.
- **Do not re-run the adversarial loop against the whole plan.** It diverged: 24 findings → 32
  findings after a full rewrite that fixed every round-1 item. Audit one small piece at a time.
- **Implement, do not audit.** The plan's own conclusion is that the blast radius exceeds what any
  single review can enumerate. Ship a small piece, verify it, move on.
- **CLAUDE.md rules that have bitten:** `Status` labels are canonical (`lib/status.ts`) — which is
  why the two-state gate uses PASS/CAUTION rather than inventing "NOT PASS"; `npm run typecheck`
  must be clean before every commit; a new persisted store field needs a version bump **and** a
  migration branch.
- **Kenneth wants plain English.** Non-coder, high IT affinity. Short, jargon-free, with worked
  numeric examples. He asks to be grilled and to have work adversarially audited — take both
  literally.
- **When something said earlier turns out wrong, say so plainly.** He responds well to direct
  corrections rather than softened ones.
