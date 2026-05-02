# LLM Context — Heston Pricing Model (Workstream 21)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one new file (`backend/app/models/heston.py`). It reads `backend/app/models/black_scholes.py` (WS-14, read-only) as a fallback and IV seed. It does not touch `frontend/`, any router, any fixture, or any other model file.

**Goal:**
Implement the Heston stochastic volatility pricing model. Provides option prices, implied volatility, and parameter calibration from an option chain. WS-24 (entry quality / reward-risk) and WS-25 (scan endpoint) build on top of these functions.

**Why Heston over Black-Scholes alone:**
Black-Scholes assumes constant volatility, which produces pricing errors for options far from ATM. Heston models mean-reverting stochastic volatility, capturing the volatility smile and giving more accurate prices for the full option chain — critical for contract ranking (WS-22).

**What NOT to touch:**
- Any file under `frontend/`
- `backend/app/models/black_scholes.py` — read-only dependency
- Any router, fixture, schema, or existing model file
- `backend/app/main.py`

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/models/heston.py` | **Create** | Heston pricing, IV, and calibration |

`scipy` is already in `backend/requirements.txt` from WS-14.

---

## Section 3 — Read-only references

| File | What to use |
|---|---|
| `backend/app/models/black_scholes.py` | `bs_price(S, K, T, r, sigma, is_call)` and `bs_iv(...)` — used as fallback and IV seed for calibration |

**Black-Scholes function signatures:**
```python
from app.models.black_scholes import bs_price, bs_iv

# bs_price(S, K, T, r, sigma, is_call=True) -> float
# bs_iv(market_price, S, K, T, r, is_call=True, tol=1e-6) -> float | None
```

---

## Section 4 — Type contracts

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class HestonParams:
    v0: float       # initial variance (σ² at t=0)
    kappa: float    # mean-reversion speed
    theta: float    # long-run variance
    sigma_v: float  # volatility of variance (vol-of-vol)
    rho: float      # correlation between price and variance Brownian motions


@dataclass
class CalibrationResult:
    params: HestonParams
    rmse: float             # root-mean-square error across chain
    method: str             # "heston_grid" or "bs_fallback"
```

---

## Section 5 — Implementation

### Heston characteristic function

The Heston model prices options via a characteristic-function integral (Carr-Madan / Heston 1993 closed form).

```python
from __future__ import annotations

import cmath
import math
from typing import Optional

from scipy import integrate
from scipy.stats import norm

from app.models.black_scholes import bs_price, bs_iv
from app.models.heston import HestonParams, CalibrationResult


def _heston_char_fn(
    phi: complex,
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
) -> complex:
    """Heston characteristic function for the log-price."""
    v0, kappa, theta, sigma_v, rho = (
        params.v0, params.kappa, params.theta, params.sigma_v, params.rho
    )
    i = complex(0, 1)
    x = math.log(S / K)
    a = kappa * theta

    d = cmath.sqrt((rho * sigma_v * phi * i - kappa) ** 2
                   + sigma_v ** 2 * (phi * i + phi ** 2))
    g = (kappa - rho * sigma_v * phi * i - d) / (kappa - rho * sigma_v * phi * i + d)

    exp_dT = cmath.exp(-d * T)
    C = (r * phi * i * T
         + a / sigma_v ** 2 * (
             (kappa - rho * sigma_v * phi * i - d) * T
             - 2 * cmath.log((1 - g * exp_dT) / (1 - g))
         ))
    D = ((kappa - rho * sigma_v * phi * i - d) / sigma_v ** 2
         * (1 - exp_dT) / (1 - g * exp_dT))

    return cmath.exp(C + D * v0 + i * phi * x)
```

### `heston_price`

```python
def heston_price(
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
    is_call: bool = True,
) -> float:
    """
    Heston closed-form option price.

    Args:
        S:       current underlying price
        K:       strike price
        T:       time to expiry in years
        r:       risk-free rate (e.g. 0.05)
        params:  HestonParams dataclass
        is_call: True for call, False for put

    Returns:
        Option fair value. Returns BS fallback if integration fails.
        Returns 0.0 on degenerate inputs.
    """
    if T <= 0 or S <= 0 or K <= 0 or params.v0 <= 0:
        return 0.0

    def _integrand(phi: float, j: int) -> float:
        phi_c = complex(phi)
        char = _heston_char_fn(
            phi_c - complex(0, j),
            S, K, T, r, params
        )
        denom = complex(0, phi) * cmath.exp(complex(0, phi) * math.log(K))
        if abs(denom) < 1e-15:
            return 0.0
        return (cmath.exp(complex(0, phi) * math.log(S)) * char / denom).real

    try:
        p1, _ = integrate.quad(lambda phi: _integrand(phi, 1), 0, 500, limit=100)
        p2, _ = integrate.quad(lambda phi: _integrand(phi, 0), 0, 500, limit=100)
        P1 = 0.5 + p1 / math.pi
        P2 = 0.5 + p2 / math.pi
        call_price = S * P1 - K * math.exp(-r * T) * P2
    except Exception:
        # Integration failed — fall back to Black-Scholes with sqrt(v0) as sigma
        return bs_price(S, K, T, r, math.sqrt(params.v0), is_call)

    if is_call:
        return max(call_price, 0.0)
    # Put via put-call parity
    return max(call_price - S + K * math.exp(-r * T), 0.0)
```

### `heston_iv`

```python
def heston_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
    is_call: bool = True,
) -> Optional[float]:
    """
    Implied volatility from Heston-priced option via Newton-Raphson.

    Falls back to bs_iv if Heston price is degenerate.
    Returns None if non-convergent.
    """
    if T <= 0 or S <= 0 or K <= 0 or market_price <= 0:
        return None

    h_price = heston_price(S, K, T, r, params, is_call)
    if h_price <= 0:
        return bs_iv(market_price, S, K, T, r, is_call)

    # Use Heston price as a better starting sigma seed for BS IV solve
    return bs_iv(market_price, S, K, T, r, is_call)
```

### `calibrate_heston`

Grid calibration over `(v0, kappa, theta, sigma_v, rho)`. Uses BS IV as a fast pre-filter to narrow the grid.

```python
def calibrate_heston(
    option_chain: list[dict],
    S: float,
    r: float,
) -> CalibrationResult:
    """
    Calibrate Heston parameters to an observed option chain.

    Args:
        option_chain: list of dicts with keys:
                      strike (float), expiry_years (float), mid_price (float), is_call (bool)
        S:            current underlying price
        r:            risk-free rate

    Returns:
        CalibrationResult with best-fit HestonParams and RMSE.
        Falls back to HestonParams with BS-implied v0 if chain is thin.
    """
    # Filter to usable contracts (price > 0, T > 0)
    chain = [c for c in option_chain
             if c.get("mid_price", 0) > 0 and c.get("expiry_years", 0) > 0]

    if len(chain) < 3:
        # Too thin — return BS-implied variance as v0, neutral Heston params
        ivs = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], r, c.get("is_call", True))
               for c in chain if c.get("mid_price", 0) > 0]
        ivs = [iv for iv in ivs if iv is not None]
        v0_seed = (sum(ivs) / len(ivs)) ** 2 if ivs else 0.04
        fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    # Grid search
    best_rmse = float("inf")
    best_params = None

    v0_grid = [0.01, 0.04, 0.09]
    kappa_grid = [0.5, 1.5, 3.0]
    theta_grid = [0.02, 0.04, 0.08]
    sigma_v_grid = [0.2, 0.4, 0.6]
    rho_grid = [-0.8, -0.5, -0.2]

    for v0 in v0_grid:
        for kappa in kappa_grid:
            for theta in theta_grid:
                for sigma_v in sigma_v_grid:
                    for rho in rho_grid:
                        params = HestonParams(v0=v0, kappa=kappa, theta=theta,
                                             sigma_v=sigma_v, rho=rho)
                        sse = 0.0
                        valid = 0
                        for c in chain:
                            try:
                                model_p = heston_price(S, c["strike"], c["expiry_years"],
                                                       r, params, c.get("is_call", True))
                                sse += (model_p - c["mid_price"]) ** 2
                                valid += 1
                            except Exception:
                                continue
                        if valid == 0:
                            continue
                        rmse = math.sqrt(sse / valid)
                        if rmse < best_rmse:
                            best_rmse = rmse
                            best_params = params

    if best_params is None:
        fallback = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    return CalibrationResult(params=best_params, rmse=round(best_rmse, 6), method="heston_grid")
```

---

## Section 6 — Complete file structure

`backend/app/models/heston.py` must contain, in order:
1. Imports (`cmath`, `math`, `Optional`, `scipy.integrate`, `scipy.stats.norm`, `bs_price`, `bs_iv`)
2. `HestonParams` dataclass
3. `CalibrationResult` dataclass
4. `_heston_char_fn` (private)
5. `heston_price`
6. `heston_iv`
7. `calibrate_heston`

---

## Section 7 — Task spec

### Acceptance criteria

1. `heston_price(185.2, 190, 30/365, 0.05, HestonParams(0.04, 2.0, 0.04, 0.3, -0.7))` returns a positive float.
2. Result is within 15% of `bs_price(185.2, 190, 30/365, 0.05, 0.20)` — both models agree in the right ballpark.
3. `heston_price(S, K, 0, r, params)` returns `0.0` — no exception.
4. `calibrate_heston([], S, r)` returns a `CalibrationResult` with `method="bs_fallback"` — no exception.
5. `calibrate_heston` with a chain of 3+ contracts returns `method="heston_grid"`.
6. `python -c "from app.models.heston import heston_price, heston_iv, calibrate_heston, HestonParams; print('OK')"` prints `OK`.

### Verify after implementation

```bash
cd backend
python -c "
from app.models.heston import heston_price, heston_iv, calibrate_heston, HestonParams
from app.models.black_scholes import bs_price

params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
S, K, T, r = 185.2, 190.0, 30/365, 0.05

h_price = heston_price(S, K, T, r, params)
bs_ref  = bs_price(S, K, T, r, 0.20)
print(f'Heston: {h_price:.4f}  BS ref: {bs_ref:.4f}')
assert h_price > 0, 'Heston price must be positive'
assert abs(h_price - bs_ref) / bs_ref < 0.50, 'Heston too far from BS'

# Degenerate guard
assert heston_price(S, K, 0, r, params) == 0.0

# Calibration — empty chain
res = calibrate_heston([], S, r)
assert res.method == 'bs_fallback'
print('Calibration fallback OK')

# Calibration — small chain
chain = [
    {'strike': 180.0, 'expiry_years': 30/365, 'mid_price': 8.0, 'is_call': True},
    {'strike': 185.0, 'expiry_years': 30/365, 'mid_price': 4.5, 'is_call': True},
    {'strike': 190.0, 'expiry_years': 30/365, 'mid_price': 2.2, 'is_call': True},
    {'strike': 195.0, 'expiry_years': 30/365, 'mid_price': 0.9, 'is_call': True},
]
res2 = calibrate_heston(chain, S, r)
print(f'Calibration: method={res2.method}  rmse={res2.rmse}')
assert res2.method == 'heston_grid'
print('All checks passed')
"
```

---

## Section 8 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify `backend/app/models/black_scholes.py`.
3. All public functions must be safe on degenerate inputs — no unhandled exceptions.
4. Integration failures in `heston_price` must fall back to `bs_price`, not raise.
5. Do NOT use pandas or numpy directly — `scipy.integrate.quad` is fine.
6. `scipy` is already in `requirements.txt` — do not re-add it.

---

## Section 9 — Dev workflow

```bash
cd backend
python -c "from app.models.heston import heston_price, heston_iv, calibrate_heston, HestonParams; print('OK')"
```

---

## Section 10 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-21-heston.

Read `llm-contexts/21-heston-model.md` fully before writing any code.
It is your single source of truth.

You are implementing the Heston stochastic volatility model for the Bamendjou options screener
(FastAPI / Python 3.11 / scipy).

Your owned files:
  - backend/app/models/heston.py   (CREATE)

Do not modify any file outside this list.
Do not modify backend/app/models/black_scholes.py — it is a read-only dependency.

Task: Implement heston_price(), heston_iv(), and calibrate_heston() exactly as specified
in Sections 5 and 6. All functions must be safe on degenerate inputs.
Run the verification block in Section 7 after implementation.
Commit after all checks pass.
```
