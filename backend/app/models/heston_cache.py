from __future__ import annotations

import hashlib
import math
import os
import concurrent.futures
from functools import lru_cache

from app.models.heston import HestonParams, CalibrationResult, heston_price
from app.models.black_scholes import bs_iv

_CALIBRATION_TIMEOUT = 2.0
_USE_FULL_GRID = os.getenv("HESTON_FULL_CALIBRATION", "").lower() in ("1", "true")


def _iv_surface_key(option_chain: list[dict], S: float, r: float) -> str:
    payload = str(sorted(
        (c.get("strike"), c.get("expiry_years"), c.get("mid_price"))
        for c in option_chain
    )) + f"|S={round(S, 2)}|r={round(r, 4)}"
    return hashlib.md5(payload.encode()).hexdigest()


@lru_cache(maxsize=256)
def _run_calibration(iv_key: str, chain_repr: str, S: float, r: float) -> CalibrationResult:
    import json
    chain = json.loads(chain_repr)

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

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_calibration, iv_key, chain_repr, S, r)
        try:
            return future.result(timeout=_CALIBRATION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            ivs = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], r, c.get("is_call", True))
                   for c in chain if c.get("mid_price", 0) > 0]
            ivs = [iv for iv in ivs if iv is not None]
            v0_seed = (sum(ivs) / len(ivs)) ** 2 if ivs else 0.04
            fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
            return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")
