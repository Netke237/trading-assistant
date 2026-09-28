"""DOCC-1: the four money blocks of scoring_rules.yaml are required, explicit
and closed (docs/superpowers/plans/2026-09-28-docc-1-money-blocks-plan.md §3).

Decisions DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28 and
DOCC-9.8-CLOSED-MONEY-SUBTREES-2026-09-28. Unit tests run the validator on the
SHIPPED file, mutated per case; endpoint and fire tests patch the shipped doc
with a block removed.
"""
from __future__ import annotations

import logging
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import money_config
from app.services.money_config import (
    MONEY_BLOCK_KEYS, REQUIRED_BLOCKS, MoneyConfigError, validate_money_blocks,
)
from tests.conftest import shipped_scoring_doc

_SHIPPED = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"


@pytest.fixture(autouse=True)
def _fresh_warn_memory():
    """Rule 5 warns once per PROCESS; each test starts with a clean memory."""
    money_config._warned_top_level.clear()
    yield
    money_config._warned_top_level.clear()


def _paths(exc: MoneyConfigError) -> list[str]:
    return [p for p, _ in exc.errors]


# ── T1 ───────────────────────────────────────────────────────────────────────

def test_t1_the_shipped_file_passes_with_no_warning(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.money_config")
    validate_money_blocks(shipped_scoring_doc())
    assert not caplog.records, [r.getMessage() for r in caplog.records]


def test_t1b_the_table_and_the_shipped_file_name_the_same_keys():
    """Not a rule of the plan, a guard on the table: every key the shipped file
    carries is declared, and every declared leaf appears in the shipped file,
    so a key cannot be dropped from one without the other noticing."""
    doc = shipped_scoring_doc()

    def walk(node, spec, path):
        assert set(node) == set(spec), path
        for k, sub in spec.items():
            if sub is not None:
                walk(node[k], sub, f"{path}.{k}")

    for block in REQUIRED_BLOCKS:
        walk(doc[block], MONEY_BLOCK_KEYS[block], block)


# ── T2 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("block", REQUIRED_BLOCKS)
def test_t2_each_block_deleted_refuses_naming_it(block):
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(shipped_scoring_doc(drop=(block,)))
    assert _paths(ei.value) == [block]
    assert "enabled: false" in str(ei.value)


@pytest.mark.parametrize("block", REQUIRED_BLOCKS)
def test_t2b_a_null_block_counts_as_absent(block):
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(shipped_scoring_doc(**{block: None}))
    assert _paths(ei.value) == [block]


def test_t2c_a_non_mapping_block_refuses():
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(shipped_scoring_doc(regime_gate=[1, 2]))
    assert _paths(ei.value) == ["regime_gate"]
    assert "mapping" in str(ei.value)


# ── T3 ───────────────────────────────────────────────────────────────────────

def test_t3_a_renamed_block_refuses_and_warns_with_the_suggestion(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.money_config")
    doc = shipped_scoring_doc(drop=("regime_sizing",))
    doc["regime_sizng"] = shipped_scoring_doc()["regime_sizing"]
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(doc)
    assert _paths(ei.value) == ["regime_sizing"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "regime_sizng" in warnings[0] and "'regime_sizing'" in warnings[0]


# ── T4 ───────────────────────────────────────────────────────────────────────

def test_t4_a_misspelled_require_stable_for_reject_refuses():
    """The worst case in plan §1: the default True would apply and fire into
    Fragile headwinds the operator meant to REJECT."""
    gate = dict(shipped_scoring_doc()["regime_gate"])
    del gate["require_stable_for_reject"]
    gate["require_stable_for_rejct"] = False
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(shipped_scoring_doc(regime_gate=gate))
    assert _paths(ei.value) == ["regime_gate.require_stable_for_rejct"]
    assert "MONEY_BLOCK_KEYS" in str(ei.value)


# ── T5 ───────────────────────────────────────────────────────────────────────

_MISSING = object()


@pytest.mark.parametrize("block", REQUIRED_BLOCKS)
@pytest.mark.parametrize("value", [_MISSING, "false", None, 1, 0])
def test_t5_enabled_must_be_present_and_a_real_bool(block, value):
    blk = dict(shipped_scoring_doc()[block])
    if value is _MISSING:
        del blk["enabled"]
    else:
        blk["enabled"] = value
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(shipped_scoring_doc(**{block: blk}))
    assert _paths(ei.value) == [f"{block}.enabled"]


@pytest.mark.parametrize("block", REQUIRED_BLOCKS)
def test_t5b_enabled_false_with_valid_keys_passes(block):
    blk = dict(shipped_scoring_doc()[block])
    blk["enabled"] = False
    validate_money_blocks(shipped_scoring_doc(**{block: blk}))


# ── T6 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("block", REQUIRED_BLOCKS)
def test_t6_an_unknown_key_inside_a_disabled_block_refuses(block):
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(shipped_scoring_doc(**{block: {"enabled": False, "min_mul": 0.3}}))
    assert _paths(ei.value) == [f"{block}.min_mul"]


# ── T7 ───────────────────────────────────────────────────────────────────────

def _fg_with(mutate):
    fg = shipped_scoring_doc()["fundamentals_gate"]
    mutate(fg)
    return shipped_scoring_doc(fundamentals_gate=fg)


@pytest.mark.parametrize("mutate,path", [
    (lambda fg: fg["thresholds"].update(gross_margn={"strong": 0.4, "weak": 0.2}),
     "fundamentals_gate.thresholds.gross_margn"),
    (lambda fg: fg["safety"].update(debt_to_equity_rejct=3.0),
     "fundamentals_gate.safety.debt_to_equity_rejct"),
    (lambda fg: fg["thresholds"]["gross_margin"].update(strng=0.4),
     "fundamentals_gate.thresholds.gross_margin.strng"),
    (lambda fg: fg.update(weights=0.3),
     "fundamentals_gate.weights"),
])
def test_t7_nested_problems_name_the_dotted_path(mutate, path):
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(_fg_with(mutate))
    assert _paths(ei.value) == [path]


# ── T8 ───────────────────────────────────────────────────────────────────────

def test_t8_several_problems_are_reported_together():
    gate = dict(shipped_scoring_doc()["regime_gate"], enabled="yes", headwind_rejct_pct=-40)
    doc = shipped_scoring_doc(drop=("regime_sizing",), regime_gate=gate)
    doc["fundamentals_gate"]["safety"]["typo"] = 1
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(doc)
    assert sorted(_paths(ei.value)) == sorted([
        "regime_sizing", "regime_gate.enabled", "regime_gate.headwind_rejct_pct",
        "fundamentals_gate.safety.typo",
    ])
    for p in _paths(ei.value):
        assert p in str(ei.value)


# ── T9 ───────────────────────────────────────────────────────────────────────

def test_t9_a_file_truncated_before_regime_gate_refuses_for_all_three():
    text = _SHIPPED.read_text()
    cut = text.index("\nregime_gate:")
    doc = yaml.safe_load(text[:cut])
    assert isinstance(doc, dict)   # the truncated file still parses -- that is the defect
    with pytest.raises(MoneyConfigError) as ei:
        validate_money_blocks(doc)
    assert sorted(_paths(ei.value)) == sorted(
        ["regime_gate", "regime_sizing", "fundamentals_gate"])


# ── T10 ──────────────────────────────────────────────────────────────────────

def test_t10_the_unknown_top_level_warning_is_logged_once_per_process(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.money_config")
    doc = shipped_scoring_doc(regme={"a": 1})
    for _ in range(3):
        validate_money_blocks(doc)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "regme" in warnings[0] and "'regime'" in warnings[0]


# ── T11-T13: the three HTTP call sites ───────────────────────────────────────

@pytest.fixture
def stock_client():
    from app.database import get_db
    from app.routers.stock_scan import router
    from tests.conftest import _override_get_db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture
def scan_client():
    from app.database import get_db
    from app.routers.scan import router
    from tests.conftest import _override_get_db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_t11_stock_scan_refuses_before_any_price_fetch(stock_client):
    fetch = MagicMock(return_value={})
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan._load_full_scoring_cfg",
                                  return_value=shipped_scoring_doc(drop=("regime_gate",))))
        stack.enter_context(patch("app.routers.stock_scan.fetch_quotes", fetch))
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bullish",
            "horizon": "Swing", "strategy": "pullback_ema",
        })
    assert r.status_code == 500, r.text
    assert "regime_gate" in r.json()["detail"]
    assert fetch.call_count == 0


def test_t12_options_scan_refuses_naming_the_block(scan_client):
    fetch = MagicMock(return_value={})
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._load_scoring_cfg",
                                  return_value=shipped_scoring_doc(drop=("confidence_gate",))))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", fetch))
        r = scan_client.post("/api/scan", json={
            "universe": ["AAA"], "direction": "Bullish", "horizon": "Swing",
        })
    assert r.status_code == 500, r.text
    assert "confidence_gate" in r.json()["detail"]
    assert fetch.call_count == 0


def test_t13_analyze_stock_refuses_naming_the_block(stock_client):
    core = MagicMock()
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan._load_full_scoring_cfg",
                                  return_value=shipped_scoring_doc(drop=("fundamentals_gate",))))
        stack.enter_context(patch("app.routers.stock_scan._analyze_core", core))
        r = stock_client.post("/api/analyze-stock", json={"symbol": "AAA"})
    assert r.status_code == 500, r.text
    assert "fundamentals_gate" in r.json()["detail"]
    core.assert_not_called()


# ── T14: the fire ────────────────────────────────────────────────────────────

def _strategy():
    from app.services.auto_trader import ArmedStrategy
    return ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
    )


@pytest.mark.parametrize("block", ["regime_sizing", "regime_gate"])
def test_t14_a_fire_with_a_block_removed_is_refused_recorded_and_alerted(mocker, tmp_path, block):
    """With `regime_gate` removed this fire used to go through UNGATED; with
    `regime_sizing` removed it went at FULL size."""
    import app.services.auto_trader as at

    f = tmp_path / "scoring_rules.yaml"
    f.write_text(yaml.safe_dump(shipped_scoring_doc(drop=(block,))))
    mocker.patch.object(at, "_SCORING_CONFIG_PATH", f)
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    measure = mocker.patch.object(at, "_measure_trade_regime", return_value=None)
    alert = mocker.patch.object(at, "_alert_sizing_config_refusal")
    at._load_scoring_doc.cache_clear()
    try:
        svc = at.AutoTradeService()
        svc.arm(_strategy())
        svc.maybe_fire_on_scan()          # the trigger; must not raise

        execute.assert_not_called()
        measure.assert_not_called()
        assert alert.call_count == 1
        assert isinstance(alert.call_args.args[1], MoneyConfigError)
        state = svc.get_state()
        assert state.armed is False
        last = state.history[-1]
        assert last["status"] == "sizing_config_blocked"
        assert last["order_id"] is None
        assert block in last["error"]

        # A direct fire() raises the same error (POST /auto-trade/fire's 500).
        svc.arm(_strategy())
        with pytest.raises(MoneyConfigError, match=block):
            svc.fire()
        execute.assert_not_called()
    finally:
        at._load_scoring_doc.cache_clear()


def test_t14b_the_alert_wording_names_the_money_blocks_not_regime_sizing(mocker):
    import app.services.auto_trader as at

    sent = mocker.patch.object(at, "_alert_refusal")
    at._alert_sizing_config_refusal(
        "AAPL", MoneyConfigError([("regime_gate", "is missing")]))
    text = sent.call_args.args[2]
    assert "money blocks" in text and "regime_gate" in text
    assert "regime_sizing block cannot be honoured" not in text
