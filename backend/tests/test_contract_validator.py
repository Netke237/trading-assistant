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


def test_caution_tier_stock_score_hard_rejects():
    """A CAUTION-tier stock score (35-54, below the documented >=55 gate but
    above the separate REJECT-status cutoff elsewhere) must reject here —
    previously this parameter was accepted but never checked."""
    card = validate_contract(_base_contract(), stock_score=45)
    assert card.status == "REJECT"
    assert "stock_score_below_threshold" in card.reject_reasons


def test_stock_score_at_threshold_passes():
    """stock_score exactly at the gate (55, matching scoring_rules.yaml's stock
    `pass` bar) should not be rejected on this basis."""
    card = validate_contract(_base_contract(), stock_score=55)
    assert "stock_score_below_threshold" not in card.reject_reasons


def test_stock_score_just_below_new_threshold_rejects():
    """stock_score=50 passed under the old 50-point gate; after raising
    min_stock_score to 55 (matching the stock pass bar), a CAUTION-grade
    underlying (35-54) no longer qualifies for an options recommendation."""
    card = validate_contract(_base_contract(), stock_score=50)
    assert card.status == "REJECT"
    assert "stock_score_below_threshold" in card.reject_reasons


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


# ── CONTRACT-LIQUIDITY-DTE: volume is soft by default, one liquidity flag ─────
# Fix 1: hard_reject.min_volume defaults to 0 (off) -- PRD FR-25 lists volume
# as a SOFT rule. An explicit floor above 0 still rejects, and still exempts
# volume 0 when OI clears min_open_interest. Fix 2: volume and OI below
# preference raise ONE soft flag, thin_liquidity, instead of low_volume +
# low_open_interest. Every test starts from _contract_with_expiry(40) (4.9%
# spread, delta 0.45, absolute IV 30, vol 500, OI 2000), overrides only the
# fields it is about, and asserts the EXACT soft_flags list.

def _liq(**overrides):
    return _contract_with_expiry(40, **overrides)


def test_aapl_315c_liquidity_shape_passes_hard_gates_at_default_config():
    """vol 3 / OI 1,534 / spread 1.2% (AAPL 315C 2027-04-16, 2026-09-30) was
    a volume_too_low hard reject at the old default of 50 while vol 0 / OI 319
    passed. At the default floor (0 = off) it clears every hard gate."""
    card = validate_contract(
        _liq(volume=3, open_interest=1534, bid=2.00, ask=2.025), stock_score=70,
    )
    assert card.reject_reasons == []
    assert card.soft_flags == ["thin_liquidity"]


def test_zero_and_small_volume_grade_identically_at_default_floor():
    """The inconsistency fix 1 removes: vol 0 and vol 3 differ only in the
    volume figure, so at the default floor they get the same hard reasons and
    the same soft flags. Scores are not compared -- int(3/200*60) == 0 makes
    them equal only by truncation."""
    card_0 = validate_contract(_liq(volume=0, open_interest=1534), stock_score=70)
    card_3 = validate_contract(_liq(volume=3, open_interest=1534), stock_score=70)
    assert card_0.reject_reasons == card_3.reject_reasons == []
    assert card_0.soft_flags == card_3.soft_flags == ["thin_liquidity"]


def test_explicit_min_volume_floor_rejects_small_volume():
    card = validate_contract(
        _liq(volume=3, open_interest=1534), stock_score=70, overrides={"min_volume": 50},
    )
    assert card.reject_reasons == ["volume_too_low"]


def test_explicit_min_volume_floor_keeps_zero_volume_exemption():
    """Volume 0 with OI >= min_open_interest stays exempt under an explicit
    floor: before the open Tradier reports 0 and, without a live-quote signal
    (phase NO-LIVE-QUOTE), that cannot be told apart from no trades."""
    card = validate_contract(
        _liq(volume=0, open_interest=1534), stock_score=70, overrides={"min_volume": 50},
    )
    assert "volume_too_low" not in card.reject_reasons
    assert card.reject_reasons == []


def test_zero_volume_exemption_keeps_its_oi_clause():
    """The exemption is 'volume 0 AND OI adequate'. With OI 150 (< 200) an
    explicit floor rejects on both axes -- kills a mutant that drops the OI
    clause from the exemption."""
    card = validate_contract(
        _liq(volume=0, open_interest=150), stock_score=70, overrides={"min_volume": 50},
    )
    assert "volume_too_low" in card.reject_reasons
    assert "open_interest_too_low" in card.reject_reasons


@pytest.mark.parametrize("volume", [0, 3, 500])
def test_open_interest_floor_still_hard_rejects(volume):
    """min_open_interest (200) stays a liquidity hard gate whatever the volume."""
    card = validate_contract(_liq(volume=volume, open_interest=150), stock_score=70)
    assert "open_interest_too_low" in card.reject_reasons
    assert "volume_too_low" not in card.reject_reasons


@pytest.mark.parametrize("volume,oi", [
    (100, 500),   # both below preference (200 / 1000)
    (100, 2000),  # only volume below preference
    (500, 500),   # only OI below preference
])
def test_thin_liquidity_raised_exactly_once(volume, oi):
    card = validate_contract(_liq(volume=volume, open_interest=oi), stock_score=70)
    assert card.soft_flags == ["thin_liquidity"]
    assert "low_volume" not in card.soft_flags
    assert "low_open_interest" not in card.soft_flags


@pytest.mark.parametrize("volume,oi", [(200, 1000), (500, 2000)])
def test_no_liquidity_flag_at_or_above_preference(volume, oi):
    card = validate_contract(_liq(volume=volume, open_interest=oi), stock_score=70)
    assert card.soft_flags == []


def test_thin_liquidity_costs_one_soft_slot():
    """vol 100 (< 200) AND OI 500 (in [200, 1000)): both liquidity
    sub-conditions below preference, one slot. With an elevated spread
    (~9.5%, in (8%, 20%)) that is two flags, under max_soft_fail_count 3.
    Only reject_reasons is asserted: this contract's weighted score is 44,
    below caution 45, so its status is REJECT by score with no reasons."""
    card = validate_contract(
        _liq(volume=100, open_interest=500, bid=1.00, ask=1.10), stock_score=70,
    )
    assert card.soft_flags == ["thin_liquidity", "spread_elevated"]
    assert card.reject_reasons == []


def test_thin_liquidity_plus_two_more_flags_hits_soft_fail_cap():
    card = validate_contract(
        _liq(volume=100, open_interest=500, bid=1.00, ask=1.10, delta=0.25), stock_score=70,
    )
    assert card.soft_flags == ["thin_liquidity", "spread_elevated", "delta_outside_preferred"]
    assert "too_many_soft_failures" in card.reject_reasons


def test_liquidity_score_arithmetic_unchanged():
    """vol 100 / OI 500 against 200 / 1000: int(100/200*60)=30 and
    int(500/1000*60)=30, averaged -> 30. Fix 2 merges flags only; this pins
    the score so a change to the arithmetic cannot ride along."""
    card = validate_contract(_liq(volume=100, open_interest=500), stock_score=70)
    assert card.breakdown.liquidity_score == 30
