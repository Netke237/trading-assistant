"""Shared helper: merge YAML fundamentals_gate defaults with per-request overrides.

Extracted from app.routers.scan so both the options-scan and stock-scan routers
can import it without a sibling-router cross-dependency.
"""
from __future__ import annotations

import copy

from app.services.config_loader import load_scoring_cfg


def resolve_fundamentals_gate(req) -> dict:
    """Return the effective fundamentals_gate config dict for a scan request.

    Starts from the YAML fundamentals_gate block and applies any per-request
    field overrides (fundamentals_enabled, fundamentals_caution_below, etc.).
    Bearish-only overrides (fundamentals_caution_above/reject_above — "don't
    short a company whose fundamentals are too strong") are applied only when
    req.direction is Bearish, matching the Step-3 slider's documented scope.
    """
    g = copy.deepcopy(load_scoring_cfg().get("fundamentals_gate", {}))
    if req.fundamentals_enabled is not None:
        g["enabled"] = req.fundamentals_enabled
    if req.fundamentals_caution_below is not None:
        g["cautionBelow"] = req.fundamentals_caution_below
    if req.fundamentals_reject_below is not None:
        g["rejectBelow"] = req.fundamentals_reject_below
    if req.fundamentals_de_reject is not None:
        g.setdefault("safety", {})["debt_to_equity_reject"] = req.fundamentals_de_reject
    if str(req.direction).lower() in ("bearish", "bear"):
        if req.fundamentals_caution_above is not None:
            g["cautionAbove"] = req.fundamentals_caution_above
        if req.fundamentals_reject_above is not None:
            g["rejectAbove"] = req.fundamentals_reject_above
    return g
