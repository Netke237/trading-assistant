"""Characterization tests for the shared trade-plan math.

build_trade_plan is the single source of truth for the Entry/Exit/RR/targets
used by BOTH the scan pipeline and the POST /api/contracts/recompute-plan
endpoint. These tests pin its numeric behaviour so the two callers can't
silently drift.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.trade_plan import build_trade_plan

# Fixed config so the assertions don't couple to risk_rules.yaml edits.
CFG = {
    "bullish_target_pct": 0.08, "bearish_target_pct": 0.08,
    "bullish_invalidation_pct": 0.03, "bearish_invalidation_pct": 0.03,
    "premium_stop_pct": 0.60,
}


def _plan(**overrides):
    base = dict(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=7.47, entry_bid=7.34, entry_ask=7.59, rr_cfg=CFG,
    )
    base.update(overrides)
    base.setdefault("entry_mid", base["premium"])
    return build_trade_plan(**base)


def test_premium_stop_is_pct_of_selected_premium():
    # This is the exact bug the fix set out to kill: the premium stop must be a
    # fraction of the SELECTED contract's premium, not the auto-pick's.
    p = _plan()
    assert p.premium_stop == 4.48          # 7.47 * 0.60
    assert p.entry.limit_price == 7.47     # limit = selected mid
    assert len(p.targets) == 3


def test_invalidation_is_stock_pct_move_not_delta_derived():
    # Finding 1 fix: invalidation is a stock-price percentage move off
    # bullish_invalidation_pct, mirroring target_price's own formula -- delta
    # no longer plays any part in it (the old formula back-calculated a stock
    # move from premium_stop_pct/delta; that was never what
    # bullish_invalidation_pct/bearish_invalidation_pct in risk_rules.yaml
    # actually documented).
    p = _plan()
    expected = 318.73 * (1 - 0.03)
    assert round(p.invalidation_price_raw, 2) == round(expected, 2)


def test_invalidation_uses_bearish_invalidation_pct_for_bearish():
    p = _plan(direction="Bearish")
    expected = 318.73 * (1 + 0.03)
    assert round(p.invalidation_price_raw, 2) == round(expected, 2)


def test_bearish_target_moves_down():
    p = _plan(direction="Bearish")
    assert p.target_price < 318.73


def test_default_rr_cfg_invalidation_matches_risk_rules_yaml():
    # Uses the REAL load_reward_risk_cfg() (not the fixed CFG constant) so a
    # future edit to risk_rules.yaml's bullish_invalidation_pct default is
    # caught here rather than silently drifting from what's displayed.
    from app.services.config_loader import load_reward_risk_cfg
    rr_cfg = load_reward_risk_cfg()
    p = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=7.47, entry_bid=7.34, entry_ask=7.59, entry_mid=7.47,
        rr_cfg=rr_cfg,
    )
    expected = round(318.73 * (1 - rr_cfg["bullish_invalidation_pct"]), 2)
    assert p.invalidation_price == expected


def test_merge_reward_risk_overrides_bullish_invalidation_pct_changes_plan():
    # Mirrors the existing rr_bullish_target_pct override pattern -- an
    # override to rr_bullish_invalidation_pct must actually change the
    # computed invalidation_price, not just the merged config dict.
    from app.services.config_loader import merge_reward_risk_overrides
    default_cfg = merge_reward_risk_overrides(None)
    overridden_cfg = merge_reward_risk_overrides({"rr_bullish_invalidation_pct": 0.10})

    default_plan = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=7.47, entry_bid=7.34, entry_ask=7.59, entry_mid=7.47,
        rr_cfg=default_cfg,
    )
    overridden_plan = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=7.47, entry_bid=7.34, entry_ask=7.59, entry_mid=7.47,
        rr_cfg=overridden_cfg,
    )
    assert overridden_plan.invalidation_price != default_plan.invalidation_price
    assert overridden_plan.invalidation_price == round(318.73 * (1 - 0.10), 2)


def test_heston_params_flow_through_to_rr_and_targets():
    from app.models.heston import HestonParams
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    # Override _plan()'s default fixture (stock=318.73, strike=375, dte=185) to
    # a well-behaved, not-deep-OTM/long-dated one. The default fixture is
    # exactly the shape that triggers Task 1's monotonicity guard for T2/T3 (a
    # real heston_price numerical-integration artifact — verified while
    # writing this plan: heston_price on the default fixture's T1/T2/T3 gives
    # 12.52 / 10.09 / 14.08, non-monotonic), which would make this "everything
    # is Heston-priced" happy-path test assert something that isn't true.
    p = _plan(
        heston_params=params,
        stock_price=185.0, strike=190.0, dte=30, premium=2.50,
        entry_bid=2.45, entry_ask=2.55,
    )
    assert p.rr_model == "Heston repriced"
    assert len(p.targets) == 3
    assert all(t.pricingMethod == "Heston repriced" for t in p.targets)


def test_heston_params_default_none_preserves_delta_approx():
    # No heston_params passed — must behave exactly as before this change.
    p = _plan()
    assert p.rr_model == "BS repriced (IV-derived)"


def test_heston_params_floors_non_monotonic_target_instead_of_falling_back():
    """Using _plan()'s own default (deep-OTM, long-dated) fixture together
    with heston_params: T1 is Heston-priced, T2's raw Heston price is a
    numerical artifact (verified directly against this exact fixture:
    12.518866931556794 / 10.086141661385824 / 14.081229812545331) and is
    floored up to T1's price rather than switched to the delta
    approximation, and T3's own legitimate Heston price is preserved
    unmodified — see backend/tests/test_reward_risk.py's
    test_estimate_targets_real_fixture_preserves_t3_after_t2_artifact for the
    reward_risk-level version of this same regression."""
    from app.models.heston import HestonParams
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    p = _plan(heston_params=params)  # default fixture: stock=318.73, strike=375, dte=185
    assert [t.pricingMethod for t in p.targets] == [
        "Heston repriced", "Heston repriced", "Heston repriced",
    ]
    prices = [t.estimatedOptionPrice for t in p.targets]
    assert prices == [12.52, 12.52, 14.08]


def test_recompute_endpoint_matches_helper():
    # The endpoint must equal build_trade_plan for the same inputs — otherwise
    # the "single source of truth" claim is hollow. Reconstruct the helper call
    # exactly as the endpoint does (real risk_rules.yaml cfg, symmetric bid/ask
    # from spread) and compare field-by-field.
    from app.routers.contracts import router
    from app.services.config_loader import load_reward_risk_cfg as _rr_cfg

    premium, spread = 7.47, 0.25
    half = spread / 2
    expected = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=premium,
        entry_bid=max(0.01, premium - half), entry_ask=premium + half,
        entry_mid=premium, rr_cfg=_rr_cfg(),
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": premium, "delta": 0.24, "spread": spread,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"]["limit"] == expected.entry.limit_price
    assert body["entry"]["maxFill"] == expected.entry.max_fill
    assert body["exit"]["premiumStop"] == expected.premium_stop
    assert body["exit"]["invalidation"] == expected.invalidation_price
    assert body["exit"]["timeStopDays"] == expected.time_stop_days
    assert body["rrRatio"] == expected.rr_ratio
    assert len(body["exit"]["targets"]) == len(expected.targets) == 3


def test_recompute_endpoint_uses_bullish_invalidation_pct_not_delta():
    # delta no longer affects invalidation at all (see Finding 1 fix) -- the
    # endpoint must still accept a request with no delta field (Pydantic
    # default kicks in) and computes invalidation purely from
    # bullish_invalidation_pct now, mirroring target_price's own formula.
    from app.routers.contracts import router
    from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,  # no delta
    })
    assert r.status_code == 200, r.text
    expected_inval = round(318.73 * (1 - _rr_cfg()["bullish_invalidation_pct"]), 2)
    assert r.json()["exit"]["invalidation"] == expected_inval


def test_recompute_endpoint_rejects_nonpositive_premium():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 0, "delta": 0.24, "spread": 0.25,
    })
    assert r.status_code == 422


# ── Finding 2c: rr_* bounds on RecomputePlanRequest itself ────────────────────

def test_recompute_endpoint_rejects_negative_rr_target_pct():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,
        "rr_bullish_target_pct": -1,
    })
    assert r.status_code == 422


def test_recompute_endpoint_rejects_rr_target_pct_above_cap():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,
        "rr_bullish_target_pct": 5.0,
    })
    assert r.status_code == 422
