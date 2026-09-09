"""The Monte Carlo card and the Fixed % Ladder must reprice at the SAME horizon.

Both cards sit on one TradeCard, a few inches apart, and both answer "what is
this contract worth at that level". Before this suite existed they answered it
differently: Stage 1 of ``estimate_first_passage`` had moved to the resolved
holding horizon while ``build_trade_plan``'s ladder still back-solved at
``expiry_years * 0.5``, and a caution note under the ladder admitted the gap in
prose. Wiring the ladder to the same horizon is only half the fix — the other
half is pinning it, because the failure mode is silent: two numbers that drift
apart still render, still look plausible, and nothing throws.

The specific trap these tests exist for is the VOCABULARY. ``resolve_reprice_days``
looks the preset up in a dict keyed by exact string and, on a miss, falls through
to Swing's 7 days WITHOUT complaint. So a path that sends "Position" where the
other sends "Quarterly" does not error — it silently reprices 25 days apart, and
removing the caution note would leave nothing at all to say so. That is strictly
worse than the disagreement it replaced, which is why the equality is asserted
per preset rather than on one happy-path example.
"""
import pytest

from app.models.black_scholes import bs_iv
from app.scoring.first_passage import (
    _solve_target_stock_price,
    estimate_first_passage,
)
from app.scoring.reprice_horizon import display_reprice_years
from app.scoring.trade_plan import build_trade_plan


# Every key frontend/lib/horizonPresets.ts HORIZON_PRESETS can produce, plus the
# two "not a key" cases that must resolve rather than raise.
ALL_PRESETS = [
    "Intraday", "Swing", "Position", "Quarterly", "SemiAnnual", "Annual",
    "Custom",
    None,          # absent — both endpoints document this as "Swing"
    "swing",       # wrong case: a real spelling mismatch, must not 500
    "Position (15–45d)",   # the DISPLAY string, a plausible wiring mistake
]

RR_CFG = {
    "bullish_target_pct": 0.05,
    "bearish_target_pct": 0.05,
    "bullish_invalidation_pct": 0.03,
    "bearish_invalidation_pct": 0.03,
    "premium_stop_pct": 0.60,
}


def _plan(preset, dte=30, hold_min=15.0, hold_max=45.0):
    return build_trade_plan(
        direction="Bullish",
        stock_price=185.0,
        strike=190.0,
        dte=dte,
        premium=5.20,
        entry_bid=5.10,
        entry_ask=5.30,
        entry_mid=5.20,
        rr_cfg=RR_CFG,
        # Piece 3: the stop is received, not derived. These tests are about the
        # repricing HORIZON, which the stop plays no part in -- a fixed level
        # keeps them measuring only what they claim to.
        final_stop_price=179.45,
        horizon_preset=preset,
        hold_min=hold_min,
        hold_max=hold_max,
    )


@pytest.mark.parametrize("preset", ALL_PRESETS)
@pytest.mark.parametrize("dte", [1, 7, 30, 120, 365])
def test_ladder_reprices_at_the_shared_resolved_horizon(preset, dte):
    """build_trade_plan's horizon IS display_reprice_years', for every preset."""
    plan = _plan(preset, dte=dte)
    assert plan.reprice_years == display_reprice_years(preset, 15.0, 45.0, float(dte))


@pytest.mark.parametrize("preset", ALL_PRESETS)
def test_stage_one_and_the_ladder_resolve_the_same_horizon(preset):
    """The two cards, same inputs, same number — the whole point of the change.

    Stage 1 does not return its horizon, so this reconstructs the back-solve it
    must have done: at the shared horizon, the target stock price it reports has
    to be the one that prices the contract at the target option price. Both call
    sites route through ``display_reprice_years``; if either inlines its own
    composition again (which is how they diverged the first time), or reverts to
    the preset-blind half-expiry, these prices stop matching.
    """
    dte, stock, strike, premium = 30, 185.0, 190.0, 5.20
    expected = display_reprice_years(preset, 15.0, 45.0, float(dte))
    assert _plan(preset, dte=dte).reprice_years == expected

    est = estimate_first_passage(
        stock_price=stock,
        strike=strike,
        dte=dte,
        premium=premium,
        delta=0.45,
        is_call=True,
        trend_score=60.0,
        invalidation_price=179.45,
        candles=[],
        t1_pct=0.30, t2_pct=0.60, t3_pct=1.00,
        n_paths=200,
        seed=7,
        horizon_preset=preset,
        hold_min=15.0,
        hold_max=45.0,
    )

    sigma_iv = bs_iv(premium, stock, strike, dte / 365.0, 0.05, True)
    assert sigma_iv is not None, "fixture contract must have a solvable IV"

    for t in est.targets:
        assert t.stock_price == _solve_target_stock_price(
            stock, strike, expected, 0.05, sigma_iv, True, t.option_price,
        ), f"Stage 1 did not back-solve at {expected} for preset {preset!r}"


def test_scoring_horizon_is_not_the_repricing_horizon():
    """Quarterly/SemiAnnual/Annual all SCORE as "Position" and must not reprice as it.

    This is the mismatch the frontend actually had: /scan carried
    presetByKey(...).scoringHorizon (three values) while /first-passage carried
    the preset key (seven). Feeding the scoring horizon into the ladder would
    have given a 200-day hold and a 20-day hold the same repricing time — the
    exact thing risk_rules.yaml's comment warns about — and the equality tests
    above would still have passed, because both sides would have been equally
    wrong. So assert the values are genuinely distinct.
    """
    dte = 365
    years = {p: _plan(p, dte=dte).reprice_years
             for p in ("Position", "Quarterly", "SemiAnnual", "Annual")}
    assert len(set(years.values())) == 4, years
    # Longer holds reprice further out, so LESS life remains at the barrier.
    assert years["Position"] > years["Quarterly"] > years["SemiAnnual"] > years["Annual"]


def test_the_ladder_actually_moved_off_half_expiry():
    """A regression guard with teeth: half-expiry is preset-blind, so if the
    wiring is ever dropped, Swing and Annual produce identical target prices."""
    dte = 365
    swing = _plan("Swing", dte=dte)
    annual = _plan("Annual", dte=dte)

    assert swing.reprice_years != annual.reprice_years
    swing_targets = [t.estimatedOptionPrice for t in swing.targets]
    annual_targets = [t.estimatedOptionPrice for t in annual.targets]
    assert swing_targets != annual_targets, (
        "Swing and Annual priced identically — the ladder is back on the "
        "preset-blind expiry_years * 0.5 half-life."
    )
    # Half-expiry on a 365-DTE contract is 182.5 days remaining. Neither preset
    # should now land anywhere near it.
    assert abs(swing.reprice_years - 0.5) > 0.1
    assert abs(annual.reprice_years - 0.5) > 0.1


def test_custom_derives_from_the_typed_range_on_both_paths():
    """"Custom" has no table row. If hold_min/hold_max reach one card and not
    the other, they diverge exactly as a spelling mismatch would."""
    narrow = _plan("Custom", dte=365, hold_min=5.0, hold_max=15.0)
    wide = _plan("Custom", dte=365, hold_min=90.0, hold_max=110.0)
    assert narrow.reprice_years > wide.reprice_years
    assert narrow.reprice_years == display_reprice_years("Custom", 5.0, 15.0, 365.0)
    assert wide.reprice_years == display_reprice_years("Custom", 90.0, 110.0, 365.0)

    # A Custom with nothing typed must not silently derive 0 days.
    empty = _plan("Custom", dte=365, hold_min=None, hold_max=None)
    assert empty.reprice_years == display_reprice_years("Custom", None, None, 365.0)
    assert empty.reprice_years == display_reprice_years("Swing", None, None, 365.0)


def test_unknown_preset_falls_back_to_swing_on_both_paths():
    """The silent-miss branch. It is allowed to default — it is NOT allowed to
    default differently on the two paths."""
    for bogus in ("swing", "Position (15–45d)", "", "Weekly"):
        assert (_plan(bogus, dte=30).reprice_years
                == display_reprice_years("Swing", 15.0, 45.0, 30.0)), bogus
