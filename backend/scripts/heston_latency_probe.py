"""Measures where Heston calibration actually spends a scan's time budget.

Run: cd backend && .venv/bin/python scripts/heston_latency_probe.py

Written for TIMEOUT-DELETE-INNER-2026-09-13, whose decision was conditional on
"measure the real latency spread across a full scan FIRST". It answers three
questions, in the order they matter:

  1. SOLO   -- what one calibration costs, swept over the chain shapes a real
               scan produces (one expiry, N delta-banded strikes).
  2. THREADS-- whether `_HESTON_EXECUTOR`'s thread pool buys any parallelism.
               It is the load-bearing measurement: `heston_price` integrates a
               PYTHON integrand through scipy's QUADPACK, so the GIL is held
               almost throughout and N threads cost about N times one thread
               rather than one. If that holds on your box, no amount of
               widening `_HESTON_CALIBRATION_TIMEOUT_S` fixes coverage.
  3. SCAN   -- a staggered 40-symbol slice driven through scan.py's OWN
               machinery (`_run_heston_calibration`, `_HESTON_SEMAPHORE`,
               `_HESTON_EXECUTOR`, the real `asyncio.wait` ceiling), reporting
               what fraction of symbols would show "Heston repriced" rather
               than falling back to the delta approximation. Run it with
               --no-guard to remove the outer ceiling and see what the
               calibrations actually cost when nobody gives up on them.

MEASURED HERE (4 cores, 2.1GHz Xeon, CPython 3.11, after the inner timeout was
deleted): solo 0.16-1.73s across the sweep; 4 threads 5.52x one thread's wall
time on 4 IDLE cores; 40 of 40 symbols abandoned at the 2.0s guard. Numbers
from any other box are the point of this script -- especially core count, and
especially whether the runtime is free-threaded (`sys._is_gil_enabled()`), in
which case measurement 2 should come out near 1.0x and the whole picture with
it.
"""
import argparse
import asyncio
import concurrent.futures
import json
import logging
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.black_scholes import bs_price
from app.models import heston_cache
from app.models.heston_cache import _run_calibration

R = 0.05
SPOT = 201.86
# The spec's section 7 reference smile (ATM level, skew, curvature).
ATM, SKEW, CURV = 0.345, 0.45, 1.6


def chain(dte: int, n_strikes: int, spot: float = SPOT) -> list[dict]:
    """One expiry, `n_strikes` strikes spanning a band that widens with
    sqrt(T) so it stays economically comparable across DTE, snapped to a $2.50
    ladder and priced at the reference smile, rounded to the cent exactly as a
    real quote is. Calls above spot, puts below -- the same split the
    scanner's delta band produces."""
    T = dte / 365.0
    width = spot * 0.45 * math.sqrt(max(T, 1e-6))
    out = []
    for i in range(n_strikes):
        k = (spot - width) + 2 * width * i / max(n_strikes - 1, 1)
        k = round(k / 2.5) * 2.5
        is_call = k >= spot
        m = math.log(k / spot)
        mid = round(bs_price(spot, k, T, R, ATM + SKEW * (-m) + CURV * m ** 2, is_call), 2)
        if mid > 0:
            out.append({"strike": k, "expiry_years": T, "mid_price": mid,
                        "is_call": is_call})
    return out


def _calibrate_uncached(c: list[dict], spot: float = SPOT, tag: str = "probe"):
    """Past `calibrate_cached` so the lru_cache can never turn a measurement
    into a 1ms hit. Each call gets its own key AND clears the cache."""
    _run_calibration.cache_clear()
    return _run_calibration(tag, json.dumps(c, sort_keys=True), spot, R)


def measure_solo() -> None:
    print("=" * 72)
    print("1. SOLO -- one calibration, nothing else running")
    print("=" * 72)
    print(f"{'DTE':>5} {'strikes':>8} {'min':>8} {'median':>8} {'max':>8}  method")
    medians = []
    for dte in (21, 30, 45, 60, 90, 120, 180, 270, 365):
        for n in (8, 15, 25, 40, 60):
            c = chain(dte, n)
            if len(c) < 3:
                continue
            times = []
            for rep in range(3):
                t0 = time.perf_counter()
                res = _calibrate_uncached(c, tag=f"solo{dte}-{n}-{rep}")
                times.append(time.perf_counter() - t0)
            medians.append(statistics.median(times))
            print(f"{dte:>5} {len(c):>8} {min(times):>8.3f} "
                  f"{statistics.median(times):>8.3f} {max(times):>8.3f}  {res.method}")
    print(f"\n  {len(medians)} shapes: median {statistics.median(medians):.3f}s, "
          f"max {max(medians):.3f}s")


def measure_threads() -> None:
    print()
    print("=" * 72)
    print("2. THREADS -- does the calibration thread pool parallelise?")
    print("=" * 72)
    cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    gil = getattr(sys, "_is_gil_enabled", None)
    print(f"  cores available: {cores}   "
          f"GIL enabled: {gil() if gil else 'n/a (pre-3.13 build)'}")

    def work(i: int):
        return _run_calibration(f"thr{i}", json.dumps(chain(45, 25, SPOT + i * 1.13),
                                                      sort_keys=True), SPOT + i * 1.13, R)

    _run_calibration.cache_clear()
    t0 = time.perf_counter()
    work(0)
    solo = time.perf_counter() - t0
    print(f"\n  1 thread : {solo:.3f}s")
    for n in (2, 4, 8):
        _run_calibration.cache_clear()
        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(work, range(100 * n, 100 * n + n)))
        wall = time.perf_counter() - t0
        print(f"  {n} threads: {wall:.3f}s wall = {wall / solo:.2f}x one thread "
              f"(1.00x = perfectly parallel, {n}.00x = fully serialised)")


async def measure_scan(n_symbols: int, guard: bool) -> None:
    from app.routers import scan as scan_mod

    print()
    print("=" * 72)
    print(f"3. SCAN -- {n_symbols} symbols through scan.py's own machinery"
          f"{'' if guard else ', OUTER GUARD REMOVED'}")
    print("=" * 72)
    print(f"  _SCAN_CONCURRENCY={scan_mod._SCAN_CONCURRENCY}  "
          f"_HESTON_CONCURRENCY={scan_mod._HESTON_CONCURRENCY}  "
          f"outer guard={scan_mod._HESTON_CALIBRATION_TIMEOUT_S if guard else None}")

    random.seed(7)
    _run_calibration.cache_clear()
    results: list[tuple[float, str]] = []
    scan_sem = asyncio.Semaphore(scan_mod._SCAN_CONCURRENCY)

    async def symbol(i: int) -> None:
        async with scan_sem:
            spot = 80.0 + i * 3.7
            # Stand in for the Tradier chain fetch. Async, so it yields the
            # GIL exactly as httpx does -- symbols reach calibration staggered,
            # not as one synchronised burst.
            await asyncio.sleep(random.uniform(0.15, 0.45))
            c = chain(random.choice([30, 45, 60, 90, 180]),
                      random.choice([15, 25, 40]), spot)
            t0 = time.perf_counter()
            task = asyncio.ensure_future(scan_mod._run_heston_calibration(c, spot))
            done, _ = await asyncio.wait(
                {task},
                timeout=scan_mod._HESTON_CALIBRATION_TIMEOUT_S if guard else None,
            )
            dt = time.perf_counter() - t0
            if task in done:
                results.append((dt, task.result().method))
            else:
                # Exactly what scan.py does: leave it running, consume its
                # exception, move on to the delta approximation.
                task.add_done_callback(lambda f: f.exception())
                results.append((dt, "abandoned"))

    t0 = time.perf_counter()
    await asyncio.gather(*(symbol(i) for i in range(n_symbols)))
    wall = time.perf_counter() - t0

    times = [t for t, _ in results]
    counts: dict[str, int] = {}
    for _, m in results:
        counts[m] = counts.get(m, 0) + 1
    print(f"\n  {n_symbols} symbols in {wall:.1f}s ({wall / n_symbols:.2f}s/symbol)")
    print(f"  calibration wait: min {min(times):.3f}s  "
          f"median {statistics.median(times):.3f}s  max {max(times):.3f}s")
    print(f"  over {scan_mod._HESTON_CALIBRATION_TIMEOUT_S}s: "
          f"{sum(1 for t in times if t >= scan_mod._HESTON_CALIBRATION_TIMEOUT_S)}/{len(times)}\n")
    for m, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        shown = ("-> 'Heston repriced' on the card" if m == "heston_grid"
                 else "-> delta approximation (nothing Heston reaches the card)")
        print(f"  {m:<12} {n:>3}/{n_symbols}  {shown}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=("solo", "threads", "scan"),
                    help="run one measurement instead of all three")
    ap.add_argument("--symbols", type=int, default=40,
                    help="symbols in the scan slice (default 40)")
    ap.add_argument("--no-guard", action="store_true",
                    help="drop scan.py's outer ceiling, to see the true cost")
    args = ap.parse_args()

    # The boundary/verdict WARNING fires roughly once per calibration and
    # would bury the table; this script reports the verdicts itself.
    logging.disable(logging.CRITICAL)

    if args.only in (None, "solo"):
        measure_solo()
    if args.only in (None, "threads"):
        measure_threads()
    if args.only in (None, "scan"):
        asyncio.run(measure_scan(args.symbols, guard=not args.no_guard))


if __name__ == "__main__":
    main()
