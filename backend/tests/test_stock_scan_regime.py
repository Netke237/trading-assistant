"""A9: Unit tests for _conviction_mult and _load_regime_cfg helpers."""
from app.routers.stock_scan import _conviction_mult, _load_regime_cfg


def test_conviction_mult_only_reduces():
    """The invariant in the name still holds: the multiplier never exceeds 1.0.

    The SHAPE moved on 2026-09-19 (two-sided ramp), and this test is on the
    scan side deliberately — it is the second of the two call sites that share
    `conviction_mult`, so it is where a change reaching one path and not the
    other would show. Neutral is now the midpoint, not the floor; the floor
    starts at -full_conviction_pct.
    """
    sizing = {"enabled": True, "min_mult": 0.5, "full_conviction_pct": 40}
    assert _conviction_mult(40, sizing) == 1.0          # full conviction -> full size
    assert _conviction_mult(0, sizing) == 0.75          # neutral -> MIDPOINT, was the floor
    assert _conviction_mult(-40, sizing) == 0.5         # the floor, reached at -full
    assert _conviction_mult(-50, sizing) == 0.5         # headwind clamps to floor (never <)
    assert _conviction_mult(40, {"enabled": False}) == 1.0   # disabled -> no change


def test_regime_cfg_per_horizon():
    cfg = _load_regime_cfg("Swing")
    assert cfg["timeframe"] == "daily"
    assert cfg["lookback"] == 20
