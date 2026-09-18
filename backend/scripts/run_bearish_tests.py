"""Run the bearish-path test suite.

Usage: python scripts/run_bearish_tests.py [extra pytest args]

SELECTION IS BY KEYWORD, NOT A HARDCODED LIST. The script first shipped with a
fixed list of six `tests/test_*bearish*.py` modules and was wrong on day one:
the same commit added `tests/test_iv_basis_analysis.py`, whose choose_primary
section runs on Bearish candidates only, and the list did not name it. 30 tests
collected where 121 exist.

WHAT `-k bearish` DOES NOT CATCH, stated plainly because the previous version of
this docstring claimed "a bearish test is collected wherever it is written" and
that is false. `-k` matches literal substrings in node-id components, so a
bearish-path test named after its MECHANISM is missed. Known examples:

    test_alerts.py::test_short_stock_stop_message_says_above_not_below
    test_alerts.py::test_short_stock_structural_stop_triggers_on_price_rise
    test_alerts.py::test_short_stock_stop_triggers_on_price_rise
    test_alerts.py::test_short_stock_target_triggers_on_price_fall
    test_scan_router_spreads.py::test_spread_filter_credit_too_low_no_primary_bear_call
    test_stock_stop_resolution.py::test_the_fallback_honours_the_step_3_parameter_in_both_directions
    test_strategy_watch_evaluator.py::test_armed_opposite_direction_signal_fires_reversal
    test_regime_omm.py::test_conviction_is_direction_aware
    test_reproducibility.py::TestStockScorerReproducibility::test_direction_affects_score

Each sets direction="Bearish" or exercises the short path. This is a convenience
runner, not a proof of bearish coverage: `pytest` with no arguments remains the
only thing that runs everything.
"""
import subprocess
import sys
from pathlib import Path

BEARISH_EXPR = "bearish"

if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parent.parent
    extra = sys.argv[1:]

    # A caller-supplied -k must NARROW the bearish set, not replace it. pytest's
    # -k is last-wins, so appending the caller's after ours silently dropped the
    # filter entirely: `run_bearish_tests.py -k structural` collected all 51
    # structural tests in the repo, bullish ones included, under a script whose
    # name promises the opposite.
    expr = BEARISH_EXPR
    rest = []
    i = 0
    while i < len(extra):
        arg = extra[i]
        if arg == "-k" and i + 1 < len(extra):
            expr = f"({expr}) and ({extra[i + 1]})"
            i += 2
            continue
        # Covers BOTH attached forms. `-k=EXPR` was handled and the bare
        # attached `-kEXPR` -- which argparse accepts and pytest honours -- was
        # not: it fell through to `rest`, landed after the script's own -k, and
        # pytest's last-wins rule dropped the bearish filter entirely.
        # Measured before the fix: `-kstructural` collected 51 tests, the whole
        # repo's structural suite, bullish included.
        if arg.startswith("-k") and len(arg) > 2:
            expr = f"({expr}) and ({arg[3:] if arg[2] == '=' else arg[2:]})"
            i += 1
            continue
        rest.append(arg)
        i += 1

    cmd = [sys.executable, "-m", "pytest", "tests", "-k", expr, *rest]
    sys.exit(subprocess.call(cmd, cwd=backend_root))
