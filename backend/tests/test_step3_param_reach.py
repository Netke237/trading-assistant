"""STEP3-PARAM-REACH: a scan echoes what Steps 5-7 must reuse.

ScanResult.rr_overrides -- the Reward/Risk overrides the scan priced its plans
with, so Step 7's recompute-plan does not reprice with Step-3 values edited
after the scan. ScanResult.request_context -- the direction / horizon / hold
days the result was produced from, so a result restored from /api/scan/last
into an empty browser does not fall back to Bullish / Swing in Steps 5-7.
"""

import pytest

from app.services.config_loader import effective_rr_overrides
from tests.test_step6_contract_rules import _scan_patches

_RR = {"rr_target_r_multiple": 2.5, "rr_bearish_invalidation_pct": 0.05}


def _post(client, body):
    with _scan_patches():
        return client.post("/api/scan", json={
            "universe": ["XOM"], "direction": "Bullish", "horizon": "Swing", **body,
        })


# ── effective_rr_overrides ────────────────────────────────────────────────────

def test_effective_rr_overrides_keeps_only_set_rr_keys_as_floats():
    assert effective_rr_overrides({**_RR, "min_volume": 5, "rr_bearish_target_pct": None}) == _RR
    assert effective_rr_overrides({"rr_target_r_multiple": 1}) == {"rr_target_r_multiple": 1.0}
    assert isinstance(effective_rr_overrides({"rr_target_r_multiple": 1})["rr_target_r_multiple"], float)


@pytest.mark.parametrize("overrides", [None, {}, {"min_volume": 5}])
def test_effective_rr_overrides_is_empty_when_none_set(overrides):
    assert effective_rr_overrides(overrides) == {}


@pytest.mark.parametrize("bad", [-0.1, 0, 10.01, "nan", "x"])
def test_effective_rr_overrides_validates_as_the_merge_does(bad):
    with pytest.raises(ValueError):
        effective_rr_overrides({"rr_target_r_multiple": bad})


# ── scan echo ─────────────────────────────────────────────────────────────────

def test_scan_records_the_rr_overrides_it_priced_with(client):
    r = _post(client, {"overrides": {**_RR, "min_volume": 20}})
    assert r.status_code == 200
    assert r.json()["rr_overrides"] == _RR


def test_scan_without_rr_overrides_records_an_empty_set(client):
    r = _post(client, {})
    assert r.status_code == 200
    assert r.json()["rr_overrides"] == {}


def test_an_invalid_rr_override_still_fails_the_scan_with_422(client):
    r = _post(client, {"overrides": {"rr_target_r_multiple": -1}})
    assert r.status_code == 422


def test_scan_records_its_request_context(client):
    r = _post(client, {
        "direction": "Bearish", "horizon": "Position", "horizon_preset": "Quarterly",
        "hold_min_days": 45, "hold_max_days": 60,
    })
    assert r.status_code == 200
    assert r.json()["request_context"] == {
        "universe": ["XOM"], "direction": "Bearish", "horizon": "Position",
        "horizon_preset": "Quarterly", "hold_min_days": 45, "hold_max_days": 60,
    }


def test_request_context_without_hold_days_or_preset_records_nulls(client):
    r = _post(client, {})
    assert r.status_code == 200
    assert r.json()["request_context"] == {
        "universe": ["XOM"], "direction": "Bullish", "horizon": "Swing",
        "horizon_preset": None, "hold_min_days": None, "hold_max_days": None,
    }


def test_last_scan_serves_both_echoes(client):
    r = _post(client, {"direction": "Bearish", "overrides": _RR,
                       "hold_min_days": 15, "hold_max_days": 45})
    assert r.status_code == 200
    last = client.get("/api/scan/last").json()
    assert last["scan_id"] == r.json()["scan_id"]
    assert last["rr_overrides"] == _RR
    assert last["request_context"]["direction"] == "Bearish"
    assert last["request_context"]["hold_max_days"] == 45


def test_a_result_from_before_the_echo_parses_with_both_absent():
    from app.schemas import ScanResult
    old = ScanResult.model_validate({"scan_id": "s", "timestamp": "t", "candidates": [], "rejected": []})
    assert old.rr_overrides is None
    assert old.request_context is None
