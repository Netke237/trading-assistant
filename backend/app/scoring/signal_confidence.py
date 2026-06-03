from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_backtest_cfg(horizon: str) -> dict:
    return _cfg()["confidence_backtest"][horizon.lower()]


def load_gate_cfg() -> dict:
    return _cfg()["confidence_gate"]
