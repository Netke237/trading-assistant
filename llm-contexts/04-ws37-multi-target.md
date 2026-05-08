---
workstream: WS-37
branch: feat/ws-37-multi-target
phase: 1
depends_on: fix/ws-33-foundation (merged to main)
conflict_class: Medium — touches backend schemas, scan.py, TradeCard component
scan_py_note: WS-37 touches scan.py. REBASE on feat/ws-35-universe-expand BEFORE finalising if WS-35 has merged. Then WS-41 rebases on WS-37.
---

# WS-37: Multi-target Sell-to-Close + Final Recommendation Scorecard

## Mission

Trade cards currently have a single `target` price. This workstream adds 3 graduated target levels (T1/T2/T3) to every trade card, each with a model-based estimated option price and R:R contribution. It also elevates the "Final Recommendation" from a badge to a full score card section with the same visual weight as the Stock and Contract score cards.

**PRD coverage:** G3, G8, FR-15, FR-40, FR-30

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/schemas/__init__.py` | Modify | Add `TargetLevel`, `PricingMethod` types; extend `TradeExit` with `targets` |
| `backend/app/routers/scan.py` | Modify | Build `targets[]` array in trade card construction |
| `backend/app/scoring/reward_risk.py` | Modify | Return `list[TargetLevel]` for 3 standard targets |
| `frontend/components/organisms/TradeCard/index.tsx` | Modify | Render targets table; add Final Recommendation scorecard section |
| `frontend/components/organisms/TradeCard/TradeCard.module.css` | Modify | Style Final Recommendation section |
| `frontend/mocks/tradecards.ts` | Modify | Update mock to include `targets[]` with 3 entries |
| `frontend/types/domain.ts` | Modify | Update `TargetLevel` interface and `TradeExit` to include `targets` |
| `backend/tests/test_multi_target.py` | Create | Tests for target array generation |

**Do NOT touch any other files.**

---

## Read-Only References

- `backend/app/models/heston.py` — `HestonParams` dataclass and `heston_price()` signature
- `backend/app/models/black_scholes.py` — `bs_price()` fallback
- `backend/app/scoring/reward_risk.py` — current `RrResult` + `estimate_rr()` (you will extend this)
- `frontend/components/atoms/StatusBadge/` — for rendering `finalStatus`
- `frontend/components/primitives/` — `<Text>`, `<Data>`, `<Title>` primitives
- `frontend/lib/alertEngine.ts` — reads `firstTarget.stockPrice`; must keep `stockPrice` field for backward compat
- `backend/config/risk_rules.yaml` — `bullish_target_pct` and `bearish_target_pct` (already externalised by WS-33)

---

## Backend Schema Changes

### Add to `backend/app/schemas/__init__.py`

```python
from enum import Enum

class PricingMethod(str, Enum):
    HESTON = "Heston repriced"
    DELTA_APPROX = "Delta approximation"
    UNAVAILABLE = "Unavailable"

class TargetLevel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    target_price: float          # underlying stock price at this target
    stock_price: float           # alias of target_price (keep for backward compat)
    estimated_option_price: float
    pricing_method: PricingMethod
    rr_contribution: float       # estimated reward at this target / risk

class TradeExit(BaseModel):      # EXTEND — keep all existing fields
    model_config = ConfigDict(populate_by_name=True)
    invalidation: float
    premiumStop: float
    timeStopDays: int
    target: float                # KEEP — first target stock price (backward compat)
    targets: list[TargetLevel]   # NEW — at least 1 entry required
```

**Important:** `target` (singular) must remain in `TradeExit`. Do not rename or remove it.

---

## `reward_risk.py` Changes

Extend `estimate_rr()` to also return a list of 3 target levels. Add a new function:

```python
def estimate_targets(
    stock_price: float,
    base_target_price: float,   # T1 = the existing single target
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
) -> list[TargetLevel]:
    """
    Build 3 target levels: T1=base, T2=base*1.5 move, T3=base*2.0 move.
    For Bullish calls: T2 = stock_price + 1.5 * (T1 - stock_price)
    For Bearish puts:  T2 = stock_price - 1.5 * (stock_price - T1)
    Each level repriced via Heston if available, else delta approximation.
    """
    from app.schemas import TargetLevel as TargetLevelSchema, PricingMethod

    move = abs(base_target_price - stock_price)
    direction_sign = 1 if base_target_price > stock_price else -1

    targets_prices = [
        stock_price + direction_sign * move,          # T1
        stock_price + direction_sign * move * 1.5,    # T2
        stock_price + direction_sign * move * 2.0,    # T3
    ]

    results = []
    for t_price in targets_prices:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        if heston_params is not None:
            try:
                from app.models.heston import heston_price
                opt_price = heston_price(t_price, strike, dte_at_target, r, heston_params, is_call)
                method = PricingMethod.HESTON
            except Exception:
                opt_price = None
                method = PricingMethod.UNAVAILABLE
        else:
            opt_price = None
            method = PricingMethod.DELTA_APPROX

        if opt_price is None or opt_price <= 0:
            delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
            price_move = abs(t_price - stock_price)
            opt_price = max(0.01, current_premium + delta * price_move)
            method = PricingMethod.DELTA_APPROX

        risk = current_premium
        reward = opt_price - current_premium
        rr = round(reward / risk, 2) if risk > 0 and reward > 0 else 0.0

        results.append(TargetLevelSchema(
            target_price=round(t_price, 2),
            stock_price=round(t_price, 2),
            estimated_option_price=round(opt_price, 2),
            pricing_method=method,
            rr_contribution=rr,
        ))

    return results
```

---

## scan.py Changes

In `run_scan()`, after computing `rr = estimate_rr(...)`, add:

```python
from app.scoring.reward_risk import estimate_targets

targets = estimate_targets(
    stock_price=price,
    base_target_price=target_price,
    strike=strike,
    expiry_years=expiry_years,
    current_premium=premium,
    is_call=(req.direction == "Bullish"),
    heston_params=heston_params,
)
```

Then in the `TradeExit(...)` constructor, add `targets=targets`:

```python
exit=TradeExit(
    invalidation=round(invalidation_price, 2),
    premiumStop=round(premium * _rr["premium_stop_pct"], 2),
    timeStopDays=max(3, int(contract.get("dte", 30) * 0.4)),
    target=round(target_price, 2),
    targets=targets,       # NEW
),
```

**IMPORTANT**: If WS-35 has already merged when you start this work, rebase `feat/ws-37-multi-target` on `feat/ws-35-universe-expand` before making scan.py changes. Check with `git log --oneline feat/ws-35-universe-expand` to see if the universe expansion call is present.

---

## Frontend Types (`frontend/types/domain.ts`)

Replace the existing `TargetLevel` interface:

```typescript
export interface TargetLevel {
  id?: string;                   // optional now (backend doesn't send it)
  stockPrice: number;            // KEEP — alertEngine.ts reads this (= targetPrice)
  targetPrice: number;           // new backend field name
  estimatedOptionPrice: number;  // was optional, now required
  pricingMethod: 'Heston repriced' | 'Delta approximation' | 'Unavailable';
  contractsToSell?: number;      // optional for backend-generated targets
  status?: string;               // optional for backend-generated targets
  rrContribution: number;        // new field
}
```

Extend `TradeExit` in `domain.ts`:

```typescript
export interface TradeExit {   // check existing interface name in domain.ts
  invalidation: number;
  premiumStop: number;
  timeStopDays: number;
  target: number;         // keep — first target (backward compat)
  targets: TargetLevel[]; // this field already exists per domain.ts line 126 — verify and align types
}
```

Check `domain.ts` line 126 carefully — `exit` in `TradeCardData` may already have `targets: TargetLevel[]`. If so, just update `TargetLevel` to match the new fields.

---

## Frontend Mock (`frontend/mocks/tradecards.ts`)

Update each mock trade card's `exit` object to include `targets`:

```typescript
targets: [
  { stockPrice: 192.00, targetPrice: 192.00, estimatedOptionPrice: 4.20, pricingMethod: 'Heston repriced', rrContribution: 1.8 },
  { stockPrice: 196.50, targetPrice: 196.50, estimatedOptionPrice: 7.10, pricingMethod: 'Heston repriced', rrContribution: 3.2 },
  { stockPrice: 201.00, targetPrice: 201.00, estimatedOptionPrice: 10.50, pricingMethod: 'Delta approximation', rrContribution: 5.1 },
]
```

---

## TradeCard UI Changes

### Targets table (in `TradeCard/index.tsx`)

Add a targets table section inside the Exit section:

```tsx
{tradeCard.exit.targets.length > 0 && (
  <div className={styles.targetsTable}>
    <Text size={11} tone="secondary">Targets</Text>
    {tradeCard.exit.targets.map((t, i) => (
      <div key={i} className={styles.targetRow}>
        <Text size={12} tone="secondary">T{i + 1}</Text>
        <Data size={12} tone="primary">${t.targetPrice.toFixed(2)}</Data>
        <Data size={12} tone="pass">~${t.estimatedOptionPrice.toFixed(2)}</Data>
        <Text size={11} tone="dim">{t.pricingMethod}</Text>
        <Text size={11} tone="secondary">R:R {t.rrContribution.toFixed(1)}x</Text>
      </div>
    ))}
  </div>
)}
```

### Final Recommendation scorecard section

The current TradeCard shows `finalStatus` as a badge. Elevate it to a card matching the visual weight of the Stock Score Card and Contract Score Card. Add a third card section:

```tsx
{/* Final Recommendation Card */}
<div className={styles.scoreCard}>
  <div className={styles.scoreCardHeader}>
    <Text size={12} tone="secondary">Final Recommendation</Text>
    <StatusBadge status={tradeCard.finalStatus} />
  </div>
  <div className={styles.scoreCardBody}>
    <div className={styles.scoreRow}>
      <Text size={12} tone="secondary">Stock confidence</Text>
      <StatusBadge status={tradeCard.stockConfidence} size="sm" />
    </div>
    <div className={styles.scoreRow}>
      <Text size={12} tone="secondary">Contract confidence</Text>
      <StatusBadge status={tradeCard.contractConfidence} size="sm" />
    </div>
    <div className={styles.scoreRow}>
      <Text size={12} tone="secondary">R:R ratio</Text>
      <Data size={14} tone="primary">{tradeCard.rrRatio.toFixed(2)}x</Data>
    </div>
    <div className={styles.scoreRow}>
      <Text size={11} tone="dim">{tradeCard.rrModel}</Text>
    </div>
  </div>
</div>
```

Use the same `styles.scoreCard`, `styles.scoreCardHeader`, `styles.scoreCardBody` CSS classes as the existing score cards. If they don't exist, add them to `TradeCard.module.css` matching the visual pattern of the existing score cards (border, padding, radius from design tokens).

---

## Tests (`backend/tests/test_multi_target.py`)

```python
import pytest
from app.scoring.reward_risk import estimate_targets
from app.schemas import PricingMethod

def test_three_targets_returned():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30/365,
        current_premium=2.50,
        is_call=True,
    )
    assert len(targets) == 3

def test_t2_price_is_1_5x_move():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,  # T1 move = 8
        strike=105.0,
        expiry_years=30/365,
        current_premium=2.50,
        is_call=True,
    )
    t1, t2, t3 = targets
    assert abs(t2.target_price - 112.0) < 0.1  # 100 + 8*1.5 = 112
    assert abs(t3.target_price - 116.0) < 0.1  # 100 + 8*2.0 = 116

def test_pricing_method_not_empty():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30/365,
        current_premium=2.50,
        is_call=True,
    )
    for t in targets:
        assert t.pricing_method in (PricingMethod.HESTON, PricingMethod.DELTA_APPROX, PricingMethod.UNAVAILABLE)
        assert t.pricing_method != ""

def test_rr_contribution_positive():
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30/365,
        current_premium=2.50,
        is_call=True,
    )
    for t in targets:
        assert t.rr_contribution >= 0

def test_stock_price_equals_target_price():
    """stockPrice must equal targetPrice for backward compat with alertEngine."""
    targets = estimate_targets(
        stock_price=100.0,
        base_target_price=108.0,
        strike=105.0,
        expiry_years=30/365,
        current_premium=2.50,
        is_call=True,
    )
    for t in targets:
        assert t.stock_price == t.target_price
```

Run: `cd backend && pytest tests/test_multi_target.py -v` — all pass.
Run: `cd frontend && npm run typecheck` — clean (only pre-existing Playwright errors allowed).

---

## Acceptance Criteria

- [ ] Every trade card response includes `targets[]` with exactly 3 `TargetLevel` entries
- [ ] Each target has `pricing_method` set (not empty, not null)
- [ ] TradeCard UI shows 3 visually equal-weight score card sections (Stock / Contract / Final Recommendation)
- [ ] `alertEngine.ts` still works — `firstTarget.stockPrice` reads correctly (stockPrice === targetPrice)
- [ ] `npm run typecheck` — clean (pre-existing Playwright errors are acceptable)
- [ ] `pytest tests/test_multi_target.py` — all pass
- [ ] No files outside the Owned Files table were modified

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-37 (Multi-target Sell-to-Close + Final Recommendation Scorecard) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-37-multi-target (already created — checkout before starting)
Base: main (WS-33 merged)

Read the full context doc before writing any code:
F:\Git\GitHub\Trading assistant\llm-contexts\04-ws37-multi-target.md

Key files to read before modifying:
- backend/app/schemas/__init__.py  (current TradeExit — you will extend it)
- backend/app/scoring/reward_risk.py  (current estimate_rr() — you will add estimate_targets())
- backend/app/routers/scan.py  (read the trade card construction block ~lines 225-276)
- frontend/types/domain.ts  (current TargetLevel and TradeCardData.exit types)
- frontend/components/organisms/TradeCard/index.tsx  (existing score card sections)
- frontend/lib/alertEngine.ts  (reads firstTarget.stockPrice — must stay working)

IMPORTANT scan.py rebase rule:
- Check if feat/ws-35-universe-expand is already merged to main
- If YES: rebase feat/ws-37-multi-target on main (which already has WS-35) before touching scan.py
- If NO: make your scan.py changes — they will be compatible since you're only adding lines inside the trade card construction block

Tasks in order:
1. Add PricingMethod, TargetLevel schemas to backend/app/schemas/__init__.py
2. Extend TradeExit schema with targets field
3. Add estimate_targets() to reward_risk.py
4. Call estimate_targets() in scan.py and add targets= to TradeExit constructor
5. Update frontend/types/domain.ts TargetLevel interface
6. Update frontend/mocks/tradecards.ts to include targets[]
7. Update TradeCard/index.tsx: add targets table + Final Recommendation score card section
8. Update TradeCard.module.css if needed
9. Write backend/tests/test_multi_target.py
10. Run: cd backend && pytest tests/test_multi_target.py -v  (must pass)
11. Run: cd frontend && npm run typecheck  (pre-existing Playwright errors OK, no new errors)

Return: one-paragraph summary + pytest output + typecheck summary.
```
