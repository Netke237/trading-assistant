"""Run the bearish-path test suite (scoring, triggers, strategy engine/backtest, watch, fundamentals gate).

Usage: python scripts/run_bearish_tests.py [extra pytest args]
"""
import subprocess
import sys
from pathlib import Path

BEARISH_TESTS = [
    "tests/test_bearish_scoring.py",
    "tests/test_bearish_trigger.py",
    "tests/test_strategy_engine_bearish.py",
    "tests/test_strategy_watch_bearish.py",
    "tests/test_strategy_backtest_bearish.py",
    "tests/test_fundamentals_gate_bearish.py",
]

if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "pytest", *BEARISH_TESTS, *sys.argv[1:]]
    sys.exit(subprocess.call(cmd, cwd=backend_root))
