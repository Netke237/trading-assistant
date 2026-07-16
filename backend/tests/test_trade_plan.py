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
