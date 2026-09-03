"""The repricing horizon — resolve_reprice_days().

Spec: docs/superpowers/plans/2026-09-02-barrier-race-spec.md section 2.2 (Q2,
tests 14-16).

"How far ahead do we reprice an option when we ask what it is worth AT a
barrier." Before this module, two call sites each hardcoded
`max(expiry_years * 0.5, 7/365)` — a fixed half-life that ignores both how long
the user intends to hold and what the simulation itself observed.
"""
import pytest

from app.scoring.reprice_horizon import remaining_years_at_barrier, resolve_reprice_days
from app.services.config_loader import load_reprice_horizon_cfg

# Every key HORIZON_PRESETS (frontend/lib/horizonPresets.ts) can send us.
_ALL_PRESETS = ["Intraday", "Swing", "Position", "Quarterly", "SemiAnnual", "Annual", "Custom"]


def test_the_yaml_block_exists_and_carries_all_six_table_presets():
    """Custom is deliberately absent from the table — it derives instead."""
    cfg = load_reprice_horizon_cfg()
    assert cfg["source"] == "simulation_median"
    assert set(cfg["fallback_days"]) == {
        "Intraday", "Swing", "Position", "Quarterly", "SemiAnnual", "Annual",
    }
    assert cfg["clamp"]["min_days"] >= 1
    assert 0 < cfg["clamp"]["max_fraction_of_dte"] <= 1


# -- 14. All seven presets resolve --------------------------------------------

def test_every_preset_resolves_to_a_positive_number_of_days():
    for preset in _ALL_PRESETS:
        days = resolve_reprice_days(preset, 30, 35, dte=365, sim_median=None)
        assert days > 0, f"{preset} resolved to {days}"


def test_the_table_is_keyed_on_the_holding_preset_not_the_scoring_horizon():
    """scoringHorizonForHold collapses Quarterly/SemiAnnual/Annual into
    "Position". Keying the fallback on that would give a 200-day hold and a
    20-day hold the same repricing time. This is the assertion that stops
    someone from "simplifying" it back."""
    dte = 3650   # long enough that the DTE clamp never binds
    position = resolve_reprice_days("Position", None, None, dte=dte, sim_median=None)
    quarterly = resolve_reprice_days("Quarterly", None, None, dte=dte, sim_median=None)
    semi = resolve_reprice_days("SemiAnnual", None, None, dte=dte, sim_median=None)
    annual = resolve_reprice_days("Annual", None, None, dte=dte, sim_median=None)
    assert position < quarterly < semi < annual


def test_custom_derives_from_the_typed_range_rather_than_snapping_to_a_preset():
    """A manual 30-35 day range sits between Position (14d) and Quarterly (25d),
    and either snap moves the repriced loss by real money. Derive instead —
    scoringHorizonForHold already sets that precedent."""
    days = resolve_reprice_days("Custom", 30, 35, dte=365, sim_median=None)
    assert days == pytest.approx(((30 + 35) / 2) * 0.50)

    # A different typed range gives a different answer; a snap would not.
    wider = resolve_reprice_days("Custom", 90, 110, dte=365, sim_median=None)
    assert wider == pytest.approx(((90 + 110) / 2) * 0.50)
    assert wider != days


def test_an_unknown_preset_falls_back_to_swing():
    """presetByKey() falls back to HORIZON_PRESETS[1], which is Swing. Match it
    rather than crashing on a payload from an older client."""
    swing = resolve_reprice_days("Swing", None, None, dte=365, sim_median=None)
    assert resolve_reprice_days(None, None, None, dte=365, sim_median=None) == swing
    assert resolve_reprice_days("NotAPreset", None, None, dte=365, sim_median=None) == swing


# -- 15. The DTE clamp binds --------------------------------------------------

def test_max_fraction_of_dte_binds_for_annual_on_a_short_contract():
    """Not decoration. Without it, Annual (80d) on a 30-day contract reprices at
    80 days — past expiry — and every level silently prices at intrinsic value
    only, which quietly deletes all the time value from the risk leg."""
    dte = 30
    days = resolve_reprice_days("Annual", None, None, dte=dte, sim_median=None)
    assert days == pytest.approx(0.75 * dte)
    assert days < 80

    # It does NOT clamp a simulation median. That ceiling protects the fallback
    # from a holding-period table that knows nothing about this contract; a
    # simulated median is a day index inside the simulation and cannot exceed
    # the contract's life. Clamping it overrode an observed 26d with 22.5d on
    # the reference contract, valuing the option at the stop as if 7.5 days of
    # life were left instead of 4 — risk understated ~3.5% and R:R overstated
    # ~3.6%, always flattering, on the number the card bolds as THE measurement,
    # while the card printed "median ~26d" a few lines above "repriced at 22.5d".
    observed = resolve_reprice_days("Swing", None, None, dte=dte, sim_median=29.0)
    assert observed == pytest.approx(29.0)


def test_min_days_floors_the_result_but_the_dte_ceiling_outranks_it():
    """min_days stops an absurdly short horizon; max_fraction_of_dte stops one
    that lands at or past expiry. When they conflict the CEILING wins.

    On a 1-day contract 0.75 x dte is 0.75 of a day and min_days is 1. Letting
    the floor win puts the barrier exactly AT expiry, so
    remaining_years_at_barrier returns its floor and every level prices at
    intrinsic value only — precisely what max_fraction_of_dte exists to
    prevent."""
    assert resolve_reprice_days("Intraday", None, None, dte=1, sim_median=None) == 0.75
    # The floor applies to a simulated median too — but only where it does not
    # push the barrier past the half-day-before-expiry cap (see below).
    assert resolve_reprice_days("Swing", None, None, dte=30, sim_median=0.1) == 1.0
    assert resolve_reprice_days("Swing", None, None, dte=1, sim_median=0.1) == 0.5


def test_a_simulated_median_is_capped_half_a_day_short_of_expiry():
    """A simulated median cannot EXCEED the contract's life but can EQUAL it —
    the median is a day index plus one, so it ranges 1..dte. At dte exactly, the
    remaining life collapses to remaining_years_at_barrier's floor and every
    level prices at intrinsic value only: the risk leg becomes the whole premium
    and rr_stock_stop collapses to exactly the typed target percentage, which is
    the greyed constant it is printed beside.

    THE CEILING MUST WIN OVER min_days HERE. Written as
    `max(min_days, min(median, dte - 0.5))` the floor won at dte=1 — and dte=1
    is where a simulated median is ALWAYS exactly 1.0, so the cap did nothing on
    precisely the contracts it existed for. Deleting the cap entirely used to
    leave all 68 tests green."""
    assert resolve_reprice_days("Swing", None, None, dte=10, sim_median=10.0) == 9.5
    assert resolve_reprice_days("Swing", None, None, dte=2, sim_median=2.0) == 1.5
    # dte=1: the floor would say 1.0, which is expiry. The cap outranks it.
    assert resolve_reprice_days("Swing", None, None, dte=1, sim_median=1.0) == 0.5
    # A sub-1-day contract still leaves life to price with. A flat "dte - 0.5"
    # floored at 0.5 returns 0.5 on a 0.4-day contract — at or past expiry,
    # which is what this cap exists to prevent, reached from the other side.
    assert resolve_reprice_days("Swing", None, None, dte=0.4, sim_median=1.0) < 0.4

    # And the remaining life it implies is always genuinely positive — including
    # for the sub-1-day DTEs the loop used to skip, which is where the fixture
    # was incapable of exhibiting the failure this assertion guards.
    for dte in (0.4, 0.75, 1, 2, 3, 10, 30):
        days = resolve_reprice_days("Swing", None, None, dte=dte, sim_median=float(dte))
        assert remaining_years_at_barrier(dte, days) * 365 > 0.0
        if dte >= 1:
            assert remaining_years_at_barrier(dte, days) * 365 >= 0.5


def test_custom_with_no_typed_range_falls_back_rather_than_deriving_from_zero():
    """"Custom" with nothing typed carries no information. Deriving from a 0-0
    range returned 0 days, then the floor, so 1 — a made-up answer dressed as a
    derived one, and a 1-day reprice horizon with no signal to the user."""
    assert resolve_reprice_days("Custom", None, None, dte=60, sim_median=None) == 7.0
    # One end typed is still information: use it for both.
    assert resolve_reprice_days("Custom", 30.0, None, dte=180, sim_median=None) == 15.0
    assert resolve_reprice_days("Custom", None, 30.0, dte=180, sim_median=None) == 15.0


def test_remaining_years_at_barrier_inverts_elapsed_days_not_theta():
    """THE BUG THIS PINS: resolve_reprice_days returns days ELAPSED to a
    barrier; bs_price wants the life REMAINING at that moment. Feeding the
    former in as the latter inverts theta — the later a stop is reached, the
    MORE the contract appears to be worth at it, which understates risk on
    exactly the fast stop-outs that hurt most."""
    early = remaining_years_at_barrier(60, 2)
    late = remaining_years_at_barrier(60, 45)
    assert early > late, "a barrier reached sooner must leave MORE life, not less"
    assert early == pytest.approx(58 / 365.0)
    assert late == pytest.approx(15 / 365.0)
    # Never negative, never zero: bs_price's T <= 0 branch returns 0.0 flat.
    assert remaining_years_at_barrier(30, 30) > 0
    assert remaining_years_at_barrier(30, 999) > 0
    # Unusable inputs collapse to the floor rather than raising.
    assert remaining_years_at_barrier(float("nan"), 7) > 0


def test_an_unknown_dte_does_not_collapse_the_answer_to_the_floor():
    """dte <= 0 or non-finite means "unknown", not "expires immediately".
    Collapsing to min_days there would be a worse answer than the preset's."""
    assert resolve_reprice_days("Position", None, None, dte=0, sim_median=None) == 14.0
    assert resolve_reprice_days("Position", None, None, dte=float("nan"), sim_median=None) == 14.0


# -- 16. The simulation wins when it has something to say ---------------------

def test_the_simulation_median_beats_the_fallback_table():
    """It is the best available estimate of WHEN the barrier gets hit, measured
    on the same paths that decided WHETHER it does."""
    observed = resolve_reprice_days("Swing", None, None, dte=365, sim_median=19.0)
    assert observed == pytest.approx(19.0)

    fallback = resolve_reprice_days("Swing", None, None, dte=365, sim_median=None)
    assert fallback == pytest.approx(7.0)
    assert observed != fallback


def test_a_non_finite_simulation_median_is_treated_as_absent():
    for bad in (None, float("nan"), float("inf")):
        assert resolve_reprice_days("Swing", None, None, dte=365, sim_median=bad) == pytest.approx(7.0)
