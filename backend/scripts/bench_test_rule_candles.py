"""Measures how long test_rule's per-candle regime recompute takes at the cap.
Run: cd backend && venv/Scripts/python.exe scripts/bench_test_rule_candles.py"""
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.alert_evaluator import build_regime_snapshot


def synth(n: int) -> list[dict]:
    price = 100.0
    out = []
    for _ in range(n):
        price *= 1 + random.uniform(-0.01, 0.01)
        out.append({"open": price, "high": price * 1.01, "low": price * 0.99,
                    "close": price, "volume": 1_000_000})
    return out


def main():
    for n in (200, 500, 1000, 1500):
        candles = synth(n)
        # Simulate the worst case test_rule hits: recompute once per candle.
        t0 = time.perf_counter()
        for i in range(200, n + 1):
            build_regime_snapshot(candles[:i])
        dt = time.perf_counter() - t0
        print(f"n={n:5d}  total_recompute={dt:7.2f}s  per_candle={dt / max(1, n - 200) * 1000:6.1f}ms")


if __name__ == "__main__":
    main()
