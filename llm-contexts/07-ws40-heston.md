---
workstream: WS-40
branch: feat/ws-40-heston-perf
phase: 3
depends_on: WS-33 (already merged — no other dependency)
conflict_class: Zero — only modifies heston.py and creates two new files. No schema changes, no frontend changes.
---

# WS-40: Heston Performance Optimization

## Mission

The current `calibrate_heston()` runs a 5-parameter grid (3 values each = 243 combos), each combo calling `scipy.integrate.quad` twice. On a 500-symbol scan this means 121,500 integrations and a scan that never completes. Fix with three changes: (1) LRU cache keyed by IV surface hash — eliminates ~90% of calibrations for large universes, (2) reduce grid from 3→2 values per param (243→32 combos default), (3) 2-second timeout with Black-Scholes fallback.

**PRD coverage:** R5, NFR-04

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/models/heston.py` | Modify | Make `calibrate_heston()` a thin wrapper that delegates to cached function |
| `backend/app/models/heston_cache.py` | Create | LRU cache for calibration results keyed by IV surface hash |
| `backend/tests/test_heston_perf.py` | Create | Performance tests: single call < 500ms, cache hit < 5ms, timeout fallback |

**Do NOT touch any other files.**

---

## Read-Only References

- `backend/app/models/heston.py` — current `calibrate_heston()`, `HestonParams`, `CalibrationResult`, `heston_price()`
- `backend/app/models/black_scholes.py` — `bs_price()`, `bs_iv()` signatures for timeout fallback

---

## Current Implementation (read before writing)

`calibrate_heston()` is in `backend/app/models/heston.py` starting at line 140. It does:

```python
v0_grid      = [0.01, 0.04, 0.09]    # 3 values
kappa_grid   = [0.5, 1.5, 3.0]       # 3 values
theta_grid   = [0.02, 0.04, 0.08]    # 3 values
sigma_v_grid = [0.2, 0.4, 0.6]       # 3 values
rho_grid     = [-0.8, -0.5, -0.2]    # 3 values
# Total: 3^5 = 243 combinations, each calling heston_price() twice
```

Returns `CalibrationResult(params: HestonParams, rmse: float, method: str)`.

---

## What to Build

### 1. heston_cache.py — LRU Cache

```python
# backend/app/models/heston_cache.py
import hashlib
import math
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from functools import lru_cache

from app.models.heston import HestonParams, CalibrationResult, heston_price
from app.models.black_scholes import bs_iv

_CALIBRATION_TIMEOUT = 2.0   # seconds
_USE_FULL_GRID = os.getenv("HESTON_FULL_CALIBRATION", "").lower() in ("1", "true")


def _iv_surface_key(option_chain: list[dict], S: float, r: float) -> str:
    """Stable hash of the IV surface inputs — cache key."""
    payload = str(sorted(
        (c.get("strike"), c.get("expiry_years"), c.get("mid_price"))
        for c in option_chain
    )) + f"|S={round(S, 2)}|r={round(r, 4)}"
    return hashlib.md5(payload.encode()).hexdigest()


@lru_cache(maxsize=256)
def _run_calibration(iv_key: str, chain_repr: str, S: float, r: float) -> CalibrationResult:
    """
    Actual grid-search calibration. LRU-cached by IV surface key.
    Reconstructs chain from chain_repr (JSON string) for hashability.
    """
    import json
    chain = json.loads(chain_repr)

    # Reduced grid: 2 values per param = 32 combos (default)
    # Full grid: 3 values per param = 243 combos (HESTON_FULL_CALIBRATION=1)
    if _USE_FULL_GRID:
        v0_grid      = [0.01, 0.04, 0.09]
        kappa_grid   = [0.5, 1.5, 3.0]
        theta_grid   = [0.02, 0.04, 0.08]
        sigma_v_grid = [0.2, 0.4, 0.6]
        rho_grid     = [-0.8, -0.5, -0.2]
    else:
        v0_grid      = [0.01, 0.09]
        kappa_grid   = [0.5, 3.0]
        theta_grid   = [0.02, 0.08]
        sigma_v_grid = [0.2, 0.6]
        rho_grid     = [-0.8, -0.2]

    best_rmse = float("inf")
    best_params = None

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


def calibrate_cached(
    option_chain: list[dict],
    S: float,
    r: float,
) -> CalibrationResult:
    """
    Thread-safe cached calibration with 2-second timeout.
    Falls back to Black-Scholes on timeout or thin chain.
    """
    import json

    chain = [c for c in option_chain
             if c.get("mid_price", 0) > 0 and c.get("expiry_years", 0) > 0]

    if len(chain) < 3:
        ivs = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], r, c.get("is_call", True))
               for c in chain if c.get("mid_price", 0) > 0]
        ivs = [iv for iv in ivs if iv is not None]
        v0_seed = (sum(ivs) / len(ivs)) ** 2 if ivs else 0.04
        fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    iv_key = _iv_surface_key(chain, S, r)
    chain_repr = json.dumps(chain, sort_keys=True)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_calibration, iv_key, chain_repr, S, r)
        try:
            return future.result(timeout=_CALIBRATION_TIMEOUT)
        except TimeoutError:
            ivs = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], r, c.get("is_call", True))
                   for c in chain if c.get("mid_price", 0) > 0]
            ivs = [iv for iv in ivs if iv is not None]
            v0_seed = (sum(ivs) / len(ivs)) ** 2 if ivs else 0.04
            fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
            return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")
```

### 2. heston.py — Update calibrate_heston()

Replace the **body** of `calibrate_heston()` in `heston.py` with a thin wrapper. Keep all other functions (`heston_price`, `heston_iv`, `HestonParams`, `CalibrationResult`) exactly as-is.

```python
def calibrate_heston(
    option_chain: list[dict],
    S: float,
    r: float,
) -> CalibrationResult:
    """
    Calibrate Heston parameters to an observed option chain.
    Delegates to cached implementation with 2-second timeout + BS fallback.
    """
    from app.models.heston_cache import calibrate_cached
    return calibrate_cached(option_chain, S, r)
```

### 3. test_heston_perf.py

```python
# backend/tests/test_heston_perf.py
import time
import concurrent.futures
from app.models.heston import calibrate_heston
from app.models.heston_cache import _run_calibration

CHAIN = [
    {"strike": 90.0,  "expiry_years": 0.25, "mid_price": 12.0, "is_call": True},
    {"strike": 100.0, "expiry_years": 0.25, "mid_price": 5.0,  "is_call": True},
    {"strike": 110.0, "expiry_years": 0.25, "mid_price": 1.5,  "is_call": True},
    {"strike": 95.0,  "expiry_years": 0.50, "mid_price": 8.0,  "is_call": True},
    {"strike": 105.0, "expiry_years": 0.50, "mid_price": 3.0,  "is_call": True},
]
S, r = 100.0, 0.05


def test_first_calibration_under_500ms():
    _run_calibration.cache_clear()
    start = time.perf_counter()
    result = calibrate_heston(CHAIN, S, r)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"Calibration took {elapsed:.3f}s — must be < 500ms"
    assert result.params is not None
    assert result.method in ("heston_grid", "bs_fallback")


def test_cache_hit_under_5ms():
    calibrate_heston(CHAIN, S, r)  # warm cache
    start = time.perf_counter()
    result = calibrate_heston(CHAIN, S, r)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.005, f"Cache hit took {elapsed:.4f}s — must be < 5ms"
    assert result is not None


def test_thin_chain_returns_fallback():
    thin = [{"strike": 100.0, "expiry_years": 0.25, "mid_price": 5.0, "is_call": True}]
    result = calibrate_heston(thin, S, r)
    assert result.method == "bs_fallback"
    assert result.params is not None


def test_timeout_returns_fallback(monkeypatch):
    """Force a 2-second timeout by returning a never-completing Future."""
    import threading
    import time as time_mod
    from app.models import heston_cache

    _run_calibration.cache_clear()

    class _NeverCompleteExecutor:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def submit(self, fn, *args, **kwargs):
            f = concurrent.futures.Future()
            # Thread sets result after 4s — well past the 2s timeout
            def _slow():
                time_mod.sleep(4)
                f.set_result(None)
            threading.Thread(target=_slow, daemon=True).start()
            return f

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _NeverCompleteExecutor)
    result = calibrate_heston(CHAIN, S, r)
    assert result.method == "bs_fallback"
```

---

## Tasks

- [ ] 1. Create `backend/app/models/heston_cache.py` — `_iv_surface_key()`, `_run_calibration()` (LRU cached), `calibrate_cached()` with timeout wrapper
- [ ] 2. Replace `calibrate_heston()` body in `heston.py` with a one-line wrapper calling `calibrate_cached()` — leave all other functions unchanged
- [ ] 3. Create `backend/tests/test_heston_perf.py` with the 4 test cases above
- [ ] 4. Run `pytest tests/test_heston_perf.py -v` — all 4 pass
- [ ] 5. Run `pytest --tb=short -q` — full suite, no regressions

---

## Acceptance Criteria

- [ ] Single Heston calibration (first call, cold cache): < 500ms
- [ ] Cache hit (second identical call): < 5ms
- [ ] Thin chain (< 3 contracts): returns `method="bs_fallback"` immediately
- [ ] `pytest tests/test_heston_perf.py` — all 4 pass
- [ ] Full `pytest` suite — no regressions

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-40 (Heston Performance Optimization) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-40-heston-perf (create from current main)
Phase: 3
Depends: WS-33 only — already merged to main. No other dependency.

Read the full context doc before writing any code:
  F:\Git\GitHub\Trading assistant\llm-contexts\07-ws40-heston.md

Key files to read first (do not modify except heston.py):
- backend/app/models/heston.py — calibrate_heston() at line 140 (3^5=243 grid, the problem)
- backend/app/models/black_scholes.py — bs_price(), bs_iv() signatures for fallback

Problem: calibrate_heston() runs 243 combos × scipy.integrate.quad twice each.
On a 500-symbol scan = 121,500 integrations — scan never completes. Fix with:
  1. heston_cache.py (new file) — LRU cache keyed by IV surface hash
  2. Reduce grid 3→2 values per param (32 combos default)
  3. HESTON_FULL_CALIBRATION=1 env flag to re-enable full 243-combo grid
  4. 2-second ThreadPoolExecutor timeout; fall back to Black-Scholes on timeout

Tasks in order:
1. Create backend/app/models/heston_cache.py (see context doc for exact implementation)
2. Replace calibrate_heston() body in heston.py with thin wrapper → calibrate_cached()
   Keep heston_price(), heston_iv(), HestonParams, CalibrationResult unchanged
3. Create backend/tests/test_heston_perf.py — 4 test cases (500ms, 5ms cache, thin chain, timeout)
4. Run: cd backend && pytest tests/test_heston_perf.py -v  (all pass)
5. Run: cd backend && pytest --tb=short -q  (no regressions)

Return: pytest output for both runs.
```
