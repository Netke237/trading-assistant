"""Shared cached access to YAML config files.

A single lru_cache per config file avoids duplicate in-memory copies when
multiple modules (scan router, fundamentals_gate, etc.) need the same file.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


@lru_cache(maxsize=1)
def load_scoring_cfg() -> dict:
    """Return the parsed scoring_rules.yaml as a dict (cached after first load)."""
    import yaml
    return yaml.safe_load((_CONFIG_DIR / "scoring_rules.yaml").read_text())


@lru_cache(maxsize=1)
def load_reward_risk_cfg() -> dict:
    """Return risk_rules.yaml's reward_risk block (bullish/bearish target %,
    premium_stop_pct). Shared by the scan pipeline and the per-contract
    recompute endpoint — both must build a trade plan off the same numbers."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["reward_risk"]


# Maps the Step 3 "Reward/Risk" panel's override keys (frontend/lib/
# executionParamDefaults.ts) onto risk_rules.yaml's reward_risk block keys.
_RR_OVERRIDE_KEY_MAP = {
    "rr_bullish_target_pct":       "bullish_target_pct",
    "rr_bearish_target_pct":       "bearish_target_pct",
    "rr_bullish_invalidation_pct": "bullish_invalidation_pct",
    "rr_bearish_invalidation_pct": "bearish_invalidation_pct",
}


def merge_reward_risk_overrides(overrides: dict | None) -> dict:
    """Return risk_rules.yaml's reward_risk block with any per-request rr_*
    overrides applied on top.

    Returns a fresh dict every call — load_reward_risk_cfg()'s cached dict is
    never mutated, so a later call with different (or no) overrides isn't
    affected by an earlier one.
    """
    merged = dict(load_reward_risk_cfg())
    for override_key, cfg_key in _RR_OVERRIDE_KEY_MAP.items():
        if overrides and override_key in overrides:
            merged[cfg_key] = float(overrides[override_key])
    return merged
