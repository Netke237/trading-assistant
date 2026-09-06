"""Phase A finding (d) — the spread picker judges the right quantity.

`choose_primary` decides which of the two bearish structures is presented as
PRIMARY: bear_call (credit, SHORT premium) when vol is rich, bear_put (debit,
LONG premium) when it is not. Until now it compared whatever figure it had
against one unqualified threshold, so a 60% ABSOLUTE IV was judged as though
it were the 60th PERCENTILE — the conflation Phase A exists to remove,
surviving in the one place that picks a trade structure.

See decision PHASE-A-SPREAD-BASIS-2026-09-06.
"""
import pytest

from app.scoring.spread_builder import choose_primary


def _pick(iv, basis, *, rank=50.0, absolute=50.0):
    return choose_primary(
        iv=iv, iv_basis=basis, rank_threshold=rank, abs_threshold=absolute
    )


def test_the_basis_selects_the_threshold():
    # The whole finding in one case: same number, same call, opposite structure,
    # because 60% IV and the 60th percentile are different claims. With the
    # thresholds driven apart, a basis-blind implementation cannot pass both.
    assert _pick(60.0, "absolute", rank=90.0, absolute=50.0) == "bear_call"
    assert _pick(60.0, "rank", rank=90.0, absolute=50.0) == "bear_put"


@pytest.mark.parametrize("basis", ["rank", "absolute"])
def test_at_or_above_the_threshold_sells_premium(basis):
    assert _pick(50.0, basis) == "bear_call"
    assert _pick(49.9, basis) == "bear_put"


def test_no_reading_at_all_buys_premium_and_says_so():
    # Was an artifact: `iv_rank or 0.0` mapped "unknown" onto the LOWEST
    # possible vol, which reached the same answer for the wrong reason and
    # would have flipped silently had the threshold ever gone negative or the
    # comparison been inverted. Now a deliberate branch: a debit spread has
    # defined risk and no assignment exposure when the regime is unknown.
    assert _pick(None, "none") == "bear_put"
    assert _pick(None, "absolute") == "bear_put"
    # A basis the resolver never produces is treated as no reading, not as a
    # silent fall-through to the absolute threshold.
    assert _pick(80.0, "unrecognised") == "bear_put"


def test_zero_is_a_reading_not_a_missing_value():
    # 0 is a legitimate absolute IV and a legitimate percentile. The old
    # `iv_rank or 0.0` could not tell it from None; this must.
    assert _pick(0.0, "absolute", absolute=0.0) == "bear_call"
    assert _pick(0.0, "absolute", absolute=0.1) == "bear_put"
