"""TRADING-REVIEW-PHASE-C-RR (review M7, decision D5): options R/R risks the
FULL premium unless a protective stop order is placed.

No protective option order is ever placed: the premium stop is an alert level
(services/premium_stop.py) and sizing already assumes the whole premium can be
lost. Dividing reward by `premium x premium_stop_pct` (0.60) therefore
overstated reward per unit of real risk by at least 1/0.6. `estimate_rr` and
`estimate_targets` now default to `protective_stop_order=False`, which divides
by the premium itself and reports `risk_basis == "full_premium"`. Passing True
reproduces the previous premium-stop / stock-stop basis exactly.
"""
from __future__ import annotations

import json

import pytest

from app.scoring.reward_risk import (
    _bs_reprice_or_delta_approx, _default_reprice_years, _derive_fallback_sigma,
    estimate_rr, estimate_targets, resolved_risk_dollars,
)
from app.scoring.trade_plan import build_trade_plan

PREMIUM = 2.00
PCT = 0.60

# Heston-free (heston_params=None) so the exit premium comes from the BS
# reprice, which is deterministic. 18 days to expiry, a 105 call on a 100 stock,
# repriced at a 108 target.
RR_ARGS = dict(
    stock_price=100.0, target_price=108.0, invalidation_price=96.0,
    strike=105.0, expiry_years=18 / 365, current_premium=PREMIUM, is_call=True,
    premium_stop_pct=PCT,
)
# A captured stock-stop fraction makes every figure cents-exact (premium, exit
# and risk are all rounded before dividing), so its expected values are exact.
STOCK_FRACTION = 0.25



def _exit(t_price: float) -> float:
    """The UNROUNDED exit premium estimate_rr / estimate_targets divide by
    (estimated_exit_premium / estimatedOptionPrice are rounded to cents for
    display, which can move the second decimal of the ratio). Same BS path,
    same inputs as RR_ARGS."""
    years = RR_ARGS["expiry_years"]
    sigma = _derive_fallback_sigma(PREMIUM, 100.0, 105.0, years, 0.05, True, 0.25)
    price, used_bs = _bs_reprice_or_delta_approx(
        t_price, 100.0, 105.0, _default_reprice_years(years), 0.05, sigma, True, PREMIUM)
    assert used_bs
    return max(price, 0.01)


LEVELS = (108.0, 112.0, 116.0)   # T1 = base, T2 = 1.5x move, T3 = 2x move

TARGET_ARGS = dict(
    stock_price=100.0, base_target_price=108.0, strike=105.0,
    expiry_years=18 / 365, current_premium=PREMIUM, is_call=True,
    premium_stop_pct=PCT,
)


# ── 1. estimate_rr ───────────────────────────────────────────────────────────

def test_estimate_rr_defaults_to_the_full_premium():
    res = estimate_rr(**RR_ARGS)
    assert res.estimated_exit_premium == round(_exit(108.0), 2)
    assert res.risk_basis == "full_premium"
    assert res.rr_ratio == round((_exit(108.0) - PREMIUM) / PREMIUM, 2)


def test_estimate_rr_full_premium_ignores_a_captured_stock_risk():
    res = estimate_rr(**RR_ARGS, risk_fraction=STOCK_FRACTION)
    assert res.risk_basis == "full_premium"
    assert res.rr_ratio == round((res.estimated_exit_premium - PREMIUM) / PREMIUM, 2)


def test_estimate_rr_with_a_protective_stop_order_keeps_todays_premium_stop_value():
    res = estimate_rr(**RR_ARGS, protective_stop_order=True)
    expected = round((_exit(108.0) - PREMIUM) / resolved_risk_dollars(PREMIUM, PCT, None), 2)
    assert res.risk_basis == "premium_stop"
    assert res.rr_ratio == expected


def test_estimate_rr_with_a_protective_stop_order_keeps_todays_stock_stop_value():
    res = estimate_rr(**RR_ARGS, risk_fraction=STOCK_FRACTION, protective_stop_order=True)
    expected = round((res.estimated_exit_premium - PREMIUM)
                     / resolved_risk_dollars(PREMIUM, PCT, STOCK_FRACTION), 2)
    assert res.risk_basis == "stock_stop"
    assert res.rr_ratio == expected


def test_the_full_premium_ratio_is_smaller_than_the_premium_stop_one():
    full = estimate_rr(**RR_ARGS).rr_ratio
    stop = estimate_rr(**RR_ARGS, protective_stop_order=True).rr_ratio
    assert full > 0
    assert full < stop


# ── 2. estimate_targets ──────────────────────────────────────────────────────

def test_estimate_targets_default_to_the_full_premium():
    levels = estimate_targets(**TARGET_ARGS)
    assert [lv.targetPrice for lv in levels] == list(LEVELS)
    for lv, t_price in zip(levels, LEVELS):
        assert lv.rrContribution == round((_exit(t_price) - PREMIUM) / PREMIUM, 2)


def test_estimate_targets_full_premium_ignores_a_captured_stock_risk():
    levels = estimate_targets(**TARGET_ARGS, risk_fraction=STOCK_FRACTION)
    for lv in levels:
        assert lv.rrContribution == round((lv.estimatedOptionPrice - PREMIUM) / PREMIUM, 2)


def test_estimate_targets_with_a_protective_stop_order_keep_todays_value():
    levels = estimate_targets(**TARGET_ARGS, protective_stop_order=True)
    risk = resolved_risk_dollars(PREMIUM, PCT, None)
    for lv, t_price in zip(levels, LEVELS):
        assert lv.rrContribution == round((_exit(t_price) - PREMIUM) / risk, 2)


def test_estimate_targets_with_a_protective_stop_order_keep_todays_stock_stop_value():
    levels = estimate_targets(**TARGET_ARGS, risk_fraction=STOCK_FRACTION, protective_stop_order=True)
    risk = resolved_risk_dollars(PREMIUM, PCT, STOCK_FRACTION)
    for lv in levels:
        assert lv.rrContribution == round((lv.estimatedOptionPrice - PREMIUM) / risk, 2)


# ── 3. build_trade_plan passes no flag ───────────────────────────────────────

def test_build_trade_plan_uses_the_full_premium_and_keeps_the_premium_stop_alert():
    plan = build_trade_plan(
        direction="Bullish", stock_price=100.0, strike=105.0, dte=18,
        premium=PREMIUM, entry_bid=1.95, entry_ask=2.05, entry_mid=PREMIUM,
        rr_cfg={"premium_stop_pct": PCT}, final_stop_price=96.0, target_price=108.0,
        stop_cost_fraction=None,
    )
    same = dict(RR_ARGS, reprice_years=plan.reprice_years)
    assert plan.rr_risk_basis == "full_premium"
    assert plan.rr_ratio == estimate_rr(**same).rr_ratio
    assert plan.rr_ratio != estimate_rr(**same, protective_stop_order=True).rr_ratio
    # The premium stop is the dollar ALERT level, unchanged by the R/R basis.
    assert plan.premium_stop == round(PREMIUM * PCT, 2) == 1.20
    targets = dict(TARGET_ARGS, reprice_years=plan.reprice_years)
    assert [t.rrContribution for t in plan.targets] == [t.rrContribution for t in estimate_targets(**targets)]
    assert ([t.rrContribution for t in plan.targets]
            != [t.rrContribution for t in estimate_targets(**targets, protective_stop_order=True)])


# ── Backend scan-result schema version: a pre-RR blob is refused ─────────────

class _StubResult:
    def __init__(self, row): self._row = row
    def scalar_one_or_none(self): return self._row


class _StubDb:
    def __init__(self, row): self._row = row
    async def execute(self, _stmt): return _StubResult(self._row)
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


@pytest.mark.asyncio
async def test_a_schema_2_scan_session_is_refused_and_scan_last_returns_null():
    """Schema 2 R/R values were computed on the premium-stop basis. The
    frontend's scanStore v18 branch discards them from localStorage, but
    StoreHydration refills a null scanResult from /scan/last -- so the backend
    must refuse the stored v2 blob too, or the old ratio comes straight back."""
    from app.routers import scan as scan_module

    orig = (scan_module._last_result, scan_module.AsyncSessionLocal,
            scan_module._last_status, scan_module._last_updated_at)
    scan_module._last_result = None
    blob = {"scan_id": "S2", "timestamp": "2026-10-01T10:00:00", "candidates": [],
            "rejected": [], "schema_version": 2}
    row = type("R", (), {"last_result_json": json.dumps(blob), "last_request_json": None,
                         "status": "complete", "updated_at": None})()
    scan_module.AsyncSessionLocal = lambda: _StubDb(row)
    try:
        await scan_module.restore_from_db()
        assert scan_module._last_result is None
        assert await scan_module.get_last_scan() is None
    finally:
        (scan_module._last_result, scan_module.AsyncSessionLocal,
         scan_module._last_status, scan_module._last_updated_at) = orig
