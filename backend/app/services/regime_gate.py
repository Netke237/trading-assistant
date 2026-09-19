"""One resolver for the `regime_gate` thresholds, shared by every path that gates.

WHY THIS MODULE EXISTS. The rule itself (`stock_scorer._regime_cap`) has always
had exactly one implementation. Its INPUTS did not: the options scan read the
YAML block raw, the stock scan overlaid the Step-3 per-scan overrides, and after
2026-09-19 the auto-trader overlays a snapshot of the same two values taken at
arm time. Three sites, three hand-written overlays, one rule — which is the
shape `conviction_sizing.py` exists one layer down to prevent, and the shape
that produced piece 2's round-1 finding 3 (the Step-3 "Headwind reject %"
reaching the stock scan and nothing else).

WHAT IT DOES NOT DO. It does not decide anything and it does not validate. It
merges two optional numbers onto a base dict and returns a COPY. The verdict is
still `_regime_cap`'s alone, and `enabled` / `require_stable_for_reject` are not
overridable by any caller — they are config, not per-scan parameters.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


def resolve_regime_gate(
    base: Optional[Mapping[str, Any]],
    caution_pct: Optional[float] = None,
    reject_pct: Optional[float] = None,
) -> dict:
    """Return `base` with the two per-run headwind thresholds overlaid.

    `base` is the `regime_gate` block from scoring_rules.yaml (None or absent ->
    {}, which `_regime_cap` reads as disabled). `caution_pct` / `reject_pct` are
    the Step-3 controls; None means "not set", and the YAML value stands. Zero
    is a legitimate threshold and is NOT treated as absent — hence the explicit
    `is not None` rather than a truthiness test.

    ALWAYS A COPY. The YAML doc behind `base` is loaded through an `lru_cache`
    and handed out by reference in all three callers, so writing an override
    into it would silently repoint every later reader in the process — for the
    rest of the process's life, since the cache is only cleared on restart.
    """
    gate = dict(base or {})
    if caution_pct is not None:
        gate["headwind_caution_pct"] = caution_pct
    if reject_pct is not None:
        gate["headwind_reject_pct"] = reject_pct
    return gate
