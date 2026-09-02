# Session handoff #5 — the design session. Eleven decisions, two documents, no code.

**Date:** 2026-09-02
**Branch:** `claude/bamendjou-stop-model-piece-3-9mh03d` (pushed)
**`main`:** `89eeb535`, unchanged this session. All three CI checks green as of round 4.
**Code written this session:** none. Two documents, both committed to the branch above.

This session did not build. It reconciled what Kenneth wanted from the options R:R / stop model
against what the code actually does, found three things that changed the plan, and settled eleven
decisions. **Read `2026-09-02-stop-model-handoff-round-4.md` for everything before this**; that file
is still the record of what shipped. This one is the record of what was decided.

---

## 1. Documents produced

| Document | Where | What it is |
|---|---|---|
| **Trade Card Schematic** | Artifact `e8843f48-17f3-406d-98fd-0351408ea3ed` | **Kenneth's reference.** All seven Step 7 cards field by field, with on-card explanation text, the new Barrier Race card, the re-derived gate thresholds, and every proposed removal flagged. He approved it explicitly. |
| **Barrier Race spec** | `docs/superpowers/plans/2026-09-02-barrier-race-spec.md` | Implementation specification. Backend, schema, frontend, config, 16 named tests, definition of done. |

The artifact is not reachable from a new session's tooling. If it is needed, ask Kenneth for the
link or rebuild from the spec — the spec is self-contained.

---

## 2. The three findings that changed the plan

Each was established by reading the code, and each contradicted an assumption in the round-4 plan.

### 2.1 Heston's most important parameter is not fitted

`backend/app/models/heston_cache.py:36` — the default calibration grid is `v0_grid = [0.04]`. One
value. `v0` is *today's* variance; 0.04 is 20% volatility, **hardcoded for every symbol on every
scan**. The reference contract has 34.5% IV and is priced as if it were 20%. Meanwhile
`reward_risk.py` backs the IV out of each contract's own quoted mid.

**So in this repo, plain Black-Scholes is almost certainly more accurate than the shipped Heston** —
the opposite of the theory Kenneth (correctly) cited. Two supporting defects: RMSE is summed in
absolute dollars across the whole chain, so deep-ITM contracts dominate the fit and the cheap OTM
contracts he trades contribute nothing; and the 1.0s timeout returns a hardcoded fallback with
`rmse = inf` that no card discloses.

The pricer itself (`heston.py`) is a legitimate closed-form characteristic-function implementation.
**The problem is entirely calibration**, so the theory-win is reachable cheaply. The correct `v0`
seed already exists in the file — `v0_seed = (mean chain IV)²` — used only in the fallback path,
never fed into the grid.

### 2.2 The half-life constant is a bigger error than the entire linear-vs-Black-Scholes question

`reward_risk.py:82`, `first_passage.py:174`: `dte_at_target = max(expiry_years * 0.5, 7/365)`.
Every reprice assumes the level is reached at exactly half the contract's remaining life.

Measured on a $100 stock, 45 DTE, IV 30%:

| | Δ-linear | BS today | BS half-life |
|---|---|---|---|
| −5% stop, OTM | 74% | 57% | **86%** |
| −2% stop, OTM | 29% | 27% | **68%** |

Linear-vs-curvature is worth ~17 points. The half-life assumption is worth **~39**. The card was
paying for a better model and then throwing away more than twice as much accuracy through an
invented holding period.

### 2.3 Delta-linear cannot discriminate at all on a wide stop

Reference contract chain, stock $201.86 → stop $185.87, 45 DTE:

| Strike | 195 | 200 | 205 | 210 | 215 | 220 | 230 | 240 |
|---|---|---|---|---|---|---|---|---|
| **New (BS today)** | 63% | 65% | 67% | 70% | 71% | 73% | 75% | 77% |
| **Old (Δ-linear)** | 81% | 86% | 93% | 99% | **100%** | **100%** | **100%** | **100%** |

The old measure pins four of eight strikes at exactly 100% — it cannot tell a 220 call from a 240
call. That is why the gate has felt like it says nothing: it kept repeating the one thing Kenneth
already knows (a long option's max loss is the premium) instead of ranking.

**Consequence:** feeding the new, less pessimistic measure into the old thresholds (0.85 / 0.80 /
0.70) would leave the *worst* contract on that chain at 77% — under the Swing line. The gate would go
permanently silent. Hence Q7.

### 2.4 Smaller facts worth carrying

- `hit_mask` (option-value barrier) and `stop_hit_mask` (stock barrier) are already computed over the
  **same paths in the same call** and never compared. The barrier race is a comparison, not a
  simulation.
- `HORIZON_PRESETS` offers **seven** presets; `scoringHorizonForHold` collapses Quarterly /
  SemiAnnual / Annual into `Position`. A holding-time table keyed on the scoring horizon would give a
  200-day hold and a 20-day hold the same value.
- `contractDetails` already carries **theta in $/day** but **not** the contract's IV. The gate's new
  basis needs the IV; it is computed server-side and simply never sent.

---

## 3. Decisions — Q1–Q11, all settled by Kenneth

| # | Decision |
|---|---|
| **Q1** | **R:R only where a leg lives in stock-price space.** Premium-% targets (T20/T30/T50) carry probability and timing, never a ratio: the backend *defines* the target as `premium × (1+pct)`, so reward is `premium × pct` and any premium-proportional denominator cancels. Keep both cards; R:R belongs to the stock-defined one. |
| **Q2** | **Kill the half-life constant.** Reprice at the simulation's own median days to that barrier, falling back to a **per-preset** YAML table (seven rows, not three). `Custom` derives from the typed hold range (`fraction_of_hold`, midpoint halved), never snaps to a preset. A `max_fraction_of_dte: 0.75` clamp stops an Annual preset repricing a 30-day contract past expiry. |
| **Q3** | **Gate basis → Black-Scholes at today's date** (curvature, zero theta). Needs no click and no exit plan, so it satisfies the constraint that killed the exit-plan basis. Requires the contract's IV in the scan payload. |
| **Q4→Q8** | **Heston: fix the calibration, do not drop it.** Seed `v0` from the chain's own ATM IV; fit relative or vega-weighted error instead of absolute dollars; then **use the Heston price only when its measured RMSE beats the BS-own-IV baseline on the same chain**, falling back otherwise. Kenneth's instinct that Heston should beat BS was right in theory; §2.1 is why it doesn't here. |
| **Q5** | **Build the barrier race, ahead of piece 3.** |
| **Q6** | **Armed stop = whichever fires first**, once the race can measure it. Until then the structural stock stop. The race *informs* the choice; it does not make it. |
| **Q7** | **Gate thresholds re-derived: 0.80 / 0.70 / 0.60** (Intraday / Swing / Position). Taken as proposed rather than measured against a real scan — Kenneth's explicit call. Plain meaning: PASS means at least 20% / 30% / 40% of the premium is still there when the stop hits. |
| **Q9** | **Barrier Race is its own card**, below Monte Carlo. Same simulation, same click, no second button. Monte Carlo answers a per-target question; the race answers a whole-position one. |
| **Q10** | **The premium-stop barrier reads the card's existing editable "Premium stop" field.** Piece 4 (per-position `premium_stop_pct` + Alembic migration) stays deferred and is not a prerequisite. |
| **Q11** | **Build order:** (1) barrier race + reprice-horizon YAML, (2) gate basis + thresholds, riding piece 3's scan payload, (3) rest of piece 3, (4) Heston calibration, (5) piece 4. |

**Also settled:** the race table is **one row per profit target** (T1/T2/T3), not one race against a
hand-picked target. The two stop barriers are identical across rows; only the target changes, so
racing all three tells you which target is worth aiming at. Approved 2026-09-02; the artifact matches.

**D1–D12 from `2026-08-31-stop-model-unification.md` §1 all still stand.** Nothing this session
overturned them. D8 in particular: two states, PASS/CAUTION, never REJECT, never red, never blocks.

---

## 4. Two designs still rejected — do not re-propose

1. **An R:R column driven by a premium-proportional denominator.** Compute the closed form first and
   check whether `premium` cancels. The race's *stock-stop* R:R survives this test because
   `premium − BS(stop, …)` is not proportional to premium; its *premium-stop* R:R does not survive —
   it reduces to `pct ÷ premium_stop_pct` — and is therefore shown greyed and explicitly labelled as
   not a discriminator. **Both are displayed; only one is a measurement.**
2. **Expected value computed with `(1 − p_target)` as the loss probability.** The barrier race is
   what makes a correct version possible, because it produces genuinely exclusive path shares.

---

## 5. Open questions

| # | Question | State |
|---|---|---|
| **Q-A** | **The stocks gate basis.** `compute_final_stop` returns a stop ≥ 2.0 ATR away by construction, so an "ATR-multiple" gate can never fire against it. Either (a) the stocks gate measures the *strategy signal's* stop (those span 0.2–2.0 ATR), or (b) thresholds become relative to `atr_multiplier`. | **Still open. Blocks piece 6.** Unchanged from round 4. |
| — | **Whether the 0.80 / 0.70 / 0.60 thresholds hold up on a real universe.** Taken as proposed (Q7). Revisit only if the observed flag rate looks wrong once the new basis ships. | Low risk, one YAML edit |
| Q23–Q27 | Answered by Claude, not by Kenneth. Reversible assumptions. | Open, low risk |

**A1 is closed.** It was framed as a two-way choice — delta-linear vs the exit plan's half-life
reprice — and both options were wrong. The third, Black-Scholes at today's date, was never on the
table and is what Q3 selected. Do not reopen it as a two-way question.

---

## 6. Deferred build pieces

| Piece | Status |
|---|---|
| **Barrier race + reprice horizon** | **NEXT.** Spec is written: `2026-09-02-barrier-race-spec.md`. Nothing left to ask. |
| **Gate basis + thresholds (Q3/Q7)** | After the race. Rides piece 3's scan payload — both need the contract IV field added |
| **3** — scan-time `finalStop` | After that. Five parts, unchanged from round 4 §6 |
| **4** — per-position `premium_stop_pct` | Deferred, independent |
| **5** — the per-trade method selection (D4/D5) | Deferred, largest. The race *informs* it, does not implement it |
| **6** — stocks | Deferred, **blocked on Q-A** |

---

## 7. Recommended next step

**Build the barrier race and the reprice-horizon YAML together, from the spec.** They are the same
change: the YAML is what the race prices its risk leg against, and splitting them means writing
`resolve_reprice_days` twice.

Start with the backend attribution in `first_passage.py` and its tests — items 1–9 of the spec's §4.
The whole feature stands or falls on the four path shares summing to exactly 1.0, and on
`_first_day` handling the never-hit row. Get those green before touching the frontend.

Then the gate basis change, riding piece 3's scan payload.

---

## 8. Traps

Everything in round 4 §9 still applies. Added this session:

- **`np.argmax` on a boolean row returns 0 both for "first True at index 0" and for "no True
  anywhere".** Written naively, every path that reached no barrier is recorded as hitting on day one
  and wins every race. Pair every `argmax` with its `.any(axis=1)` and push non-hitting paths to an
  out-of-range index. There is a test for exactly this.
- **Two barriers can be crossed on the same simulated day.** The tie rule is pessimistic and written
  down: stop beats target, premium stop beats stock stop. Never leave it to whichever comparison ran
  first.
- **`dte < 1` returns probability 0.0 for every target** — a refusal to simulate, not a real zero.
  The race must return `None` there, and the card must say "not simulated — contract expires today".
  Four zeroes summing to 0% look like a computed answer.
- **`overlay.premiumStop` is not display-only.** Removing the Ladder card's R:R *readout* must not
  touch the field: it is a live risk denominator (`computeEditedRR`, `rrContribution`, `isDirty`) and
  is now also the race's third barrier. Round 4 §7 fact 9; both prior audit rounds caught a false
  "display only" assumption.
- **The race must clear, not silently update, when a barrier moves.** Editing the premium stop or
  re-checking structure invalidates every bar. Show "barriers changed — re-run the estimate".
- **Add `premium_stop_pct` to the first-passage seed key.** Without it, moving the premium stop
  returns a bit-identical answer and the card looks frozen.
- **Kenneth is a non-coder with high IT affinity.** Plain English, worked numeric examples, no
  jargon. He asks to be grilled and adversarially audited — take both literally. When something you
  said earlier turns out wrong, say so plainly; this session had one (the gate basis change was
  described as flipping the reference contract's verdict, which stops being true once the thresholds
  are re-derived).
