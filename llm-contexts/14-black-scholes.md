# LLM Context — Black-Scholes Module (Workstream 14)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one new file (`backend/app/models/black_scholes.py`) and modifies `backend/requirements.txt`. It does not touch `frontend/`, any router, any fixture, any schema, or any existing model file.

**Goal:**
Implement a self-contained Black-Scholes pricing and calibration module. It provides option pricing, Greeks, and implied-volatility solving. WS-21 (Heston) builds on top of these functions as a fallback and IV seed. WS-22 (contract validator) uses delta and theta for scoring.

No market data access. Pure math only.

**What NOT to touch:**
- Any file under `frontend/`
- `backend/app/models/admin.py`, `base.py`, `child.py`, `__init__.py`, `override_log.py`, `quest.py`, `time_log.py` — unrelated domain models, read-only
- Any router, fixture, or schema file
- `backend/app/main.py`

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/models/black_scholes.py` | **Create** | BS pricing, delta, theta, IV solver |
| `backend/requirements.txt` | **Modify** | Add `scipy==1.12.0` |

---

## Section 3 — Read-only references

None required. This module has no dependencies on project code.

---

## Section 4 — Implementation

### `backend/app/models/black_scholes.py`

```python
from __future__ import annotations

import math
from typing import Optional

from scipy.stats import norm


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """
    Black-Scholes option price.

    Args:
        S: current underlying price
        K: strike price
        T: time to expiry in years (e.g. 30 days → 30/365)
        r: risk-free rate (e.g. 0.05 for 5%)
        sigma: annualised implied volatility (e.g. 0.25 for 25%)
        is_call: True for call, False for put

    Returns:
        Option fair value in the same currency as S and K.
        Returns 0.0 if inputs are invalid (T <= 0, sigma <= 0, S <= 0, K <= 0).
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    if is_call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """
    Black-Scholes delta (dV/dS).
    Range: [0, 1] for calls, [-1, 0] for puts.
    Returns 0.0 on invalid inputs.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    if is_call:
        return float(norm.cdf(d1))
    else:
        return float(norm.cdf(d1) - 1)


def bs_theta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """
    Black-Scholes theta (dV/dt) per calendar day (negative for long positions).

    Returns the daily decay in the same currency as S and K.
    Returns 0.0 on invalid inputs.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    # Annual theta
    pdf_d1 = norm.pdf(d1)
    annual: float
    if is_call:
        annual = (
            -(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
            - r * K * math.exp(-r * T) * norm.cdf(d2)
        )
    else:
        annual = (
            -(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
        )
    # Convert to per-calendar-day
    return round(annual / 365, 4)


def bs_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    is_call: bool = True,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> Optional[float]:
    """
    Implied volatility via Newton-Raphson iteration.

    Returns the annualised IV that reproduces `market_price`,
    or None if non-convergent or invalid inputs.

    Args:
        market_price: observed option mid-price
        S, K, T, r, is_call: same as bs_price
        tol: convergence tolerance (default 1e-6)
        max_iter: maximum iterations before giving up
    """
    if market_price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None

    # Initial guess: Brenner-Subrahmanyam approximation
    sigma = math.sqrt(2 * math.pi / T) * market_price / S

    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, is_call)
        if abs(price - market_price) < tol:
            return round(sigma, 6)

        # Vega = S * N'(d1) * sqrt(T)
        d1 = _d1(S, K, T, r, sigma)
        vega = S * norm.pdf(d1) * math.sqrt(T)
        if vega < 1e-10:
            return None  # degenerate — give up

        sigma -= (price - market_price) / vega

        if sigma <= 0:
            return None  # crossed zero — non-convergent

    return None  # did not converge within max_iter
```

---

## Section 5 — `requirements.txt` change

Add after `yfinance==0.2.54` (which WS-13 added), or after `python-multipart` if WS-13 has not run yet:

```
scipy==1.12.0
```

If `scipy` is already present (e.g. from a prior installation), update the version pin to `1.12.0`.

---

## Section 6 — Task spec

### Acceptance criteria

1. `bs_price(185.2, 190, 30/365, 0.05, 0.25, is_call=True)` returns a positive float (expected ~2.8–3.5).
2. `bs_delta(185.2, 190, 30/365, 0.05, 0.25, is_call=True)` returns a float in (0, 1) (expected ~0.38–0.45).
3. `bs_theta(185.2, 190, 30/365, 0.05, 0.25, is_call=True)` returns a negative float (expected ~-0.07 to -0.12).
4. `bs_iv(3.0, 185.2, 190, 30/365, 0.05, is_call=True)` returns a float near 0.25 (within 0.01).
5. All four functions return `0.0` or `None` (respectively) when `T=0` or `sigma=0` — no exception raised.
6. `python -c "from app.models.black_scholes import bs_price, bs_delta, bs_theta, bs_iv; print('OK')"` prints `OK`.

### Verify after implementation

```bash
cd backend
pip install scipy==1.12.0
python -c "
from app.models.black_scholes import bs_price, bs_delta, bs_theta, bs_iv
S, K, T, r, sigma = 185.2, 190.0, 30/365, 0.05, 0.25
print('price :', round(bs_price(S, K, T, r, sigma), 4))
print('delta :', round(bs_delta(S, K, T, r, sigma), 4))
print('theta :', round(bs_theta(S, K, T, r, sigma), 4))
iv = bs_iv(bs_price(S, K, T, r, sigma), S, K, T, r)
print('iv    :', round(iv, 4) if iv else None, '(should be ~0.25)')
print('guard :', bs_price(S, K, 0, r, sigma), bs_delta(S, K, 0, r, sigma))
"
```

Expected output (approximate):
```
price : 3.xxxx
delta : 0.3x-0.4x
theta : -0.0x
iv    : 0.25xx
guard : 0.0 0.0
```

---

## Section 7 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify any existing model file (`admin.py`, `base.py`, `child.py`, etc.).
3. Do NOT add database models or imports to `black_scholes.py` — pure math only.
4. Do NOT use `numpy` directly (scipy already brings it as a dependency; use `scipy.stats.norm` only).
5. All functions must be safe: invalid or degenerate inputs return `0.0` or `None`, never raise.
6. `scipy==1.12.0` is the pinned version.

---

## Section 8 — Dev workflow

```bash
cd backend
pip install scipy==1.12.0
python -c "from app.models.black_scholes import bs_price, bs_delta, bs_theta, bs_iv; print('OK')"
```

---

## Section 9 — Copy/paste prompt

```
Read `llm-contexts/14-black-scholes.md` fully before writing any code.
It is your single source of truth.

You are implementing the Black-Scholes pricing module for the Bamendjou options screener
(FastAPI / Python 3.11 / scipy).

Your owned files:
  - backend/app/models/black_scholes.py   (CREATE)
  - backend/requirements.txt              (MODIFY — add scipy==1.12.0)

Do not modify any file outside this list.

Task: Implement bs_price(), bs_delta(), bs_theta(), and bs_iv() exactly as specified
in Section 4. All functions must be safe (no exceptions on bad inputs).
Run the verification block in Section 6 after implementation.
Commit after all checks pass.
```
