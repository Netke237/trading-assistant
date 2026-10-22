"""End-to-end integration tests for Options contract floor override (Board #389, AC 1-7)."""
from __future__ import annotations

import math
import pytest

from app.scoring.contract_validator import (
    validate_contract,
    effective_contract_overrides,
    _int_score_floor,
    _load_config,
)


def _base_contract(**overrides):
    c = {
        "symbol": "TEST",
        "strike": 100.0,
        "expiry": "2026-11-20",
        "is_call": True,
        "bid": 2.00,
        "ask": 2.10,
        "volume": 500,
        "open_interest": 2000,
        "delta": 0.45,
        "iv_rank": 30.0,
    }
    c.update(overrides)
    return c


def test_ac1_manual_options_scan_with_override_passes_intermediate_stock_score():
    """AC 1: When contract_min_stock_score is set to 30, an underlying with stock
    score 35 (which fails default 45) passes contract floor validation."""
    # Under default YAML 45, score 35 is rejected
    card_default = validate_contract(_base_contract(), stock_score=35, overrides={})
    assert "stock_score_below_threshold" in card_default.reject_reasons

    # With contract_min_stock_score override set to 30, score 35 passes
    card_overridden = validate_contract(
        _base_contract(),
        stock_score=35,
        overrides={"contract_min_stock_score": 30},
    )
    assert "stock_score_below_threshold" not in card_overridden.reject_reasons

    # Effective contract overrides records min_stock_score: 30
    eff = effective_contract_overrides({"contract_min_stock_score": 30})
    assert eff["min_stock_score"] == 30
    assert "contract_min_stock_score" not in eff


def test_ac2_field_reset_applies_yaml_default_45():
    """AC 2: When field is reset (cleared/empty), contract_rules.yaml default (45)
    applies, rejecting stock score < 45 and recording no override in contract_rules."""
    card = validate_contract(_base_contract(), stock_score=40, overrides={})
    assert "stock_score_below_threshold" in card.reject_reasons

    # At or above 45, it passes
    card_pass = validate_contract(_base_contract(), stock_score=45, overrides={})
    assert "stock_score_below_threshold" not in card_pass.reject_reasons

    # Effective overrides for empty dict has no min_stock_score
    eff = effective_contract_overrides({})
    assert "min_stock_score" not in eff


@pytest.mark.asyncio
async def test_ac3_scheduled_options_scan_preserves_contract_min_stock_score(monkeypatch):
    """AC 3: Scheduled options scan saved with contract_min_stock_score at 30
    retains the override and dispatches it to scan core."""
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from tests.test_scan_schedule import _options_entry_body
    from tests.conftest import _TestSession
    import app.database as dbmod

    entry = _options_entry_body(resolved_request={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
        "overrides": {"contract_min_stock_score": 30, "min_volume": 10},
    })
    entry["id"] = "e2e-sched-1"
    scan_schedule_store.upsert(entry)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    seen = []

    async def _fake_core(req, db, previous_result=None):
        seen.append(req)
        raise RuntimeError("stop here")

    async def _quiet(*a, **k):
        return None

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _fake_core)
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _quiet)
    try:
        await sss._run_scheduled_entry("e2e-sched-1")
        assert len(seen) == 1
        assert seen[0].overrides["contract_min_stock_score"] == 30
    finally:
        scan_schedule_store.delete("e2e-sched-1")


@pytest.mark.asyncio
async def test_ac4_legacy_schedule_with_min_stock_score_is_stripped(monkeypatch):
    """AC 4: Legacy schedule whose overrides carries min_stock_score is still
    stripped by scheduler, and thus evaluates on YAML 45."""
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from tests.test_scan_schedule import _options_entry_body
    from tests.conftest import _TestSession
    import app.database as dbmod

    entry = _options_entry_body(resolved_request={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
        "overrides": {"min_stock_score": 25, "min_volume": 10},
    })
    entry["id"] = "e2e-sched-legacy"
    scan_schedule_store.upsert(entry)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    seen = []

    async def _fake_core(req, db, previous_result=None):
        seen.append(req)
        raise RuntimeError("stop here")

    async def _quiet(*a, **k):
        return None

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _fake_core)
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _quiet)
    try:
        await sss._run_scheduled_entry("e2e-sched-legacy")
        assert len(seen) == 1
        assert "min_stock_score" not in seen[0].overrides
        # Core evaluates on YAML default
        eff = effective_contract_overrides(seen[0].overrides)
        assert "min_stock_score" not in eff
    finally:
        scan_schedule_store.delete("e2e-sched-legacy")


def test_ac5_stocks_mode_min_stock_score_never_crosses_to_options():
    """AC 5: Stocks-field min_stock_score does not override contract_min_stock_score
    if both are present; contract_min_stock_score wins by design."""
    eff = effective_contract_overrides({
        "contract_min_stock_score": 30,
        "min_stock_score": 50,
    })
    assert eff["min_stock_score"] == 30


def test_ac6_empty_or_cleared_override_reverts_cleanly():
    """AC 6: Empty dict or omitted override reverts cleanly with no residual keys."""
    eff = effective_contract_overrides({})
    assert eff == {}
    eff_none = effective_contract_overrides(None)
    assert eff_none == {}


def test_ac7_bounds_enforcement_and_validation():
    """AC 7: Bounds [0, 100], non-finite float rejection, boolean rejection,
    and rounding behavior are strictly enforced."""
    # Valid boundaries
    assert _int_score_floor(0) == 0
    assert _int_score_floor(100) == 100
    assert _int_score_floor(45) == 45
    assert _int_score_floor(44.6) == 45
    assert _int_score_floor(44.4) == 44

    # Out of range
    with pytest.raises(ValueError, match="out of bounds"):
        _int_score_floor(-1)
    with pytest.raises(ValueError, match="out of bounds"):
        _int_score_floor(101)

    # Non-finite floats
    with pytest.raises(ValueError, match="Non-finite"):
        _int_score_floor(float("nan"))
    with pytest.raises(ValueError, match="Non-finite"):
        _int_score_floor(float("inf"))
    with pytest.raises(ValueError, match="Non-finite"):
        _int_score_floor(float("-inf"))

    # Booleans and None
    with pytest.raises(TypeError):
        _int_score_floor(True)
    with pytest.raises(TypeError):
        _int_score_floor(False)
    with pytest.raises(TypeError):
        _int_score_floor(None)
