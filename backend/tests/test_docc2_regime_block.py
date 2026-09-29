"""DOCC-2: a broken `regime.<horizon>` block refuses at all four sites.

Plan: docs/superpowers/plans/2026-09-28-docc-2-options-regime-plan.md.
Decision DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28 (Kenneth): refuse the whole scan
with a named 500, at the options scan, the stock scan, POST /analyze-stock and
the auto-trade fire. Closes round-5 finding G2: the options scan used to read
the block inside a `try` whose handler only logged a WARNING, so the symbol was
scored with NO headwind gate and names the gate would REJECT came back PASS.
"""
from __future__ import annotations

import copy
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.money_config import (
    REGIME_HORIZONS, RegimeConfigError, regime_block_errors, validate_regime_block,
)
from tests.conftest import shipped_scoring_doc


def _doc(mutate=None) -> dict:
    doc = shipped_scoring_doc()
    if mutate is not None:
        mutate(doc)
    return doc


def _paths(errs) -> list[str]:
    return [p for p, _ in errs]


# ── R1-R7: the rules ─────────────────────────────────────────────────────────

def test_r1_the_shipped_file_passes_for_every_horizon():
    assert regime_block_errors(_doc(), REGIME_HORIZONS) == []


@pytest.mark.parametrize("value", ["<delete>", None, [1]])
def test_r2_a_missing_or_non_mapping_regime_refuses(value):
    def m(d):
        if value == "<delete>":
            del d["regime"]
        else:
            d["regime"] = value
    assert _paths(regime_block_errors(_doc(m), ("swing",))) == ["regime"]


@pytest.mark.parametrize("value", ["<delete>", None, 5])
def test_r3_a_broken_horizon_refuses_only_that_horizon(value):
    def m(d):
        if value == "<delete>":
            del d["regime"]["swing"]
        else:
            d["regime"]["swing"] = value
    doc = _doc(m)
    assert _paths(regime_block_errors(doc, ("swing",))) == ["regime.swing"]
    assert regime_block_errors(doc, ("intraday",)) == []


@pytest.mark.parametrize("value", ["<delete>", "15m", "daily ", None, "Daily"])
def test_r4_timeframe_must_be_15min_or_daily(value):
    def m(d):
        if value == "<delete>":
            del d["regime"]["swing"]["timeframe"]
        else:
            d["regime"]["swing"]["timeframe"] = value
    assert _paths(regime_block_errors(_doc(m), ("swing",))) == ["regime.swing.timeframe"]


@pytest.mark.parametrize("key", ["lookback", "window", "min_obs"])
@pytest.mark.parametrize("value", ["<delete>", 0, -5, 20.5, "20", True, None])
def test_r5_the_three_numbers_must_be_positive_ints(key, value):
    def m(d):
        if value == "<delete>":
            del d["regime"]["swing"][key]
        else:
            d["regime"]["swing"][key] = value
    assert _paths(regime_block_errors(_doc(m), ("swing",))) == [f"regime.swing.{key}"]


def test_r6_several_faults_are_reported_together():
    def m(d):
        d["regime"]["swing"]["timeframe"] = "1h"
        d["regime"]["swing"]["window"] = 0
        del d["regime"]["position"]
    doc = _doc(m)
    with pytest.raises(RegimeConfigError) as ei:
        validate_regime_block(doc, REGIME_HORIZONS)
    assert _paths(ei.value.errors) == [
        "regime.swing.timeframe", "regime.swing.window", "regime.position",
    ]


def test_r7_an_extra_key_is_not_refused():
    def m(d):
        d["regime"]["swing"]["foo"] = 1
    assert regime_block_errors(_doc(m), ("swing",)) == []


def test_horizon_is_matched_case_insensitively():
    assert regime_block_errors(_doc(), ("Swing", "INTRADAY")) == []


# ── R8-R11: the three HTTP sites ─────────────────────────────────────────────

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


def _no_swing(d):
    del d["regime"]["swing"]


def test_r8_g2_options_scan_refuses_a_broken_regime_block(scan_client):
    """G2, the headline: this used to be HTTP 200 with every name scored
    without the headwind gate."""
    fetch = MagicMock(return_value={})
    process = AsyncMock()
    doc = _doc(_no_swing)
    assert doc["regime_gate"]["enabled"] is True
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._load_scoring_cfg", return_value=doc))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", fetch))
        stack.enter_context(patch("app.routers.scan._process_symbol", process))
        r = scan_client.post("/api/scan", json={
            "universe": ["AAA"], "direction": "Bullish", "horizon": "Swing",
        })
    assert r.status_code == 500, r.text
    assert "regime.swing" in r.json()["detail"]
    assert fetch.call_count == 0
    process.assert_not_called()


def test_r8b_options_scan_checks_only_the_requested_horizon(scan_client):
    """A broken Position block does not refuse a Swing options scan: that scan
    never reads it. It proceeds past S2 (it fails later on the mocked-out
    universe, which is not this test's concern)."""
    fetch = MagicMock(side_effect=RuntimeError("past S2"))
    doc = _doc(lambda d: d["regime"].pop("position"))
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._load_scoring_cfg", return_value=doc))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", fetch))
        try:
            r = scan_client.post("/api/scan", json={
                "universe": ["AAA"], "direction": "Bullish", "horizon": "Swing",
            })
            detail = r.json().get("detail", "") if r.status_code >= 400 else ""
        except RuntimeError:
            detail = ""
    assert "regime." not in str(detail)


@pytest.mark.asyncio
async def test_r9_a_regime_computation_failure_still_abstains():
    """Only CONFIG faults refuse. A data or compute failure inside the regime
    `try` still abstains: the card is scored with no regime gate, as before."""
    from app.routers.scan import _process_symbol
    from tests.test_a4_intraday_regime_bars import DAILY, _sem

    with patch("app.routers.scan.fetch_candles_async"), \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan._compute_omm", side_effect=RuntimeError("compute blew up")), \
         patch("app.routers.scan._compute_dhmm", return_value=None), \
         patch("app.routers.scan.score_stock") as score, \
         patch("app.routers.scan.log_event"):
        score.return_value = MagicMock(status="REJECT", score=20, rules=[], components={})
        await _process_symbol(
            symbol="AAPL", direction="Bullish", horizon="Swing", client=AsyncMock(),
            sem=_sem(), scan_id="docc2", bars_map={"AAPL": DAILY},
        )
    assert score.called
    assert score.call_args.kwargs["regime_signal"] is None
    assert score.call_args.kwargs["regime_gate"] is None


@pytest.mark.asyncio
async def test_r9b_a_config_fault_is_no_longer_swallowed_inside_the_worker():
    """Belt and braces for a caller that skips S2: the read now sits OUTSIDE
    the WARNING-only `try`, so a missing block raises instead of producing an
    ungated card."""
    from app.routers.scan import _process_symbol
    from tests.test_a4_intraday_regime_bars import DAILY, _sem

    with patch("app.routers.scan._load_scoring_cfg", return_value=_doc(_no_swing)), \
         patch("app.routers.scan.fetch_candles_async"), \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.score_stock") as score, \
         patch("app.routers.scan.log_event"):
        with pytest.raises(KeyError):
            await _process_symbol(
                symbol="AAPL", direction="Bullish", horizon="Swing", client=AsyncMock(),
                sem=_sem(), scan_id="docc2", bars_map={"AAPL": DAILY},
            )
    score.assert_not_called()


def test_r10_stock_scan_refuses_a_bad_timeframe(stock_client):
    fetch = MagicMock(return_value={})
    doc = _doc(lambda d: d["regime"]["swing"].update(timeframe="15m"))
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan._load_full_scoring_cfg", return_value=doc))
        stack.enter_context(patch("app.routers.stock_scan.fetch_quotes", fetch))
        r = stock_client.post("/api/stock-scan", json={
            "symbols": ["AAA"], "universe": [], "direction": "Bullish",
            "horizon": "Swing", "strategy": "pullback_ema",
        })
    assert r.status_code == 500, r.text
    assert "regime.swing.timeframe" in r.json()["detail"]
    assert fetch.call_count == 0


def test_r11_analyze_stock_checks_all_three_horizons(stock_client):
    """A Swing request still refuses on a broken Position block: this page
    builds the Position regime card too."""
    core = MagicMock()
    doc = _doc(lambda d: d["regime"].pop("position"))
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan._load_full_scoring_cfg", return_value=doc))
        stack.enter_context(patch("app.routers.stock_scan._analyze_core", core))
        r = stock_client.post("/api/analyze-stock", json={"symbol": "AAA", "horizon": "Swing"})
    assert r.status_code == 500, r.text
    assert "regime.position" in r.json()["detail"]
    core.assert_not_called()


# ── R12-R13: the fire ────────────────────────────────────────────────────────

def _strategy(horizon="Swing"):
    from app.services.auto_trader import ArmedStrategy
    return ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=4, order_type="LMT",
        limit_price=2.50, conid=None,
        entry_premium=2.50, portfolio_value=100_000.0,
        horizon=horizon,
    )


def _fire_env(mocker, tmp_path, doc):
    import app.services.auto_trader as at
    f = tmp_path / "scoring_rules.yaml"
    f.write_text(yaml.safe_dump(doc))
    mocker.patch.object(at, "_SCORING_CONFIG_PATH", f)
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    at._load_scoring_doc.cache_clear()
    return at


def test_r12_a_fire_with_its_regime_block_missing_is_refused_recorded_and_alerted(mocker, tmp_path):
    """This fire used to go through with the regime UNMEASURED (the gate
    abstained, sizing took the unmeasured floor) and only a WARNING said so."""
    at = _fire_env(mocker, tmp_path, _doc(_no_swing))
    execute = mocker.patch("app.services.auto_trader.execute_option_order")
    fetch = mocker.patch("app.data.market.fetch_candles")
    alert = mocker.patch.object(at, "_alert_regime_gate_config_refusal")
    try:
        svc = at.AutoTradeService()
        svc.arm(_strategy())
        svc.maybe_fire_on_scan()          # the trigger; must not raise

        execute.assert_not_called()
        fetch.assert_not_called()
        assert alert.call_count == 1
        assert isinstance(alert.call_args.args[1], at.RegimeGateConfigError)
        last = svc.get_state().history[-1]
        assert last["status"] == "regime_gate_config_blocked"
        assert last["order_id"] is None
        assert "regime.swing" in last["error"]

        svc.arm(_strategy())
        with pytest.raises(at.RegimeGateConfigError, match="regime.swing"):
            svc.fire()
        execute.assert_not_called()
    finally:
        at._load_scoring_doc.cache_clear()


def test_r13_with_gate_and_sizing_off_a_missing_block_is_not_read(mocker, tmp_path):
    """Nothing the fire computes depends on the block when the gate is off and
    sizing is off, so it is not read and the fire goes through."""
    from app.data.ibkr_paper import OrderResult

    def m(d):
        del d["regime"]["swing"]
        d["regime_gate"]["enabled"] = False
        d["regime_sizing"]["enabled"] = False
    at = _fire_env(mocker, tmp_path, _doc(m))
    execute = mocker.patch("app.services.auto_trader.execute_option_order",
                           return_value=OrderResult("r13", "ok", "ibkr_paper"))
    try:
        svc = at.AutoTradeService()
        svc.arm(_strategy())
        svc.fire()
        assert execute.call_count == 1
        assert execute.call_args.args[0].quantity == 4
    finally:
        at._load_scoring_doc.cache_clear()
