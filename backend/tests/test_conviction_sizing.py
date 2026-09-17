"""Conviction sizing — the shared ramp, and the drift that made it necessary.

Before this module existed, auto_trader used max(min_mult, conv/full) while
stock_scan used min_mult + (1 - min_mult) * frac. On the shipped config those
sized the same setup up to 1.5x apart at conviction 20, and the clamp form made
the entire bottom half of the conviction scale inert.
"""
from pathlib import Path

import pytest
import yaml

from app.scoring.conviction_sizing import (
    DEFAULT_FULL_CONVICTION_PCT,
    SizingConfigError,
    conviction_mult,
    resolve_sizing,
)

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


def test_zero_full_conviction_falls_back_to_the_default_scale():
    """D-A1, decided by Kenneth 2026-09-17 as option (b).

    auto_trader's old form raised ZeroDivisionError here, in the live-money
    path, while stock_scan's floored the multiplier — one input, two sizes.
    The ruling is that zero falls back to the documented default of 40 rather
    than being read as "no conviction scale", so both paths agree.

    The 0.75 is the number the decision was taken on: min_mult 0.5,
    conviction 20, full falling back to 40.
    """
    cfg = {"enabled": True, "min_mult": 0.5, "full_conviction_pct": 0}
    assert conviction_mult(20, cfg) == pytest.approx(0.75)
    assert resolve_sizing(cfg) == (0.5, DEFAULT_FULL_CONVICTION_PCT)


def test_zero_full_conviction_is_logged_at_error(caplog):
    cfg = {"enabled": True, "min_mult": 0.3, "full_conviction_pct": 0}
    with caplog.at_level("ERROR", logger="app.scoring.conviction_sizing"):
        conviction_mult(40, cfg)
    assert "full_conviction_pct is 0" in caplog.text


# ── FAIL CLOSED (§9.1, Kenneth 2026-09-17) ────────────────────────────────────
#
# Every case here used to return a multiplier of 1.0 or min_mult, or crash
# deep in the fire path. 1.0 is FULL SIZE: "sizing is off" and "sizing is
# broken" must not be the same outcome, which is the whole point of the class.

def test_a_disabled_block_is_off_not_broken():
    """Sizing off by configuration is a decision, and junk inside it is inert."""
    assert conviction_mult(20, None) == 1.0
    assert conviction_mult(20, {}) == 1.0
    assert conviction_mult(20, {"enabled": False}) == 1.0
    assert conviction_mult(20, {"enabled": False, "full_conviction_pct": "nonsense"}) == 1.0
    assert resolve_sizing({"enabled": False}) is None


@pytest.mark.parametrize("bad", [
    {"enabled": True, "full_conviction_pct": -40},
    {"enabled": True, "full_conviction_pct": "forty"},
    {"enabled": True, "full_conviction_pct": True},
    {"enabled": True, "full_conviction_pct": float("nan")},
    {"enabled": True, "full_conviction_pct": float("inf")},
    {"enabled": True, "full_conviction_pct": None},
    {"enabled": True, "full_conviction_pct": [40]},
    {"enabled": True, "min_mult": "half"},
    {"enabled": True, "min_mult": True},
    {"enabled": True, "min_mult": float("nan")},
    {"enabled": True, "min_mult": None},
])
def test_an_unusable_block_refuses_instead_of_sizing_full(bad):
    with pytest.raises(SizingConfigError):
        conviction_mult(20, bad)
    with pytest.raises(SizingConfigError):
        resolve_sizing(bad)


def test_a_block_that_is_not_a_mapping_refuses():
    with pytest.raises(SizingConfigError):
        resolve_sizing([{"enabled": True}])
    with pytest.raises(SizingConfigError):
        resolve_sizing("enabled: true")


def test_a_nan_conviction_cannot_reach_a_broker_quantity():
    """max()/min() let nan through every range check, and round(nan) raises
    inside fire() after the order is already committed to."""
    with pytest.raises(SizingConfigError):
        conviction_mult(float("nan"), CFG)


def test_the_error_is_a_runtimeerror_so_existing_handlers_still_map_it():
    """POST /auto-trade/fire catches (ValueError, RuntimeError) -> 400, and
    fire() signals every other refusal as RuntimeError. If this stopped being
    a RuntimeError subclass, a refusal would surface as an unhandled 500."""
    assert issubclass(SizingConfigError, RuntimeError)


def test_the_error_names_the_file_and_the_key():
    """The message is the whole remedy — it reaches the 400 body, the scan's
    500 detail and the alert, and none of those has anything else to go on."""
    with pytest.raises(SizingConfigError) as exc:
        conviction_mult(20, {"enabled": True, "full_conviction_pct": -40})
    assert "scoring_rules.yaml" in str(exc.value)
    assert "full_conviction_pct" in str(exc.value)


def test_an_out_of_range_min_mult_is_still_clamped_and_now_recorded(caplog):
    """Unchanged behaviour (clamp, not refuse) — the clamp can only size DOWN,
    and refusing instead is open question 9.9, which is Kenneth's call. What is
    new is that the clamped run says so."""
    with caplog.at_level("ERROR", logger="app.scoring.conviction_sizing"):
        assert conviction_mult(0, {"enabled": True, "min_mult": 1.7}) == pytest.approx(1.0)
    assert "min_mult" in caplog.text


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
