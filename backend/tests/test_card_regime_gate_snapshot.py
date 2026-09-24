"""Every options card carries the regime-gate rule its own scan resolved.

Decision AUTOTRADE-ARMED-TRADE-JUDGED-BY-ITS-SCANS-RULE-2026-09-21, closing
arm-door round 1's F1. The arm payload used to read the headwind thresholds
from the live Step-3 store at submit time; that store is not persisted and
survives a threshold edit or "Reset to defaults" without invalidating the
scan, so a trade could be armed under a rule its scan never used. The scan now
echoes the RESOLVED thresholds (YAML overlaid by the request's overrides) onto
every card, and the arm reads them from there.

What would go wrong quietly, and is pinned below:
1. The card describes a rule other than the one its scoring used -- e.g.
   echoing the raw request fields (None when Step 3 is untouched) instead of
   the resolved values, which would send "read the YAML" and re-open the gap
   across a restart that changes scoring_rules.yaml.
2. A zero threshold is dropped as falsy.
3. A card persisted before the field existed parses as if it had a rule.
"""
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.scan import _regime_gate_snapshot
from app.schemas import TradeCardData
from app.services.config_loader import load_scoring_cfg

from tests.test_scan_stop_cost import _OVERRIDES, _candles, _contract


def _scan(client, **body_extra):
    candles = _candles("MSFT")
    price = candles[-1]["close"]
    chain = [_contract(price, strike_mult=1.0)]
    with ExitStack() as stack:
        # Same hermetic patch set as test_scan_stop_cost._candidates, for the
        # reasons given there.
        stack.enter_context(patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
        stack.enter_context(patch("app.data.confidence_cache.get_cached",
                                  return_value={"confidence": 70, "sample_size": 40}))
        stack.enter_context(patch("app.data.confidence_cache.set_cached", AsyncMock()))
        stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
        stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles)))
        stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)))
        stack.enter_context(patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Test Co")))
        stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)))
        r = client.post("/api/scan", json={
            "universe": ["MSFT"], "direction": "Bullish", "horizon": "Swing",
            "overrides": _OVERRIDES, **body_extra,
        })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert cands, "fixture produced no surviving candidate; every assertion below would be vacuous"
    return cands


def test_an_untouched_step3_echoes_the_yaml_values_not_null(client):
    """Untouched Step 3 sends no threshold -- the card must still carry NUMBERS.

    Echoing null here would tell the fire path "read the YAML", which is the
    same answer only while the YAML has not changed since the scan.
    """
    yaml_gate = load_scoring_cfg()["regime_gate"]
    for c in _scan(client):
        assert c["regimeGate"] == {
            "headwindCautionPct": float(yaml_gate["headwind_caution_pct"]),
            "headwindRejectPct":  float(yaml_gate["headwind_reject_pct"]),
        }


def test_request_overrides_are_what_the_card_carries(client):
    for c in _scan(client, regime_headwind_caution_pct=-25, regime_headwind_reject_pct=-80):
        assert c["regimeGate"] == {"headwindCautionPct": -25.0, "headwindRejectPct": -80.0}


def test_a_zero_threshold_survives_onto_the_card(client):
    for c in _scan(client, regime_headwind_caution_pct=0, regime_headwind_reject_pct=0):
        assert c["regimeGate"] == {"headwindCautionPct": 0.0, "headwindRejectPct": 0.0}


@pytest.mark.parametrize("gate, expected", [
    ({"headwind_caution_pct": -15, "headwind_reject_pct": -40}, (-15.0, -40.0)),
    ({"headwind_caution_pct": 0, "headwind_reject_pct": 0.0}, (0.0, 0.0)),
    ({}, (None, None)),                                  # block carries no keys
    ({"headwind_reject_pct": True}, (None, None)),       # bool is not a percentage
    ({"headwind_reject_pct": "-40"}, (None, None)),      # malformed: fire path reads the same YAML
])
def test_snapshot_helper(gate, expected):
    s = _regime_gate_snapshot(gate)
    assert (s.headwindCautionPct, s.headwindRejectPct) == expected


def test_a_card_persisted_before_the_field_parses_as_having_no_rule():
    """A DB-restored or older card must read as None, which the Arm button refuses."""
    card = _scan_free_minimal_card()
    assert "regimeGate" not in card
    assert TradeCardData.model_validate(card).regimeGate is None


def _scan_free_minimal_card() -> dict:
    return {
        "symbol": "AAPL", "company": "Apple", "price": 100.0, "direction": "Bullish",
        "status": "PASS", "stockScore": 80, "stockConfidence": "PASS",
        "stockBreakdown": {"trend": 1, "pullback": 1, "trigger": 1, "event": 1, "volatility": 1},
        "contract": "AAPL|100|2026-12-18|C", "contractScore": 70, "contractConfidence": "PASS",
        "contractBreakdown": {"dteFit": 1, "delta": 1, "ivAttractiveness": 1, "liquidity": 1, "spread": 1},
        "contractDetails": {"strike": 100, "expiry": "2026-12-18", "right": "C", "mid": 2.5,
                            "delta": 0.5, "theta": -0.05, "dte": 30},
        "entry": {"limit": 2.5, "maxFill": 2.6, "orderType": "Limit"},
        "exit": {"invalidation": 95.0, "premiumStop": 1.5, "timeStopDays": 10, "target": 110.0},
        "rrRatio": 2.0, "rrModel": "Heston repriced", "finalStatus": "PASS",
    }
