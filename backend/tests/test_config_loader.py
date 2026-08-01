"""Tests for app.services.config_loader's reward/risk override merging."""
import pytest

from app.services.config_loader import load_reward_risk_cfg, merge_reward_risk_overrides


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
