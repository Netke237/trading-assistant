"""Tests for contract_validator — hard reject and soft rank."""
import pytest
from app.scoring.contract_validator import validate_contract


def _base_contract(**overrides):
    c = {
        "symbol": "AAPL",
        "strike": 185.0,
        "expiry": "2026-09-19",
        "is_call": True,
        "bid": 2.00,
        "ask": 2.10,
        "volume": 500,
        "open_interest": 2000,
        "delta": 0.45,
        "iv_rank": 30.0,
    }
    c.update(overrides)
    return c


def test_low_iv_rank_passes():
    card = validate_contract(_base_contract(iv_rank=30), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_iv_rank_at_threshold_passes():
    """IV rank exactly at the limit (70) should still pass."""
    card = validate_contract(_base_contract(iv_rank=70), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


# These two run on the DEFAULT basis, which is absolute — hence `iv_too_high`.
# The percentile-named reason is asserted by the ranked half of
# test_the_two_iv_override_keys_do_not_cross below (round 4 finding 10).
def test_iv_rank_above_threshold_hard_rejects():
    """IV rank > 70 must hard-reject — buying expensive premium is the worst options mistake."""
    card = validate_contract(_base_contract(iv_rank=71), stock_score=70)
    assert card.status == "REJECT"
    assert "iv_too_high" in card.reject_reasons


def test_iv_rank_very_high_hard_rejects():
    card = validate_contract(_base_contract(iv_rank=90), stock_score=70)
    assert card.status == "REJECT"
    assert "iv_too_high" in card.reject_reasons


def test_iv_rank_none_is_not_rejected():
    """Missing IV rank data must not hard-reject (data gap != bad contract)."""
    card = validate_contract(_base_contract(iv_rank=None), stock_score=70)
    assert "iv_rank_too_high" not in card.reject_reasons


def test_stock_score_below_options_floor_hard_rejects():
    """An underlying below 45 still fails the options floor."""
    card = validate_contract(_base_contract(), stock_score=44)
    assert card.status == "REJECT"
    assert "stock_score_below_threshold" in card.reject_reasons


def test_stock_score_at_threshold_passes():
    """The options floor is inclusive at 45."""
    card = validate_contract(_base_contract(), stock_score=45)
    assert "stock_score_below_threshold" not in card.reject_reasons


@pytest.mark.parametrize("stock_score", [45, 50, 54, 55])
def test_options_floor_is_independent_of_stock_pass_threshold(stock_score):
    from app.scoring.stock_scorer import _load_config

    thresholds = _load_config()["stock_score_thresholds"]
    assert thresholds["pass"] == 55
    assert thresholds["caution"] == 35
    card = validate_contract(_base_contract(), stock_score=stock_score)
    assert "stock_score_below_threshold" not in card.reject_reasons


def test_override_raises_max_iv_abs():
    """Caller can raise the ABSOLUTE ceiling to 80 via the overrides dict.

    `_base_contract` sets no `iv_basis`, so its `iv_rank` is read as an
    absolute IV -- which is what every pre-2026-09-06 caller was in fact
    passing. The override key that governs it is therefore `max_iv_abs`.
    """
    card = validate_contract(
        _base_contract(iv_rank=75),
        stock_score=70,
        overrides={"max_iv_abs": 80},
    )
    assert "iv_rank_too_high" not in card.reject_reasons


def test_override_raises_max_iv_rank_on_a_ranked_contract():
    """The percentile ceiling governs a contract whose figure IS a percentile."""
    card = validate_contract(
        _base_contract(iv_rank=75, iv_basis="rank"),
        stock_score=70,
        overrides={"max_iv_rank": 80},
    )
    assert "iv_rank_too_high" not in card.reject_reasons


def test_the_two_iv_override_keys_do_not_cross():
    """Raising one basis's ceiling must not loosen the other's.

    The keys name different quantities; a caller who means "allow a higher
    percentile" has said nothing about how expensive an absolute IV may be.
    """
    absolute = validate_contract(
        _base_contract(iv_rank=75),                  # basis defaults to absolute
        stock_score=70,
        overrides={"max_iv_rank": 80},               # wrong key for this basis
    )
    # ROUND 4 finding 10: the REASON is named by basis too, so an absolute IV
    # over max_iv_abs no longer reports under the percentile's name.
    assert "iv_too_high" in absolute.reject_reasons
    assert "iv_rank_too_high" not in absolute.reject_reasons

    ranked = validate_contract(
        _base_contract(iv_rank=75, iv_basis="rank"),
        stock_score=70,
        overrides={"max_iv_abs": 80},                # wrong key for this basis
    )
    assert "iv_rank_too_high" in ranked.reject_reasons


def test_override_lowers_min_stock_score():
    """Caller can override min_stock_score to relax the gate — mirrors
    frontend/e2e/tests/ws-f-full-flow.spec.ts's real-backend e2e run, which
    sends this override specifically so it can get candidates when live
    stock scores are below the default gate."""
    card = validate_contract(
        _base_contract(),
        stock_score=20,
        overrides={"min_stock_score": 20},
    )
    assert "stock_score_below_threshold" not in card.reject_reasons


def test_preferred_dte_min_intentionally_matches_hard_reject_floor():
    """contract_rules.yaml's soft_rank.preferred_dte_min is deliberately kept equal to
    hard_reject.min_dte (both 21 by default) — see the comment on that key and
    dte_window.py's widen_contract_overrides_for_dte(), which always widens both to the
    same value. This test exists so a future edit that spaces them apart (reintroducing a
    live below-window soft-penalty branch in _score_dte, and the double-penalty behavior
    dte_window.py was written to eliminate) is a deliberate, reviewed choice — not an
    accidental drift caught only by re-reading the YAML."""
    from app.scoring.contract_validator import _load_config
    cfg = _load_config()
    assert cfg["soft_rank"]["preferred_dte_min"] == cfg["hard_reject"]["min_dte"]


from datetime import date, timedelta


def _contract_with_expiry(days_out: int, **overrides):
    c = _base_contract(expiry=(date.today() + timedelta(days=days_out)).isoformat())
    c.update(overrides)
    return c


def test_dte_small_miss_below_window_scores_between_zero_and_old_flat_value():
    """Default preferred window is 21-60 (contract_rules.yaml). 20 DTE is 1 day
    short of d_min=21 -- half_range = (60-21)/2 = 19.5, so a 1-day miss should
    score just under the old flat 25, not exactly 25."""
    card = validate_contract(_contract_with_expiry(20), stock_score=70)
    assert 0 < card.breakdown.dte_score < 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_large_miss_below_window_floors_at_zero():
    """A miss at least half_range (19.5 -> 20 rounds via int()) days below d_min
    must floor at 0, not stay at the old flat 25."""
    card = validate_contract(_contract_with_expiry(1), stock_score=70)  # 20 days short of d_min=21
    assert card.breakdown.dte_score == 0
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_small_miss_above_window_scores_between_zero_and_old_flat_value():
    """61 DTE is 1 day past d_max=60."""
    card = validate_contract(_contract_with_expiry(61), stock_score=70)
    assert 0 < card.breakdown.dte_score < 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_large_miss_above_window_floors_at_zero():
    card = validate_contract(_contract_with_expiry(200), stock_score=70)  # 140 days past d_max=60
    assert card.breakdown.dte_score == 0
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_near_miss_scores_higher_than_far_miss():
    """The core complaint being fixed: a 1-day miss must no longer score
    identically to a 100+ day miss."""
    near = validate_contract(_contract_with_expiry(61), stock_score=70)
    far = validate_contract(_contract_with_expiry(200), stock_score=70)
    assert near.breakdown.dte_score > far.breakdown.dte_score


def test_dte_in_window_scoring_is_unchanged():
    """Centre of the default 21-60 window is 40.5 -> round to nearest int DTE;
    use 40 and 60 to lock in the existing in-window formula is untouched."""
    centre_ish = validate_contract(_contract_with_expiry(40), stock_score=70)
    edge = validate_contract(_contract_with_expiry(60), stock_score=70)
    assert centre_ish.breakdown.dte_score > edge.breakdown.dte_score
    assert edge.breakdown.dte_score == 0  # exact edge already scored 0 before this fix


def test_dte_collapsed_window_out_of_range_does_not_divide_by_zero():
    """A hold-derived override can collapse preferred_dte_min == preferred_dte_max
    (half_range == 0). The existing in-window guard only covers dte == that exact
    point; this covers the NEW out-of-window decay_span guard by picking a dte one
    day off the collapsed point, which must score cleanly instead of raising."""
    card = validate_contract(
        _contract_with_expiry(31),
        stock_score=70,
        overrides={"preferred_dte_min": 30, "preferred_dte_max": 30},
    )
    assert 0 <= card.breakdown.dte_score <= 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dal_style_near_miss_scores_in_window_once_preferred_band_is_widened():
    """Reproduces Kenneth's reported DAL case directly: Position horizon
    (90-105d hold -> ideal window 180-210), contract at 177 DTE (3 days short
    of the ideal floor). Once preferred_dte_min/max are widened by the same
    10-day tolerance as the hard-reject bounds, 177 falls INSIDE the widened
    170-220 preferred band (in-window taper), not in the out-of-window decay
    branch -- so it must no longer carry the dte_outside_preferred flag."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte

    overrides = widen_contract_overrides_for_dte({}, lo=180, hi=210, hold_max_days=105)
    card = validate_contract(_contract_with_expiry(177), stock_score=70, overrides=overrides)
    assert "dte_outside_preferred" not in card.soft_flags
    # centre=(170+220)/2=195, half_range=25 -> 100*(1-|177-195|/25) = 100*(1-18/25) = 28
    assert card.breakdown.dte_score == 28


def test_score_card_detail_has_all_five_metrics():
    contract = _contract_with_expiry(
        35, bid=2.40, ask=2.50, delta=0.45, volume=500, open_interest=2000, iv_rank=40,
    )
    card = validate_contract(contract, stock_score=70)
    assert set(card.detail.keys()) == {"dte", "delta", "iv_rank", "liquidity", "spread"}
    assert card.detail["dte"]["dte"] == 35
    assert card.detail["delta"]["delta"] == pytest.approx(0.45)
    assert card.detail["iv_rank"]["iv_rank"] == 40
    assert card.detail["liquidity"]["volume"] == 500
    assert card.detail["liquidity"]["open_interest"] == 2000
    assert card.detail["spread"]["spread_pct"] == pytest.approx((2.50 - 2.40) / 2.45, rel=1e-3)


def test_score_card_detail_present_even_on_hard_reject():
    contract = _contract_with_expiry(
        1, bid=2.40, ask=2.50, delta=0.45, volume=500, open_interest=2000, iv_rank=40,
    )
    card = validate_contract(contract, stock_score=70)
    assert card.status == "REJECT"
    assert "dte" in card.detail  # detail is computed before the reject branch, not skipped


def test_hard_reject_delta_band_reads_from_config():
    from app.scoring.contract_validator import hard_reject_delta_band
    assert hard_reject_delta_band() == (0.20, 0.85)


# ── NO-LIVE-QUOTE (plan 3b, test T6): quote_mode ─────────────────────────────
#
# A chain row whose quote is not live (quoteLive False: market closed, stale,
# one-sided) is hard-rejected by default -- the scan's mode -- and only
# labelled, capped at CAUTION, in Step 6 / the Watchlist ("label").

def _live_pass_contract(**overrides):
    """A contract that grades PASS when its quote is live (score 69)."""
    return _contract_with_expiry(35, bid=2.40, ask=2.50, iv_rank=30, **overrides)


def _not_live(contract, state="session_closed"):
    return {**contract, "quoteLive": False, "quoteState": state}


def test_quote_mode_defaults_to_reject():
    """Relies on the DEFAULT (r0 finding 18): no quote_mode is passed, so a new
    caller that forgets it gets the safe behaviour, a hard reject."""
    card = validate_contract(_not_live(_live_pass_contract()), stock_score=70)
    assert card.status == "REJECT"
    assert card.score == 0
    assert card.reject_reasons == ["no_live_quote"]


def test_quote_mode_default_in_the_signature_is_reject():
    import inspect
    assert inspect.signature(validate_contract).parameters["quote_mode"].default == "reject"


def test_reject_mode_short_circuits_to_exactly_no_live_quote():
    """Every other hard rule this row breaks (volume, DTE, delta, stock score,
    too many soft failures) is NOT evaluated: the reasons are exactly
    ["no_live_quote"], with one blocker entry for it."""
    bad = _not_live(
        _contract_with_expiry(1, bid=2.40, ask=2.50, volume=1, open_interest=1,
                              delta=0.05, iv_rank=95),
        state="stale",
    )
    card = validate_contract(bad, stock_score=10, quote_mode="reject")
    assert card.status == "REJECT"
    assert card.reject_reasons == ["no_live_quote"]
    blockers = card.explanation["blockers"]
    assert blockers == [{
        "code": "no_live_quote",
        "label": "No live quote",
        "metric": "quote_state",
        "observed": "stale",
        "threshold": "live",
        "operator": "!=",
    }]
    assert card.explanation["reject_reasons"] == ["no_live_quote"]
    assert card.explanation["outcome"] == "blocked"
    # The soft scores are still computed so the breakdown renders.
    assert set(card.detail) == {"dte", "delta", "iv_rank", "liquidity", "spread"}
    assert card.breakdown.spread_score > 0
    assert card.breakdown.dte_score == 0
    assert "no_live_quote" not in card.soft_flags
    # The explanation builds on the wire model.
    from app.schemas import ContractExplanation
    ContractExplanation.model_validate(card.explanation)


def test_label_mode_caps_pass_at_caution_and_flags_the_card():
    live = validate_contract(_live_pass_contract(), stock_score=70, quote_mode="label")
    assert live.status == "PASS"
    assert live.no_live_quote is False and live.quote_state is None

    card = validate_contract(_not_live(_live_pass_contract()), stock_score=70, quote_mode="label")
    assert card.status == "CAUTION"
    assert card.score == live.score          # graded exactly as the live row
    assert card.reject_reasons == []
    assert "no_live_quote" in card.soft_flags
    assert card.no_live_quote is True
    assert card.quote_state == "session_closed"
    assert card.explanation["status"] == "CAUTION"
    assert card.explanation["soft_fail_count"] == live.explanation["soft_fail_count"]


def test_label_mode_flag_does_not_count_as_a_soft_failure():
    """Two real soft flags plus the label must not reach max_soft_fail_count
    (3) and turn into too_many_soft_failures: the label changes no grade.
    Thin liquidity is ONE flag (volume and OI together), so the second real
    miss is an IV just above the Preferred ceiling (56 > 55); the live card
    scores 48, CAUTION. (A delta of 0.25 or a spread just above 8% would
    each sink it below caution 45.)"""
    thin = {**_live_pass_contract(volume=100, open_interest=500), "iv_rank": 56}
    live = validate_contract(thin, stock_score=70, quote_mode="label")
    assert live.status == "CAUTION"
    assert live.soft_flags == ["thin_liquidity", "iv_rank_elevated"]
    card = validate_contract(_not_live(thin), stock_score=70, quote_mode="label")
    assert card.status == "CAUTION"
    assert card.reject_reasons == []
    assert card.score == live.score


def test_label_mode_still_applies_every_other_hard_rule():
    # min_volume defaults to 0 (off); an explicit floor keeps volume_too_low
    # the hard rule exercised here.
    card = validate_contract(
        _not_live(_live_pass_contract(volume=1)), stock_score=70, quote_mode="label",
        overrides={"min_volume": 50},
    )
    assert card.status == "REJECT"
    assert "volume_too_low" in card.reject_reasons
    assert "no_live_quote" not in card.reject_reasons
    assert card.no_live_quote is True


def test_label_mode_one_sided_row_still_rejects_as_spread_too_wide():
    """A no-bid row as the chain builder emits it (price = ask/2, spread = ask)
    through _augment, as Step 6 grades it: rejected on its own spread, as
    before NO-LIVE-QUOTE."""
    from app.data.augment import _augment
    row = {
        "symbol": "AAPL", "strike": 200, "right": "C", "dte": 35,
        "expiry": (date.today() + timedelta(days=35)).isoformat(),
        "price": 0.2, "spread": 0.41, "delta": 0.45, "volume": 500,
        "open_interest": 2000, "iv": 30.0,
        "quoteState": "one_sided", "quoteLive": False, "quoteAgeS": 4.0,
    }
    card = validate_contract(_augment(row, stock_price=190.0), stock_score=70, quote_mode="label")
    assert card.status == "REJECT"
    assert "spread_too_wide" in card.reject_reasons
    assert "no_live_quote" not in card.reject_reasons
    assert card.quote_state == "one_sided"


@pytest.mark.parametrize("mode", ["reject", "label"])
def test_missing_or_true_quote_live_reads_as_live(mode):
    for c in (_live_pass_contract(),
              {**_live_pass_contract(), "quoteLive": True, "quoteState": "live"},
              {**_live_pass_contract(), "quoteLive": None}):
        card = validate_contract(c, stock_score=70, quote_mode=mode)
        assert card.status == "PASS", c
        assert card.no_live_quote is False and card.quote_state is None
        assert "no_live_quote" not in card.soft_flags


def test_unknown_quote_mode_is_refused():
    with pytest.raises(ValueError):
        validate_contract(_live_pass_contract(), stock_score=70, quote_mode="ignore")


# ── CONTRACT-LIQUIDITY-DTE (fixes 1 + 2) ─────────────────────────────────────
#
# Fix 1: hard_reject.min_volume defaults to 0 (an optional hard floor, off by
# default; FR-25 treats volume as soft). The zero-volume exemption is kept for
# an explicit floor above 0. Fix 2: volume and open interest below their
# Preferred floors raise ONE soft flag, thin_liquidity, so a long-dated
# contract no longer spends two of its max_soft_fail_count (3) slots on one axis.
# Every case is _contract_with_expiry(40, ...): bid 2.00 / ask 2.10, delta
# 0.45, iv_rank 30 (absolute), vol 500, OI 2,000 -- no soft flag of its own.

def _liq_contract(**overrides):
    return _contract_with_expiry(40, **overrides)


def test_aapl_315c_shape_is_not_rejected_at_the_default_config():
    """The case that opened the phase: vol 3, OI 1,534, a 1.2% spread. Today's
    floor of 50 rejected it while a vol-0 / OI-319 contract passed."""
    card = validate_contract(
        _liq_contract(volume=3, open_interest=1534, bid=2.00, ask=2.025), stock_score=70,
    )
    assert card.reject_reasons == []
    assert card.soft_flags == ["thin_liquidity"]


def test_zero_and_small_volume_grade_alike_at_the_default_floor():
    """Scores are not compared: int(3 / 200 * 60) == 0, the same as volume 0."""
    zero = validate_contract(_liq_contract(volume=0), stock_score=70)
    three = validate_contract(_liq_contract(volume=3), stock_score=70)
    assert zero.reject_reasons == three.reject_reasons == []
    assert zero.soft_flags == three.soft_flags == ["thin_liquidity"]


def test_explicit_volume_floor_still_rejects_small_nonzero_volume():
    card = validate_contract(_liq_contract(volume=3), stock_score=70,
                             overrides={"min_volume": 50})
    assert card.reject_reasons == ["volume_too_low"]
    assert card.soft_flags == ["thin_liquidity"]


@pytest.mark.parametrize("oi", [200, 2000])
def test_explicit_volume_floor_keeps_the_zero_volume_exemption(oi):
    """For a user who opts into a floor, volume 0 with OI >= min_open_interest
    still passes the volume rule (recorded residual)."""
    card = validate_contract(_liq_contract(volume=0, open_interest=oi), stock_score=70,
                             overrides={"min_volume": 50})
    assert card.reject_reasons == []
    assert card.soft_flags == ["thin_liquidity"]


def test_explicit_volume_floor_exemption_needs_adequate_open_interest():
    """Kills a mutant that drops the exemption's OI clause."""
    card = validate_contract(_liq_contract(volume=0, open_interest=150), stock_score=70,
                             overrides={"min_volume": 50})
    assert card.reject_reasons == ["volume_too_low", "open_interest_too_low"]
    assert card.soft_flags == ["thin_liquidity"]


@pytest.mark.parametrize("volume", [0, 3, 500])
def test_open_interest_floor_is_still_a_hard_reject(volume):
    card = validate_contract(_liq_contract(volume=volume, open_interest=150), stock_score=70)
    assert card.reject_reasons == ["open_interest_too_low"]
    assert card.soft_flags == ["thin_liquidity"]


@pytest.mark.parametrize(("volume", "oi", "expected"), [
    (100, 500, ["thin_liquidity"]),    # both below their Preferred floors (200 / 1000)
    (100, 2000, ["thin_liquidity"]),   # volume only
    (500, 500, ["thin_liquidity"]),    # open interest only
    (500, 2000, []),                   # neither
])
def test_thin_liquidity_is_raised_at_most_once(volume, oi, expected):
    card = validate_contract(_liq_contract(volume=volume, open_interest=oi), stock_score=70)
    assert card.soft_flags == expected
    assert card.explanation["components"]["liquidity"]["flags"] == expected
    assert "low_volume" not in card.soft_flags
    assert "low_open_interest" not in card.soft_flags


def test_one_liquidity_axis_costs_one_soft_failure_slot():
    """Thin on both volume and OI plus an elevated spread is two soft misses,
    not three. Reasons only, never status: the weighted score is 43.8, below
    caution 45, on this code."""
    two = validate_contract(
        _liq_contract(volume=100, open_interest=500, bid=2.00, ask=2.25), stock_score=70,
    )  # spread 0.25 / 2.125 = 11.8%, inside (8%, 20%)
    assert two.soft_flags == ["thin_liquidity", "spread_elevated"]
    assert two.reject_reasons == []
    three = validate_contract(
        _liq_contract(volume=100, open_interest=500, bid=2.00, ask=2.25, delta=0.25),
        stock_score=70,
    )
    assert three.soft_flags == ["thin_liquidity", "spread_elevated", "delta_outside_preferred"]
    assert "too_many_soft_failures" in three.reject_reasons


def test_merged_flag_leaves_the_liquidity_score_unchanged():
    """Volume and OI still each weigh half: (int(100/200*60) + int(500/1000*60)) // 2."""
    card = validate_contract(_liq_contract(volume=100, open_interest=500), stock_score=70)
    assert card.breakdown.liquidity_score == 30
