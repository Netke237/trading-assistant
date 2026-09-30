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


def _no_daily_loss_cap(mocker) -> None:
    """125 contracts at $2.50 is $31,250 of premium, over the fixture's daily
    loss limit. That limit is a separate refusal, not sizing; it is lifted here
    so the fired quantity is the sizer's alone."""
    mocker.patch.object(auto_trader.AutoTradeService, "_check_daily_loss",
                        return_value=0.0)


def _floor_sized(base: int, conviction: float) -> int:
    return max(1, math.floor(base * conviction_mult(conviction, _ON) + 1e-9))


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

@pytest.mark.parametrize("conviction", _GRID)
def test_both_paths_size_the_same_base_to_the_same_quantity(mocker, conviction):
    _no_daily_loss_cap(mocker)
    want = _floor_sized(_BASE, conviction)
    card = _run(_ON, omm_result=_omm(conviction))
    fired = _fired_quantity(mocker, direction="Bullish", conviction=conviction,
                            quantity=_BASE)
    assert card.shares == want, f"card at {conviction}"
    assert fired == want, f"fire at {conviction}"


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
