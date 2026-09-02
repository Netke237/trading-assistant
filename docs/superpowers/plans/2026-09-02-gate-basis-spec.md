# Stop-cost gate — Black-Scholes basis and re-derived thresholds (Q3 / Q7)

**Date:** 2026-09-02 · **Status:** specification, nothing built.
**Decisions:** Q3 (basis → Black-Scholes at today's date), Q7 (thresholds → 0.80 / 0.70 / 0.60).
**Build order:** after the barrier race, alongside piece 3 — both need the same new scan field.

---

## 1. What changes and why

`stopPremiumRisk` (`frontend/lib/risk.ts:70`) estimates the loss at the stop as a straight line:
`|stop − spot| × |delta|`, capped at the premium. On a wide stop that cap binds constantly. Measured
on one real chain (stock $201.86 → stop $185.87, 45 DTE):

| Strike | 195 | 200 | 205 | 210 | 215 | 220 | 230 | 240 |
|---|---|---|---|---|---|---|---|---|
| Black-Scholes at today's date | 63% | 65% | 67% | 70% | 71% | 73% | 75% | 77% |
| Δ-linear (today) | 81% | 86% | 93% | 99% | **100** | **100** | **100** | **100** |

Four of eight strikes pin at exactly 100%. The gate cannot distinguish a 220 call from a 240 call —
it just restates that a long option's maximum loss is its premium, which the user already knows.

**New basis:** `loss = premium − BS(stop_price, strike, dte, r, iv, is_call)`, at **today's**
time-to-expiry (no theta). Curvature is real — delta falls as the stock falls, so a straight line
charges a loss the contract cannot produce. Today's date, not the exit plan's half-life, because the
gate must fire before any button has been pressed.

**New thresholds** (`scoring_rules.yaml → horizons.<key>.stop_premium.pass_max_fraction`):

| Horizon | Old | New | PASS means |
|---|---|---|---|
| Intraday | 0.85 | **0.80** | ≥20% of premium still there when the stop hits |
| Swing | 0.80 | **0.70** | ≥30% still there |
| Position | 0.70 | **0.60** | ≥40% still there |

They **must** move. Under the new basis the worst contract on the chain above reads 77% — beneath the
old Swing line of 0.80. Keeping the old numbers silences the gate permanently.

Taken as proposed rather than measured against a real universe: Kenneth's explicit call. Revisit only
if the observed flag rate looks wrong. One YAML edit either way.

**Unchanged:** D8 in full. Two states, PASS/CAUTION, never REJECT, never red, never blocks a send.
The badge keeps printing the raw percentage so a high-conviction trade can be taken anyway.

---

## 2. The hard part nobody has noticed yet

**The gate is evaluated at a stop that moves.** `stopRisk` (`TradeCard/index.tsx:820-842`) reads
`sharedStop.price`, which changes when the user clicks *Check structure* or *Compute Arithmetic Plan*.
A value precomputed at scan time cannot serve it.

So the new basis needs a Black-Scholes evaluation at an arbitrary stop, on demand. Two ways:

- **(rejected)** Black-Scholes plus an IV solver in TypeScript. The frontend contains no
  option-pricing maths at all today — not one `Math.exp` in `frontend/lib/`. This would permanently
  duplicate the Python implementation. Consistent with the "show the arithmetic, don't relocate it"
  decision on the barrier race, this is out.
- **(chosen)** **The endpoints that produce a stop also return its cost.** The card never computes;
  it renders what it was given, and prints the inputs.

### 2.1 `/contracts/structural-stop`

Its docstring is explicit: *"NOT options-specific despite the /contracts/ prefix … The stocks-mode
StockPositionCard calls this same endpoint … do not fork an alias route."* So the contract fields are
**optional**, and the stop-cost block is omitted when they are absent.

```python
class StructuralStopRequest(BaseModel):
    symbol: str; direction: Literal["Bullish","Bearish"]; stock_price: float
    # NEW — all optional. Present together or not at all; a partial set is a 422,
    # not a silently skipped gate.
    strike:  Optional[float] = Field(default=None, gt=0)
    dte:     Optional[int]   = Field(default=None, ge=0)
    premium: Optional[float] = Field(default=None, gt=0)
    iv:      Optional[float] = Field(default=None, gt=0)

class StopCostOut(BaseModel):
    lossDollar:       float    # premium − valueAtStop
    valueAtStop:      float    # BS(stop, K, dte, r, iv) — printed, so the user sees the input
    fraction:         float    # lossDollar / premium, clamped to [0, 1]
    status:           Literal["PASS","CAUTION"]
    passMaxFraction:  float    # the threshold applied, echoed for auditability
    basis:            Literal["bs_today"]
```

`StructuralStopResponse` gains `stopCost: Optional[StopCostOut]`.

**A partial contract set must 422.** Silently omitting the gate because one field was missing is how
a contract with no verdict reads as an unremarkable one.

### 2.2 `/contracts/exit-plan`

`ExitPlanStopOut` gains the same `stopCost` block, computed against `final_stop.price`. This is what
the card shows once an Arithmetic Plan has been run — a *different, wider* stop than the raw
structural level, so a different verdict is correct, not a bug.

### 2.3 Scan time — the ranking badge

`compute_final_stop` is per **symbol** (piece 3), and the auto-picked contract is known at scan time,
so the backend computes the gate there too and the row carries only the result:

```
WatchlistRow += stopCostPct: number | null
                stopCostStatus: Status | null
```

**Two fields, not five.** `WatchlistRow` carries no contract data today; adding strike/dte/premium/iv/
delta to every row so the client could price it would be the TypeScript-pricer decision by the back
door. The badge must state it describes the **auto-picked** contract, because a Step 6 override can
later change it.

### 2.4 The new scan field

`contractDetails` carries `ivRank` (a 0–100 percentile) but **not** the contract's implied volatility.
Add `iv: number` — `bs_iv(mid, spot, strike, expiry_years, r, is_call)`, already implemented in
`app/models/black_scholes.py`. It is needed by the gate, by the barrier race, and by piece 3.
`bs_iv` returns `None` when it cannot converge: carry `iv: null` and render the gate as
**"not computed"**, never as a silent PASS.

---

## 3. Frontend

`stopPremiumRisk` stops computing and becomes a **presenter**. Its inputs are the returned block; its
output is the same `StopPremiumRisk` shape, so `TradeCard` and its tests keep their structure.

```ts
export function stopPremiumRisk(c: StopCostOut | null): StopPremiumRisk | null
```

The delta-linear arithmetic is **deleted, not kept as a fallback** — a fallback that quietly answers a
different question is worse than no answer. Where no `stopCost` came back, the badge reads
"not computed".

`formatStopPremiumRisk` changes to print the new inputs:

```
old:  $15.99 away × Δ0.34 = $5.20 of $5.20 premium (uncapped $5.18)
new:  $5.20 premium − $1.49 at $185.87 = $3.71 of $5.20 premium
```

`capped` and the `(uncapped …)` tail **go away**: Black-Scholes cannot exceed the premium for a long
option, so there is nothing to cap and nothing to disclose past the cap. Grep `capped` repo-wide before
removing it — `risk.test.ts` asserts on it in at least three places.

---

## 4. Tests

1. `stopPremiumRisk` renders a `StopCostOut` unchanged; `null` in → `null` out
2. `formatStopPremiumRisk` prints premium, value at stop, stop price, loss, fraction
3. Endpoint: full contract set → a `stopCost`; no contract fields → `stopCost is None`
4. Endpoint: **partial** contract set → 422
5. `iv is None` → `stopCost is None` → badge reads "not computed", never PASS
6. The eight-strike chain in §1 reproduces to within a cent, and 0.70 splits it 3 PASS / 5 CAUTION
7. `pass_max_fraction` YAML values are 0.80 / 0.70 / 0.60, and the endpoint's key set matches
   `HorizonStopPremiumThresholds` **exactly** (the `reject_fraction` regression guard — a
   re-added key must fail loudly, see handoff #4 §2.1)
8. Exit-plan stop and structural stop can legitimately disagree — asserted, not treated as a bug
9. Ranking row carries `stopCostPct`/`stopCostStatus`; a pre-migration restore renders
   "not computed — re-run the scan"

## 5. Out of scope

Anything with theta in it. The gate is deliberately a today's-date question; the repriced-at-horizon
value is the barrier race's job and drives sizing, never the gate verdict.
