"""Shared helper: merge YAML fundamentals_gate defaults with per-request overrides.

Extracted from app.routers.scan so both the options-scan and stock-scan routers
can import it without a sibling-router cross-dependency.
"""
from __future__ import annotations

import copy
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path


_SCORING_CFG_PATH = _Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@_lru_cache(maxsize=1)
def _load_scoring_cfg() -> dict:
    import yaml
    return yaml.safe_load(_SCORING_CFG_PATH.read_text())


def resolve_fundamentals_gate(req) -> dict:
    """Return the effective fundamentals_gate config dict for a scan request.

    Starts from the YAML fundamentals_gate block and applies any per-request
    field overrides (fundamentals_enabled, fundamentals_caution_below, etc.).
    """
    g = copy.deepcopy(_load_scoring_cfg().get("fundamentals_gate", {}))
    if req.fundamentals_enabled is not None:
        g["enabled"] = req.fundamentals_enabled
    if req.fundamentals_caution_below is not None:
        g["cautionBelow"] = req.fundamentals_caution_below
    if req.fundamentals_reject_below is not None:
        g["rejectBelow"] = req.fundamentals_reject_below
    if req.fundamentals_de_reject is not None:
        g.setdefault("safety", {})["debt_to_equity_reject"] = req.fundamentals_de_reject
    return g
