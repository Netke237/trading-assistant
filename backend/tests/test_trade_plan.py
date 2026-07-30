"""Characterization tests for the shared trade-plan math.

build_trade_plan is the single source of truth for the Entry/Exit/RR/targets
used by BOTH the scan pipeline and the POST /api/contracts/recompute-plan
endpoint. These tests pin its numeric behaviour so the two callers can't
silently drift, and guard the delta-floor regression found in review.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.trade_plan import build_trade_plan

# Fixed config so the assertions don't couple to risk_rules.yaml edits.
CFG = {"bullish_target_pct": 0.08, "bearish_target_pct": 0.08, "premium_stop_pct": 0.60}


def _plan(**overrides):
    base = dict(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=7.47, delta=0.24, entry_bid=7.34, entry_ask=7.59, rr_cfg=CFG,
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


def test_invalidation_matches_delta_approximation():
    p = _plan()
    # stock_stop_move = premium * pct / delta ; invalidation = spot - move (bullish)
    expected = 318.73 - (7.47 * 0.60 / 0.24)
    assert round(p.invalidation_price_raw, 2) == round(expected, 2)


def test_zero_delta_floors_at_005_not_default_045():
    # Regression guard: a legitimate 0.0 delta must floor at 0.05, NOT be coerced
    # to the 0.45 missing-key default (which would 9x the stop distance).
    p = _plan(delta=0.0)
    expected = 318.73 - (7.47 * 0.60 / 0.05)
    assert round(p.invalidation_price_raw, 2) == round(expected, 2)
    # And the 0.45 *default* is the caller's job, not the helper's: the helper
    # must NOT invent a default. Confirm 0.45 produces a different result.
    p45 = _plan(delta=0.45)
    assert round(p45.invalidation_price_raw, 2) == round(318.73 - (7.47 * 0.60 / 0.45), 2)
    assert p.invalidation_price_raw != p45.invalidation_price_raw


def test_bearish_target_moves_down():
    p = _plan(direction="Bearish", delta=-0.24)
    assert p.target_price < 318.73


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
        stock_price=185.0, strike=190.0, dte=30, premium=2.50, delta=0.45,
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
    from app.routers.contracts import router, _rr_cfg

    premium, spread = 7.47, 0.25
    half = spread / 2
    expected = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=premium, delta=0.24,
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


def test_recompute_endpoint_defaults_missing_delta_to_045():
    # The 0.45 default for a missing delta lives at the endpoint boundary (pydantic
    # default), mirroring scan's contract.get("delta", 0.45).
    from app.routers.contracts import router, _rr_cfg
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,  # no delta
    })
    assert r.status_code == 200, r.text
    expected_inval = round(318.73 - (7.47 * _rr_cfg()["premium_stop_pct"] / 0.45), 2)
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
