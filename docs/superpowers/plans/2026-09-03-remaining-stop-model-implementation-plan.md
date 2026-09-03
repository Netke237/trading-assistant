# Implementation plan — the remaining stop-model pieces

**Date:** 2026-09-03 · **Status:** plan, nothing built.
**Baseline:** `main` = `dc051a5` (Barrier Race round 9, clean).
**Sources:** handoffs #4 §6/§7, #5 (Q1–Q11), #6 (§4 coverage, §5 build order), #11 §5; the gate-basis,
piece-4 and piece-6 specs; and the Trade Card Schematic artifact `e8843f48` (read in full this
session — see §8).

This is the consolidated build plan for everything specified but not built. It supersedes the build
orders in round 5 §6 and round 6 §5 only where §7 below records a conflict; otherwise it follows them.

---

## 1. Status ledger — verified against `dc051a5`, not taken from doc status lines

| Item | State | Evidence |
|---|---|---|
| Stop-vs-premium gate (PASS/CAUTION, D8) | **Shipped** | `risk.ts:70` `stopPremiumRisk`, `TradeCard:1606` |
| Piece 1 — MC uses structural+ATR stop | **Shipped** | round 4 |
| Piece 2 — gate + MC share a stop | **Shipped (half)** | third consumer `structuralRR` deleted, not repointed |
| Barrier Race + `reprice_horizon` YAML | **Shipped** | `scoring/reprice_horizon.py`, `risk_rules.yaml:73`, 7 presets + clamp — matches the artifact verbatim |
| Removal: half-life repricing | **Done** | replaced by `resolve_reprice_days` |
| Removal: `structuralRR` (MC card R:R) | **Done** | absent from production code; survives only in test comments |
| **Contract `iv` field** | **NOT BUILT** | `ContractDetails` has `delta`/`theta`/`ivRank`/`ivPercentile`, no `iv` |
| **Gate basis (Q3/Q7)** | **NOT BUILT** | `risk.ts` still Δ-linear; no `StopCostOut`; YAML still `pass_max_fraction: 0.8` |
| **Piece 3 — scan-time `finalStop`** | **NOT BUILT** | `scan.py` never calls `compute_final_stop`; `scanStore` v12 |
| **Piece 4 — per-position premium stop** | **NOT BUILT** | `PortfolioPositionModel` has `stop`/`structural_stop` only |
| **Piece 6 — `/stocks/exit-plan`** | **NOT BUILT** | only `/contracts/exit-plan` exists |
| **Heston calibration (Q8)** | **NOT SPEC'D** | decided paragraph only |
| **Piece 5 — per-trade pick (D4/D5)** | **NOT SPEC'D** | needs a card→page channel that does not exist |
| Removal: Invalidation row (MC card) | **Pending your OK** | still at `TradeCard:2057` |
| Removal: Projected R/R (+8%) | **Pending your OK** | still at `TradeCard:2075` |

Preconditions confirmed clean: **Alembic has exactly one head** (`2bf3bf834b29`), so Piece 4's
migration is safe to generate. `estimate_stock_first_passage` exists at `first_passage.py:714` (the
piece-6 spec says `:275` — stale line number, same function). `bs_price` and `bs_iv` both exist in
`models/black_scholes.py`.

---

## 2. The critical path

One field gates two pieces. Everything else is parallel.

```
        Phase A ── contract `iv` on the scan payload
             │
      ┌──────┴──────┐
      ▼             ▼
  Phase B        Phase C            Phase D          Phase E
  Gate basis     Piece 3            Piece 4          Piece 6
  (Q3/Q7)        scan finalStop     premium stop     stocks plan
      │             │               (independent)    (independent)
      └──────┬──────┘
             ▼
        Phase F Heston  →  Phase G Piece 5 (needs A–D landed)
```

**Do Phase A alone, first, as its own commit.** Both B and C need it; sequencing them after A means
the scan payload is touched once instead of twice, which is the whole reason round 6 §5 put the gate
basis directly after the race.

**D and E can start today, in parallel, by anyone.** Neither touches `iv`, the gate, or the scan
payload. If you have two sessions, run D or E alongside A→B→C rather than idling.

---

## 3. Phase A — the contract `iv` field

**Why first:** the gate's new Black-Scholes basis and the ranking badge both need the contract's
actual implied volatility. `ivRank` is a percentile (where today's vol sits inside its own year), not
a volatility — it cannot substitute. The value is already computed server-side and simply never sent.

**Backend**
1. `ContractDetails` (`schemas/__init__.py:~405`) gains `iv: Optional[float] = None`.
2. Populate from `bs_iv(mid, spot, strike, expiry_years, r, is_call)` — already implemented.
3. **`bs_iv` returns `None` when it cannot converge.** Carry `iv: null` through. Never substitute a
   default, never fall back to `ivRank / 100`.

**Frontend**
4. `ContractDetails` type gains `iv?: number | null`.
5. The Contract Details card renders **IV 34.5%** beside IV rank (artifact card 01: "One field
   added"). Render `—` when null.

**Tests**
6. A contract whose mid does not solve → `iv is None`, and nothing downstream throws.
7. Round-trip: backend `iv` reaches the frontend type with no optional-field surprise.

**Definition of done:** `iv` is on the wire and on the card, and a non-converging contract renders
`—` rather than a plausible-looking number. No gate change yet.

---

## 4. Phase B — gate basis and thresholds (Q3 / Q7)

Follow `2026-09-02-gate-basis-spec.md`. Additions and corrections from this session's code read:

### B1. The endpoints return the cost — the card never computes

The gate is evaluated at a stop **that moves** (`Check structure`, `Compute Arithmetic Plan`). A
scan-time precompute cannot serve it, and a TypeScript pricer is rejected (there is not one
`Math.exp` in `frontend/lib/` today, and the artifact's card 03 explicitly keeps the arithmetic
printed rather than relocated).

- `StructuralStopRequest` (`routers/contracts.py:289`, currently 3 fields) gains four **optional**
  fields: `strike`, `dte`, `premium`, `iv`. Present together or not at all.
  **A partial set must 422.** Silently skipping the gate because one field was missing is how a
  contract with no verdict reads as an unremarkable one.
- New `StopCostOut`: `lossDollar`, `valueAtStop`, `fraction`, `status`, `passMaxFraction`,
  `basis: "bs_today"`. `StructuralStopResponse` gains `stopCost: Optional[StopCostOut]`.
- `/contracts/exit-plan`'s `ExitPlanStopOut` gains the same block, computed against
  `final_stop.price`. **The two will legitimately disagree** — a wider stop, a different verdict.
  Assert that in a test rather than treating it as a bug.
- **Do not fork an alias route.** `/contracts/structural-stop`'s docstring says the stocks-mode
  `StockPositionCard` calls this same endpoint. The new fields are optional precisely so the stock
  caller omits them.

### B2. Basis and thresholds

`loss = premium − BS(stop_price, strike, dte_today, r, iv, is_call)` — **today's** time to expiry,
zero theta. The gate must fire before any button is pressed, so it cannot use the exit plan's horizon.

`scoring_rules.yaml → horizons.<key>.stop_premium.pass_max_fraction`: **0.80 / 0.70 / 0.60**
(Intraday / Swing / Position). There are three `stop_premium:` blocks in the file today, all reading
`0.8` — all three must move.

They **must** move together with the basis. Under the new ruler the worst contract on the reference
chain reads 77%, beneath the old Swing line of 0.80 — keep the old numbers and the gate goes
permanently silent.

### B3. Frontend — `stopPremiumRisk` becomes a presenter

```ts
export function stopPremiumRisk(c: StopCostOut | null): StopPremiumRisk | null
```

The Δ-linear arithmetic is **deleted, not kept as a fallback.** A fallback that quietly answers a
different question is worse than no answer; where no `stopCost` came back the badge reads
"not computed".

`formatStopPremiumRisk` prints the new inputs:
`$5.20 premium − $1.49 at $185.87 = $3.71 of $5.20 premium`.

**`capped` and the `(uncapped …)` tail go away** — Black-Scholes cannot exceed the premium on a long
option. I counted **21 `capped` references** across `risk.ts`, `risk.test.ts` and `TradeCard`; work
through all of them, do not leave a dangling field.

Badge additionally shows **dollars left at the stop** ($1.49) — per the artifact, more actionable
than a percent when deciding whether to overrule.

### B4. Tests

The spec's nine, plus the artifact's reference chain as a fixture. The chain reproduces to the cent
and **0.70 splits it 3 PASS / 5 CAUTION** — the spec and the artifact agree exactly on this, so it is
a hard assertion, not a guide:

| Strike | 195 | 200 | 205 | 210 | 215←ref | 220 | 230 | 240 |
|---|---|---|---|---|---|---|---|---|
| Left at stop | $4.87 | $3.70 | $2.76 | $2.03 | $1.49 | $1.10 | $0.62 | $0.36 |
| New | 63% | 65% | 67% | 70% | 71% | 73% | 75% | 77% |
| Swing @ 0.70 | PASS | PASS | PASS | CAUTION | CAUTION | CAUTION | CAUTION | CAUTION |

(Stock $201.86 → stop $185.87, 45 DTE.) Also keep the `reject_fraction` regression guard: the
endpoint's key set must match `HorizonStopPremiumThresholds` **exactly**, so a re-added key fails loudly.

---

## 5. Phase C — Piece 3, scan-time `finalStop`

Round 4 §6, all five parts. **This is what makes pieces 1 and 2 take effect by default** — today, on
any card where the Arithmetic Plan button was never pressed, Monte Carlo still sends the flat −3%.

1. **Backend, at scan time.** Call `compute_final_stop` per **symbol**, attach `exit.finalStop`:
   `{price, source, structuralPrice, structuralSource, atrFloorPrice, distanceDollar, atr, computedAt}`.
   `structuralSource` and `distanceDollar` are **required** — the "Bottom (final stop)" row reads both.
   Wrap in `asyncio.to_thread`; `find_structural_stop` is synchronous CPU work and `scan.py` already
   offloads every comparable computation. Assembly point is `scan.py:863` (`exit=TradeExit(...)`).
2. **`stop.contractPrice` cannot exist at scan time** (it needs a contract). Contract-priced sub-cells
   and `recommendedSize` render `—` until a plan is computed. State it explicitly.
3. **Survive a Step 6 contract override.** `mergePlan` does `exit: plan.exit` — a wholesale
   replacement — and `TradeExit` (`schemas/__init__.py:420`) has no `finalStop`, so it would be wiped
   for exactly the cards where a contract was hand-picked. Add `finalStop` to `TradeExit`, echo it
   from `/contracts/recompute-plan`, **and** splice it in `withCachedEstimate` as defence in depth.
4. **Persisted-store migration.** `scanStore` is at `version: 12` (`scanStore.ts:310`). Bump to **13**
   with an explicit migration branch — CLAUDE.md requires both. Pre-13 restores render
   **"not computed — re-run the scan"**, never a blank and never a silent PASS.
5. **Ranking badge (D8).** `WatchlistRow` (`types/domain.ts:134`) carries no `exit` and no
   `contractDetails`. Add exactly **two** fields — `stopCostPct` and `stopCostStatus` — populate in
   `cardToRow`, add one grid track to `COLUMNS` and `TableRow`, and check it against the 1200px
   min-width gate. The badge must say it describes the **auto-picked** contract, since a Step 6
   override can change it later.

> **Basis for the ranking badge: Black-Scholes, computed backend-side.** See §7 conflict 1 — round 4
> §6 part 5 says delta-linear and is superseded.

---

## 6. Phases D–G

### Phase D — Piece 4, per-position premium stop *(independent, start any time)*

Follow `2026-09-02-piece-4-per-position-premium-stop-spec.md`. The load-bearing points:

- Column `premium_stop_pct = Column(Float, nullable=True, default=None)`. **NULL means "inherit the
  global"** and is a distinct, load-bearing state — a position stamped 0.60 at creation would stop
  responding to a global change, which is exactly today's behaviour and the thing this removes.
- Alembic: one nullable column, no backfill. Head is currently single (`2bf3bf834b29`) — re-check
  `alembic heads` immediately before generating; this repo has had a multiple-heads incident.
- **Settable at creation, not update-only.** `active_tp_method` is on the update schema only; do not
  repeat that. A trade sent from the card must carry the per-trade stop or its first alert silently
  uses the global.
- **One shared resolver for all three alert paths** — `alert_generator.py:295`, `alertEngine.ts`'s
  `scanPortfolio` (which currently takes a single `premiumStopPct` for all positions,
  `alertEngine.ts:96-100` — resolve per position inside the loop), and `EditDrawer`'s
  `alertFiresAgainst`. A preview that disagrees with the alert that later fires is worse than no
  preview. `thresholdPct` in the emitted alert must be the **resolved** value.
- `auto_trader.py:254,352` threads the per-position value through, `?? auto_trade.premium_stop_pct`.
- Both send paths carry it: `positionFromOrder` (`step-7-trade-card/page.tsx:75`) and
  `buildPaperPosition` (`:603`). These two already disagree about stop re-anchoring — do not add a
  second field they disagree on. One test asserts they produce the same value for the same input.
- EditDrawer distinguishes **inherited** from **set**: `"60% (global)"` vs `"45%"`.

### Phase E — Piece 6, stocks arithmetic plan *(independent, start any time)*

Follow `2026-09-02-piece-6-stocks-arithmetic-plan-spec.md`. Mostly assembly:

- **There is no stocks gate.** Q-A is closed. A stock's stop cost is exact (`distance × shares`) and
  sizing already covers it. Do not build a badge that looks like the options one but answers a
  different question.
- `compute_final_stop` and `compute_target_row` take no contract input — they survive verbatim.
  `estimate_rr` and the gate are dropped; `estimate_first_passage` is replaced by
  `estimate_stock_first_passage` (`first_passage.py:714`).
- New `POST /stocks/exit-plan` — needed because `/contracts/exit-plan` requires `strike > 0`, `dte`
  and `premium > 0`. Reuse `/contracts/structural-stop` (its contract fields from Phase B are
  optional and simply omitted).
- **Carry both guards over:** `< 2 candles` and `atr <= 0` both 422. Without them the ATR floor
  collapses to the entry price and every target lands on entry.
- **Disclose the day-count difference:** options counts calendar days, the stock engine counts
  trading days. Do not silently unify — ship `daysBasis: "trading"` and render "~10 trading days".
- Include the **stop's probability** — `estimate_stock_first_passage` returns it free, and "this stop
  is reached on 34% of paths, typically in 6 trading days" is the most decision-relevant number.
- Test 9 is the anti-regression: assert on the schema's **key set** that no premium, strike, DTE, IV,
  delta or stop-cost field appears anywhere, so an options field cannot leak back in later.
- The spec's §5 recommends the two-barrier stock version of the Barrier Race. **Flagged as an
  addition, not assumed** — it needs your yes.

### Phase F — Heston calibration (Q8) *(needs a spec first)*

Decided, never written up. The substance: `heston_cache.py:36` has `v0_grid = [0.04]` — one value,
20% vol, hardcoded for every symbol on every scan, while the reference contract has 34.5% IV. **The
pricer is fine; the calibration is the defect.** Seed `v0` from the chain's own ATM IV (the correct
seed `v0_seed = (mean chain IV)²` already exists in the file and is used only in the fallback path),
fit relative or vega-weighted error instead of absolute dollars, and **use Heston only when its
measured RMSE beats the BS-own-IV baseline on the same chain.** Write the spec before building.

### Phase G — Piece 5, the per-trade method pick (D4/D5) *(needs a spec first)*

Largest, last, needs A–D landed. Every decision behind it is made; what is missing is a card→page
channel and persistence so the choice survives step navigation. Today "Computed via" is still
"whichever method ran most recently", now with Barrier Race as a fourth option.

---

## 7. Three conflicts in the source documents — resolved here

1. **Ranking-badge basis.** Round 4 §6 part 5 says *"Use the delta-linear basis — see A1 in §4; it
   matches the shipped card gate by construction, so no decision is pending."* The gate-basis spec
   §2.3 says the backend computes it with Black-Scholes and the row carries only the result. **The
   gate-basis spec wins** — it is later, it is what Q3 decided, and the artifact's summary table
   independently lists the ranking badge under "Black-Scholes, contract's own IV, today". Round 4's
   text was written when the card gate was still Δ-linear; leaving both bases live would put two
   different rulers on one screen.
2. **`estimate_stock_first_passage` line number.** Piece-6 spec says `first_passage.py:275`; it is at
   `:714`. Same function, stale reference.
3. **Round 4 §6 vs. the artifact on `iv`.** Round 4 treats the scan `iv` field as part of piece 3; the
   gate-basis spec treats it as shared. Pulled out as **Phase A** here so neither piece owns it and
   the payload is touched once.

---

## 8. On the artifact

Read in full this session from the uploaded HTML (42 KB, 603 lines) — the earlier sessions could not
reach it, and neither could I via the artifact URL (it belongs to your other account, so I am served
as a public reader and that path is not enabled). **Your upload closed the last documentation gap.**

It agrees with the specs everywhere I checked, including the 3 PASS / 5 CAUTION split and the seven
`reprice_horizon` fallback rows. Round 6's rule still stands: **reference, not authoritative where the
specs differ.** Two things it adds that the specs do not state:

- Card 01 shows `iv` rendered **on the Contract Details card**, not only carried in the payload.
- Its closing table, *"Where each number comes from, after the change"*, is the clearest one-page
  statement of the target state. Worth keeping.

**Recommendation:** commit the HTML to `docs/superpowers/specs/` so it stops being reachable only
from your Downloads folder and one account.

---

## 9. Two removals still pending your word

The artifact flags four; two are done (half-life repricing, `structuralRR`). These two are still live:

| What | Where | Why it should go |
|---|---|---|
| **Invalidation row** | MC card, `TradeCard:2057` | Not a removal — a **move**. Its probability and expected days are the stop half of the race; standing beside independently-measured target probabilities it invites a comparison that does not hold. |
| **Projected R/R (+8%)** | Fixed % Ladder, `TradeCard:2075` | Third R:R on one page, and the least defensible: reward from a hardcoded +8% stock move you never chose, risk from a flat 60% of premium. |

**In both cases only the readout goes — the stored field stays.** `overlay.premiumStop` is a live risk
denominator in `computeEditedRR`, `rrContribution` and `isDirty`, and it is the Barrier Race's third
barrier. Round 7 already had to revert one over-eager deletion of the Invalidation row; note also that
`exit.invalidation` **blocks every send** ("Invalidation stop required"), so the field is a hard submit
gate, not decoration.

---

## 10. Traps carried forward

- **`np.argmax` on a boolean row returns 0 for both "hit on day 1" and "never hit."** Pair every
  `argmax` with `.any(axis=1)`.
- **`dte < 1` returns probability 0.0 for every target** — a refusal to simulate, not a real zero.
  Return `None` and say "not simulated"; four zeroes summing to 0% look like a computed answer.
- **The backend re-anchors stops on save** (`portfolio.py:198-213`). Defensible for a percentage
  level, **wrong for a structural stop**, which is an absolute chart level. The two send paths already
  disagree here.
- **No stop order exists anywhere.** All four paper adapters are `Literal["MKT","LMT"]`. Everything
  called a "stop" is an in-app alert. D10 stands.
- **Grep before removing.** The `capped` field has 21 references; the "129 KB" venv estimate in an
  earlier handoff was wrong by >2000×. Verify, do not repeat.
- **Kenneth is a non-coder with high IT affinity.** Plain English, worked numeric examples, no jargon.
  He asks to be grilled and adversarially audited — take both literally.

---

## 11. Suggested first move

**Phase A on its own branch, then Phase B.** A is small, it is the only thing two pieces both need,
and it is the cheapest possible proof that the payload change is clean before the gate rewrite lands
on top of it. If a second session is available, start **Phase D or E** in parallel — neither touches
`iv`, the gate or the scan payload.
