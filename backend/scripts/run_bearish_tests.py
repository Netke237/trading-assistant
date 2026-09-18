"""Run the bearish-path test suite.

Usage: python scripts/run_bearish_tests.py [extra pytest args]

SELECTION IS BY KEYWORD, NOT BY A HARDCODED LIST, and that is the whole point.
This script shipped with a fixed list of six `tests/test_*bearish*.py` modules
and was immediately wrong: the very commit that added it also added
`tests/test_iv_basis_analysis.py`, whose `choose_primary` section runs on
Bearish candidates only and whose fixtures are all `direction: "Bearish"` --
and which the list did not name. A hardcoded list rots silently; nothing fails
when a new bearish test is written somewhere the list does not look.

`-k bearish` matches on module, class and test names (case-insensitively), so a
bearish test is collected wherever it is written.
"""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "pytest", "tests", "-k", "bearish", *sys.argv[1:]]
    sys.exit(subprocess.call(cmd, cwd=backend_root))
