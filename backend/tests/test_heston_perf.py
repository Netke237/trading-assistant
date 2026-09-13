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
            def _slow():
                time_mod.sleep(4)
                f.set_result(None)
            threading.Thread(target=_slow, daemon=True).start()
            return f

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _NeverCompleteExecutor)
    result = calibrate_heston(CHAIN, S, r)
    assert result.method == "bs_fallback"
