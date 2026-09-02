# Barrier Race — implementation specification

**Date:** 2026-09-02
**Branch:** `claude/bamendjou-stop-model-piece-3-9mh03d`
**Status:** specification, nothing built.
**Reference drawing:** the Trade Card Schematic artifact (card 05).
**Supersedes nothing.** Sits ahead of piece 3 in the build order agreed in session #5.

---

## 0. What this is, in one paragraph

Today `estimate_first_passage` simulates 2,000 stock paths, reprices the option along every
simulated day, and computes two things over the **same** paths that it never compares: a mask for
"the option's value crossed the profit target" and a mask for "the stock crossed the invalidation
price". Each is reported as an independent probability, so on the card they can sum past 100% and
nothing says they are not mutually exclusive. The Barrier Race compares the per-path first-hit days
of those masks — plus a third, new barrier for the premium stop — so every simulated path is
attributed to exactly one outcome. From that attribution fall out an honest R:R (whose risk leg is
not proportional to premium, so premium does not cancel) and an expected value per contract.

**It is a referee, not a fourth profit-target method.** It proposes no level of its own. Every
barrier it races is a level one of the three existing cards already produced.

---

## 1. Decisions this spec assumes (settled, do not relitigate)

| # | Decision |
|---|---|
| **Q1** | R:R exists only where a leg is defined in stock-price space. Premium-% targets carry probability and timing, never a ratio. The race's R:R is legitimate because its **risk** leg is model-priced, even when the reward leg is premium-defined. |
| **Q2** | No fixed half-life. Every reprice uses the simulation's own median days to that barrier, falling back to a per-preset YAML value. |
| **Q3** | The stop-cost gate reprices at today's date via Black-Scholes with the contract's own IV. |
| **Q5** | Build the race, ahead of piece 3. |
| **Q6** | The armed stop is whichever fires first, informed by this card. Until it ships, the structural stock stop. |
| **Q7** | Gate thresholds re-derived to **0.80 / 0.70 / 0.60** (Intraday / Swing / Position), taken as proposed rather than measured against a real scan. Kenneth's explicit call; revisit only if the observed flag rate looks wrong in practice. |
| **Q9** | Its own card, below Monte Carlo. Same simulation, same click. |
| **Q10** | The premium-stop barrier reads the card's existing editable "Premium stop" field. Piece 4 stays deferred. |
| **D8** | Two states, PASS/CAUTION, never REJECT, never red. The race adds no new gate. |
| **D10** | No stop orders. Everything here is an in-app number, not a broker instruction. |

**Refinement to the reference drawing** (introduced by this spec, **approved by Kenneth 2026-09-02**; the artifact now matches): the drawing
shows one race against a single target. This spec races **one row per target** (T1/T2/T3). The two
stop barriers are shared across all three; only the target barrier changes. This is strictly more
informative — it answers "which profit target is worth aiming at on this contract" — and costs
nothing extra, because all three are already evaluated over the same `option_paths` array.

---

## 2. Backend

### 2.1 `backend/app/scoring/first_passage.py`

Everything below happens inside the existing `estimate_first_passage`, over the arrays it already
builds. **No second simulation, no extra paths, no new model.**

Existing, unchanged:

```python
stock_paths  = ...                      # (n_paths, n_days)
option_paths = ...                      # (n_paths, n_days), repriced daily
hit_mask      = option_paths >= target_option          # per target
stop_hit_mask = stock_paths  <= invalidation_price     # is_call; >= for puts
```

New, added:

```python
premium_stop_price = premium * (1.0 - premium_stop_pct)
prem_hit_mask = option_paths <= premium_stop_price
```

Then, per target, a first-hit-day comparison. `np.argmax` on a boolean row returns 0 both for
"first True at index 0" and for "no True anywhere", so **every `argmax` must be paired with its
`.any(axis=1)` mask** and non-hitting paths pushed to `n_days` (an index no real hit can occupy):

```python
def _first_day(mask: np.ndarray, n_days: int) -> np.ndarray:
    """Index of each row's first True, or n_days where the row never hits.
    n_days is deliberately out of range, so a never-hit path always loses
    an argmin race against any path that did hit."""
    ever = mask.any(axis=1)
    day  = np.argmax(mask, axis=1)
    return np.where(ever, day, n_days)

d_tgt  = _first_day(hit_mask, n_days)
d_stop = _first_day(stop_hit_mask, n_days)
d_prem = _first_day(prem_hit_mask, n_days)
```

Attribution — strict `<`, with a documented tie rule:

```python
# TIE RULE: the simulation resolves to daily closes, so two barriers can be
# crossed on the same simulated day. Resolve ties PESSIMISTICALLY — a stop
# ahead of the target, and the premium stop ahead of the stock stop (it is
# always the tighter of the two in option-value terms when both are hit the
# same day). This never flatters the trade. Documented, not incidental.
best      = np.minimum(np.minimum(d_tgt, d_stop), d_prem)
none_hit  = best == n_days
prem_first = (d_prem == best) & ~none_hit
stop_first = (d_stop == best) & ~prem_first & ~none_hit
tgt_first  = (d_tgt  == best) & ~prem_first & ~stop_first & ~none_hit
```

Each returned share is `float(mask.mean())`. The four shares sum to exactly 1.0 by construction —
**assert this in a test**, not just in a comment.

Median days per outcome, computed only over that outcome's own paths:

```python
median_days = float(np.median(best[m]) + 1) if m.any() else None   # +1: column 0 == day 1
```

Terminal value for the `none_hit` group — needed by the edge calculation and by nothing else:

```python
# Mean value at expiry of paths that reached no barrier. Uses the payoff, not
# a repriced value: at expiry there is no time value left.
S_T = stock_paths[none_hit, -1]
payoff = np.maximum(S_T - strike, 0.0) if is_call else np.maximum(strike - S_T, 0.0)
terminal_mean = float(payoff.mean()) if none_hit.any() else None
```

New dataclasses, returned alongside the existing fields (nothing existing is removed or renamed):

```python
@dataclass
class RaceOutcome:
    target_pct:          float
    p_target_first:      float
    p_stock_stop_first:  float
    p_premium_stop_first:float
    p_neither:           float
    days_target:         Optional[float]
    days_stock_stop:     Optional[float]
    days_premium_stop:   Optional[float]
    terminal_mean:       Optional[float]   # mean option value at expiry, p_neither paths

@dataclass
class BarrierRaceResult:
    outcomes:            list[RaceOutcome]      # one per target, same order as `targets`
    premium_stop_price:  float                  # the option-value barrier actually used
    stock_stop_price:    float                  # echo of invalidation_price, for auditability
    n_paths:             int
```

`estimate_first_passage` gains one keyword-only parameter, `premium_stop_pct: float = 0.60`, and
returns `race: BarrierRaceResult` on `FirstPassageResult`. **Defaulted, so every existing caller
keeps compiling** — `exit_plan`'s per-target-row calls included, which pass `t1=t2=t3=pct` and
should simply ignore the race field.

#### 2.1.1 The `dte < 1` branch

`first_passage.py:195-205` returns `probability = 0.0` for every target without simulating —
a refusal, not a real zero (session handoff #4, fact 11). The race must **not** invent a
100%-summing result there. It returns `race=None`, and the card renders
**"not simulated — contract expires today"**, never a blank and never four zeroes.

### 2.2 Repricing horizon (Q2) — `backend/config/risk_rules.yaml`

New block, read through the existing `config_loader`:

```yaml
reprice_horizon:
  source: simulation_median
  fallback_days:
    Intraday: 1
    Swing: 7
    Position: 14
    Quarterly: 25
    SemiAnnual: 45
    Annual: 80
  custom:
    rule: fraction_of_hold
    fraction: 0.50
  clamp:
    min_days: 1
    max_fraction_of_dte: 0.75
```

**Seven presets, not three.** `HORIZON_PRESETS` (frontend/lib/horizonPresets.ts:34) offers seven
keys but `scoringHorizonForHold` collapses Quarterly/SemiAnnual/Annual into `Position`. Keying the
fallback on the scoring horizon would give a 200-day hold and a 20-day hold the same repricing time.
**Key on the preset.**

`Custom` derives: `days = ((holdMin + holdMax) / 2) * fraction`, then clamped. Chosen over
snapping to the nearest preset because a manual 30–35 day range sits between Position and Quarterly
and either snap moves the repriced loss by real money; `scoringHorizonForHold` already sets the
precedent of deriving from the typed range.

`max_fraction_of_dte` is not decoration: without it, Annual on a 30-day contract reprices at 80 days
— past expiry — and every level silently prices at intrinsic value only.

A new helper `resolve_reprice_days(preset, hold_min, hold_max, dte, sim_median) -> float` owns this
and is the **only** place the rule lives. `reward_risk.estimate_rr` and `estimate_targets` take it
as a parameter, replacing `dte_at_target = max(expiry_years * 0.5, 7/365)` at `reward_risk.py:82`
and `first_passage.py:174`.

> **Grep before deleting.** `dte_at_target` appears in at least `reward_risk.py`, `first_passage.py`
> and their tests, and the constant `0.5` is referenced in comments elsewhere. Session handoff #4
> §2.3: when a decision deletes a field, grep the name repo-wide.

### 2.3 API — `backend/app/routers/contracts.py`

`FirstPassageRequest` gains one optional field:

```python
premium_stop_pct: Optional[float] = Field(default=None, gt=0, lt=1)
```

`None` falls back to `rr_cfg["premium_stop_pct"]`, matching how `t1_pct`/`t2_pct`/`t3_pct` already
resolve. `lt=1` because a 100% premium stop is a total loss and makes the barrier unreachable-by-
definition rather than a stop.

`FirstPassageResponse` gains `race: Optional[BarrierRaceOut]`. Optional because of §2.1.1.

**The seed must include the new input.** `seed_key` at `contracts.py:~393` is a `sha256` of symbol,
strike, dte, stock price and the three target percents. Add `premium_stop_pct`, otherwise moving the
premium stop returns a bit-identical cached-looking answer and the card appears frozen.

**No new endpoint.** The race rides `/contracts/first-passage`.

### 2.4 R:R and edge — computed where?

**Backend**, in the router, not the client. Both need `bs_price` at a resolved horizon; duplicating
Black-Scholes in TypeScript to serve one card is exactly the kind of drift this codebase has been
bitten by. Per target row the response carries:

```
rewardDollar        = target_option_price - premium
riskStockStop       = premium - bs_price(stop, K, resolve_reprice_days(...days_stock_stop...), ...)
riskPremiumStop     = premium * premium_stop_pct
rrStockStop         = rewardDollar / riskStockStop
rrPremiumStop       = rewardDollar / riskPremiumStop
edgePerContract     = 100 * ( p_target_first    * rewardDollar
                            - p_stock_stop_first  * riskStockStop
                            - p_premium_stop_first* riskPremiumStop
                            + p_neither           * (terminal_mean - premium) )
```

Note the last term is a **signed** contribution, not a loss: a `none_hit` path can end above the
premium paid. Writing it as `- p_neither * loss` would be wrong whenever `terminal_mean > premium`.

**`rrStockStop` guards.** `riskStockStop` can be ≤ 0 when the repriced value at the stop exceeds the
premium (possible for a deep-ITM contract on a tight stop). Return `null`, and render `—`, never a
negative or infinite ratio.

**Why premium does not cancel here** — the trap that killed two earlier designs. `rewardDollar` is
`premium * pct` by construction, so any risk leg proportional to premium cancels it. `riskStockStop`
is `premium - BS(stop, …)`, and `BS(stop, …)` is not proportional to premium — it depends on
strike, spot at the stop, time and IV independently. So `rrStockStop` genuinely varies by contract.
`rrPremiumStop` **does** cancel (it is exactly `pct / premium_stop_pct`) and is therefore shown as a
labelled constant, not as a discriminating metric. **Both are displayed; only one is a measurement.
The card must say which.**

---

## 3. Frontend

### 3.1 Types — `frontend/types/domain.ts`

```ts
export interface BarrierRaceOutcome {
  targetPct:           number;
  pTargetFirst:        number;
  pStockStopFirst:     number;
  pPremiumStopFirst:   number;
  pNeither:            number;
  daysTarget:          number | null;
  daysStockStop:       number | null;
  daysPremiumStop:     number | null;
  rewardDollar:        number;
  riskStockStop:       number | null;
  riskPremiumStop:     number;
  rrStockStop:         number | null;   // the measurement
  rrPremiumStop:       number;          // constant by construction — labelled as such
  edgePerContract:     number | null;
}

export interface BarrierRace {
  outcomes:          BarrierRaceOutcome[];
  premiumStopPrice:  number;
  stockStopPrice:    number;
  nPaths:            number;
}
```

`FirstPassageEstimate` gains `race?: BarrierRace | null`.

### 3.2 Component — `components/organisms/BarrierRaceCard/`

`index.tsx` + `BarrierRaceCard.module.css`, per the repo's one-folder-per-component convention.
Organism, not molecule: it composes StatusBadge, KV and a table.

Rendered in `TradeCard/index.tsx` directly below the Monte Carlo section. Props: the `race`, the
resolved barrier prices, and the same freshness signals `ProfitTargetRow` already receives.

Four blocks, per the reference drawing:

1. **The three barriers** — level, how it is set, and which is armed
2. **Race outcome** — one row per target, a 100%-stacked bar per row, and the four shares
3. **Risk / reward** — reward, both risk legs, both ratios, with the constant one labelled
4. **Edge** — the contribution table and the per-contract total

CSS follows CLAUDE.md: `border: 1px solid var(--border-subtle)`, **no card shadow**; status tints
via `color-mix(in srgb, var(--pass) N%, var(--bg-surface))`; `Data` for every number.

### 3.3 Freshness — the trap this card walks into

`structuralRR` requires **both** its inputs confirmed fetched this mount (`structuralIsFreshRef`,
`firstPassageIsFreshRef`), because a restored cached value can be arbitrarily old and pairing it
with a fresh one silently misstates risk. Five audit rounds produced that mechanism.

The race is **safer by construction**: every share, every median day and both risk legs come out of
**one backend call with one set of inputs**. There is no pairing of independently-fetched values, so
there is no mixed-vintage hazard *inside* the card.

But two of its **inputs** cross that boundary:

- **the stock stop** — `sharedStop`, which may be a restored Check-structure level
- **the premium stop** — `overlay.premiumStop`, live and user-editable

So: **the race renders only when the estimate that produced it was fetched this mount**
(`firstPassageIsFreshRef.current`), and it is **cleared, not recomputed, whenever `sharedStop.price`
or `overlay.premiumStop` changes** — replaced by "barriers changed — re-run the estimate". Never
show a race whose bars were computed against a stop the user has since moved. Editing the premium
stop and watching the bars re-sort requires a click; it must not appear to update on its own.

### 3.4 What changes on the existing cards

| Change | Where | Note |
|---|---|---|
| Remove `R:R vs. structural stop` | `ProfitTargetRow`, MC card | Degenerates to the typed percent. Replaced by §2.4's `rrStockStop`. **Kenneth's OK obtained.** |
| Move the Invalidation row | MC card → race card | Not a deletion |
| New line on the MC card | MC card | "Each probability is measured on its own … the Barrier Race card below counts every path once." |
| `Risk / Reward` readout | Fixed % Ladder | Display removed. **The `overlay.premiumStop` field stays** — it is a live risk denominator (`computeEditedRR`, `rrContribution`, `isDirty`) *and now also the race's third barrier.* |

> **`overlay.premiumStop` is not display-only** (handoff #4 §7 fact 9). Removing the readout must not
> touch the field, its editor, or its consumers. Both audit rounds caught a "display only"
> assumption that was false; this is the same shape.

### 3.5 Persistence

`estimatesByContract` in `step-7-trade-card/page.tsx` caches `FirstPassageEstimate` per contract. The
new `race` field rides inside it — **no store version bump**, because that cache is component state,
not a persisted zustand store. `scanStore`'s v12→v13 bump belongs to piece 3 and stays there.

**Verify before building.** If `estimatesByContract` turns out to be persisted anywhere, this
becomes a versioned migration and CLAUDE.md's version-bump-plus-migration-branch rule applies.

---

## 4. Tests

**Backend** (`backend/tests/test_barrier_race.py`):

1. The four shares sum to 1.0 for every target, on a fixed seed
2. A path that hits the target and later the stop is attributed to the target, not both
3. Same-day ties resolve to the stop, and premium-before-stock (§2.1's tie rule)
4. `_first_day` returns `n_days` for a never-hitting row — the `argmax`-returns-0 trap
5. `dte < 1` returns `race=None`, not four zeroes
6. A premium stop tighter than the stock stop drives `p_stock_stop_first` toward zero — the
   reference contract's actual behaviour, and the card's headline insight
7. `rrStockStop` genuinely varies across strikes on one chain; `rrPremiumStop` is identical across
   all of them — the anti-cancellation guarantee, asserted rather than asserted-in-prose
8. `riskStockStop <= 0` yields `rrStockStop is None`
9. Seed determinism, including that changing `premium_stop_pct` changes the answer

**Frontend** (`BarrierRaceCard/__tests__/`):

10. Bars render at the returned widths; the four labels are present and sum to 100%
11. `race == null` renders the "not simulated" copy, not an empty card
12. Changing `overlay.premiumStop` clears the race and shows "barriers changed"
13. A restored (not-fresh-this-mount) estimate renders no race

**Reprice horizon** (`test_reprice_horizon.py`):

14. All seven presets resolve; `Custom` derives from the typed range
15. `max_fraction_of_dte` binds — Annual on a 30-DTE contract
16. Simulation median wins over the fallback when present; fallback used when `None`

---

## 5. Definition of done

- `cd frontend && npm run typecheck && npm run test` clean
- `cd backend && pytest` clean (~4 min; needs `pip install -r backend/requirements.txt` in a fresh
  container)
- **All three CI checks green** — `backend`, `frontend`, `test`. The frontend suite says nothing
  about the backend; a week-old user-facing bug survived precisely because a red check made real
  regressions indistinguishable from a standing failure (handoff #4 §2.3).
- Every removal in §3.4 grepped for consumers first

## 6. Explicitly out of scope

- The per-trade method pick (D4/D5, piece 5) — the race informs it, does not implement it
- Arming a stop anywhere (D10) — every number here is in-app
- Per-position `premium_stop_pct` (piece 4) — the race reads the card's existing field
- The Heston calibration fix (Q8) — independent, later
- Piece 3's scan-time `finalStop` and the ranking badge — next, after this
