# backend/tests/test_regime_sizing_unification.py
"""Document A — `regime-sizing-fix`: the scan card and the auto-trade fire path
size the same setup identically, and a `regime_sizing` value outside its usable
range can no longer multiply a broker order or invert the position it produces.

THE DEFECT THIS PINS: `regime_sizing` had two consumers computing DIFFERENT
multipliers over the SAME config block — a linear ramp on the card
(`stock_scan._conviction_mult`) and a step floor on the fire path
(`auto_trader._apply_vol_sizing`). On the SHIPPED, VALID config
(`enabled: true, min_mult: 0.5, full_conviction_pct: 40`) they diverged by up
to 50%: at conviction 20 the fire path sized 0.500 where the card showed 0.750.
No typo and no config edit were needed to reach that.

Kenneth confirmed the LINEAR RAMP as canonical on 2026-09-17, having been told
the cost: live auto-trades get BIGGER at mid conviction. The step floor is what
changed; the card did not move.

Each test below names the §5 acceptance clause it discharges.
"""
from __future__ import annotations

import pytest

from app.routers.stock_scan import _conviction_mult, _position_size
from app.services import auto_trader as at
from app.services.auto_trader import ArmedStrategy, _apply_vol_sizing
from app.services.config_loader import conviction_multiplier, load_regime_sizing

SHIPPED = {"enabled": True, "min_mult": 0.5, "full_conviction_pct": 40}

# The curve the shipped config produces over conviction 0..40. Every
# out-of-range `min_mult` must fall back to exactly this.
SHIPPED_CURVE = [0.5, 0.625, 0.75, 0.875, 1.0]
CONVICTIONS = [0, 10, 20, 30, 40]


def _historical_step(pct: float, sizing: dict) -> float:
    """The formula the fire path used before this change, kept so the tests can
    show the divergence rather than assert against a remembered number."""
    lo = float(sizing.get("min_mult", 0.5))
    full = float(sizing.get("full_conviction_pct", 40))
    return max(lo, min(1.0, pct / full))


def _strategy(**extra) -> ArmedStrategy:
    base = dict(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
    )
    base.update(extra)
    return ArmedStrategy(**base)


@pytest.fixture
def conviction(mocker):
    """Set the market-wide cached conviction the fire path reads."""
    def _set(value):
        mocker.patch("app.services.regime_monitor.get_last_conviction",
                     return_value=value)
    return _set


@pytest.fixture
def seam(mocker):
    """Patch `_load_scoring_config` by name — the exact shape
    tests/test_phase_g_arm_pick.py:287 uses, and the reason the range guard
    must live at the POINT OF USE rather than at the loader."""
    def _set(raw: dict):
        mocker.patch.object(at, "_load_scoring_config", return_value=raw)
    return _set


# ── Clause 1: both paths, one multiplier ─────────────────────────────────

def test_clause1_both_paths_return_the_same_multiplier():
    """The §1 divergence table collapses to a single column."""
    for pct in CONVICTIONS:
        card = _conviction_mult(pct, SHIPPED)
        canonical = conviction_multiplier(pct, SHIPPED)
        assert card == canonical
    assert [_conviction_mult(p, SHIPPED) for p in CONVICTIONS] == SHIPPED_CURVE


def test_clause1_the_fire_path_actually_routes_through_it(conviction, seam):
    """Asserting the table alone is NOT enough — it would pass with the step
    formula still shipped on the fire path. This asserts the fire path's own
    observable.

    THE QUANTITY MATTERS AND 4 WILL NOT DO. `_apply_vol_sizing` returns an
    ArmedStrategy, not a multiplier, and returns it UNCHANGED when
    `adjusted_qty == quantity`, so the only observable is
    `round(quantity * mult)` — quantised, with banker's rounding. At
    conviction 10 (the 1.25x row of the §1 table):

        quantity   step   ramp
        4          2      2      <- divergence INVISIBLE
        10         5      6
        100        50     62
    """
    seam(dict(SHIPPED))
    conviction(10.0)

    resized = _apply_vol_sizing(_strategy(quantity=100))
    assert resized.quantity == 62, "the fire path must use the ramp, not the step"
    assert round(100 * _historical_step(10, SHIPPED)) == 50, (
        "sanity: the historical step formula really did give 50 here"
    )

    # And the quantity that would have hidden it.
    assert round(4 * conviction_multiplier(10, SHIPPED)) == \
           round(4 * _historical_step(10, SHIPPED)) == 2


# ── Clause 2: min_mult: 5 cannot enlarge an order ────────────────────────

def test_clause2_min_mult_5_cannot_enlarge_an_order_through_the_seam(conviction, seam):
    """A decimal typo (`5` for `0.5`) reaching the fire path as a RAW dict —
    the guard has to catch it at the point of use, because this dict never
    passes through the loader.

    With the guard at the loader instead this fails: executed, qty 10 at
    conviction 10 returns 40.
    """
    seam({"enabled": True, "min_mult": 5, "full_conviction_pct": 40})
    conviction(10.0)

    for qty in (1, 4, 10, 100):
        resized = _apply_vol_sizing(_strategy(quantity=qty))
        assert resized.quantity <= qty, (
            f"min_mult: 5 enlarged a broker order: {qty} -> {resized.quantity}"
        )


def test_clause2_min_mult_5_cannot_enlarge_the_card():
    assert all(conviction_multiplier(p, {"enabled": True, "min_mult": 5,
                                         "full_conviction_pct": 40}) <= 1.0
               for p in CONVICTIONS)


# ── Clause 3: min_mult: 5 cannot invert the card ─────────────────────────

@pytest.mark.parametrize("min_mult", [5, -2, 0, 0.5, 1])
def test_clause3_the_multiplier_is_monotonically_non_decreasing(min_mult):
    """The INVERSION is the shape that hid the direction-conviction gate for
    three months: with `min_mult > 1` the raw ramp DECREASES as conviction
    rises, so the strongest signal gets the smallest position."""
    sizing = {"enabled": True, "min_mult": min_mult, "full_conviction_pct": 40}
    curve = [conviction_multiplier(p, sizing) for p in CONVICTIONS]
    assert curve == sorted(curve), f"min_mult={min_mult!r} inverted the ramp: {curve}"


@pytest.mark.parametrize("min_mult", [5, -2, 0])
def test_clause3_out_of_range_min_mult_returns_the_shipped_curve(min_mult):
    """FALL BACK, not CLAMP. Clamping to either bound is itself a wrong number
    on an order — see clause 4 for the lower bound and clause 2 for the upper."""
    sizing = {"enabled": True, "min_mult": min_mult, "full_conviction_pct": 40}
    assert [conviction_multiplier(p, sizing) for p in CONVICTIONS] == SHIPPED_CURVE


# ── Clause 4: never a multiplier <= 0, and specifically never 0.0 ────────

@pytest.mark.parametrize("min_mult", [-2, 0])
def test_clause4_no_multiplier_is_ever_zero_or_negative(min_mult):
    sizing = {"enabled": True, "min_mult": min_mult, "full_conviction_pct": 40}
    for p in (-50, 0, 10, 20, 40, 1000):
        mult = conviction_multiplier(p, sizing)
        assert mult > 0.0, f"min_mult={min_mult!r} at conviction {p} gave {mult}"


def test_clause4_a_zero_multiplier_would_double_the_card_not_shrink_it():
    """WHY clause 4 is a gate-level assertion and not hygiene.

    `_position_size` computes
    `dollar_risk = risk_fixed if risk_fixed else (account * (risk_pct or 0.01))`.
    A multiplier of 0.0 makes `sized_risk_pct` 0.0, which is FALSY, so it falls
    through to the hardcoded 1% default — a "shrink to nothing" multiplier
    DOUBLES the share count that reaches StockPositionCard -> StockSendDialog
    -> the broker.
    """
    account, base_risk_pct, entry, stop = 100_000.0, 0.005, 100.0, 95.0

    unscaled, unscaled_risk = _position_size(account, base_risk_pct, None, entry, stop)
    floored, floored_risk = _position_size(account, base_risk_pct * 0.5, None, entry, stop)
    zeroed, zeroed_risk = _position_size(account, base_risk_pct * 0.0, None, entry, stop)

    assert (unscaled, unscaled_risk) == (100, 500.0)
    assert (floored, floored_risk) == (50, 250.0)
    # The trap, pinned so it cannot be "fixed" into the guard by accident:
    assert (zeroed, zeroed_risk) == (200, 1000.0)
    assert zeroed == 2 * unscaled

    # And the normaliser guarantees the multiplier can never be the trigger.
    assert conviction_multiplier(0, {"enabled": True, "min_mult": 0,
                                     "full_conviction_pct": 40}) > 0.0


# ── Clause 5: full_conviction_pct: 0 raises nothing ──────────────────────

@pytest.mark.parametrize("full", [0, -10])
def test_clause5_full_conviction_zero_raises_no_zero_division_on_the_card(full):
    """Per D-A1(b): fall back to the shipped 40, giving 0.750 at conviction 20
    — exactly the 1.5x the ramp produces everywhere else, where treating the
    block as disabled would have been a 2x on a live card."""
    sizing = {"enabled": True, "min_mult": 0.5, "full_conviction_pct": full}
    assert _conviction_mult(20, sizing) == 0.75


def test_clause5_full_conviction_zero_raises_no_zero_division_on_the_fire_path(
        conviction, seam):
    """This used to be an uncaught ZeroDivisionError, which — because `fire()`
    disarms BEFORE `_apply_vol_sizing` — destroyed the armed pick and placed no
    order at all."""
    seam({"enabled": True, "min_mult": 0.5, "full_conviction_pct": 0})
    conviction(20.0)
    resized = _apply_vol_sizing(_strategy(quantity=100))
    assert resized.quantity == 75


# ── Clause 6: the existing card test's NAME becomes true ─────────────────

def test_clause6_the_disabled_block_carries_no_keys_and_still_returns_one():
    """`test_conviction_mult_only_reduces` line 10 passes
    `{"enabled": False}` — no `min_mult`, no `full_conviction_pct`. A literal
    one-line delegation to an UNGUARDED formula raises KeyError there."""
    assert _conviction_mult(40, {"enabled": False}) == 1.0


@pytest.mark.parametrize("min_mult", [5, -2, 0, 0.5, 1])
def test_clause6_the_test_name_only_reduces_now_holds_for_every_admitted_value(min_mult):
    sizing = {"enabled": True, "min_mult": min_mult, "full_conviction_pct": 40}
    assert all(conviction_multiplier(p, sizing) <= 1.0
               for p in (-50, 0, 10, 20, 40, 1000))


# ── Clause 7: a missing key does not empty a whole scan ──────────────────

@pytest.mark.parametrize("sizing", [
    {"enabled": True},
    {"enabled": True, "min_mult": 0.5},
    {"enabled": True, "full_conviction_pct": 40},
    {"enabled": True, "min_mult": None, "full_conviction_pct": None},
    {"enabled": True, "min_mult": "0.5", "full_conviction_pct": "40"},
])
def test_clause7_a_missing_or_unparseable_key_returns_a_number_not_a_raise(sizing):
    """Bare-indexing made a missing key raise KeyError inside the per-symbol
    try, so EVERY symbol rejected with `reason: "'min_mult'"` — HTTP 200, zero
    candidates, and nothing naming the file. On the stocks path that failure is
    completely silent in the UI, so an empty scan was the only symptom."""
    mult = _conviction_mult(20, sizing)
    assert isinstance(mult, float)
    assert 0.0 < mult <= 1.0


def test_clause7_a_non_mapping_block_disables_rather_than_raising():
    assert _conviction_mult(20, {}) == 1.0


# ── Clause 8: a malformed config must not destroy an armed pick ──────────

def test_clause8_an_unreadable_scoring_yaml_leaves_the_armed_pick_intact(mocker):
    """`fire()` disarms at :223-225 and calls `_apply_vol_sizing` at :228, so a
    propagating exception loses the pick with NO ORDER AND NO RETRY. The
    try/except that used to sit on `_load_scoring_config`'s dropped lru_cache
    had to move, not disappear — `load_scoring_cfg` has no error handling of
    its own."""
    mocker.patch("app.services.config_loader.load_scoring_cfg",
                 side_effect=OSError("scoring_rules.yaml is gone"))

    assert load_regime_sizing() == {"enabled": False}

    original = _strategy(quantity=7)
    resized = _apply_vol_sizing(original)
    assert resized is original, "the pick must survive a malformed config"
    assert resized.quantity == 7, "and fire at the typed quantity, as it did before"


# ── The SELL direction, which shares the formula but not the argument ────

def test_the_sell_side_uses_the_same_ramp_on_its_own_derived_conviction(
        conviction, seam):
    """§2.1: unification shares the FUNCTION, not the ARGUMENT. `100 -
    conviction` stays in auto_trader — it is the fire path's own concern — and
    it is NOT equivalent to compute_omm(direction="Bearish"), which the card
    uses. That divergence is logged against main, not closed here."""
    seam(dict(SHIPPED))
    conviction(30.0)  # SELL sees 100 - 30 = 70, which caps at full -> 1.0
    assert _apply_vol_sizing(_strategy(action="SELL", quantity=100)).quantity == 100
    assert _apply_vol_sizing(_strategy(action="BUY", quantity=100)).quantity == 88


# ── The `enabled` flag: truthiness, not identity ─────────────────────────
#
# Found by the post-implementation adversarial round. The first cut of
# `_normalise_regime_sizing` tested `block.get("enabled") is not True`, which
# looks harmless and is not: both pre-change consumers tested
# `not cfg.get("enabled", False)`, so a quoted `enabled: "true"` ENABLED
# sizing and an identity check DISABLES it. Disabled means multiplier 1.0 —
# FULL SIZE — so a YAML typo silently made every sized order LARGER on both
# paths, and it was the one input class that carried no record at all.

_TRUTHY_NON_BOOLS = ["true", "True", 1, "yes", "false"]


@pytest.mark.parametrize("enabled", _TRUTHY_NON_BOOLS)
def test_a_truthy_non_bool_enabled_still_enables_sizing(enabled):
    """The pre-change numbers, exactly. `"false"` is in this list on purpose:
    a non-empty string is truthy, so it enabled sizing before this change too,
    and preserving that is the point — the fix restores behaviour, it does not
    improve on it."""
    sizing = {"enabled": enabled, "min_mult": 0.5, "full_conviction_pct": 40}
    assert _conviction_mult(20, sizing) == 0.75


@pytest.mark.parametrize("enabled", _TRUTHY_NON_BOOLS)
def test_a_non_bool_enabled_is_recorded_rather_than_swallowed(enabled):
    """"Never refuse, always record." Every other rejected value appends to
    `problems`; this one must too, or the typo is invisible everywhere."""
    from app.services.config_loader import _normalise_regime_sizing
    _, problems = _normalise_regime_sizing(
        {"enabled": enabled, "min_mult": 0.5, "full_conviction_pct": 40}
    )
    assert any("enabled" in p for p in problems), (
        f"enabled={enabled!r} was accepted or rejected with no record"
    )


@pytest.mark.parametrize("enabled", [False, None])
def test_a_falsy_enabled_disables_without_a_spurious_record(enabled):
    """Absent or null means "not turned on" — the historical
    `.get("enabled", False)` default. Recording it would fire an ERROR on
    every scan of a config that simply omits the block."""
    from app.services.config_loader import _normalise_regime_sizing
    sizing = {"min_mult": 0.5, "full_conviction_pct": 40}
    if enabled is not None:
        sizing["enabled"] = enabled
    normalised, problems = _normalise_regime_sizing(sizing)
    assert normalised == {"enabled": False}
    assert problems == []
    assert _conviction_mult(20, sizing) == 1.0


def test_a_quoted_enabled_does_not_enlarge_the_fire_path(conviction, seam):
    """The fire-path half of the same defect: a 100-contract armed pick fires
    at 100 instead of 75 on a real broker order. Same 1.33x as the card, since
    both paths already shared the ramp when this bug existed."""
    seam({"enabled": "true", "min_mult": 0.5, "full_conviction_pct": 40})
    conviction(20.0)
    assert _apply_vol_sizing(_strategy(quantity=100)).quantity == 75
