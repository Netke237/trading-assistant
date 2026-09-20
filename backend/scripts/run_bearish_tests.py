"""Run the bearish-path test suite.

Usage: .venv/bin/python scripts/run_bearish_tests.py [extra pytest args]

`-k` IS INTERCEPTED, not passed through: the caller's expression is merged as
`(bearish) and (yours)` so it NARROWS rather than replaces, and repeated -k is
cumulative rather than pytest's last-wins. An expression with unbalanced parens,
or a bundle whose letters are ambiguous, is refused with exit 4.

SELECTION IS BY KEYWORD, NOT A HARDCODED LIST. The script first shipped with a
fixed list of six `tests/test_*bearish*.py` modules and was wrong on day one:
the same commit added `tests/test_iv_basis_analysis.py`, whose choose_primary
section runs on Bearish candidates only, and the list did not name it. 30 tests
collected where 121 existed at the time; `-k bearish` collects more now, so treat
that pair as the measurement that condemned the hardcoded list, not a current count.

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
import re
import subprocess
import sys
from pathlib import Path

BEARISH_EXPR = "bearish"


class KeywordArgError(ValueError):
    """A caller-supplied -k that cannot be merged without losing the bearish filter."""


def _balanced(expr: str) -> bool:
    """True when every parenthesis in `expr` closes inside `expr`.

    THIS IS THE WHOLE INVARIANT, not a politeness check. The merge below wraps
    the caller's expression in parentheses to keep it subordinate to the
    bearish filter -- but a caller expression that closes a paren it never
    opened escapes that wrapper, and pytest binds `and` tighter than `or`:

        -k "nonexistent) or (structural"
            -> (bearish) and (nonexistent) or (structural)
            -> ((bearish) and (nonexistent)) or (structural)

    which is the bearish filter GONE, silently, exit 0. Measured against the
    real suite: 51 tests collected -- the repo's whole structural suite,
    bullish included -- against 6 for the correctly narrowed `-k structural`.
    Both the separate and the attached form carried it identically.
    """
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _merge(expr: str, addition: str) -> str:
    """Narrow `expr` by `addition`, or refuse to."""
    addition = addition.strip()
    if not addition:
        raise KeywordArgError("-k was given an empty expression")
    if not _balanced(addition):
        raise KeywordArgError(
            f"-k expression has unbalanced parentheses: {addition!r}. "
            "It would break out of the bearish filter and select bullish tests."
        )
    return f"({expr}) and ({addition})"


# THE DANGEROUS LETTERS, not the safe ones. This was a whitelist of "valueless"
# shorts, set("xvqslfd"), and it was wrong on day one in both directions -- the
# exact failure its own module docstring opens by condemning. `f` and `d` are
# not pytest options in this environment at all (no pytest-xdist), so `-fk EXPR`
# built a command pytest rejects; while `-h` IS a real valueless flag and was
# missing, so `-hk EXPR` was refused for no reason.
#
# Inverted, it only has to name the letters whose bundling is genuinely
# AMBIGUOUS: a short that TAKES a value means `-pk` is `-p k`, not `-p -k`.
# These are pytest's own value-taking shorts. Any OTHER letter is passed
# through to pytest, which errors loudly if it is not a real flag -- a bounded,
# visible failure, where a false refusal blocks a legitimate run.
# `k` is UNREACHABLE here and deliberately kept: the lazy quantifier makes
# `bundle` the prefix BEFORE the first k, so it can never contain one. It stays
# so the set remains a truthful list of pytest's value-taking shorts, and so a
# future edit to the regex cannot silently make `-kk...` ambiguous without this
# catching it.
VALUE_TAKING_SHORTS = set("kmcoprW")

# `-k`, or any bundle of shorts ending in k: -k, -kEXPR, -k=EXPR, -xk EXPR,
# -xkEXPR, -vk=EXPR ...
#
# THE QUANTIFIER IS LAZY, AND THAT IS LOAD-BEARING. Greedy, `[A-Za-z]*` binds to
# the LAST k in the token, so `-kbreakout` (k-b-r-e-a-k-o-u-t) backtracked to the
# SECOND k and yielded bundle='kbrea' -- which contains `k`, a value-taking
# short, so the script refused an ordinary expression that argparse and pytest
# both accept (`pytest -kbreakout` collects 26). Every keyword in this repo
# carrying a second k was affected: breakout, stock, backtest, markov, risk.
# Lazy binds the option letter left-to-right, exactly as argparse consumes a
# bundle.
_K_ARG = re.compile(r"^-([A-Za-z]*?)k(.*)$")


def build_args(extra):
    """Split caller args into the merged -k expression and everything else.

    Kept a module-level function purely so it can be tested -- `scripts/` is not
    collected by `pytest tests`, so every earlier version of this loop had no
    test of any kind behind it, and two separate defects shipped that way.
    """
    expr = BEARISH_EXPR
    rest = []
    i = 0
    while i < len(extra):
        arg = extra[i]
        if arg == "--":
            # END OF OPTIONS -- AND THIS BRANCH EXISTS TO FAIL LOUDLY, NOT TO
            # SUPPORT `--`. Measured: pytest 8.1.1 rejects a bare `--` outright
            # ("unrecognized arguments: --", exit 4) in every placement, so a
            # post-`--` -k can never reach a successful run. What the branch
            # buys is that we do not INTERCEPT it: previously `--` matched no
            # branch and fell through to `rest`, landing after the injected -k,
            # so a -k the caller had explicitly marked positional was merged
            # into ours anyway. Passing the tail through verbatim keeps the
            # caller's mistake theirs and keeps pytest's error honest -- and
            # dropping the marker here re-opens last-wins widening.
            rest.extend(extra[i:])
            break
        m = _K_ARG.match(arg)
        if m is None:
            rest.append(arg)
            i += 1
            continue

        bundle, tail = m.group(1), m.group(2)

        # BUNDLED SHORT OPTIONS. `-xk structural` is how a human actually types
        # this, argparse accepts it, pytest honours it -- and matching only on
        # `startswith("-k")` missed every one of them. They fell through to
        # `rest`, landed AFTER the script's own -k, and pytest's last-wins rule
        # dropped the bearish filter. Measured: `-xk structural` collected 51
        # tests (the repo's whole structural suite, TestBullish cases included)
        # against 6 for the correctly narrowed form, and exited 0.
        # `next`, NOT `sorted`. argparse consumes a bundle LEFT TO RIGHT, so the
        # option that actually swallows the rest is the FIRST value-taking letter
        # in the bundle. sorted() named the alphabetically-first one, which for
        # any multi-letter bundle is a reading argparse never performs: `-rpk`
        # means `-r pk`, and the message said "-p takes a value, so '-rpk' may
        # mean '-p k...'". Fixed only for single-letter bundles before.
        ambiguous = next((c for c in bundle if c in VALUE_TAKING_SHORTS), None)
        if ambiguous:
            # The message names the ACTUAL letter. It used to say "it bundles a
            # short option that takes a value" for every refusal, including
            # `-kbreakout`, which bundles nothing -- sending the reader hunting
            # for a bundle that was not there.
            raise KeywordArgError(
                f"cannot tell where -k starts in {arg!r}: -{ambiguous} takes a value, "
                f"so {arg!r} may mean '-{ambiguous} k...'. Pass -k as its own argument."
            )

        if tail == "":
            # NOT `i + 1 < len(extra)` alone. That consumed the next token
            # unconditionally, including one that is plainly a flag: argparse
            # refuses this and pytest errors with "expected one argument", but
            # this script swallowed it -- `-k -v` merged to `(bearish) and (-v)`,
            # deselected the whole suite and exited 5, which in CI reads as
            # "nothing matched" rather than as a mistake.
            if i + 1 >= len(extra) or extra[i + 1].startswith("-"):
                raise KeywordArgError("-k expects an expression, not a flag or nothing")
            addition, step = extra[i + 1], 2
        else:
            addition, step = (tail[1:] if tail.startswith("=") else tail), 1

        expr = _merge(expr, addition)
        if bundle:
            rest.append(f"-{bundle}")
        i += step
    return expr, rest


def build_cmd(executable, extra):
    """The full pytest command. Split out from __main__ so the ORDERING can be
    tested: the defect these guards exist for was never in the expression alone,
    it was a caller -k reaching `rest` and landing AFTER the script's own -k,
    where pytest's last-wins rule silently discarded the narrower filter.
    """
    expr, rest = build_args(extra)
    return [executable, "-m", "pytest", "tests", "-k", expr, *rest]


if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parent.parent
    # A caller-supplied -k must NARROW the bearish set, not replace it. pytest's
    # -k is last-wins, so appending the caller's after ours silently dropped the
    # filter entirely: `run_bearish_tests.py -k structural` collected all 51
    # structural tests in the repo, bullish ones included, under a script whose
    # name promises the opposite.
    try:
        cmd = build_cmd(sys.executable, sys.argv[1:])
    except KeywordArgError as exc:
        print(f"run_bearish_tests.py: {exc}", file=sys.stderr)
        # 4, NOT 2. This IS a usage error and 4 is pytest's own code for one;
        # 2 is pytest's ExitCode.INTERRUPTED. STATED HONESTLY, BECAUSE THE FIRST
        # VERSION OF THIS COMMENT OVERSOLD IT: 4 does not disambiguate either.
        # It reaches the caller from the PASS-THROUGH path routinely (`-Kstructural`,
        # any `--` form), so a CI step branching on the code alone still cannot
        # tell "the wrapper refused your -k" from "pytest rejected your args".
        # Only the `run_bearish_tests.py:` prefix on stderr does. 4 is chosen
        # because it is the truthful CLASS of error, not because it is unique.
        # Verified before changing it: nothing in this repo depended on 2.
        sys.exit(4)

    sys.exit(subprocess.call(cmd, cwd=backend_root))
