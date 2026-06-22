from __future__ import annotations

import functools
from pathlib import Path

import yaml
from fastapi import APIRouter

_CFG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"

router = APIRouter(prefix="/api/config", tags=["config"])


@functools.lru_cache(maxsize=1)
def _scoring_cfg() -> dict:
    return yaml.safe_load(_CFG_PATH.read_text())


clear_scoring_cfg_cache = _scoring_cfg.cache_clear


@router.get("/iv-thresholds")
def get_iv_thresholds() -> dict:
    """Return per-horizon IV rank pass/caution thresholds from scoring_rules.yaml."""
    horizons = _scoring_cfg()["horizons"]
    return {
        label: {
            "pass_max":    horizons[key]["vol"].get("iv_rank_pass_max"),
            "caution_max": horizons[key]["vol"].get("iv_rank_caution_max"),
        }
        for label, key in [
            ("Intraday", "intraday"),
            ("Swing",    "swing"),
            ("Position", "position"),
        ]
    }
