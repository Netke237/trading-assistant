"""Tests for the -k merging in scripts/run_bearish_tests.py.

WHY THIS FILE EXISTS. That script hand-rolls an argument parser whose silent
failure mode is "runs the whole repo's suite under a script named after one
direction", and it lives in `scripts/`, which `pytest tests` never collects --
so every earlier version of the parser shipped with no test behind it. Three
separate defects reached the repo that way:

  1. the bare attached `-kEXPR` form falling through to pytest's last-wins rule;
  2. a caller expression escaping the wrapper through an unbalanced paren;
  3. BUNDLED SHORT OPTIONS (`-xk EXPR`) -- the form a human actually types --
     matching none of the above and falling through identically.

Each collected 51 tests against the correct 6, and exited 0.

NAMING: this file is deliberately NOT named `test_run_bearish_tests.py`. The
script selects its own suite with `-k bearish`, which matches on the node id --
so a filename, class or test name containing that word enrols these parser
tests into the very set the script is meant to run. The first version of this
file put 12 argument-parser tests into it.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_bearish_tests.py"
_spec = importlib.util.spec_from_file_location("run_short_suite", _SCRIPT)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

build_args = runner.build_args
build_cmd = runner.build_cmd
KeywordArgError = runner.KeywordArgError
BASE = runner.BEARISH_EXPR


class TestTheDirectionFilterSurvives:
    """The one invariant: a caller -k NARROWS the base set, never replaces it."""

    @pytest.mark.parametrize(
        "argv, expected_rest",
        [
            (["-k", "structural"], []),        # separate
            (["-kstructural"], []),            # bare attached
            (["-k=structural"], []),           # attached with equals
            (["-xk", "structural"], ["-x"]),   # bundled + separate value
            (["-xkstructural"], ["-x"]),       # bundled + attached value
            (["-qk=structural"], ["-q"]),      # bundled + equals value
            (["-vvk", "structural"], ["-vv"]),  # repeated bundle
        ],
        ids=["separate", "attached", "equals", "bundled", "bundled-attached",
             "bundled-equals", "bundled-repeated"],
    )
    def test_every_k_form_narrows_rather_than_replaces(self, argv, expected_rest):
        expr, rest = build_args(argv)
        assert expr == f"({BASE}) and (structural)"
        # The bundled valueless flags must SURVIVE, not be eaten with the -k...
        assert rest == expected_rest
        # ...and nothing resembling a -k may reach pytest a second time, where
        # last-wins would discard the narrowing we just did.
        assert not any(r.startswith("-k") for r in rest)

    @pytest.mark.parametrize(
        "argv",
        [["-k", "nonexistent) or (structural"], ["-knonexistent) or (structural"],
         ["-xk", "nonexistent) or (structural"]],
        ids=["separate", "attached", "bundled"],
    )
    def test_an_unbalanced_paren_cannot_escape_the_wrapper(self, argv):
        # (base) and (nonexistent) or (structural) parses as
        # ((base) and (nonexistent)) or (structural) -- the filter is GONE.
        # Measured when this was accepted: 51 collected against 6.
        with pytest.raises(KeywordArgError, match="unbalanced"):
            build_args(argv)

    def test_balanced_parens_are_still_allowed(self):
        # The guard must reject the ESCAPE, not parentheses as such.
        assert build_args(["-k", "structural or stop"])[0] == f"({BASE}) and (structural or stop)"
        assert build_args(["-k", "(a or b) and not slow"])[0] == f"({BASE}) and ((a or b) and not slow)"


class TestOrderingIsWhatActuallyBites:
    """The defect was never the expression alone -- it was WHERE it landed."""

    def test_the_merged_expression_is_the_only_k_in_the_command(self):
        cmd = build_cmd("py", ["-xk", "structural", "--tb=short"])
        assert cmd.count("-k") == 1
        assert cmd[cmd.index("-k") + 1] == f"({BASE}) and (structural)"
        # everything after it is inert, so last-wins has nothing to win with
        assert all(not a.startswith("-k") for a in cmd[cmd.index("-k") + 2:])

    def test_pass_through_args_keep_their_order_after_the_filter(self):
        cmd = build_cmd("py", ["--tb=short", "-x", "--collect-only"])
        assert cmd == ["py", "-m", "pytest", "tests", "-k", BASE,
                       "--tb=short", "-x", "--collect-only"]


class TestItRefusesRatherThanRunningTheWrongThing:
    @pytest.mark.parametrize(
        "argv", [["-k", "-v"], ["-k"], ["-k="], ["-xk"]],
        ids=["flag", "trailing", "empty", "bundled-trailing"],
    )
    def test_a_missing_expression_is_refused_not_swallowed(self, argv):
        # `-k -v` used to merge to `(base) and (-v)`, deselect everything and
        # exit 5 -- in CI that reads as "nothing matched", not "you erred".
        with pytest.raises(KeywordArgError):
            build_args(argv)

    @pytest.mark.parametrize("argv", [["-pk", "x"], ["-rk", "x"], ["-ck", "x"]])
    def test_a_bundle_holding_a_value_taking_option_is_refused_not_guessed(self, argv):
        # -p/-r/-c all TAKE a value, so `-pk` means `-p k`, not `-p -k`.
        # Guessing either way is a silent wrong answer; refuse instead.
        with pytest.raises(KeywordArgError, match="takes a value"):
            build_args(argv)


class TestEverythingElseIsPassedThrough:
    def test_non_k_args_reach_pytest_untouched(self):
        expr, rest = build_args(["-x", "--collect-only", "-q"])
        assert expr == BASE
        assert rest == ["-x", "--collect-only", "-q"]

    @pytest.mark.parametrize("arg", ["--keep-going", "--keyword", "-m", "-rA", "--kill"])
    def test_options_that_merely_contain_k_are_not_mistaken_for_it(self, arg):
        expr, rest = build_args([arg])
        assert expr == BASE
        assert rest == [arg]

    def test_repeated_k_args_all_narrow_cumulatively(self):
        assert build_args(["-k", "structural", "-kstop"])[0] == f"(({BASE}) and (structural)) and (stop)"


class TestTheBaseSetItself:
    """THE GAP THAT MADE EVERY OTHER TEST IN THIS FILE SELF-REFERENTIAL.

    Every assertion above is written against `BASE = runner.BEARISH_EXPR`, so
    they pin the merge SHAPE and never the thing being merged. Measured: editing
    the constant to "bearish or bullish" -- a one-token change that makes this
    script run the opposite direction's suite at exit 0, the precise defect class
    of six prior rounds -- left all 27 tests GREEN.
    """

    def test_the_base_expression_is_the_literal_direction_keyword(self):
        assert runner.BEARISH_EXPR == "bearish"

    def test_the_merged_expression_starts_from_that_keyword(self):
        expr, _ = build_args(["-k", "structural"])
        assert expr == "(bearish) and (structural)"


class TestTheAttachedFormWithASecondK:
    """REGRESSION, round 1 of this target's loop. `_K_ARG`'s quantifier was
    greedy, so it bound to the LAST k in the token: `-kbreakout` yielded
    bundle='kbrea', which contains a value-taking short, and the script REFUSED
    an expression argparse and pytest both accept. Every keyword in this repo
    with a second k was affected."""

    @pytest.mark.parametrize("word", ["breakout", "stock", "backtest", "markov", "risk", "k"])
    def test_an_attached_expression_containing_k_is_not_refused(self, word):
        expr, rest = build_args([f"-k{word}"])
        assert expr == f"({BASE}) and ({word})"
        assert rest == []

    def test_a_bundle_before_such_an_expression_still_splits(self):
        expr, rest = build_args(["-xkbreakout"])
        assert expr == f"({BASE}) and (breakout)"
        assert rest == ["-x"]

    def test_a_single_dash_option_merely_containing_k_reads_as_k(self):
        # `-key` IS `-k ey` to argparse, and this is the only single-dash form
        # that actually exercises the regex -- the existing pass-through cases
        # are double-dashed and fail on their second character.
        expr, rest = build_args(["-key"])
        assert expr == f"({BASE}) and (ey)"
        assert rest == []


class TestTheEndOfOptionsMarker:
    def test_a_k_after_a_double_dash_belongs_to_pytest(self):
        # Everything after `--` is positional by argparse's rule, so a -k beyond
        # it must not be intercepted. Previously `--` matched no branch, fell to
        # `rest` AFTER the injected -k, and the -k the caller had explicitly
        # marked positional was merged anyway.
        expr, rest = build_args(["--", "-k", "structural"])
        assert expr == BASE
        assert rest == ["--", "-k", "structural"]


class TestTheScriptAsActuallyInvoked:
    """THE WIRING, which nothing above touches. Every other test in this file
    calls build_args/build_cmd directly, so `__main__` -- where the refusal is
    caught, reported and turned into an exit code -- had ZERO coverage. Both of
    these mutations survived the whole suite:

        sys.exit(4) -> sys.exit(0)           27 passed
        delete the try/except entirely       27 passed

    i.e. "refuses loudly" was held by nobody having edited five lines. These are
    subprocess tests because that is the only thing that can observe an exit
    code, and the headline claim of this whole piece ("6, not 51") was until now
    verified only by a human at a terminal.
    """

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True,
        )

    def test_a_bundled_selector_narrows_to_the_intersection(self):
        # The exact form that collected 51 tests at exit 0 across three rounds.
        r = self._run("-xk", "structural", "--collect-only", "-q")
        assert r.returncode == 0, r.stderr
        assert "6/" in r.stdout, r.stdout[-400:]

    def test_an_unbalanced_expression_refuses_loudly_rather_than_running(self):
        r = self._run("-k", "a) or (b", "--collect-only", "-q")
        assert r.returncode == 4, f"rc={r.returncode} out={r.stdout[-200:]}"
        assert "run_bearish_tests.py:" in r.stderr
        assert "tests collected" not in r.stdout
