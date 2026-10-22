"""test_search_profiles_recalibration.py — Regression tests for the 18 Options Search Profiles recalibration.

Target: Issue #187 (SEARCH-PROFILES-RECAL-OPTIONS / PR #508).
Verifies:
- docs/search-profiles/search-profiles-export.json Schema Version 5 compliance.
- Preservation of all 18 stable profile IDs.
- Parameter matrix invariants across horizons, tiers, and directions.
- Pydantic model validation of ScanRequest payloads.
- Standalone CLI execution of backend/scripts/run_options_profiles_measurement.py in dry-run mode.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from app.schemas import ScanRequest
from scripts.run_options_profiles_measurement import (
    DEFAULT_PROFILES_FILE,
    profile_to_scan_request_payload,
    run_measurement,
    validate_profile_schema_v5,
)

EXPECTED_PROFILE_IDS: List[str] = [
    "mu2n6u2bxt11",  # Intraday_Baseline_Bullish
    "mu2n6u8qlkqx",  # Intraday_Restrictive_Bullish
    "mu2n6uh2o5iy",  # Intraday_Loose_Bullish
    "mu2n6us7zsyl",  # Intraday_Baseline_Bearish
    "mu2n6uz5ciqd",  # Intraday_Restrictive_Bearish
    "mu2n6v7g9r4p",  # Intraday_Loose_Bearish
    "mu2n6vi56pd4",  # Swing_Baseline_Bullish
    "mu2n6vokoroy",  # Swing_Restrictive_Bullish
    "mu2n6vvzvia6",  # Swing_Loose_Bullish
    "mu2n6w3ghw31",  # Swing_Baseline_Bearish
    "mu2n6wdkphqe",  # Swing_Restrictive_Bearish
    "mu2n6wlgp0oc",  # Swing_Loose_Bearish
    "mu2n6wtt37o9",  # SemiAnnual_Baseline_Bullish
    "mu2n6x4w0gb9",  # SemiAnnual_Restrictive_Bullish
    "mu2n6xcbasfh",  # SemiAnnual_Loose_Bullish
    "mu2n6xjqcewd",  # SemiAnnual_Baseline_Bearish
    "mu2n6xtffvnn",  # SemiAnnual_Restrictive_Bearish
    "mu2n6y1r5fyf",  # SemiAnnual_Loose_Bearish
]


@pytest.fixture
def export_payload() -> Dict[str, Any]:
    assert DEFAULT_PROFILES_FILE.exists(), f"Missing export file at {DEFAULT_PROFILES_FILE}"
    with open(DEFAULT_PROFILES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_export_file_has_18_profiles_and_schema_version_5(export_payload: Dict[str, Any]):
    assert export_payload.get("version") == 5
    profiles = export_payload.get("state", {}).get("profiles", [])
    assert len(profiles) == 18

    ids = [p.get("id") for p in profiles]
    assert ids == EXPECTED_PROFILE_IDS

    for p in profiles:
        assert p.get("mode") == "options"
        assert "strategy" not in p
        assert "strategyParams" not in p
        # Schema v5 validation
        errors = validate_profile_schema_v5(p)
        assert errors == [], f"Validation errors for profile {p.get('id')}: {errors}"


def test_every_profile_validates_as_pydantic_scan_request(export_payload: Dict[str, Any]):
    profiles = export_payload.get("state", {}).get("profiles", [])
    for p in profiles:
        payload = profile_to_scan_request_payload(p)
        # Verify Pydantic v2 validation succeeds without raising ValidationError
        scan_req = ScanRequest.model_validate(payload)
        assert scan_req.direction in ("Bullish", "Bearish")
        assert scan_req.horizon in ("Intraday", "Swing", "Position")
        assert scan_req.horizon_preset in ("Intraday", "Swing", "SemiAnnual")
        assert scan_req.overrides.get("shortlist_max_candidates") == p["scanSettings"]["shortlistMaxCandidates"]


def test_parameter_matrix_and_liquidity_overrides(export_payload: Dict[str, Any]):
    profiles = export_payload.get("state", {}).get("profiles", [])
    for p in profiles:
        direction = p["direction"]
        name = p["name"]
        horizon_preset = p["horizonPreset"]
        ss = p["scanSettings"]
        overrides = p["scanOverrides"]

        # Fundamentals D/E gate: Bullish 3, Bearish 10
        assert ss["fundamentalsGate"]["deReject"] == (3 if direction == "Bullish" else 10)

        # SemiAnnual event window overrides: 7 / 30 across all 6 SemiAnnual profiles
        if horizon_preset == "SemiAnnual":
            assert overrides.get("event_reject_days") == 7
            assert overrides.get("event_caution_days") == 30
        else:
            assert "event_reject_days" not in overrides
            assert "event_caution_days" not in overrides

        # Tier-specific liquidity overrides
        if "_Baseline_" in name:
            assert ss["shortlistMaxCandidates"] == 10
            if horizon_preset != "SemiAnnual":
                assert overrides == {}
            else:
                assert overrides == {"event_reject_days": 7, "event_caution_days": 30}
        elif "_Restrictive_" in name:
            assert ss["shortlistMaxCandidates"] == 10
            assert overrides.get("max_bid_ask_spread_pct") == 0.08
            assert overrides.get("min_open_interest") == 1000
            assert overrides.get("min_volume") == (50 if horizon_preset == "SemiAnnual" else 200)
        elif "_Loose_" in name:
            assert ss["shortlistMaxCandidates"] == 20
            assert overrides.get("max_bid_ask_spread_pct") == 0.3
            assert overrides.get("preferred_spread_pct_max") == 0.3
            assert overrides.get("min_volume") == 0
            assert overrides.get("preferred_volume_min") == 20
            assert overrides.get("min_open_interest") == 75
            assert overrides.get("preferred_oi_min") == 75


def test_run_options_profiles_measurement_dry_run():
    report = run_measurement(
        profiles_path=DEFAULT_PROFILES_FILE,
        dry_run=True,
    )
    assert report["total_profiles"] == 18
    assert report["valid_count"] == 18
    assert report["failure_count"] == 0
    assert len(report["results"]) == 18


def test_run_options_profiles_measurement_single_profile():
    report = run_measurement(
        profiles_path=DEFAULT_PROFILES_FILE,
        dry_run=True,
        profile_id_filter="mu2n6u2bxt11",
    )
    assert report["total_profiles"] == 1
    assert report["valid_count"] == 1
    assert report["failure_count"] == 0
    assert report["results"][0]["id"] == "mu2n6u2bxt11"


def test_run_options_profiles_measurement_rejects_malformed_profile():
    malformed_profile = {
        "id": "bad-1",
        "name": "Bad_Profile",
        "mode": "options",
        # missing direction, missing confidenceGate, missing universe
    }
    errors = validate_profile_schema_v5(malformed_profile)
    assert len(errors) > 0
    assert any("universe" in e for e in errors)
    assert any("direction" in e for e in errors)

    # Options profile with strategy fields defined must be rejected
    options_with_strategy = {
        "id": "mu2n6u2bxt11",
        "name": "Intraday_Baseline_Bullish",
        "mode": "options",
        "direction": "Bullish",
        "horizonPreset": "Intraday",
        "createdAt": "2026-09-15T12:22:42.610Z",
        "updatedAt": "2026-10-22T00:00:00.000Z",
        "holdMin": 0,
        "holdMax": 2,
        "universe": {
            "pick": "SP500",
            "customRaw": "",
            "minPriceRaw": "",
            "maxPriceRaw": "",
            "minCapRaw": "",
            "maxCapRaw": "",
            "capUnit": "B",
        },
        "scanOverrides": {},
        "scanSettings": {
            "confidenceGate": {
                "enabled": True,
                "cautionBelow": 50,
                "rejectBelow": 35,
                "atrMult": {
                    "intraday": {"target": 2, "stop": 1.5},
                    "swing": {"target": 3, "stop": 1.5},
                    "position": {"target": 2.5, "stop": 1.5},
                },
            },
            "fundamentalsGate": {"enabled": True, "cautionBelow": 45, "rejectBelow": 30, "deReject": 3},
            "shortlistMaxCandidates": 10,
            "spreads": {
                "shortLegDelta": 0.3,
                "widthPoints": 5,
                "ivRankThreshold": 50,
                "ivAbsThreshold": 50,
                "minCredit": 0.5,
                "maxDebitPctOfWidth": 40,
            },
        },
        "strategy": "pullback_ema",  # illegal in options mode!
    }
    strat_errors = validate_profile_schema_v5(options_with_strategy)
    assert any("strategy" in e for e in strat_errors)
