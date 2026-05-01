# LLM Context — Entry Quality + Reward-Risk (Workstream 24)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates two new files: `backend/app/scoring/entry_quality.py` and `backend/app/scoring/reward_risk.py`. It reads existing modules as read-only dependencies. It does not touch `frontend/`, any router, any fixture, or any existing model/schema file.

**Goal:**
Implement entry-quality assessment and reward-risk estimation — the last two scoring layers before a trade card is generated. WS-25 (scan endpoint) calls both of these to complete the pipeline.

**What NOT to touch:**
- Any file under `frontend/`
- `backend/app/models/black_scholes.py` — read-only
- `backend/app/models/heston.py` — read-only
- `backend/app/scoring/contract_validator.py` — read-only
- `backend/app/scoring/stock_scorer.py` — read-only
- Any router, fixture, or `backend/app/main.py`

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/scoring/entry_quality.py` | **Create** | Limit price, max fill, order type, entry quality status |
| `backend/app/scoring/reward_risk.py` | **Create** | R:R ratio and exit price estimation |

---

## Section 3 — Read-only references

| File | What to use |
|---|---|
| `backend/app/models/heston.py` | `heston_price(S, K, T, r, params, is_call)`, `HestonParams` |
| `backend/app/models/black_scholes.py` | `bs_price(S, K, T, r, sigma, is_call)` — fallback when Heston params are None |
| `backend/app/scoring/contract_validator.py` | `ContractScoreCard` shape (read the dataclass, don't import it in these files) |

**Import paths:**
```python
from app.models.heston import heston_price, HestonParams
from app.models.black_scholes import bs_price
```

---

## Section 4 — Type contracts

### `entry_quality.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

OrderType = Literal["Limit", "Market"]
Status = Literal["PASS", "CAUTION", "REJECT"]


@dataclass
class EntryConfig:
    spread_tolerance_pct: float = 0.05   # max acceptable bid-ask spread as % of mid
    max_slippage_pct: float = 0.03       # max fill above mid as % of mid
    min_premium: float = 0.10            # reject contracts below this premium ($)


@dataclass
class EntryAssessment:
    limit_price: float           # recommended limit order price (= mid)
    max_fill: float              # worst acceptable fill (= mid * (1 + max_slippage_pct))
    order_type: OrderType        # "Limit" always in MVP
    quality_status: Status       # PASS / CAUTION / REJECT
    quality_reasons: list[str] = field(default_factory=list)  # human-readable flags
```

### `reward_risk.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal

RrModel = Literal["Heston repriced", "Delta approximation"]


@dataclass
class RrResult:
    rr_ratio: float                   # reward-to-risk ratio (e.g. 2.5 = 2.5:1)
    model_used: RrModel               # label for UI
    estimated_exit_premium: float     # projected premium at target price ($)
```

---

## Section 5 — Implementation

### `entry_quality.py` — `assess_entry`

```python
def assess_entry(
    bid: float,
    ask: float,
    mid: float,
    config: EntryConfig | None = None,
) -> EntryAssessment:
    """
    Assess entry quality for a single option contract.

    Args:
        bid:    best bid price ($)
        ask:    best ask price ($)
        mid:    mid-market price ($) — (bid + ask) / 2
        config: EntryConfig with thresholds (uses defaults if None)

    Returns:
        EntryAssessment with limit price, max fill, order type, and quality flags.
    """
```

**Logic:**
1. Default `config` to `EntryConfig()` if None.
2. Compute `spread_pct = (ask - bid) / mid` if mid > 0, else 1.0.
3. `limit_price = round(mid, 2)`
4. `max_fill = round(mid * (1 + config.max_slippage_pct), 2)`
5. `order_type = "Limit"` always.
6. Build `quality_reasons: list[str]` and determine `quality_status`:
   - If `mid < config.min_premium`: append `"premium too low"` → status `REJECT`
   - If `spread_pct > config.spread_tolerance_pct * 3`: append `"wide spread"` → status `REJECT`
   - Elif `spread_pct > config.spread_tolerance_pct`: append `"elevated spread"` → status `CAUTION`
   - If no reasons → status `PASS`
   - Multiple reasons: worst status wins (REJECT > CAUTION > PASS).
7. Return `EntryAssessment(limit_price, max_fill, order_type, quality_status, quality_reasons)`.

---

### `reward_risk.py` — `estimate_rr`

```python
def estimate_rr(
    stock_price: float,
    target_price: float,
    invalidation_price: float,
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
) -> RrResult:
    """
    Estimate reward-to-risk ratio for a long option position.

    Args:
        stock_price:         current underlying price (S)
        target_price:        price objective for exit (profit target)
        invalidation_price:  price that would invalidate the setup (stop)
        strike:              option strike price
        expiry_years:        time to expiry in years (approximate DTE/365)
        current_premium:     current option mid-price ($) — used as risk
        is_call:             True for call options
        r:                   risk-free rate (default 0.05)
        heston_params:       HestonParams if available, else None (falls back to BS delta approx)
        sigma_fallback:      implied volatility to use when heston_params is None

    Returns:
        RrResult with ratio, model label, and estimated exit premium.
    """
```

**Logic:**

**Reward (estimated exit premium at target):**
- If `heston_params` is not None:
  - `dte_at_target = max(expiry_years * 0.5, 7/365)` (assume target hit halfway through trade)
  - `exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)`
  - `model_used = "Heston repriced"`
- Else (delta approximation):
  - Approximate delta: for calls, `delta ≈ 0.5` if `target_price > strike`, else `0.3`
  - `price_move = abs(target_price - stock_price)`
  - `exit_premium = current_premium + delta * price_move`
  - `model_used = "Delta approximation"`
- `exit_premium = max(exit_premium, 0.01)` — floor to avoid zero division

**Risk (entry cost = current_premium):**
- `risk = current_premium`

**R:R ratio:**
- `reward = exit_premium - current_premium`
- If `reward <= 0` or `risk <= 0`: return `RrResult(rr_ratio=0.0, model_used=model_used, estimated_exit_premium=exit_premium)`
- `rr_ratio = round(reward / risk, 2)`

Return `RrResult(rr_ratio=rr_ratio, model_used=model_used, estimated_exit_premium=round(exit_premium, 2))`.

---

## Section 6 — Complete file structure

### `entry_quality.py` must contain, in order:
1. `from __future__ import annotations`
2. Imports (`dataclass`, `field`, `Literal`)
3. `OrderType`, `Status` type aliases
4. `EntryConfig` dataclass
5. `EntryAssessment` dataclass
6. `assess_entry(bid, ask, mid, config) -> EntryAssessment`

### `reward_risk.py` must contain, in order:
1. `from __future__ import annotations`
2. Imports (`dataclass`, `Optional`, `Literal`, `heston_price`, `HestonParams`, `bs_price`)
3. `RrModel` type alias
4. `RrResult` dataclass
5. `estimate_rr(stock_price, target_price, invalidation_price, strike, expiry_years, current_premium, is_call, r, heston_params, sigma_fallback) -> RrResult`

---

## Section 7 — Task spec

### Acceptance criteria

1. `assess_entry(bid=1.90, ask=2.10, mid=2.00)` returns `quality_status="PASS"` with empty reasons.
2. `assess_entry(bid=0.50, ask=3.00, mid=1.75)` returns `quality_status="REJECT"` with `"wide spread"` in reasons.
3. `assess_entry(bid=0.05, ask=0.12, mid=0.085)` returns `quality_status="REJECT"` with `"premium too low"` in reasons.
4. `estimate_rr(185, 200, 175, 190, 30/365, 2.50, True)` returns `rr_ratio > 0` with `model_used="Delta approximation"`.
5. `estimate_rr(185, 200, 175, 190, 30/365, 2.50, True, heston_params=HestonParams(0.04,2.0,0.04,0.3,-0.7))` returns `model_used="Heston repriced"`.
6. `python -c "from app.scoring.entry_quality import assess_entry; from app.scoring.reward_risk import estimate_rr; print('OK')"` prints `OK`.

### Verify

```bash
cd backend
python -c "
from app.scoring.entry_quality import assess_entry, EntryConfig
from app.scoring.reward_risk import estimate_rr
from app.models.heston import HestonParams

# Entry quality — PASS
ea = assess_entry(bid=1.90, ask=2.10, mid=2.00)
assert ea.quality_status == 'PASS', f'Expected PASS, got {ea.quality_status}'
assert ea.limit_price == 2.00
print(f'PASS: {ea}')

# Entry quality — wide spread REJECT
ea2 = assess_entry(bid=0.50, ask=3.00, mid=1.75)
assert ea2.quality_status == 'REJECT'
assert 'wide spread' in ea2.quality_reasons
print(f'REJECT wide spread: {ea2}')

# Entry quality — premium too low
ea3 = assess_entry(bid=0.05, ask=0.12, mid=0.085)
assert ea3.quality_status == 'REJECT'
print(f'REJECT low premium: {ea3}')

# R:R — delta approx
rr = estimate_rr(185, 200, 175, 190, 30/365, 2.50, True)
assert rr.rr_ratio > 0
assert rr.model_used == 'Delta approximation'
print(f'R:R delta: {rr}')

# R:R — Heston
params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
rr2 = estimate_rr(185, 200, 175, 190, 30/365, 2.50, True, heston_params=params)
assert rr2.model_used == 'Heston repriced'
print(f'R:R Heston: {rr2}')

print('All checks passed')
"
```

---

## Section 8 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify any existing backend file.
3. All functions must be safe on degenerate inputs (zero prices, zero DTE, None params).
4. No pandas, no numpy — pure Python + scipy allowed only in reward_risk for heston_price.
5. `scipy` and `pyyaml` are already in `requirements.txt` — do not re-add them.

---

## Section 9 — Dev workflow

```bash
cd backend
python -c "from app.scoring.entry_quality import assess_entry; from app.scoring.reward_risk import estimate_rr; print('OK')"
```

---

## Section 10 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-24-entry-quality.

Read `llm-contexts/24-entry-quality.md` fully before writing any code.
It is your single source of truth.

You are implementing entry quality assessment and reward-risk estimation for the
Bamendjou options screener (FastAPI / Python 3.11).

Your owned files:
  - backend/app/scoring/entry_quality.py   (CREATE)
  - backend/app/scoring/reward_risk.py     (CREATE)

Do not modify any file outside this list.

Task: Implement assess_entry() and estimate_rr() exactly as specified in Sections 5 and 6.
Run the verification block in Section 7 after implementation.
Commit after all checks pass.
```
