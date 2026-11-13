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


@pytest.mark.parametrize("horizon,refuses", [("Swing", True), ("Intraday", False)])
def test_r8b_daily_scan_validates_all_count_contributors(scan_client, horizon, refuses):
    """Uniform daily counts require Position even for Swing; Intraday is independent."""
    after_s2 = MagicMock(side_effect=RuntimeError("past S2"))
    doc = _doc(lambda d: d["regime"].pop("position"))
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._load_scoring_cfg", return_value=doc))
        stack.enter_context(patch("app.routers.scan._resolve_gate", after_s2))
        if refuses:
            result = scan_client.post("/api/scan", json={
                "universe": ["AAA"], "direction": "Bullish", "horizon": horizon,
            })
            assert result.status_code == 500
            assert "regime.position" in result.json()["detail"]
            after_s2.assert_not_called()
        else:
            try:
                result = scan_client.post("/api/scan", json={
                    "universe": ["AAA"], "direction": "Bullish", "horizon": horizon,
                })
                assert "regime.position" not in str(result.json())
            except RuntimeError as exc:
                assert str(exc) == "past S2"
            after_s2.assert_called_once()


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


# ── DOCC-2-REGIME-RELATIONS: combinations that can never be measured ────────
# Each value passes the per-key rules alone; together they leave every symbol
# (or every Bull/Bear symbol) unmeasured, and so ungated.

import datetime as _dt
import inspect as _inspect
import re as _re
from pathlib import Path as _Path

from app.services.money_config import REGIME_SERIES_FLOOR

_APP = _Path(__file__).parent.parent / "app"


def _with(h: str, **vals) -> dict:
    doc = shipped_scoring_doc()
    doc["regime"][h].update(vals)
    return doc


@pytest.mark.parametrize("h,vals,path", [
    ("swing", {"window": 50}, "regime.swing.min_obs"),            # min_obs 100 > window
    ("swing", {"min_obs": 1000}, "regime.swing.min_obs"),
    ("swing", {"lookback": 2000}, "regime.swing.lookback"),
    ("swing", {"lookback": 500}, "regime.swing.lookback"),        # == window
    ("swing", {"min_obs": 350, "window": 750}, "regime.swing.min_obs"),  # only the floor
    ("swing", {"min_obs": 240}, "regime.swing.min_obs"),          # > 250 - 20
    ("position", {"min_obs": 210}, "regime.position.min_obs"),    # > 250 - 50
    ("intraday", {"min_obs": 825}, "regime.intraday.min_obs"),    # > 850 - 26
])
def test_rel1_combinations_that_can_never_be_measured_refuse(h, vals, path):
    errs = regime_block_errors(_with(h, **vals), (h,))
    assert path in _paths(errs), errs


@pytest.mark.parametrize("h,vals", [
    ("swing", {"min_obs": 230}),
    ("position", {"min_obs": 200}),
    ("intraday", {"min_obs": 824}),
])
def test_rel2_the_largest_measurable_min_obs_passes(h, vals):
    assert regime_block_errors(_with(h, **vals), (h,)) == []


def test_rel3_the_floor_message_names_lookback_too():
    errs = regime_block_errors(_with("swing", min_obs=240), ("swing",))
    assert any("lookback" in msg for p, msg in errs if p == "regime.swing.min_obs")


def test_rel4_relations_are_skipped_for_a_key_that_failed_its_own_rule():
    """A broken window reports once, as itself, not again as a relation."""
    errs = regime_block_errors(_with("swing", window="500"), ("swing",))
    assert _paths(errs) == ["regime.swing.window"]


def test_rel5_the_scan_refuses_a_relation_fault_through_the_same_validator():
    with pytest.raises(RegimeConfigError, match="regime.swing.min_obs"):
        validate_regime_block(_with("swing", min_obs=1000), ("Swing",))


def _min_weekdays(n: int) -> int:
    """The fewest weekdays in any n consecutive calendar days."""
    start = _dt.date(2024, 1, 1)  # a Monday; every weekday alignment is tried
    return min(
        sum((start + _dt.timedelta(days=o + i)).weekday() < 5 for i in range(n))
        for o in range(7)
    )


def test_rel6_daily_floor_fits_the_shortest_daily_series():
    from app.data.market import fetch_candles_async
    bars_default = _inspect.signature(fetch_candles_async).parameters["bars"].default
    assert REGIME_SERIES_FLOOR["daily"] <= bars_default - 2
    m = _re.search(r"_bar_start = _bar_end - _td\(days=int\(([\d.]+) \* (\d+)\)\)",
                   (_APP / "routers" / "scan.py").read_text())
    assert m, "scan.py's DB window expression moved; re-derive the daily floor"
    calendar_days = int(float(m.group(1)) * int(m.group(2)))
    assert REGIME_SERIES_FLOOR["daily"] <= _min_weekdays(calendar_days) - 10


def test_rel7_15min_floor_fits_the_shortest_intraday_series():
    from app.routers.stock_scan import _INTRADAY_FETCH_DAYS
    assert _min_weekdays(_INTRADAY_FETCH_DAYS) == 39
    assert REGIME_SERIES_FLOOR["15min"] <= (_min_weekdays(_INTRADAY_FETCH_DAYS) - 4) * 26 - 2 * 13
    # The other two 15-min readers fetch the same span, as literals.
    assert (f'fetch_intraday_candles, symbol, "15min", {_INTRADAY_FETCH_DAYS}'
            in (_APP / "routers" / "scan.py").read_text())
    assert (f'fetch_intraday_candles(symbol, "15min", {_INTRADAY_FETCH_DAYS})'
            in (_APP / "services" / "auto_trader.py").read_text())
