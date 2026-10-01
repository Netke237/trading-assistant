from app.scoring.contract_validator import dte_holding_multiplier


def test_multiplier_loads_from_config():
    assert dte_holding_multiplier() == 2.0


from datetime import date, timedelta

from app.scoring.contract_validator import validate_contract


def _expiry_str(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def _make_contract(*, bid=1.0, ask=1.10, delta=0.45, days=40, volume=500, oi=1000) -> dict:
    return {
        "symbol": "AAPL",
        "strike": 185,
        "expiry": _expiry_str(days),
        "is_call": True,
        "bid": bid,
        "ask": ask,
        "price": (bid + ask) / 2,
        "delta": delta,
        "theta": -0.05,
        "volume": volume,
        "open_interest": oi,
        "iv_rank": 30,
        "ivRank": 30,
    }


def test_preferred_dte_override_centres_the_soft_score():
    """A 365-DTE contract scores poorly against the fixed 21-60 default preferred
    band, but should score near-perfectly once the preferred band is overridden
    to match a 330-400 DTE Annual window (centre 365)."""
    contract = _make_contract(days=365)
    card_default   = validate_contract(contract, 70)
    card_annual_ov = validate_contract(
        contract, 70,
        overrides={"min_dte": 330, "max_dte": 400, "preferred_dte_min": 330, "preferred_dte_max": 400},
    )
    assert "dte_outside_preferred" in card_default.soft_flags
    assert "dte_outside_preferred" not in card_annual_ov.soft_flags
    assert card_annual_ov.breakdown.dte_score > card_default.breakdown.dte_score


def test_preferred_dte_override_does_not_affect_hard_reject_alone():
    """Setting only preferred_dte_* (no min_dte/max_dte) must not change hard-reject
    behaviour — it only affects the soft score."""
    contract = _make_contract(days=10)  # below default hard min_dte=21
    card = validate_contract(contract, 70, overrides={"preferred_dte_min": 5, "preferred_dte_max": 15})
    assert "dte_too_short" in card.reject_reasons


def test_tolerance_widened_hard_reject_accepts_a_chain_fetch_fallback_contract():
    """Reproduces the Semi-annual (180-210d) pipeline bug: the chain-fetch
    fallback (_nearest_expiration_in_window's tolerance) can hand back a 179d
    contract for a 180-210d window. Without widening the validator's own
    min_dte/max_dte by the same DTE_WINDOW_TOLERANCE_DAYS margin (as
    scan.py's contract_overrides now does), that contract would be
    hard-rejected as dte_too_short immediately after the fetch accepted it —
    the fix must apply on both sides of the fetch/validate boundary."""
    from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS, widened_min_dte

    contract = _make_contract(days=179)
    lo, hi = 180, 210

    card_raw = validate_contract(
        contract, 70,
        overrides={"min_dte": lo, "max_dte": hi, "preferred_dte_min": lo, "preferred_dte_max": hi},
    )
    assert "dte_too_short" in card_raw.reject_reasons

    card_widened = validate_contract(
        contract, 70,
        overrides={
            "min_dte": widened_min_dte(lo, hold_max_days=105),  # Semi-annual hold_max
            "max_dte": hi + DTE_WINDOW_TOLERANCE_DAYS,
            "preferred_dte_min": lo,
            "preferred_dte_max": hi,
        },
    )
    assert "dte_too_short" not in card_widened.reject_reasons


def test_widened_min_dte_floors_at_hold_max_for_narrow_horizons():
    """Adversarial-audit finding: a flat 10-day tolerance subtraction is safe
    for wide windows but not narrow ones. Swing (hold 5-15d -> lo=10) minus a
    flat 10 days would drop the floor to 1 — letting through a contract that
    expires before a 15-day hold is even over, which directly contradicts this
    module's "dte must exceed the intended hold" rule. The floor must never
    drop below hold_max_days + 1."""
    from app.scoring.dte_window import widened_min_dte

    assert widened_min_dte(10, hold_max_days=15) == 16  # Swing
    assert widened_min_dte(30, hold_max_days=45) == 46   # Position


def test_widened_min_dte_matches_flat_tolerance_for_wide_horizons():
    """Semi-annual/Annual: hold_max_days is already far below lo - tolerance,
    so the hold_max floor is a no-op and the original AAPL 179d fix (full
    10-day tolerance) is unaffected by the narrow-horizon guard."""
    from app.scoring.dte_window import widened_min_dte

    assert widened_min_dte(90, hold_max_days=60) == 80    # Quarterly
    assert widened_min_dte(180, hold_max_days=105) == 170  # Semi-annual
    assert widened_min_dte(330, hold_max_days=200) == 320  # Annual


def test_widened_min_dte_without_hold_max_skips_the_clamp():
    """No holding-horizon override in play (hold_max_days=None) -> no intended
    hold to protect, so only the flat tolerance applies."""
    from app.scoring.dte_window import widened_min_dte

    assert widened_min_dte(180, hold_max_days=None) == 170
    assert widened_min_dte(10, hold_max_days=None) == 1


def test_swing_hard_reject_still_blocks_a_contract_expiring_before_the_hold_ends():
    """A 12-DTE contract for a Swing 5-15d hold would (under a flat, unclamped
    10-day tolerance) have been wrongly accepted — the option would expire
    before the 15-day hold is over. With the hold_max floor it must still be
    hard-rejected."""
    from app.scoring.dte_window import widened_min_dte

    contract = _make_contract(days=12)
    lo, hi, hold_max = 10, 30, 15
    card = validate_contract(contract, 70, overrides={
        "min_dte": widened_min_dte(lo, hold_max),
        "max_dte": hi + 10,
        "preferred_dte_min": lo, "preferred_dte_max": hi,
    })
    assert "dte_too_short" in card.reject_reasons


import pytest
from pydantic import ValidationError

from app.schemas import DteWindow, ScanRequest, ScanResult


def test_scan_request_accepts_hold_days():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bullish",
        "horizon": "Position",
        "hold_min_days": 15,
        "hold_max_days": 45,
    })
    assert req.hold_min_days == 15
    assert req.hold_max_days == 45


def test_scan_request_hold_days_default_none():
    req = ScanRequest.model_validate({
        "universe": ["AAPL"],
        "direction": "Bullish",
        "horizon": "Position",
    })
    assert req.hold_min_days is None
    assert req.hold_max_days is None


def test_scan_request_rejects_inverted_hold_range():
    """D9: an inverted range must be a clean validation error, not a 500 later
    when dte_window() raises."""
    with pytest.raises(ValidationError):
        ScanRequest.model_validate({
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Position",
            "hold_min_days": 100, "hold_max_days": 15,
        })


def test_scan_request_rejects_negative_hold_days():
    with pytest.raises(ValidationError):
        ScanRequest.model_validate({
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Position",
            "hold_min_days": -5, "hold_max_days": 15,
        })


def test_scan_result_carries_dte_window():
    result = ScanResult(
        scan_id="REC-1",
        timestamp="2026-07-10T00:00:00Z",
        candidates=[],
        rejected=[],
        dte_window=DteWindow(min_dte=30, max_dte=90, multiplier=2.0),
    )
    assert result.dte_window.min_dte == 30
    assert result.dte_window.max_dte == 90
    assert result.dte_window.multiplier == 2.0


def test_scan_result_dte_window_defaults_none():
    result = ScanResult(scan_id="REC-1", timestamp="t", candidates=[], rejected=[])
    assert result.dte_window is None


from app.scoring.dte_window import dte_window


def test_position_hold_rejects_the_reported_22_dte_contract():
    """The 31.07.2026 case: a 22-DTE contract must not survive a 15-45 day hold."""
    min_dte, max_dte = dte_window(15, 45, 2.0)
    card = validate_contract(_make_contract(days=22), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte,
                                        "preferred_dte_min": min_dte, "preferred_dte_max": max_dte})
    assert "dte_too_short" in card.reject_reasons


def test_position_hold_accepts_a_60_dte_contract():
    min_dte, max_dte = dte_window(15, 45, 2.0)
    card = validate_contract(_make_contract(days=60), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte,
                                        "preferred_dte_min": min_dte, "preferred_dte_max": max_dte})
    assert "dte_too_short" not in card.reject_reasons
    assert "dte_too_long" not in card.reject_reasons


def test_annual_hold_accepts_a_365_dte_contract_and_scores_it_cleanly():
    min_dte, max_dte = dte_window(165, 200, 2.0)
    card = validate_contract(_make_contract(days=365), 70,
                             overrides={"min_dte": min_dte, "max_dte": max_dte,
                                        "preferred_dte_min": min_dte, "preferred_dte_max": max_dte})
    assert "dte_too_short" not in card.reject_reasons
    assert "dte_too_long" not in card.reject_reasons
    assert "dte_outside_preferred" not in card.soft_flags


import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_get_contracts_applies_hold_day_dte_window(monkeypatch):
    """A hold of 165-200 days (Annual) must restrict returned contracts to 330-400 DTE."""
    near_contract = {
        "id": "AAPL|185|near|C", "symbol": "AAPL", "strike": 185,
        "expiry": _expiry_str(40), "dte": 40, "dteTotal": 40,
        "price": 2.0, "bid": 1.9, "ask": 2.1, "delta": 0.45, "theta": -0.05,
        "volume": 500, "open_interest": 1000, "iv_rank": 30,
    }
    far_contract = {
        **near_contract, "id": "AAPL|185|far|C",
        "expiry": _expiry_str(365), "dte": 365, "dteTotal": 365,
    }
    async def _fake_option_chain(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        return [far_contract] if dte_bounds == (330, 400) else [near_contract, far_contract]

    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_option_chain)
    # get_contracts() also calls fetch_price_async() unconditionally (contracts.py:46), which
    # otherwise makes a real Tradier/yfinance network call in a test run — the same reason
    # backend/tests/conftest.py's `client` fixture patches both together.
    async def _fake_price(client, symbol):
        return 190.0

    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    resp = client.get("/api/contracts", params={
        "symbol": "AAPL", "right": "C", "hold_min_days": 165, "hold_max_days": 200,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["dte"] == 365


def test_get_contracts_without_hold_days_keeps_legacy_behaviour(monkeypatch):
    """No hold days -> dte_bounds=None -> unchanged from today's behaviour."""
    calls = []
    async def _fake_fetch(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        calls.append(dte_bounds)
        return []
    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_fetch)
    async def _fake_price(client, symbol):
        return 190.0
    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    client.get("/api/contracts", params={"symbol": "AAPL", "right": "C"})
    assert calls == [None]


def test_get_contracts_does_not_hard_reject_a_tolerance_fallback_expiry(monkeypatch):
    """Reproduces the Step 6 Contracts "everything shows REJECT" bug: for a
    180-210d window, fetch_option_chain's tolerance fallback can hand back a
    179d contract (see test_falls_back_to_nearest_expiry_within_tolerance_when_
    window_is_empty in test_option_chain_expiry_selection.py). Without widening
    /api/contracts' own min_dte/max_dte override by the same tolerance, that
    179d contract was hard-rejected here as dte_too_short — forcing score=0
    (contract_validator.py:256) — so every contract the frontend's
    statusForScore() saw came back REJECT, even though the fetch had already
    accepted the expiry as a reasonable stand-in."""
    contract_179d = {
        "id": "AAPL|330|179d|C", "symbol": "AAPL", "strike": 330,
        "expiry": _expiry_str(179), "dte": 179, "dteTotal": 179,
        "price": 27.1, "bid": 26.85, "ask": 27.4, "delta": 0.558, "theta": -0.02,
        "volume": 224, "open_interest": 19059, "iv_rank": 30,
    }
    async def _fake_option_chain(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        return [contract_179d]

    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_option_chain)
    async def _fake_price(client, symbol):
        return 326.59
    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    resp = client.get("/api/contracts", params={
        "symbol": "AAPL", "right": "C", "hold_min_days": 90, "hold_max_days": 105,
        "max_price": 50.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["score"] > 0   # score=0 is the hard-reject sentinel


def test_get_contracts_still_rejects_a_too_short_contract_for_a_narrow_horizon(monkeypatch):
    """The tolerance widening must not let a Swing (5-15d hold) scan accept a
    12-DTE contract, which would expire before the 15-day hold is over. This
    is the /api/contracts-endpoint counterpart of
    test_swing_hard_reject_still_blocks_a_contract_expiring_before_the_hold_ends
    in test_horizon_dte.py — same guard, different call site."""
    contract_12d = {
        "id": "AAPL|185|12d|C", "symbol": "AAPL", "strike": 185,
        "expiry": _expiry_str(12), "dte": 12, "dteTotal": 12,
        "price": 2.0, "bid": 1.9, "ask": 2.1, "delta": 0.45, "theta": -0.05,
        "volume": 500, "open_interest": 1000, "iv_rank": 30,
    }
    async def _fake_option_chain(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        return [contract_12d]

    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_option_chain)
    async def _fake_price(client, symbol):
        return 190.0
    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    resp = client.get("/api/contracts", params={
        "symbol": "AAPL", "right": "C", "hold_min_days": 5, "hold_max_days": 15,
        "max_price": 50.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["score"] == 0   # still hard-rejected — expires before the hold ends


def test_equal_min_max_dte_override_does_not_divide_by_zero():
    """Found by adversarial audit: a Custom range typed as the same day twice
    (e.g. hold_min_days == hold_max_days) makes dte_window() legitimately return
    min_dte == max_dte. The preferred-band soft score's half_range = (max-min)/2
    then collapses to 0, and a contract landing exactly on that DTE (guaranteed,
    since _nearest_expiration_in_window only returns expiries strictly inside the
    window) triggered a ZeroDivisionError. Must score cleanly instead of crashing."""
    contract = _make_contract(days=30)
    card = validate_contract(
        contract, 70,
        overrides={"min_dte": 30, "max_dte": 30, "preferred_dte_min": 30, "preferred_dte_max": 30},
    )
    assert "dte_outside_preferred" not in card.soft_flags
    assert card.breakdown.dte_score == 100


def test_equal_min_max_delta_override_does_not_divide_by_zero():
    """Same collapse hazard in _score_delta(), fixed defensively even though no
    current caller overrides min_delta/max_delta to equal values."""
    from app.scoring.contract_validator import _score_delta

    cfg = {"soft_rank": {"preferred_delta_min": 0.45, "preferred_delta_max": 0.45}}
    score, flags = _score_delta({"delta": 0.45}, cfg)
    assert score == 100
    assert flags == []


def test_get_contracts_falls_back_gracefully_on_misconfigured_multiplier(monkeypatch):
    """Round-2 audit finding: contracts.py had the same unguarded dte_window()
    call as scan.py's round-1 fix addressed, just on the sibling endpoint. A
    misconfigured dte_holding_multiplier (0 here) must not 500 /api/contracts."""
    monkeypatch.setattr("app.routers.contracts.dte_holding_multiplier", lambda: 0.0)
    async def _fake_option_chain(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        return []
    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_option_chain)
    async def _fake_price(client, symbol):
        return 190.0
    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    resp = client.get("/api/contracts", params={
        "symbol": "AAPL", "right": "C", "hold_min_days": 15, "hold_max_days": 45,
    })
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_contracts_rejects_inverted_hold_range(monkeypatch):
    """Parity with ScanRequest: an inverted range must be a clean 422, not a
    silent fallback to default DTE bounds. Also checks the response body's
    top-level shape matches FastAPI's own validation-error format — `detail`
    is a list of {loc, msg, type} dicts, same as /api/scan's ScanRequest
    model_validator — so a client that parses `detail` as a list (not a bare
    string) works against both endpoints. The `loc` contents legitimately
    differ (this is a query-param check, /api/scan's is a whole-body check) —
    only the list-of-dicts envelope is asserted here, not exact loc equality."""
    async def _fake_option_chain(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        return []
    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_option_chain)
    async def _fake_price(client, symbol):
        return 190.0
    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    resp = client.get("/api/contracts", params={
        "symbol": "AAPL", "right": "C", "hold_min_days": 100, "hold_max_days": 15,
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)
    assert "hold_max_days" in detail[0]["msg"]


def test_get_contracts_passes_the_validator_floor_to_the_expiry_pick(monkeypatch):
    """The fetch picks ONE expiry. If it may pick below the validator's floor
    (hold_max + 1), every contract comes back dte_too_short. A Custom 15-200d
    hold is window (30, 400) at multiplier 2, floor 201: the fetch must be told."""
    calls = []
    async def _fake_fetch(client, symbol, expiry=None, option_type="C", dte_bounds=None, min_dte_floor=None, dte_limits=None):
        calls.append((dte_bounds, min_dte_floor))
        return []
    monkeypatch.setattr("app.routers.contracts.fetch_option_chain_async", _fake_fetch)
    async def _fake_price(client, symbol):
        return 190.0
    monkeypatch.setattr("app.routers.contracts.fetch_price_async", _fake_price)
    client = TestClient(app)
    client.get("/api/contracts", params={"symbol": "AAPL", "right": "C",
                                          "hold_min_days": 15, "hold_max_days": 200})
    assert calls == [((30, 400), 201)]
