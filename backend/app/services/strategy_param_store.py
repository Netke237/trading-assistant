"""Strategy parameter store with YAML-based configuration and archive-on-adopt."""

from __future__ import annotations

import copy
import os
import shutil
from datetime import datetime
from pathlib import Path

import yaml


CFG = Path(__file__).parent.parent.parent / "config" / "strategy_params.yaml"


def _load() -> dict:
    """Load strategy_params.yaml or return empty structure if missing."""
    if not CFG.exists():
        return {"strategies": {}}
    content = CFG.read_text(encoding="utf-8")
    return yaml.safe_load(content) or {"strategies": {}}


def get_active(strategy: str) -> dict:
    """Get active (production) parameters for a strategy.

    Returns a copy of the active params dict, or empty dict if strategy not found.
    The caller should provide signal-function defaults if the strategy is unknown.
    """
    return dict(_load().get("strategies", {}).get(strategy, {}).get("active", {}))


def get_search_space(strategy: str) -> dict:
    """Get search space (hyperparameter grid) for a strategy.

    Returns a copy of the search params dict, or empty dict if strategy not found.
    """
    return dict(_load().get("strategies", {}).get(strategy, {}).get("search", {}))


def get_windows() -> dict:
    """Get rolling window configuration."""
    return dict(
        _load().get(
            "windows",
            {"type": "rolling", "train_months": 12, "test_months": 3},
        )
    )


def get_costs() -> dict:
    """Get transaction cost configuration."""
    return dict(
        _load().get("costs", {"fee_pct": 0.001, "slippage_pct": 0.001})
    )


def adopt(strategy: str, params: dict) -> None:
    """Archive current active params and write the proposed set as the new active.

    Creates a backup of the YAML before overwriting.
    Uses atomic write (tmp-then-replace) to prevent corruption on crash.
    """
    data = _load()

    # Archive the current config before modification (if it exists)
    if CFG.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = CFG.with_suffix(f".bak.{timestamp}.yaml")
        shutil.copy(CFG, backup_path)

    # Update the active parameters for this strategy
    data.setdefault("strategies", {}).setdefault(strategy, {})["active"] = (
        copy.deepcopy(params)
    )

    # Write back to YAML using atomic write (tmp-then-replace)
    tmp = CFG.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    os.replace(tmp, CFG)
