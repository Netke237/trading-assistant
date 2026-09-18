"""Tests for the -k merging in scripts/run_bearish_tests.py.

WHY THIS FILE EXISTS. The script hand-rolls an argument parser whose silent
failure mode is "runs the bullish suite under a script named bearish", and it
lives in `scripts/`, which `pytest tests` never collects -- so every previous
version of that parser shipped with no test of any kind behind it. Two separate
defects reached the repo that way (the bare attached `-kEXPR` form falling
through to pytest's last-wins rule, and a caller expression escaping the
wrapper through an unbalanced paren). Both are pinned below.
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_bearish_tests.py"
_spec = importlib.util.spec_from_file_location("run_bearish_tests", _SCRIPT)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

build_args = runner.build_args
KeywordArgError = runner.KeywordArgError


class TestTheBearishFilterSurvives:
    """The one invariant: a caller -k NARROWS the bearish set, never replaces it."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["-k", "structural"],   # separate
            ["-kstructural"],       # bare attached -- fell through before 511311c9
            ["-k=structural"],      # attached with equals
        ],
        ids=["separate", "attached-bare", "attached-equals"],
    )
    def test_every_k_form_narrows_rather_than_replaces(self, argv):
        expr, rest = build_args(argv)
        assert expr == "(bearish) and (structural)"
        # and nothing leaks through to be re-applied by pytest's last-wins rule
        assert rest == []

    def test_an_unbalanced_paren_cannot_escape_the_wrapper(self):
        # (bearish) and (nonexistent) or (structural) parses as
        # ((bearish) and (nonexistent)) or (structural) -- bearish filter gone.
        # Measured against the real suite when this was accepted: 51 collected
        # (the repo's whole structural suite, bullish included) against 6.
        with pytest.raises(KeywordArgError, match="unbalanced"):
            build_args(["-k", "nonexistent) or (structural"])

    def test_the_attached_form_carries_the_same_guard(self):
        with pytest.raises(KeywordArgError, match="unbalanced"):
            build_args(["-knonexistent) or (structural"])

    def test_balanced_parens_are_still_allowed(self):
        # The guard must reject the ESCAPE, not parentheses as such -- a wrapped
        # `or` is correctly subordinate and must keep working.
        expr, _ = build_args(["-k", "structural or stop"])
        assert expr == "(bearish) and (structural or stop)"
        expr, _ = build_args(["-k", "(structural or stop) and not slow"])
        assert expr == "(bearish) and ((structural or stop) and not slow)"


class TestItRefusesRatherThanRunningTheWrongThing:
    @pytest.mark.parametrize("argv", [["-k", "-v"], ["-k"], ["-k="]], ids=["flag", "trailing", "empty"])
    def test_a_missing_expression_is_refused_not_swallowed(self, argv):
        # `-k -v` used to merge to `(bearish) and (-v)`, deselect all 2611 tests
        # and exit 5 -- which in CI reads as "nothing matched", not "you made a
        # mistake". argparse refuses this; so does the script now.
        with pytest.raises(KeywordArgError):
            build_args(argv)


class TestEverythingElseIsPassedThrough:
    def test_non_k_args_reach_pytest_untouched(self):
        expr, rest = build_args(["-x", "--collect-only", "-q"])
        assert expr == "bearish"
        assert rest == ["-x", "--collect-only", "-q"]

    def test_long_options_beginning_with_k_are_not_mistaken_for_k(self):
        # "--keep-going".startswith("-k") is False, but pin it: a future edit to
        # the prefix test is exactly how this class of bug returns.
        expr, rest = build_args(["--keep-going"])
        assert expr == "bearish"
        assert rest == ["--keep-going"]

    def test_repeated_k_args_all_narrow_cumulatively(self):
        expr, _ = build_args(["-k", "structural", "-kstop"])
        assert expr == "((bearish) and (structural)) and (stop)"
