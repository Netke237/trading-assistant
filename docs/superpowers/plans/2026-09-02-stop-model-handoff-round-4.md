# Session handoff #4 — everything merged, `main` is green, piece 3 is next

**Date:** 2026-09-02
**Branch:** `claude/executing-vs-auditing-7rnjeo`, restarted from `main` after its PR merged.
**State of `main`:** commit `77517981`. **All three CI checks green** (`backend`, `frontend`, `test`).
**For:** the next session picking this up.

**Relationship to the earlier handoffs:** this file supersedes the *status* sections of rounds 1–3
(what is merged, what to do next). Their analysis is still the record — read them for depth:

| # | Document | What it holds |
|---|---|---|
| 1 | **this file** | Current state, all decisions, all open questions, all deferred topics |
| 2 | `2026-09-01-stop-model-handoff-round-3.md` | The scanStore hydration bug write-up (§1.4), the CI lesson |
| 3 | `2026-09-01-stop-model-handoff-round-2.md` | Piece split detail, Q-A strategy-stop evidence table |
| 4 | `2026-09-01-stop-model-session-handoff.md` | The expensive codebase facts (§4) — still the primary reference |
| 5 | `2026-08-31-stop-model-unification.md` | The plan. **DO NOT BUILD AS ONE PIECE.** §8 is the split. |
| 6 | `2026-08-31-montecarlo-premium-stop-columns.md` | Rejection record + the algebraic proof |

---

## 1. What is now on `main`

Two PRs merged this session, both green on all three checks.

### PR #19 — stop-model unification

| Commit | What |
|---|---|
| `f01c69ae` | **Stop-vs-premium gate**, cherry-picked forward (excluding an accidental `backend/.venv-check/` virtualenv dump). Flags contracts where the structural stop costs most/all of the premium. Thresholds in `scoring_rules.yaml → horizons.<key>.stop_premium`, served by `/api/config/stop-premium-thresholds`, consumed via `stopPremiumThresholdsStore`. Two states, PASS \| CAUTION, never red (D8). |
| `76bfa362` | **Piece 1** — the Monte Carlo request sends the exit plan's structural+ATR stop as `invalidation_price` instead of the flat scan-time −3%. |
| `09e684bd` | **Piece 2** — a `sharedStop` memo so the gate and `structuralRR` read the same stop. |
| `59e1d0a8` | **Piece 1/2 gap closed.** `sharedStop` moved above `estimateFirstPassage`; the Monte Carlo request now reads `sharedStop?.price ?? data.exit.invalidation`. All three consumers resolve through one memo, including on a cache-restored exit plan with no fresh click this mount. Two regression tests reproduce the CandidateNav Next-then-Prev scenario; **verified failing against the pre-fix code** (185.87 vs 178.50 mismatch) before restoring. |
| `659b788b` | **Backend CI fix.** See §2. |
| docs | The four planning documents, carried onto a branch that would actually merge. |

### PR #20 — the Playwright e2e fix (a real user-facing bug)

| Commit | What |
|---|---|
| `8003e7ba` | `scanStore`'s persist `merge` dereferenced `persisted` without a null guard. See §2. |
| `eaf7ac17` | Two test races: a pre-hydration click, and cold `next dev` route compile. See §2. |

---

## 2. Two bugs found by actually running the checks — the methodological lesson

Both were found because CI was read properly for the first time. Neither was in the planned work.

### 2.1 `backend` was red when PR #19 was opened

The prior session reported "97 suites / 1001 tests green, typecheck clean" and opened the PR. True,
and insufficient: that was the **frontend** suite. The backend suite was never run, and was red:

```
FAILED tests/test_config_score_thresholds.py::test_stop_premium_thresholds_endpoint_mirrors_yaml
FAILED tests/test_config_score_thresholds.py::test_stop_premium_thresholds_are_coherent
  KeyError: 'reject_fraction'
```

The D8 revision reduced the gate to one threshold (`pass_max_fraction`). The YAML and the endpoint
were updated; the test was not. **Fixed the tests, not the code** — re-adding `reject_fraction`
would have silently undone D8. The coherence test now asserts the payload's key set *exactly*, so a
`reject_fraction` reappearing server-side fails loudly instead of drifting from
`HorizonStopPremiumThresholds` on the client.

### 2.2 The red `test` check was hiding a live user-facing bug

`test` had failed on `main` for **30+ consecutive runs (#98–#128, from 2026-08-26)**. It was not a
test defect. In `frontend/lib/scanStore.ts`:

```ts
const p = persisted as Partial<ScanStoreState>;
const lastState = p.scanState;   // throws when persisted === undefined
```

On a **first visit** — empty `localStorage`, `persisted === undefined` — this throws
`TypeError: Cannot read properties of undefined (reading 'scanState')`. **zustand swallows it in its
internal catch**, so `rehydrate()` resolves normally while `onFinishHydration` never fires and
`persist.hasHydrated()` stays `false` forever. `ScreenerStepGate` mirrors that flag; when it never
flips, the gate's 1500ms grace timer treats storage as corrupt and redirects to `step-1-regime`.

**This shipped.** With a fresh browser profile, **Steps 2–7 were unreachable** — every deep screener
URL bounced to Step 1 and Next appeared dead. It also explains why `localStorage` stayed empty: the
throw happens before persist's `setItem`, so no store ever saved anything.

Fix mirrors the guard `migrate` in the same config already uses (`persistedState ?? {}`), plus
`lib/__tests__/scanStoreMergeHydration.test.ts` — verified failing against the pre-fix code.

Two flakes underneath, both fixed: a click dispatched **before React attached its handler**
(`ScreenerPage.goto()` now waits for the step header — measured, 3/3 cold runs navigate with it,
dropped without), and genuine `next dev` first-visit route compile exceeding the 5s default (the two
Next-navigation assertions got an explicit 20s budget; nothing skipped or quarantined).

### 2.3 The lesson — carry this forward

- **This repo has three CI checks: `backend`, `frontend`, `test`. "Green" means all three.** The
  frontend suite passing says nothing about the backend. Run both:
  ```bash
  cd frontend && npm run typecheck && npm run test
  cd backend  && pytest        # ~4 min; needs pip install -r backend/requirements.txt in a fresh container
  ```
- **A permanently-red check is not a tidiness problem.** A real regression is indistinguishable from
  the standing failure. That is exactly how a week-old user-facing bug survived, and how #19 was
  opened red. Never let a check stay red.
- **When a decision deletes a field, grep the field name repo-wide.** `reject_fraction` outlived its
  own removal in a test file for four commits because the change was reasoned about as "the gate"
  rather than as every file naming the key.
- **CI runs on GitHub's `ubuntu-latest`, not anyone's workstation.** A machine migration or local
  virtualenv cannot cause a CI failure. (This was asked and ruled out.)

---

## 3. Decisions — authoritative, do not relitigate

Full list is D1–D12 in `2026-08-31-stop-model-unification.md` §1. These are the ones most likely to
be accidentally undone:

| # | Decision |
|---|---|
| **D1** | **Each method owns a stop.** Arithmetic and Monte Carlo both use structural+ATR; Ladder keeps stock ± %. The duplication is deliberate (door open to diverge later). Kenneth chose this over the simpler "one stop with one exception" that was recommended to him. |
| **D2** | **The flat −3% is NOT deleted.** Reassigned from "position default" to "the Ladder method's stop". Already YAML-backed and per-run editable in Step 3. Only partially deliverable — un-selected sends still carry the flat 3% (Phase 6.3). |
| **D4/D5** | **Per trade Kenneth picks:** method → one price row → stop basis (stock-price or premium). An explicit click, never "whichever method ran most recently". |
| **D6** | **All three alerts stay.** One armed, two advisory. The card must say which is which. |
| **D8** | **The gate warns, never blocks.** After Kenneth's revision it has only **two** states, PASS/CAUTION, and never paints red. His words: *"dont reject any contract. just show those with good profit or not… It will permit me upfront to identify highly profitable trades or lets say less risky."* |
| **D10** | **Stop orders are not being built.** All four paper adapters are `Literal["MKT","LMT"]`. Everything called a "stop" today is an in-app alert. Kenneth: *"dont need to build it right now."* |
| **D11** | **Existing open positions: do nothing.** |
| **D12** | **Scope is stocks AND options.** |

### Shipped threshold values (D8)

`scoring_rules.yaml → horizons.<key>.stop_premium.pass_max_fraction`, mirrored by
`stopPremiumThresholdsStore`'s `FALLBACK`:

| Horizon | `pass_max_fraction` |
|---|---|
| Intraday | 0.85 |
| Swing | 0.80 |
| Position | 0.70 |

One key only. There is deliberately **no** `reject_fraction` — see §2.1.

### Two designs built on paper and rejected — do not re-propose

1. **An R:R column for the Monte Carlo card.** The backend defines the target option price as
   `premium × (1 + pct)` (`first_passage.py:185`), so `reward = premium × pct` **always, by
   construction**. Any denominator proportional to premium cancels it, leaving `R:R = pct / k` — a
   constant multiple of the number the user typed, identical for every contract and symbol. Draft 1
   (premium stop) gave a flat 1.667×; draft 2, written to fix draft 1, gave 1.068× — *worse*.
   Deeper result: for a long option whose stop sits at or beyond total premium loss, risk **is** the
   premium, so `R:R = pct`. That is arithmetic, not a display defect. **If a third design is
   proposed, compute its closed form first and check whether `premium` cancels.** Proof in
   `2026-08-31-montecarlo-premium-stop-columns.md`.
2. **Expected value on the Monte Carlo card.** Three independent defects, any one disqualifying.
   Worst: the loss leg used `(1 − p_target)` when the card carries a real stop probability one field
   away — on the reference contract that flips T20 from **+$62 to −$100**. A correct version needs an
   option-value barrier in the simulation, a new request field and a schema change; `stop_hit_mask`
   is a *stock-price* barrier and cannot be reused.

---

## 4. Open questions — unanswered, Kenneth's to decide

| # | Question | State |
|---|---|---|
| **Q-A** | **The stocks gate basis.** `compute_final_stop` returns a stop ≥ 2.0 ATR away by construction (`max(structural, atr_multiplier × ATR)`), so an "ATR-multiple" gate can never fire against it. Either (a) the stocks gate measures the **strategy signal's** stop, or (b) thresholds become relative to `atr_multiplier`. | **Blocks piece 6** |
| **A1** | **Gate loss basis:** cheap delta-linear (works from scan data, so the badge can exist in the ranking table) vs. the exit plan's Black-Scholes repriced value (more accurate, needs a click first). If the repriced basis drives the **verdict**, `dte_at_target = expiry_years × 0.5` becomes verdict-bearing rather than display-only. | **Open — and piece 3 forces it. See below.** |
| Q23–Q27 | Answered by Claude, not by Kenneth — he said "go ahead" without responding. Flagged as reversible assumptions in the plan's §1.1. | Open, low risk |

**Evidence gathered on Q-A** (round 2) — this does not decide it, but removes the reason to assume
(a) is dead on arrival. Strategy signal stops span a wide range, unlike `compute_final_stop`'s ≥2 ATR
floor:

| Strategy | Stop | ATR multiple |
|---|---|---|
| `breakout_base` | `base_high − atr * 0.2` (`strategy_engine.py:591,601`) | **0.2** |
| (swing-based variant) | `_swing_low(bars, 10) − atr * 0.2` (`:819,827`) | **0.2** |
| `pullback_ema` / `ma_crossover` | `fast_val − atr * atr_stop_mult`, default 1.5 (`:446,462`) | **1.5** (grid `[1.0, 1.5, 2.0]`) |
| `mean_reversion_bb` | `lower[-1] − stop_atr_mult * atr` (`:921,934`) | configurable |
| `mean_reversion_vwap` | `current − stop_atr_mult * atr` (`:1024,1035`) | configurable |

**A1 is no longer safely deferrable.** Piece 3 part 5 puts a gate badge in the ranking table, before
any contract has an exit plan — so the badge **must** use the delta-linear basis by construction; it
cannot wait for a click.

**Correction to the framing above (established after this doc was first written).** The shipped card
gate is *already* delta-linear and always has been: `TradeCard/index.tsx:820-842` calls
`stopPremiumRisk(sharedStop.price, sharedStop.stockPrice, cd.delta, cd.mid, …)` off the **scan-time**
`contractDetails`, with an explicit comment that it must fire before any Estimate has run. The
Black-Scholes reprice (`estimate_rr` → `exit.stop.contractPrice`) is a *different quantity* — the
contract's modelled value at the stop, at `dte_at_target = max(expiry_years × 0.5, 7/365)` — and it
drives sizing and the max-loss approval (`risk.ts:359-364`, `maxLossAtStop`), never the gate verdict.
So the two numbers already coexist on today's card, answering different questions.

Consequences for piece 3:

- A delta-linear ranking badge **agrees with the card gate by construction**. It is not a new
  approximation; it is the same function on the same inputs, moved one step earlier.
- Making the *gate* BS-repriced would not remove a disagreement — it would create one, between the
  gate and every card where no plan has been computed, and would promote `expiry_years × 0.5` from
  display-only to verdict-bearing.
- The residual disagreement is real but narrow and is **not** about the loss model: a **Step 6
  contract override** changes `delta`/`mid`, so the badge (auto-picked contract) and the card
  (overridden contract) describe different contracts. Piece 3 part 5 already requires the badge to
  say it describes the auto-picked contract; that label is what closes this, not a change of basis.

---

## 5. Deferred build pieces

| Piece | Scope | Status |
|---|---|---|
| **3** | Scan-time `finalStop` (plan Phase 1) | **NEXT.** See §6. |
| **4** | Per-position `premium_stop_pct` (Phase 4) — column + Alembic migration + three alert paths (`alertEngine.ts`, `alert_generator.py`, `EditDrawer`'s `alertFiresAgainst`) | Deferred. **Independent of piece 3** — could run in parallel. `auto_trader.py:254,352` sizes off the global pct and needs threading or an explicit "deliberately ignores it" note. |
| **5** | The per-trade selection (Phases 3 + 5 + 6) | Deferred. Largest, most unknowns. Needs a `TradeCard`→page channel that does not exist today (only `contracts` crosses that boundary) **and** persistence, because component state dies on step navigation and would silently disarm the choice. **Do not attempt until 1–4 have shipped.** |
| **6** | Stocks (Phase 7) | Deferred, **blocked on Q-A**. Also needs a new `POST /stocks/exit-plan` endpoint — `/contracts/exit-plan` requires `strike > 0`, `dte`, `premium > 0`, none of which a stock has. Seven `buildPaperStockPosition` call sites. |

---

## 6. Next: piece 3 — scan-time `finalStop`

### Why this one, not another

`computeExitPlan` is called from exactly one place — the "Compute Arithmetic Plan" button
(`TradeCard/index.tsx:1316`). It is optional and user-triggered. Both shipped pieces *prefer* the
exit plan's stop and **fall back when there isn't one**.

So on any card where Kenneth has not clicked that button, **Monte Carlo still sends the flat −3%.**
The bug the first handoff called "the worst factual wrongness on the card" is, today, fixed only for
people who click an optional button first. **Piece 3 is what makes pieces 1 and 2 take effect by
default.** That is a stronger argument than "it is next in the list".

### Scope — five parts, all of them

1. **Backend, at scan time.** Call `compute_final_stop` per **symbol**, attach `exit.finalStop`:
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
   `TableRow`, verify against the 1200 px min-width gate. State on the badge that it describes the
   **auto-picked** contract, since a Step 6 override can later change it. **This part forces A1 —
   see §4.**

---

## 7. Codebase facts that were expensive to establish

Each was discovered by an adversarial audit after a plan asserted the opposite. Verify before
trusting, but do not assume the naive reading. Full detail in
`2026-09-01-stop-model-session-handoff.md` §4.

1. **There are five stop levels, and two of them block submission.** `exit.invalidation` (flat −3%)
   feeds `checkInvalidation` (`risk.ts:303`), which **blocks every send** ("Invalidation stop
   required", `SendToBrokerDialog:270,299`). `exitPlan.stop.contractPrice` feeds
   `max_loss_per_trade_exceeded → approved = false` (`risk.ts:359-364`) plus
   `recommendedContractSize` (`TradeCard:922`). Two drafts called this "the Arithmetic card only". It
   is not.
2. **No stop order exists anywhere.** All four paper adapters are `Literal["MKT","LMT"]`. Everything
   called a "stop" today is an in-app alert.
3. **The backend re-anchors stops on save.** `portfolio.py:198-213` does
   `adjusted_stop + (live_price − scanStockPrice)`. Defensible for a percentage-of-price level,
   **wrong for a structural stop**, which is an absolute chart level. The two send paths disagree:
   `buildPaperPosition` sets `scanStockPrice` (so it re-anchors), `positionFromOrder` does not — same
   armed stop, two persisted values depending on which button was pressed. (Phase 6.2.)
4. **A post-trade selection model already ships.** `TpMethod = 'ladder' | 'monte_carlo' |
   'exit_plan_2r' | 'exit_plan_3r'` with `activeTpMethod`/`resolvedTpPrice`, persisted as
   `active_tp_method`. **But those fields are only on the PATCH schema** —
   `PortfolioPositionCreate` (`schemas/__init__.py:622-628`) has none of them. `ladder` deliberately
   stamps `resolvedTpPrice: null` so it keeps tracking live.
5. **Stock Monte Carlo already exists and is wired.** `estimate_stock_first_passage`
   (`first_passage.py:275`) via `POST /stocks/first-passage` (`stock_scan.py:1416`);
   `StockPositionCard` already has an Estimate button calling it.
6. **`compute_final_stop` takes no contract input** (`exit_plan.py:33`) — pure stock-price math over
   candles, so it already serves stocks.
7. **`compute_final_stop` returns a stop ≥ 2.0 ATR away by construction.** This kills any gate whose
   threshold is "< 1 ATR" — the origin of Q-A.
8. **Three different global premium percentages exist**, not one: `reward_risk.premium_stop_pct`,
   `auto_trade.premium_stop_pct` (`auto_trader.py:254,352`), `settingsStore.premiumStopPct`. There is
   **no per-position premium stop field at all.** (Piece 4.)
9. **The premium stop is not display-only.** It is the risk denominator in `computeEditedRR`
   (`TradeCard:83`) and `rrContribution` (`:1744`), and one of `isDirty`'s checks (`:69`).
10. **The Monte Carlo probability is an option-value barrier** (`hit_mask = option_paths >=
    target_option`, `first_passage.py:226`), while the *Invalidation* row's probability is a **stock**
    barrier (`:241`). The card does not distinguish them.
11. **`dte < 1` returns `probability = 0.0` for every target** (`first_passage.py:195-205`) — a
    refusal to simulate, not a real zero. The Intraday horizon hits this routinely. The card does not
    say so.
12. **`stop.contractPrice` reprices at half time-to-expiry** (`reward_risk.py:82`) — why a 109-DTE
    contract shows a ~94% loss. Inherited, uncorrected, out of scope.

---

## 8. Known-broken / accepted, carried forward

- **Nothing protective reaches a broker** (D10). After all seven phases you have alerts, not stops.
- **Monte Carlo freshness** (Phase 2.4). Re-running Compute Arithmetic Plan *after* an estimate does
  not retroactively update the already-rendered probability — it silently goes stale. Deliberately
  left by piece 1.
- **Backend stop re-anchoring** and the two disagreeing send paths — fact 3 above. (Phase 6.2.)
- **Three global premium percentages, no per-position field** — fact 8. (Piece 4.)
- **`dte < 1` → probability 0.0**, undisclosed on the card — fact 11.
- **Option-value vs stock barrier not distinguished** on the card — fact 10.
- **D2 only partially deliverable** — un-selected sends still carry the flat 3% (Phase 6.3).

---

## 9. Traps

- **Do not merge `claude/tradecard-setstate-render-wo6eru`** — it carries an accidental ~129 KB
  `backend/.venv-check/` virtualenv dump. Everything of value from it is now on `main`. **It can be
  deleted.**
- **Do not propose an R:R column with a premium-proportional denominator.** Two designs died on it.
  Compute the closed form first and check whether `premium` cancels. (§3)
- **Do not assume a value on the card is "display only".** Both audit rounds caught exactly this,
  twice each. Grep for consumers before calling anything cosmetic. (§7 facts 1, 9)
- **Do not re-run the adversarial loop against the whole plan.** It diverged: 24 findings → 32 after
  a rewrite that fixed every round-1 item. Audit one small piece at a time.
- **Implement, do not audit.** The plan's own conclusion is that the blast radius exceeds what any
  single review can enumerate. Ship a small piece, verify it, move on.
- **Run all three CI checks before claiming green.** (§2.3)
- **CLAUDE.md rules that have bitten:** `Status` labels are canonical (`lib/status.ts`) — which is why
  the two-state gate uses PASS/CAUTION rather than inventing "NOT PASS"; `npm run typecheck` must be
  clean before every commit; a new persisted store field needs a version bump **and** a migration
  branch (piece 3 part 4 needs exactly this).
- **Kenneth wants plain English.** Non-coder, high IT affinity. Short, jargon-free, with worked
  numeric examples. He asks to be grilled and to have work adversarially audited — take both
  literally.
- **When something said earlier turns out wrong, say so plainly.** This session had several: "all
  green" was frontend-only; the e2e failure was first blamed on the new layout bootstrap (wrong);
  the residual flake was first blamed on compile latency alone (half right — there were two
  independent races). Kenneth responds well to direct corrections.

---

## 10. Where to start

1. **Confirm A1 with Kenneth** (§4) — piece 3 part 5 needs the answer, and it is one question.
2. **Build piece 3** (§6), all five parts. Branch from `main`; `main` is green, so any red you see is
   yours.
3. **Then piece 4** — independent, can run in parallel.
4. Leave pieces 5 and 6. Piece 6 is blocked on Q-A regardless.
