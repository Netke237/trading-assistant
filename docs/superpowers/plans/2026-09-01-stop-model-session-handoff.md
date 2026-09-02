# Session handoff — trade-card stop model, the gate, and two rejected designs

**Branch:** `claude/tradecard-setstate-render-wo6eru` (all work pushed)
**For:** the next Claude session picking this up
**Read first:** this file, then `2026-08-31-stop-model-unification.md` (the plan — marked DO NOT
BUILD AS ONE PIECE), then `2026-08-31-montecarlo-premium-stop-columns.md` (a rejection record with
a proof in it).

---

## 1. What shipped (working, tested, pushed)

| Commit | What |
|---|---|
| `3c3754f` | **Bug fix.** `TradeCard`'s `patch()` called the parent's `onEditsChange` from *inside* `setOverlay`'s updater. React updaters must be pure and can run during another component's render, so this fired Step7Page's setState mid-render — "Cannot update a component while rendering a different component". Reworked to two sibling statements, matching `applyMaxLossOverride`. |
| `c8d3d75` | **Stop-vs-premium gate.** Flags contracts where the structural stop costs most/all of the premium. Renders in the Check-structure block with every input on one line (`$11.50 away × Δ0.45 = $2.50 of $2.50 premium (uncapped $5.18)`). |
| `3400041` | Gate thresholds moved to `scoring_rules.yaml → horizons.<key>.stop_premium`, served by `/api/config/stop-premium-thresholds`, consumed via `stopPremiumThresholdsStore` (fetch-with-fallback + a non-persisted per-run override layer). |
| `a095e74` | **Gate reduced to two states.** Kenneth's revision: PASS \| CAUTION, never REJECT, never red. One threshold (`pass_max_fraction`: Intraday 0.85 / Swing 0.80 / Position 0.70). |

Full suite green at each commit (989 tests, `npm run typecheck` clean).

---

## 2. Two designs that were built on paper and rejected — do not re-propose

### 2.1 An R:R column for the Monte Carlo card (rejected twice)

`2026-08-31-montecarlo-premium-stop-columns.md` holds the proof. Short version:

The backend defines the Monte Carlo target option price as `premium × (1 + pct)`
(`first_passage.py:185`), so:

```
reward = premium × pct        — ALWAYS, by construction
```

Therefore **any denominator proportional to premium cancels it out**, leaving `R:R = pct / k` — a
constant multiple of the number the user typed, identical for every contract and every symbol.

- Draft 1 used the premium stop (`premium × 0.60`) → `pct / 0.60`, a flat **1.667×**.
- Draft 2 used the exit plan's repriced loss (`premium × lossFraction`) → `pct / 0.937`, a flat
  **1.068×** — *worse*, closer to echoing the input than the design it replaced.

**And the deeper result:** for a long option whose stop sits at or beyond total premium loss, risk
*is* the premium, so `R:R = (premium × pct) / premium = pct`. That is arithmetic, not a display
defect. The existing "R:R vs. structural stop" cell reading ≈ the typed target is the cell telling
the truth. There is no denominator that fixes it.

What *does* discriminate between contracts is the **loss fraction** — `(premium − stopContractPrice)
/ premium` — which is the gate that shipped.

### 2.2 Expected value on the Monte Carlo card (rejected)

Three independent defects, any one disqualifying. Worst: the loss leg used `(1 − p_target)` when the
card carries a real stop probability one field away — on the reference contract that flips T20 from
**+$62 to −$100**. A correct version needs an option-value barrier in the simulation, a new request
field and a schema change; `stop_hit_mask` is a *stock-price* barrier and cannot be reused.

---

## 3. Decisions Kenneth made (authoritative — do not relitigate)

Full list is D1–D12 in `2026-08-31-stop-model-unification.md` §1. The ones most likely to be
accidentally undone:

- **D1 — each method owns a stop.** Arithmetic and Monte Carlo both use structural+ATR; Ladder keeps
  stock ± %. The duplication is deliberate (door open to diverge later). Kenneth chose this over the
  simpler "one stop with one exception" I recommended.
- **D2 — the flat −3% is NOT deleted.** It is reassigned from "position default" to "the Ladder
  method's stop". It is already YAML-backed and per-run editable in Step 3.
- **D4/D5 — per trade Kenneth picks:** method → one price row → stop basis (stock-price or premium).
  Explicit click, never "whichever method ran most recently".
- **D6 — all three alerts stay.** One armed, two advisory. The card must say which is which.
- **D8 + the later revision — the gate warns, never blocks, and now has only two states,
  PASS/CAUTION, and never paints red.** Kenneth's words: *"dont reject any contract. just show those
  with good profit or not… It will permit me upfront to identify highly profitable trades or lets
  say less risky."*
- **D10 — stop orders are not being built.** Kenneth: *"dont need to build it right now."*
- **D11 — existing open positions: do nothing.**
- **D12 — scope is stocks AND options.**

---

## 4. Facts about this codebase that were expensive to establish

Each of these was discovered by an adversarial audit after a plan asserted the opposite. Verify
before trusting, but do not assume the naive reading.

1. **There are five stop levels, and two of them block submission.**
   - `exit.invalidation` (flat −3%) → `PortfolioPosition.stop`, `STOP_REACHED`, the Monte Carlo
     Invalidation row, **and `checkInvalidation` (`risk.ts:303`) which blocks every send** —
     "Invalidation stop required" (`SendToBrokerDialog:270,299`).
   - `exitPlan.stop.contractPrice` → **`max_loss_per_trade_exceeded` → `approved = false`**
     (`risk.ts:359-364`), plus `recommendedContractSize` position sizing (`TradeCard:922`). Two
     drafts called this "the Arithmetic card only". It is not.
2. **No stop order exists anywhere.** All four paper adapters are `Literal["MKT","LMT"]`
   (`tradier_paper.py:15`, `ibkr_paper.py:60`, and the Alpaca/Tastytrade equivalents). Everything
   called a "stop" today is an in-app alert. Kenneth has broker interfaces, but they place *entries*.
3. **The backend re-anchors stops on save.** `portfolio.py:198-213` does
   `adjusted_stop + (live_price − scanStockPrice)` — and the same to `adjusted_structural_stop` and
   every target. Correct for a percentage-of-price level, **wrong for a structural stop**, which is
   an absolute chart level. The two send paths also disagree: `buildPaperPosition` sets
   `scanStockPrice` (so it re-anchors), `positionFromOrder` does not.
4. **A post-trade selection model already ships.** `TpMethod = 'ladder' | 'monte_carlo' |
   'exit_plan_2r' | 'exit_plan_3r'` with `activeTpMethod` / `resolvedTpPrice`, persisted as the
   `active_tp_method` column. **But those fields are only on the PATCH schema** —
   `PortfolioPositionCreate` (`schemas/__init__.py:622-628`) has none of them. And `ladder`
   deliberately stamps `resolvedTpPrice: null` so it keeps tracking live.
5. **Stock Monte Carlo already exists and is wired.** `estimate_stock_first_passage`
   (`first_passage.py:275`) via `POST /stocks/first-passage` (`stock_scan.py:1416`), and
   `StockPositionCard` already has an Estimate button calling it. It is documented as the version
   that drops IV back-out, the bisection and the BS repricing loop — i.e. "Monte Carlo without
   contract pricing" is built.
6. **`compute_final_stop` takes no contract input** (`exit_plan.py:33`) — pure stock-price math over
   candles, so it already serves stocks.
7. **`compute_final_stop` returns a stop ≥ 2.0 ATR away by construction**
   (`max(structural, atr_multiplier × ATR)`, `atr_multiplier: 2.0`). This kills any gate whose
   threshold is "< 1 ATR" — see the open question in §5.
8. **There are three different global premium percentages**, not one:
   `reward_risk.premium_stop_pct`, `auto_trade.premium_stop_pct` (`auto_trader.py:254,352`), and
   `settingsStore.premiumStopPct`. There is **no per-position premium stop field at all.**
9. **The premium stop is not display-only.** It is the risk denominator in `computeEditedRR`
   (`TradeCard:83`) and `rrContribution` (`:1744`), and one of `isDirty`'s checks (`:69`).
10. **The Monte Carlo probability is an option-value barrier**, not a stock touch:
    `hit_mask = option_paths >= target_option` (`first_passage.py:226`). The *Invalidation* row's
    probability, by contrast, IS a stock barrier (`:241`). The card does not distinguish them.
11. **`dte < 1` returns `probability = 0.0` for every target** (`first_passage.py:195-205`) — a
    refusal to simulate, not a real zero. The Intraday horizon hits this routinely.

---

## 5. Open questions — unanswered, blocking or near-blocking

| # | Question | State |
|---|---|---|
| **Q-A** | **The stocks gate basis.** A structural+ATR stop is ≥2 ATR by construction, so an "ATR-multiple" gate can never fire. Either (a) the stocks gate measures the *strategy signal's* stop — which narrows D7 to options only — or (b) thresholds become relative to `atr_multiplier`. **Recommended (a), but round 2 flagged that `pullback_ema`'s default `atr_stop_mult: 1.5` may make (a) unreachable too — verify across all seven strategies before committing.** | **Blocking Phase 7** |
| **A1** | Gate loss basis: cheap delta-linear (works from scan data, so the badge can exist in the ranking table) vs the exit plan's Black-Scholes repriced value (more accurate, needs a click first). Never answered; plan assumes delta-linear default, upgrading when a plan exists. **Round 2 note:** if the repriced basis drives the *verdict*, then `dte_at_target = expiry_years × 0.5` becomes verdict-bearing rather than display-only. | Open |
| Q23–Q27 | Answered by me, not by Kenneth — he said "go ahead" without responding. All flagged as reversible assumptions in the plan's §1.1. | Open, low risk |
| — | **Is piece 1 approved to build?** Last question asked in-session; no answer yet. | Open |

---

## 6. Where to pick up

The plan is **not** buildable as one piece. Two audit rounds went **24 findings → 32 findings** —
diverging, not converging, because the blast radius exceeds what one review can enumerate. It is
split into six pieces in §8 of the plan. Smallest first:

**Piece 1 — the Monte Carlo card should stop simulating the flat −3%.** Today the card sends
`invalidation_price: exit.invalidation` ($195.80 on the reference contract) while displaying a
structural+ATR stop of $185.87 six inches above. That is why it showed "62% probability of
invalidation" — measured against a stop three times tighter than the one on screen. Per D1, Monte
Carlo's stop is structural+ATR, so the card should send that instead. **One field on one request,
backend untouched.** The probability will drop, and that is the correction, not a regression.

Kenneth asked what this meant and it was explained in-session; he had not yet said "build it".

**Piece 2** — `structuralRR` (`TradeCard:790-825`) and the gate should read the *same* stop as each
other. Frontend only. Note `structuralRR` currently uses the **raw** structural level while the gate
now uses the shared one — a fifth stop hiding on the same card.

Pieces 3–6 (scan-time `finalStop`, per-position `premium_stop_pct` + migration, the per-trade
selection, stocks) are larger and described in the plan.

---

## 7. Traps

- **Do not propose an R:R column with a premium-proportional denominator.** Two designs died on it
  (§2.1). If a new one is proposed, first compute its closed form and check whether `premium`
  cancels.
- **Do not assume a value on the card is "display only".** Both audits caught exactly this, twice
  each. Grep for consumers before describing anything as cosmetic.
- **Do not re-run the adversarial loop against the whole plan.** It diverged. Audit one small piece
  at a time.
- **CLAUDE.md rules that bit during this session:** `Status` labels are canonical (`lib/status.ts` —
  "the ONLY allowed labels are exactly these", which is why the two-state gate uses PASS/CAUTION
  rather than inventing "NOT PASS"); `npm run typecheck` must be clean before every commit; a new
  persisted store field needs a version bump **and** a migration branch.
- **Kenneth wants plain English.** He is a non-coder with high IT affinity. He has asked repeatedly
  for short, jargon-free explanations and worked numeric examples. He also asks to be grilled and to
  have work adversarially audited — take both literally.
- **When something I said earlier turns out wrong, say so plainly.** Several corrections in this
  session were corrections *of my own earlier corrections*; Kenneth responded well to those being
  stated directly rather than softened.
