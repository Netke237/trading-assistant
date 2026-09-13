import time
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
    # Every label calibrate_cached can return. "bs_flat" joined the set in
    # Phase F2 (the fit lost to a single flat volatility on the same chain);
    # this fixture currently lands on "heston_grid", but the assertion is
    # about LATENCY, so it must not fail merely because the gate's verdict on
    # this synthetic chain changes.
    assert result.method in ("heston_grid", "bs_flat", "bs_fallback")


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


def test_realistic_single_expiry_chain_stays_within_call_site_timeout():
    """Task 4 in the scan pipeline caps calibration at a 2s wait_for ceiling
    (_HESTON_CALIBRATION_TIMEOUT_S in app/routers/scan.py). fetch_option_chain
    (app/data/market.py) always returns strikes from a SINGLE expiration, never
    a multi-expiry surface — model that shape here: one shared expiry_years,
    many strikes, using the default reduced grid (HESTON_FULL_CALIBRATION
    unset)."""
    _run_calibration.cache_clear()
    expiry_years = 45 / 365  # a mid-Swing-horizon single expiration
    strikes = [70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0]
    chain = [
        {"strike": k, "expiry_years": expiry_years, "mid_price": max(0.5, 100 - k + 15), "is_call": True}
        for k in strikes
    ]
    start = time.perf_counter()
    result = calibrate_heston(chain, 100.0, 0.05)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, (
        f"Calibration on a {len(chain)}-strike single-expiry chain took {elapsed:.3f}s — "
        "exceeds the scan pipeline's 2s wait_for ceiling"
    )
    assert result.params is not None


def test_a_slow_calibration_returns_its_fit_instead_of_a_fallback(monkeypatch):
    """TIMEOUT-DELETE-INNER-2026-09-13 deleted `calibrate_cached`'s inner 1.0s
    deadline, and this is the behaviour that replaced it: a calibration that
    runs LONGER than that old budget now returns the fit it actually computed,
    where before it computed the same fit and then threw it away as
    `bs_fallback` (the `shutdown(wait=True)` in the executor block meant the
    caller waited for the full search either way, so the timeout only ever
    changed the RESULT).

    This is the case that used to throw fits away: measured on a staggered
    40-symbol scan slice with scan.py's outer guard removed so that only this
    timeout was in play, ALL 40 symbols ran far past 1.0s (median wait 17.7s,
    minimum 3.75s) and so returned `bs_fallback`; after the deletion the same
    40 return `heston_grid`.

    Slowed deterministically by delaying each priced strike rather than by
    finding a genuinely slow chain, so it does not depend on the box's speed.
    """
    from app.models import heston_cache

    _run_calibration.cache_clear()
    real_price = heston_cache.heston_price

    def _slow_price(*args, **kwargs):
        time.sleep(0.02)
        return real_price(*args, **kwargs)

    monkeypatch.setattr(heston_cache, "heston_price", _slow_price)

    start = time.perf_counter()
    result = calibrate_heston(CHAIN, S, r)
    elapsed = time.perf_counter() - start

    assert elapsed > 1.0, (
        f"this test is only meaningful past the deleted 1.0s budget; it took "
        f"{elapsed:.3f}s, so raise the per-strike delay"
    )
    assert result.method != "bs_fallback", (
        "a calibration that completed was discarded as bs_fallback -- the inner "
        "deadline is back"
    )
