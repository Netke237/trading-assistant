"""Public calibration results own both mutable dataclass levels."""

import math
from dataclasses import asdict

import pytest

from app.models.black_scholes import bs_price
from app.models.heston import calibrate_heston, heston_price
from app.models.heston_cache import _run_calibration, calibrate_cached


S, R, T = 201.86, 0.05, 45 / 365.0


@pytest.fixture(autouse=True)
def isolated_calibration_cache():
    _run_calibration.cache_clear()
    yield
    _run_calibration.cache_clear()


def _chain(strikes, skew=False):
    chain = []
    for strike in strikes:
        log_moneyness = math.log(strike / S)
        sigma = (0.345 - 0.45 * log_moneyness + 1.6 * log_moneyness ** 2
                 if skew else 0.30)
        mid = bs_price(S, strike, T, R, sigma, True)
        chain.append({
            "strike": float(strike), "expiry_years": T,
            "mid_price": round(mid, 2) if skew else mid, "is_call": True,
        })
    return chain


def _mutate(result):
    result.params.v0 = 0.81
    result.params.kappa = 7.0
    result.params.theta = 0.49
    result.params.sigma_v = 0.9
    result.params.rho = 0.1
    result.rmse = -1.0
    result.method = "caller_mutated"


def _assert_independent_returns(calibrate, chain, method):
    first = calibrate(chain, S, R)
    original = asdict(first)
    original_price = heston_price(S, 210.0, T, R, first.params, True)
    assert first.method == method
    second = calibrate(chain, S, R)
    assert asdict(second) == original
    assert heston_price(S, 210.0, T, R, second.params, True) == original_price

    _mutate(first)
    later = calibrate(chain, S, R)
    for result in (second, later):
        assert asdict(result) == original
        assert heston_price(S, 210.0, T, R, result.params, True) == original_price
    assert first is not second and first is not later and second is not later
    assert (first.params is not second.params and first.params is not later.params
            and second.params is not later.params)


@pytest.mark.parametrize("calibrate", [calibrate_cached, calibrate_heston])
def test_heston_grid_returns_are_isolated_and_still_cached(calibrate):
    _assert_independent_returns(calibrate, _chain(range(180, 226, 5), skew=True),
                                "heston_grid")
    info = _run_calibration.cache_info()
    assert (info.misses, info.hits, info.currsize, info.maxsize) == (1, 2, 1, 256)


@pytest.mark.parametrize("calibrate", [calibrate_cached, calibrate_heston])
def test_real_bs_flat_returns_are_isolated_and_still_cached(calibrate):
    _assert_independent_returns(calibrate, _chain([190, 200, 210]), "bs_flat")
    info = _run_calibration.cache_info()
    assert (info.misses, info.hits, info.currsize) == (1, 2, 1)


@pytest.mark.parametrize("calibrate", [calibrate_cached, calibrate_heston])
def test_thin_chain_fallback_returns_are_independent(calibrate):
    _assert_independent_returns(calibrate, _chain([200]), "bs_fallback")
    info = _run_calibration.cache_info()
    assert (info.misses, info.hits, info.currsize) == (0, 0, 0)
