"""Tests for app.services.config_loader's reward/risk override merging and
direction-conviction gate resolution."""
from unittest.mock import patch

import pytest

from app.services.config_loader import (
    load_direction_conviction_min_trend,
    load_reward_risk_cfg,
    merge_reward_risk_overrides,
)


def test_merge_with_no_overrides_returns_base_config():
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides({})
    assert merged == base


def test_merge_with_none_overrides_returns_base_config():
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides(None)
    assert merged == base


def test_merge_overrides_bullish_target_pct():
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": 0.12})
    assert merged["bullish_target_pct"] == 0.12
    # Untouched keys keep the base config's values.
    base = load_reward_risk_cfg()
    assert merged["bearish_target_pct"] == base["bearish_target_pct"]
    assert merged["premium_stop_pct"] == base["premium_stop_pct"]


def test_merge_overrides_all_four_rr_keys():
    merged = merge_reward_risk_overrides({
        "rr_bullish_target_pct": 0.12,
        "rr_bearish_target_pct": 0.09,
        "rr_bullish_invalidation_pct": 0.04,
        "rr_bearish_invalidation_pct": 0.05,
    })
    assert merged["bullish_target_pct"] == 0.12
    assert merged["bearish_target_pct"] == 0.09
    assert merged["bullish_invalidation_pct"] == 0.04
    assert merged["bearish_invalidation_pct"] == 0.05


def test_merge_ignores_unrelated_override_keys():
    """Other scan overrides (e.g. rsi_floor) must not leak into rr_cfg or raise."""
    merged = merge_reward_risk_overrides({"rsi_floor": 40, "rr_bullish_target_pct": 0.11})
    assert merged["bullish_target_pct"] == 0.11
    assert "rsi_floor" not in merged


def test_merge_does_not_mutate_the_cached_base_config():
    base_before = dict(load_reward_risk_cfg())
    merge_reward_risk_overrides({"rr_bullish_target_pct": 0.99})
    assert load_reward_risk_cfg() == base_before


# ── Finding 2/3: bounds validation + None-skip ────────────────────────────────

def test_merge_skips_none_override_value():
    """A None override (e.g. a cleared frontend field) must be silently
    skipped, not crash on float(None) -- this is Finding 3's fix."""
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": None})
    assert merged["bullish_target_pct"] == base["bullish_target_pct"]


@pytest.mark.parametrize("key", [
    "rr_bullish_target_pct", "rr_bearish_target_pct",
    "rr_bullish_invalidation_pct", "rr_bearish_invalidation_pct",
])
def test_merge_rejects_negative_value(key):
    with pytest.raises(ValueError, match=key):
        merge_reward_risk_overrides({key: -0.5})


@pytest.mark.parametrize("key", [
    "rr_bullish_target_pct", "rr_bearish_target_pct",
    "rr_bullish_invalidation_pct", "rr_bearish_invalidation_pct",
])
def test_merge_rejects_zero_value(key):
    with pytest.raises(ValueError, match=key):
        merge_reward_risk_overrides({key: 0})


def test_merge_rejects_value_above_target_cap():
    with pytest.raises(ValueError, match="rr_bullish_target_pct"):
        merge_reward_risk_overrides({"rr_bullish_target_pct": 500})


def test_merge_rejects_value_above_invalidation_cap():
    with pytest.raises(ValueError, match="rr_bullish_invalidation_pct"):
        merge_reward_risk_overrides({"rr_bullish_invalidation_pct": 1.5})


def test_merge_rejects_non_finite_value():
    with pytest.raises(ValueError, match="rr_bullish_target_pct"):
        merge_reward_risk_overrides({"rr_bullish_target_pct": float("inf")})


def test_merge_accepts_valid_in_range_value_at_target_cap():
    # Regression guard: the cap is inclusive (<=), not exclusive.
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": 2.0})
    assert merged["bullish_target_pct"] == 2.0


def test_merge_accepts_valid_in_range_value_at_invalidation_cap():
    merged = merge_reward_risk_overrides({"rr_bullish_invalidation_pct": 1.0})
    assert merged["bullish_invalidation_pct"] == 1.0


def test_merge_rejects_non_numeric_string_value_with_named_key():
    """Round 2 audit finding: a non-numeric string (e.g. a mistyped override)
    must raise the function's own well-messaged ValueError naming the
    offending key -- not Python's raw float() ValueError, which doesn't."""
    with pytest.raises(ValueError, match="rr_bullish_target_pct"):
        merge_reward_risk_overrides({"rr_bullish_target_pct": "abc"})


# ── Direction-conviction gate resolution ─────────────────────────────────────
#
# The gate this resolver feeds screens every non-Intraday scan in BOTH modes.
# Its bearish half was inverted (a `max_trend` ceiling instead of a floor) from
# 2026-06-18 until 2026-09-16, which deleted the strongest short setups and
# kept the names that were not falling, so the resolution rules are pinned
# here rather than left to the callers' own tests.

def _cfg(direction_conviction_by_horizon: dict) -> dict:
    """A scoring_rules.yaml stand-in carrying only the block under test."""
    return {
        "horizons": {
            horizon: {"direction_conviction": block}
            for horizon, block in direction_conviction_by_horizon.items()
        }
    }


def test_direction_conviction_reads_the_shipped_config_as_mirrored_floors():
    """The shipped scoring_rules.yaml gates both directions on the SAME floor at
    each horizon, and exempts Intraday. Asserted as an equality between the two
    directions, so a change to one side alone fails here."""
    for horizon, expected in (("Swing", 30.0), ("Position", 40.0), ("Intraday", None)):
        bullish = load_direction_conviction_min_trend("Bullish", horizon)
        bearish = load_direction_conviction_min_trend("Bearish", horizon)
        assert bullish == expected, f"Bullish/{horizon}"
        assert bearish == expected, f"Bearish/{horizon}"
        assert bullish == bearish, (
            f"{horizon}: the two directions no longer mirror each other "
            f"(Bullish {bullish} vs Bearish {bearish})"
        )


def test_direction_conviction_yaml_value_beats_the_code_default():
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"position": {"bearish_min_trend": 55}})):
        assert load_direction_conviction_min_trend("Bearish", "Position") == 55.0
        # The key the stub did NOT set still falls back to the code default.
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0


def test_direction_conviction_falls_back_to_defaults_when_the_block_is_absent():
    """Deleting the YAML block must leave the gate at its shipped strength, not
    silently disable it — an absent threshold that read as 'no gate' would widen
    the screen without anyone noticing."""
    with patch("app.services.config_loader.load_scoring_cfg", return_value={"horizons": {}}):
        assert load_direction_conviction_min_trend("Bearish", "Swing") == 30.0
        assert load_direction_conviction_min_trend("Bullish", "Swing") == 30.0
        assert load_direction_conviction_min_trend("Bearish", "Position") == 40.0
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0
        # Intraday has no default, so it stays exempt.
        assert load_direction_conviction_min_trend("Bearish", "Intraday") is None


def test_direction_conviction_explicit_null_exempts_that_direction():
    """An explicit `null` is honoured rather than falling through to the
    default — that is how a horizon is deliberately exempted."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"position": {"bearish_min_trend": None}})):
        assert load_direction_conviction_min_trend("Bearish", "Position") is None
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0


def test_direction_conviction_accepts_the_range_boundaries():
    for value in (0, 100):
        with patch("app.services.config_loader.load_scoring_cfg",
                   return_value=_cfg({"swing": {"bearish_min_trend": value}})):
            assert load_direction_conviction_min_trend("Bearish", "Swing") == float(value)


@pytest.mark.parametrize("bad", ["abc", "", [], {}, float("nan"), float("inf"), -1, 101])
def test_direction_conviction_rejects_a_malformed_threshold(bad):
    """A malformed threshold must raise, not silently disable the gate: a typo
    in the config has to fail the scan loudly rather than quietly widening the
    screen to everything."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"swing": {"bearish_min_trend": bad}})):
        with pytest.raises(ValueError, match="bearish_min_trend"):
            load_direction_conviction_min_trend("Bearish", "Swing")


@pytest.mark.parametrize("bad", [True, False])
def test_direction_conviction_rejects_a_boolean_threshold(bad):
    """bool subclasses int, so a YAML `true` would otherwise pass float() as 1.0
    and install a floor that admits essentially every candidate — and `false`
    would become 0.0, a gate that rejects nothing at all."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"swing": {"bearish_min_trend": bad}})):
        with pytest.raises(ValueError, match="boolean"):
            load_direction_conviction_min_trend("Bearish", "Swing")


def test_direction_conviction_rejects_an_unknown_direction():
    with pytest.raises(ValueError, match="unknown direction"):
        load_direction_conviction_min_trend("Sideways", "Swing")


def test_direction_conviction_treats_an_unknown_horizon_as_exempt():
    """An unrecognised horizon has no floor to apply. It cannot reach here from
    the API — both request models Literal-restrict `horizon` — so returning None
    rather than raising keeps a non-scan caller from crashing on a horizon name
    this table simply does not cover."""
    assert load_direction_conviction_min_trend("Bearish", "Decade") is None
