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
            def _slow():
                time_mod.sleep(4)
                f.set_result(None)
            threading.Thread(target=_slow, daemon=True).start()
            return f

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _NeverCompleteExecutor)
    result = calibrate_heston(CHAIN, S, r)
    assert result.method == "bs_fallback"
