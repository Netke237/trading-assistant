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
        # Piece 3: the stock stop is RECEIVED, never derived here. Pinned to
        # what CFG's old flat 3% would have produced so every assertion in this
        # module that is not ABOUT the stop keeps measuring the same numbers it
        # always did.
        final_stop_price=318.73 * (1 - 0.03),
    )
    base.update(overrides)
    base.setdefault("entry_mid", base["premium"])
    # Explicit caller target retains these pricing-only characterization pins.
    base.setdefault("target_price", base["stock_price"] * (1.08 if base["direction"] == "Bullish" else .92))
    base.setdefault("stop_cost_fraction", None)
    return build_trade_plan(**base)


def test_premium_stop_is_pct_of_selected_premium():
    # This is the exact bug the fix set out to kill: the premium stop must be a
    # fraction of the SELECTED contract's premium, not the auto-pick's.
    p = _plan()
    assert p.premium_stop == 4.48          # 7.47 * 0.60
    assert p.entry.limit_price == 7.47     # limit = selected mid
    assert len(p.targets) == 3


def test_invalidation_is_the_stop_the_caller_passed():
    """PIECE 3. `invalidation_price` is `final_stop_price`, full stop.

    It used to be a flat percentage move off `stock_price` (rr_cfg's
    bullish_invalidation_pct), which measured the same -3% on every symbol in
    the universe regardless of where its structure sat. A value that is neither
    3% below nor derived from delta, passed with an rr_cfg that still carries
    the old keys, is what distinguishes "the stop is received" from "the stop
    is derived and the caller's argument was ignored".
    """
    p = _plan(final_stop_price=291.40)
    assert p.invalidation_price_raw == 291.40
    assert p.invalidation_price == 291.40
    # And nothing about it came from the config that still holds 0.03.
    assert round(p.invalidation_price_raw, 2) != round(318.73 * (1 - 0.03), 2)


def test_invalidation_ignores_rr_cfg_invalidation_pct_entirely():
    """The flat keys are dead here even when the caller sets them absurdly.

    A build_trade_plan that still read them would move the stop; this one
    cannot. Both directions, because the old code had a separate branch each.
    """
    loud_cfg = {**CFG, "bullish_invalidation_pct": 0.50, "bearish_invalidation_pct": 0.50}
    assert _plan(rr_cfg=loud_cfg, final_stop_price=291.40).invalidation_price == 291.40
    assert _plan(
        direction="Bearish", rr_cfg=loud_cfg, final_stop_price=340.10,
    ).invalidation_price == 340.10


def test_invalidation_is_floored_at_a_cent():
    """A caller cannot install a zero or negative stop.

    `estimate_stock_first_passage` switches on `invalidation_price > 0` to price
    the stop leg at all, so a 0 here would silently drop that leg rather than
    fail loudly.
    """
    assert _plan(final_stop_price=0.0).invalidation_price == 0.01
    assert _plan(final_stop_price=-5.0).invalidation_price == 0.01


def test_bearish_target_moves_down():
    p = _plan(direction="Bearish")
    assert p.target_price < 318.73


def test_final_stop_price_is_required():
    """Omitting the stop must be a TypeError, not a silent default.

    A default here -- of any kind -- would let a caller that forgot to resolve
    a stop ship a plan built around a level nobody chose, which is exactly the
    failure piece 3 exists to end, reintroduced quietly.
    """
    import pytest
    with pytest.raises(TypeError):
        build_trade_plan(
            direction="Bullish", stock_price=318.73, strike=375, dte=185,
            premium=7.47, entry_bid=7.34, entry_ask=7.59, entry_mid=7.47,
            rr_cfg=CFG,
        )


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


def test_heston_params_thread_through_to_a_clean_all_heston_ladder():
    """build_trade_plan must thread heston_params through to estimate_targets
    and surface all three levels Heston-priced, unfloored and increasing, on
    _plan()'s own default (deep-OTM, long-dated) fixture.

    RENAMED AND REWRITTEN BY PHASE F1 (2026-09-12). Like
    test_estimate_rr_put_heston_path_uses_correct_model_label in
    test_reward_risk.py, this test was NOT in the F1 spec's section 5.3 table,
    which named four pinned tests; six actually pinned pricer output, and this
    is the sixth. This was
    test_heston_params_floors_non_monotonic_target_instead_of_falling_back and
    asserted 12.47 / 12.47 / 15.34 — a T2 artifact dip floored up to T1. That
    dip was not an inherent property of heston_price()'s numerical
    integration, as this docstring used to claim; it was a defect in its
    Fourier inversion (a doubled frequency, 2i*phi*ln(S/K)), fixed and
    documented in
    docs/superpowers/plans/2026-09-12-heston-calibration-spec.md. This
    fixture's raw ladder is now 4.566571841077604 / 9.096729142615942 /
    15.485088007191706 — strictly increasing, so no level is floored and the
    old assertion was unstateable.

    COVERAGE NOTE, read before assuming this still guards the floor: it does
    not, and deliberately so. The flooring logic lives in
    reward_risk.estimate_targets, not here, and it is covered where it lives
    by the two monkeypatched tests in test_reward_risk.py
    (test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models
    and test_estimate_targets_put_floors_non_monotonic_heston_price), which
    force the dip rather than relying on the pricer having a bug — the right
    way to test a floor. See also
    test_estimate_targets_real_fixture_ladder_is_clean_and_all_heston for the
    reward_risk-level version of this clean-path assertion. What remains this
    test's job is the plumbing: that heston_params and horizon_preset reach
    the ladder at all.

    horizon_preset stays pinned rather than left to default because the
    ladder's prices are a property of the REPRICING HORIZON, not just of the
    fixture: "Annual" on this 185-DTE contract reprices at 80 days elapsed, so
    105 days remain, where the default (expiry_years * 0.5) would leave 92.5.
    Pinning it keeps these numbers deterministic the day the default
    changes."""
    from app.models.heston import HestonParams
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    # default fixture: stock=318.73, strike=375, dte=185
    p = _plan(heston_params=params, horizon_preset="Annual")
    assert [t.pricingMethod for t in p.targets] == [
        "Heston repriced", "Heston repriced", "Heston repriced",
    ]
    prices = [t.estimatedOptionPrice for t in p.targets]
    # AREA3 canonicalizes T1 to round(318.73 * 1.08, 2) = 344.23.
    # T3 spot is 318.73 + 2*(344.23-318.73) = 369.73,
    # Heston at the unchanged Annual horizon rounds its premium to 15.49.
    assert prices == [4.57, 9.1, 15.49]
    # Strictly increasing, not merely non-decreasing: an equality here would
    # mean the floor fired, i.e. the pricer regressed.
    assert prices[0] < prices[1] < prices[2]


def test_recompute_endpoint_matches_helper():
    # The endpoint must equal build_trade_plan for the same inputs — otherwise
    # the "single source of truth" claim is hollow. Reconstruct the helper call
    # exactly as the endpoint does (real risk_rules.yaml cfg, symmetric bid/ask
    # from spread) and compare field-by-field.
    from app.routers.contracts import router
    from app.services.config_loader import load_reward_risk_cfg as _rr_cfg

    premium, spread = 7.47, 0.25
    half = spread / 2
    # No final_stop in the request below, so the endpoint falls back to the
    # flat percentage -- reconstruct exactly that here.
    expected = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=premium,
        entry_bid=max(0.01, premium - half), entry_ask=premium + half,
        entry_mid=premium, rr_cfg=_rr_cfg(),
        final_stop_price=318.73 * (1 - _rr_cfg()["bullish_invalidation_pct"]),
        target_price=318.73 * (1 + 2 * _rr_cfg()["bullish_invalidation_pct"]),
        stop_cost_fraction=None,
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


def test_recompute_endpoint_falls_back_to_the_flat_pct_with_no_final_stop():
    # PIECE 3: a card with no resolved stop to round-trip (a scan session
    # persisted before piece 3, or a symbol whose bar feed was too thin) falls
    # back to the flat percentage. delta plays no part in it either way -- the
    # endpoint must still accept a request with no delta field.
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


def test_recompute_endpoint_horizon_preset_reaches_build_trade_plan():
    """Round 9 audit finding: horizon_preset/hold_min/hold_max are forwarded
    from RecomputePlanRequest into build_trade_plan (contracts.py:266-268),
    but no test ever POSTed a non-default horizon_preset over the wire and
    checked it actually changed the response -- every existing test either
    omits the field or calls build_trade_plan directly as a Python function,
    bypassing the router/Pydantic layer entirely. A future edit that drops or
    defaults horizon_preset in that forwarding line would ship silently: this
    pins that "Swing" (the implicit default) and "Annual" produce different
    Fixed % Ladder targets over the actual HTTP endpoint.

    dte=185 with risk_rules.yaml's real fallback_days table: Swing/absent
    resolves to 7 days, Annual resolves to 80 days clamped to
    0.75*185=138.75 -- both comfortably inside [min_days, dte], so the two
    must reprice at different remaining lives and therefore different target
    option prices."""
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    base_payload = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "delta": 0.24, "spread": 0.25,
    }
    r_default = client.post("/api/contracts/recompute-plan", json=base_payload)
    r_annual = client.post("/api/contracts/recompute-plan", json={
        **base_payload, "horizon_preset": "Annual",
    })
    assert r_default.status_code == 200, r_default.text
    assert r_annual.status_code == 200, r_annual.text

    default_targets = [t["estimatedOptionPrice"] for t in r_default.json()["exit"]["targets"]]
    annual_targets = [t["estimatedOptionPrice"] for t in r_annual.json()["exit"]["targets"]]
    assert default_targets != annual_targets, (
        "horizon_preset='Annual' produced the same ladder as the default -- "
        "the field is not reaching build_trade_plan through this endpoint"
    )

    # And it must match calling build_trade_plan directly with the same
    # horizon_preset -- the router isn't just changing SOMETHING, it's
    # changing to the right thing.
    from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
    expected_annual = build_trade_plan(
        direction="Bullish", stock_price=318.73, strike=375, dte=185,
        premium=7.47, entry_bid=max(0.01, 7.47 - 0.125), entry_ask=7.47 + 0.125,
        entry_mid=7.47, rr_cfg=_rr_cfg(), horizon_preset="Annual",
        final_stop_price=318.73 * (1 - _rr_cfg()["bullish_invalidation_pct"]),
        target_price=318.73 * (1 + 2 * _rr_cfg()["bullish_invalidation_pct"]),
        stop_cost_fraction=None,
    )
    assert annual_targets == [t.estimatedOptionPrice for t in expected_annual.targets]


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

def test_recompute_endpoint_rejects_negative_rr_target_multiple():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,
        "rr_target_r_multiple": -1,
    })
    assert r.status_code == 422


def test_recompute_endpoint_rejects_rr_target_multiple_above_cap():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/contracts/recompute-plan", json={
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,
        "rr_target_r_multiple": 10.01,
    })
    assert r.status_code == 422

# ── APP-AUDIT-B-ENTRY-OVERRIDES: entry_cfg & recompute entry overrides ───────

def test_build_trade_plan_applies_entry_config():
    from app.scoring.entry_quality import EntryConfig

    # 1. Zero slippage override
    p_zero_slip = _plan(entry_cfg=EntryConfig(max_slippage_pct=0.0))
    assert p_zero_slip.entry.max_fill == 7.47

    # 2. Default slippage (0.03)
    p_default = _plan()
    assert p_default.entry.max_fill == round(7.47 * 1.03, 2)
    assert p_default.entry.quality_status == "PASS"

    # 3. Dict override with high min premium (7.47 < 10.0 -> REJECT)
    p_reject_prem = _plan(entry_cfg={"entry_min_premium": 10.0})
    assert p_reject_prem.entry.quality_status == "REJECT"
    assert "premium too low" in p_reject_prem.entry.quality_reasons


def test_recompute_endpoint_applies_entry_overrides():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    base_payload = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "delta": 0.24, "spread": 0.25,
    }

    # Default without entry overrides uses 3% slippage: 7.47 * 1.03 = 7.69
    r_default = client.post("/api/contracts/recompute-plan", json=base_payload)
    assert r_default.status_code == 200, r_default.text
    assert r_default.json()["entry"]["maxFill"] == 7.69

    # With entry_max_slippage_pct = 0, maxFill == premium (7.47)
    r_zero_slip = client.post("/api/contracts/recompute-plan", json={
        **base_payload,
        "entry_max_slippage_pct": 0,
    })
    assert r_zero_slip.status_code == 200, r_zero_slip.text
    assert r_zero_slip.json()["entry"]["maxFill"] == 7.47

    # With custom slippage 0.05: 7.47 * 1.05 = 7.84
    r_custom = client.post("/api/contracts/recompute-plan", json={
        **base_payload,
        "entry_max_slippage_pct": 0.05,
    })
    assert r_custom.status_code == 200, r_custom.text
    assert r_custom.json()["entry"]["maxFill"] == 7.84


def test_recompute_endpoint_rejects_invalid_entry_overrides():
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    base = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 318.73,
        "strike": 375, "dte": 185, "premium": 7.47, "spread": 0.25,
    }

    # Negative spread tolerance
    r = client.post("/api/contracts/recompute-plan", json={
        **base, "entry_spread_tolerance_pct": -0.05,
    })
    assert r.status_code == 422

    # Spread tolerance > 1.0
    r = client.post("/api/contracts/recompute-plan", json={
        **base, "entry_spread_tolerance_pct": 1.5,
    })
    assert r.status_code == 422

    # Negative slippage
    r = client.post("/api/contracts/recompute-plan", json={
        **base, "entry_max_slippage_pct": -0.01,
    })
    assert r.status_code == 422

    # Slippage > 1.0
    r = client.post("/api/contracts/recompute-plan", json={
        **base, "entry_max_slippage_pct": 1.01,
    })
    assert r.status_code == 422

    # Negative min premium
    r = client.post("/api/contracts/recompute-plan", json={
        **base, "entry_min_premium": -0.5,
    })
    assert r.status_code == 422

    # Min premium > 100
    r = client.post("/api/contracts/recompute-plan", json={
        **base, "entry_min_premium": 150.0,
    })
    assert r.status_code == 422

