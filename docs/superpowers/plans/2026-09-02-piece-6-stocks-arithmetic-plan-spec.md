# Piece 6 — the stocks arithmetic plan

**Date:** 2026-09-02 · **Status:** specification, nothing built.
**Unblocks:** Q-A, which is now **closed** — see §1.

> Kenneth, 2026-09-02: *"for stock what I want is the arithmetic profit calculation without the
> options overhead. Just the stock price part. I still want to set the R:R and the system telling me
> what my exit price should be and if there is a structure beside it, within the tolerance range.
> In a nutshell for stock I would take the existing setup for options and strip away everything
> regarding options / premium."*

---

## 1. Q-A is closed: there is no stocks gate

Q-A asked which basis a stocks stop-cost gate should use. It is moot. The gate measures *what share of
the premium the stop costs* — a question that exists only because an option can be near-worthless
before the stock reaches the stop. **A stock has no such nonlinearity: a 5% stop costs 5%.** Under
"strip away everything regarding premium", the gate goes.

Its protective role is already served, exactly and without a model, by position sizing off the risk
budget: `shares = risk_budget ÷ (entry − stop)`.

**Do not build a badge that looks identical to the options one but answers a different question.**
That was the substance of the Q-A choice, and this is the resolution.

---

## 2. What survives the strip — almost everything

The options exit-plan pipeline is already two independent halves, and the stock half needs no change:

| Step | Contract input? | Fate |
|---|---|---|
| `_atr(candles, 14)` | no | **survives verbatim** |
| `compute_final_stop(candles, direction, entry, atr, atr_mult)` | **none** | **survives verbatim** |
| `compute_target_row(candles, direction, entry, final_stop, atr, rr_ratio, snap_mult)` | **none** | **survives verbatim** |
| `estimate_rr(...)` — reprices the contract at each level | yes | **dropped** |
| `estimate_first_passage(...)` — option-value barrier | yes | **replaced** by `estimate_stock_first_passage` |
| stop-vs-premium gate | yes | **dropped** (§1) |

`compute_final_stop` and `compute_target_row` take candles, a direction, a price and config —
nothing else (`exit_plan.py:33,77`). They have always been pure stock functions; the options endpoint
merely wraps them and adds repricing.

**`/contracts/structural-stop` is already shared.** Its docstring: *"NOT options-specific despite the
/contracts/ prefix … The stocks-mode StockPositionCard calls this same endpoint for its own 'Check
structure' affordance — do not fork an alias route."* Reuse it; the contract fields the gate spec adds
there are optional and simply omitted.

**`/stocks/first-passage` already exists** (`stock_scan.py:1416`) with a stop, targets, probabilities
and expected days, and it already validates that the stop and targets sit on the correct side of entry.

So this piece is mostly assembly.

---

## 3. Backend — `POST /stocks/exit-plan`

A new endpoint because `/contracts/exit-plan` requires `strike > 0`, `dte` and `premium > 0`, none of
which a stock has.

```python
class StockExitPlanRequest(BaseModel):
    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float = Field(..., gt=0)
    trend_score: float = Field(..., ge=0, le=100)
    horizon:     Literal["Intraday", "Swing", "Position"]   # picks the holding window
    rr_ratios:   Optional[list[float]] = None               # None → config default

class StockExitPlanStopOut(BaseModel):
    price: float
    source: Literal["structural", "atr_widened"]
    structuralSource: Optional[Literal["order_block","swing_low","swing_high"]] = None
    structuralConfidence: Optional[int] = None
    structuralPrice: Optional[float] = None
    atrFloorPrice: float
    distanceDollar: Optional[float] = None
    riskPerShare: float               # |entry − stop| — the whole "cost of the stop", exactly
    probability: float                # from estimate_stock_first_passage
    expectedDays: Optional[float]

class StockExitPlanTargetRowOut(BaseModel):
    rrRatio: float
    arithmeticPrice: float
    price: float
    tpSource: Literal["arithmetic", "structural_snap"]
    structuralPrice: Optional[float] = None
    distanceDollar: Optional[float] = None      # |structural − arithmetic|
    toleranceDollar: float                      # the snap band
    rewardPerShare: float                       # |target − entry|
    probability: float
    expectedDays: Optional[float]
    qualityGood: bool
    qualityReasons: list[str]

class StockExitPlanResponse(BaseModel):
    stop: StockExitPlanStopOut
    targets: list[StockExitPlanTargetRowOut]
    atr: float
    recommendedShares: Optional[int]            # risk_budget ÷ riskPerShare
    daysBasis: Literal["trading"]               # see §3.2
```

Every field Kenneth named maps to one that already exists: *"set the R:R"* → `rr_ratios`;
*"what my exit price should be"* → `arithmeticPrice` / `price`; *"if there is a structure beside it"*
→ `structuralPrice` and `tpSource`; *"within the tolerance range"* → `distanceDollar` /
`toleranceDollar`.

### 3.1 Carry over the two guards from the options endpoint

`< 2 candles` and `atr <= 0` both **422** with *"insufficient price history to compute an exit plan"*.
Without them the ATR floor collapses to the entry price and every target lands on entry — a
"computed" plan built on no data. Same guards, same message; do not reinvent them.

### 3.2 One real inconsistency to disclose, not hide

`estimate_first_passage` (options) counts **calendar** days. `estimate_stock_first_passage` counts
**trading** days, over a window from `scoring_rules.yaml → confidence_backtest.<horizon>.n_days`.
So "~10d" means different things on the two cards.

Do not silently unify them — the stock engine's trading-day basis is correct for a stock. **Label it**:
`daysBasis` in the payload, and the card renders "~10 trading days". The options card keeps calendar
days and should eventually say so too (out of scope here).

### 3.3 The stop's probability

The options endpoint never reports a probability for the stop row. `estimate_stock_first_passage`
returns one for free, in the same call. Include it: *"this stop is reached on 34% of paths, typically
in 6 trading days"* is the most decision-relevant number on the card.

---

## 4. Frontend — `step-7-position-card`

`StockPositionCard` gains an **Arithmetic Profit Target** section mirroring the options card, minus
every option row. Fields per row, and nothing else:

| Stop row | Target rows (one per R:R) |
|---|---|
| Price · structural source · ATR-floor price · ATR(14) · structural↔floor distance | Arithmetic price · nearest structural level · distance · tolerance |
| Risk per share · probability · expected time | Reward per share · probability · expected time |
| Recommended shares + Apply | quality flag and reasons |

**Dropped rows, explicitly:** contract price, pricing model, IV, delta, premium stop, stop-cost badge.

Reuse the existing `stopJustification` and `targetCompareLabel` helpers — they read `source`,
`tpSource` and `structuralPrice`, all of which the stock payload carries under the same names.

Keep the existing explanation line verbatim: *"Independent of the other profit-target methods on this
page; they can disagree."*

---

## 5. The barrier race for stocks — recommended, flagged as an addition

Not part of "strip the options out", so it is called out rather than assumed.

The race reduces cleanly: a stock has **two** barriers, not three (there is no premium stop). Over the
paths `estimate_stock_first_passage` already simulates, the same attribution gives P(target first),
P(stop first), P(neither) — summing to 100%, unlike the two independent probabilities in §3.

It needs no new model, no new endpoint, and no premium. It is strictly less work than the options
version. **Recommend including it**; if Kenneth declines, the endpoint above still stands alone and
nothing else changes.

---

## 6. Tests

1. `compute_final_stop` / `compute_target_row` are called with identical arguments by both the
   options and stock endpoints, and return identical results for the same symbol and entry — the
   guarantee that the stock path is the options path with the premium half removed
2. `< 2` candles → 422; flat candle feed (`atr == 0`) → 422
3. `rr_ratios` override respected; omitted → config default
4. A target snapped to a structural level reports `tpSource == "structural_snap"` and a
   `distanceDollar` within `toleranceDollar`
5. A target beyond the tolerance band is **not** snapped and reports `"arithmetic"`
6. `recommendedShares == floor(risk_budget / riskPerShare)`; `riskPerShare == 0` → `None`, never a
   divide-by-zero or an infinite size
7. Bearish mirrors Bullish — stop above entry, targets below
8. `daysBasis == "trading"` and the card renders the word "trading"
9. **No premium, strike, DTE, IV, delta or stop-cost field appears anywhere in the response** —
   asserted on the schema's key set, so an options field cannot leak back in later
10. Response schema round-trips through the frontend type with no optional-field surprises

## 7. Out of scope

- Any stop-cost gate (§1)
- Options-specific anything: repricing, IV, Greeks, premium
- The seven `buildPaperStockPosition` call sites — they consume the stop, and only need touching once
  the per-trade selection (piece 5) decides which stop is armed
