"""REGIME-SIZING parity: the stock card and the auto-trader size through the ONE
ramp, BEHAVIOURALLY — not just by importing the same name.

REGIME-SIZING-AUDIT round 1 finding 5: the identity tests in
test_conviction_sizing.py (`auto_trader.conviction_mult is conviction_mult`)
prove only that the name is imported. Replacing the CALL with an inline
formula, or with 1.0, passed both. The tests here drive each real call site:

  * SENTINEL: each module's ramp is patched to a constant nobody would pick,
    and the sized output must move to it. A call site that stopped calling the
    ramp keeps its old number and fails.
  * PARITY: over a conviction grid, the same base size goes out at the same
    sized quantity on both paths, and both equal a floor of base x
    conviction_mult (finding 3: the card used to truncate without the fire
    path's 1e-9 and could lose a unit on an exact boundary).

WHAT THIS DOES NOT CLAIM: that the two paths size the same SETUP. The
auto-trader fires options armed from the Step 7 options card, which is not
conviction-sized; the stock card sizes shares. They share a FORMULA and a
rounding rule, which is what is pinned here (finding 1).

BOTH SIDES READ THE SAME INJECTED BLOCK (r2 finding 1). The card takes it via
`_run`, the fire path via a patched `_load_scoring_config`. The fire side
used to read the live scoring_rules.yaml, so the two agreed only because the
file ships 0.3 / 40, and a call site passing a HARDCODED 0.3 / 40 block to
the ramp passed everything. The grid now also runs a block the file does not
ship, so that mutant fails.

NOT COVERED: direction. Both sides stub the measurement (`compute_omm`,
`_measure_trade_regime`) and the grid is Bullish only, so a frame/mirror
divergence between the paths would not show here.
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

import app.routers.stock_scan as stock_scan
import app.services.auto_trader as auto_trader
from app.scoring.conviction_sizing import conviction_mult
from tests.test_auto_trader import _fired_quantity
from tests.test_stock_scan_unmeasured_floor import _FULL_SHARES, _ON, _omm, _run

# 50_000 * 1% = 500 risk, / (152 - 148) = 125 shares at full size — the card
# fixture's base. The fire path is armed at the same 125 contracts, so both
# paths start from the same base quantity.
_BASE = _FULL_SHARES

_GRID = list(range(-45, 46, 3))

# The shipped block, and one the file does not ship.
_CONFIGS = [
    pytest.param(_ON, id="shipped-0.3-40"),
    pytest.param({"enabled": True, "min_mult": 0.5, "full_conviction_pct": 20},
                 id="unshipped-0.5-20"),
]


def _no_daily_loss_cap(mocker) -> None:
    """Up to 125 contracts at $2.50 (at least ~$9,000 even after sizing) is
    over the fixture's daily loss limit (2% of 100,000 = $2,000). That limit is a separate refusal, not sizing; it is lifted here
    so the fired quantity is the sizer's alone."""
    mocker.patch.object(auto_trader.AutoTradeService, "_check_daily_loss",
                        return_value=0.0)


def _fire_reads(mocker, cfg) -> None:
    """The fire path sizes off `cfg`, not off the live scoring_rules.yaml."""
    mocker.patch.object(auto_trader, "_load_scoring_config", return_value=cfg)


def _floor_sized(base: int, conviction: float, cfg) -> int:
    return max(1, math.floor(base * conviction_mult(conviction, cfg) + 1e-9))


# ── Sentinel: the call is live on each path ──────────────────────────────────

def test_the_stock_card_actually_calls_the_ramp():
    with patch.object(stock_scan, "_conviction_mult", return_value=0.2):
        card = _run(_ON, omm_result=_omm(20))
    assert card.sizing_basis == "measured"
    assert card.shares == 25  # 125 x 0.2 — not the ramp's 103 at +20
    assert card.dollar_risk == pytest.approx(100.0)


def test_the_fire_path_actually_calls_the_ramp(mocker):
    _no_daily_loss_cap(mocker)
    mocker.patch.object(auto_trader, "conviction_mult", return_value=0.2)
    assert _fired_quantity(mocker, direction="Bullish", conviction=20,
                           quantity=_BASE) == 25


# ── Parity over the grid ─────────────────────────────────────────────────────

@pytest.mark.parametrize("cfg", _CONFIGS)
@pytest.mark.parametrize("conviction", _GRID)
def test_both_paths_size_the_same_base_to_the_same_quantity(mocker, conviction, cfg):
    _no_daily_loss_cap(mocker)
    _fire_reads(mocker, cfg)
    want = _floor_sized(_BASE, conviction, cfg)
    card = _run(cfg, omm_result=_omm(conviction))
    fired = _fired_quantity(mocker, direction="Bullish", conviction=conviction,
                            quantity=_BASE)
    assert card.shares == want, f"card at {conviction}"
    assert fired == want, f"fire at {conviction}"


@pytest.mark.parametrize("cfg", _CONFIGS)
def test_both_paths_size_an_unmeasured_regime_at_the_same_floor(mocker, cfg):
    """The `floor:unmeasured` branch reads min_mult on each side by its own
    route (`_sizing[0]` on the card, `resolve_sizing(cfg)[0]` on the fire
    path), not through the ramp. So it needs its own parity check."""
    _no_daily_loss_cap(mocker)
    _fire_reads(mocker, cfg)
    want = max(1, math.floor(_BASE * cfg["min_mult"] + 1e-9))
    card = _run(cfg, omm_result=None)
    assert card.sizing_basis == "floor:unmeasured"
    mocker.patch.object(auto_trader, "_sizing_conviction_for", return_value=None)
    fired = _fired_quantity(mocker, direction="Bullish", conviction=0, quantity=_BASE)
    assert (card.shares, fired) == (want, want)


def test_the_card_does_not_lose_a_share_on_an_exact_boundary():
    """Finding 3's own case: 50,000 x 1% x conviction_mult(-36) = 167.5 of risk,
    / 0.25 per share is exactly 670 — but the float quotient is
    669.9999999999999, which a bare int() truncated to 669."""
    mult = conviction_mult(-36, _ON)
    assert 50_000 * 0.01 * mult / 0.25 < 670  # the float really does fall short
    shares, _ = stock_scan._position_size(50_000, 0.01 * mult, None, 10.25, 10.0)
    assert shares == 670


# ── The headwind half is graded on the fire path (finding 7) ─────────────────

def test_the_fire_path_grades_the_opposed_half(mocker):
    """At quantity=4, -20 and -40 both fire 1, so the existing bearish tests
    cannot see the negative half being graded. At 10 they separate:
    floor(10 x 0.475) = 4 vs floor(10 x 0.30) = 3."""
    at_20 = _fired_quantity(mocker, direction="Bearish", conviction=-20, quantity=10)
    at_40 = _fired_quantity(mocker, direction="Bearish", conviction=-40, quantity=10)
    assert (at_20, at_40) == (4, 3)


# ── risk_fixed_usd reaches the card only as a positive finite number (r2 f2) ──

@pytest.mark.parametrize("bad", [0, -100, float("nan"), float("inf")])
def test_a_non_positive_or_non_finite_risk_fixed_is_refused_at_the_door(bad):
    from pydantic import ValidationError
    from app.schemas.stock_scan import StockScanRequest
    with pytest.raises(ValidationError):
        StockScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing",
                         strategy="pullback_ema", risk_fixed_usd=bad)


def test_a_fixed_risk_is_conviction_sized_like_a_percentage():
    """Driven through `_process_stock`, not `_position_size` (r3 finding 1):
    the earlier version applied the 0.65 by hand, so dropping `* mult` from
    the card's risk_fixed_usd branch passed every test. $200 at neutral
    (0.65) is $130 of risk, / 4 per share = 32 shares."""
    card = _run(_ON, omm_result=_omm(0), risk_fixed_usd=200.0)
    assert card.sizing_basis == "measured"
    assert (card.shares, card.dollar_risk) == (32, pytest.approx(130.0))


def test_a_fixed_risk_is_floored_when_unmeasured():
    card = _run(_ON, omm_result=None, risk_fixed_usd=200.0)
    assert card.sizing_basis == "floor:unmeasured"
    assert (card.shares, card.dollar_risk) == (15, pytest.approx(60.0))
