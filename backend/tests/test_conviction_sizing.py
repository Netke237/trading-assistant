"""Conviction sizing — the shared ramp, and the drift that made it necessary.

Before this module existed, auto_trader used max(min_mult, conv/full) while
stock_scan used min_mult + (1 - min_mult) * frac. On the shipped config those
sized the same setup up to 1.5x apart at conviction 20, and the clamp form made
the entire bottom half of the conviction scale inert.
"""
from pathlib import Path

import pytest
import yaml

from app.scoring.conviction_sizing import conviction_mult

CFG = {"enabled": True, "min_mult": 0.3, "full_conviction_pct": 40}


# ── Anti-drift: both call sites must be the SAME function ──────────────────────

def test_stock_scan_uses_the_shared_helper():
    from app.routers.stock_scan import _conviction_mult
    assert _conviction_mult is conviction_mult


def test_auto_trader_uses_the_shared_helper():
    import app.services.auto_trader as auto_trader
    assert auto_trader.conviction_mult is conviction_mult


def test_no_inlined_formula_survives_in_either_caller():
    """The literal clamp form must not reappear in auto_trader."""
    src = Path("app/services/auto_trader.py").read_text()
    assert "max(min_mult" not in src, "auto_trader re-inlined the clamp form"


# ── Shape ─────────────────────────────────────────────────────────────────────

def test_endpoints():
    assert conviction_mult(0, CFG) == pytest.approx(0.3)
    assert conviction_mult(40, CFG) == pytest.approx(1.0)


def test_above_full_conviction_caps_at_one():
    assert conviction_mult(50, CFG) == pytest.approx(1.0)
    assert conviction_mult(1000, CFG) == pytest.approx(1.0)


def test_headwind_floors_at_min_mult_and_never_below():
    assert conviction_mult(-1, CFG) == pytest.approx(0.3)
    assert conviction_mult(-50, CFG) == pytest.approx(0.3)


def test_there_is_no_dead_zone():
    """Every conviction step must move the multiplier — the clamp's actual bug.

    Under max(min_mult, conv/full) with min_mult=0.5, conviction 0..20 all
    produced 0.5. Nothing in [0, full] may plateau.
    """
    vals = [conviction_mult(c, CFG) for c in range(0, 41)]
    assert all(b > a for a, b in zip(vals, vals[1:])), "multiplier plateaus somewhere in [0, 40]"


def test_ramp_matches_hand_computed_table():
    expected = {0: 0.300, 5: 0.3875, 10: 0.475, 15: 0.5625,
                20: 0.650, 25: 0.7375, 30: 0.825, 35: 0.9125, 40: 1.0}
    for conv, want in expected.items():
        assert conviction_mult(conv, CFG) == pytest.approx(want), f"conviction {conv}"


def test_multiplier_never_exceeds_one_or_drops_below_zero():
    for conv in range(-100, 201, 7):
        assert 0.0 <= conviction_mult(conv, CFG) <= 1.0


# ── Config robustness (the two asymmetries the old pair had) ───────────────────

def test_disabled_block_returns_unity():
    assert conviction_mult(0, {"enabled": False}) == 1.0
    assert conviction_mult(0, {}) == 1.0


def test_partial_block_falls_back_instead_of_raising():
    """stock_scan's form did sizing["min_mult"] — a KeyError on a partial block."""
    assert conviction_mult(40, {"enabled": True}) == pytest.approx(1.0)
    assert conviction_mult(0, {"enabled": True}) == pytest.approx(0.5)


def test_zero_full_conviction_does_not_divide_by_zero():
    """auto_trader's form raised ZeroDivisionError here, in the live-money path."""
    cfg = {"enabled": True, "min_mult": 0.3, "full_conviction_pct": 0}
    assert conviction_mult(40, cfg) == pytest.approx(0.3)


def test_misconfigured_min_mult_can_never_size_a_position_up():
    cfg = {"enabled": True, "min_mult": 1.7, "full_conviction_pct": 40}
    assert conviction_mult(0, cfg) == pytest.approx(1.0)
    cfg_neg = {"enabled": True, "min_mult": -2.0, "full_conviction_pct": 40}
    assert conviction_mult(0, cfg_neg) == pytest.approx(0.0)


# ── The shipped config ────────────────────────────────────────────────────────

def test_shipped_config_is_the_ramp_at_0_3():
    cfg = yaml.safe_load(Path("config/scoring_rules.yaml").read_text())["regime_sizing"]
    assert cfg["enabled"] is True
    assert cfg["min_mult"] == 0.3
    assert cfg["full_conviction_pct"] == 40
    assert conviction_mult(20, cfg) == pytest.approx(0.65)
