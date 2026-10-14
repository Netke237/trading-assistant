# backend/tests/test_request_finite_models.py
"""NUMERIC-API-INPUTS T2 -- the request models refuse non-finite numbers.

Plan: docs/superpowers/plans/2026-10-10-numeric-api-inputs-plan.md, section 3 T2.

T1's JSON guard refuses a NaN/Infinity LITERAL (and an overflowing number) in
the raw body. It cannot see a STRING: pydantic's lax mode turns "NaN", "inf"
or "1e999" into a non-finite float inside a typed `float` field. This module
pins the schema half: every (model, field) of the plan's section 1 table
refuses nan, inf, -inf, "NaN" and "1e999" with pydantic's `finite_number`
error, and still accepts a finite value.

Also pinned here:
  * FinalStopIn / DrawingPointIn are request-only subclasses; FinalStopOut,
    DrawingPoint and DrawingOut are unchanged, and the recompute-plan response
    for a finite final_stop is the same as with a plain FinalStopOut.
  * auto-trade booking refuses a non-finite position instead of writing it.
  * GET /api/scan-schedule skips (and logs) a stored entry that no longer
    validates, instead of failing the whole list.
  * the scheduler records a failed run for such an entry, never scanning it.
  * ScanRequest.model_dump_json() of a finite request round-trips.
  * one HTTP check per router: a string "NaN"/"1e999" in a float field is a
    422 `finite_number` through main.py's handler, and the endpoint never runs.

The HTTP checks use `create_app()` WITHOUT a `with` block (no lifespan, so no
scheduler or monitor starts). `get_db` is replaced by a tripwire session and
each endpoint's first downstream call is patched to raise, so a request that
got past validation shows up as a 500 rather than reaching a provider.
"""
from __future__ import annotations

import copy
import dataclasses
import logging
import math
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
import app.routers.auto_trade as auto_trade_mod
import app.routers.broker as broker_mod
import app.routers.contracts as contracts_mod
import app.routers.portfolio as portfolio_mod
import app.routers.scan as scan_mod
import app.routers.stock_scan as stock_scan_mod
from app.database import Base, get_db
from app.main import create_app
from app.routers.alerts import AlertNotifyRequest
from app.routers.auto_trade import ArmRequest
from app.routers.broker import OptionOrderRequest, StockOrderRequest
from app.routers.chart_drawings import DrawingIn, DrawingOut, DrawingPoint
from app.routers.contracts import (
    ExitPlanRequest, FirstPassageRequest, RecomputePlanRequest, StructuralStopRequest,
)
from app.routers.journal import JournalEntryCreate
from app.routers.stock_scan import StockExitPlanRequest, StockFirstPassageRequest
from app.schemas import (
    ClosePositionRequest, FinalStopOut, PortfolioPositionCreate, PortfolioPositionUpdate,
    ScanRequest,
)
from app.schemas.stock_scan import StockAnalysisRequest, StockScanRequest

NON_FINITE = [float("nan"), float("inf"), float("-inf"), "NaN", "1e999"]
NON_FINITE_IDS = ["nan", "inf", "-inf", "str-NaN", "str-1e999"]

COMPUTED_AT = "2026-10-10T14:30:00Z"
FINAL_STOP = {
    "price": 169.00, "source": "final_stop", "stopSource": "atr_widened",
    "structuralSource": None, "structuralPrice": None,
    "atrFloorPrice": 169.00, "distanceDollar": None, "atr": 8.0,
    "computedAt": COMPUTED_AT,
}

ARM_BASE = {
    "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": "AAPL|185|2026-12-18|C",
    "action": "BUY", "direction": "Bullish", "horizon": "Swing", "hold_max_days": 15,
    "quantity": 1, "entry_premium": 2.50,
}

RECOMPUTE_BASE = {
    "symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
    "strike": 190, "dte": 30, "premium": 2.50, "delta": 0.45, "spread": 0.20,
}

# Minimal valid payload per model, built from each model's required fields.
MINIMAL: dict[type, dict] = {
    AlertNotifyRequest: {"symbol": "AAPL", "alertType": "TP_HIT", "reason": "r", "recId": "REC-1"},
    ArmRequest: ARM_BASE,
    StockOrderRequest: {"broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY",
                        "effect": "OPEN", "quantity": 1},
    OptionOrderRequest: {"broker": "ibkr_paper", "symbol": "AAPL",
                         "option_symbol": "AAPL|185|2026-12-18|C", "action": "BUY",
                         "effect": "OPEN", "quantity": 1},
    DrawingIn: {"id": "d1", "symbol": "AAPL", "interval": "1D", "kind": "hline",
                "points": [{"time": 1_700_000_000, "price": 180.0}], "color": "#fff",
                "createdAt": COMPUTED_AT},
    RecomputePlanRequest: {**RECOMPUTE_BASE, "final_stop": FINAL_STOP},
    StructuralStopRequest: {"symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
                            "strike": 190.0, "dte": 30, "premium": 2.5},
    FirstPassageRequest: {"symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
                          "strike": 190.0, "dte": 30, "premium": 2.5, "trend_score": 60,
                          "invalidation_price": 175.0},
    ExitPlanRequest: {"symbol": "AAPL", "direction": "Bullish", "entry_price": 185.0,
                      "strike": 190.0, "dte": 30, "premium": 2.5, "trend_score": 60},
    JournalEntryCreate: {"entry_type": "trade", "entry_date": "2026-10-10T00:00:00Z",
                         "symbol": "AAPL"},
    PortfolioPositionCreate: {"recId": "REC-1", "symbol": "AAPL",
                              "contract": "AAPL|185|2026-12-18|C", "direction": "Bullish",
                              "entryPrice": 2.5, "entryDate": "2026-10-10"},
    PortfolioPositionUpdate: {},
    ClosePositionRequest: {},
    ScanRequest: {"universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing"},
    StockScanRequest: {"universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
                       "strategy": "pullback_ema"},
    StockAnalysisRequest: {"symbol": "AAPL"},
    StockFirstPassageRequest: {"symbol": "AAPL", "direction": "Bullish", "horizon": "Swing",
                               "strategy": "pullback_ema", "stock_price": 185.0,
                               "stop_price": 175.0, "targets": [200.0], "trend_score": 60},
    StockExitPlanRequest: {"symbol": "AAPL", "direction": "Bullish", "entry_price": 185.0,
                           "trend_score": 60, "horizon": "Swing"},
}

_STOCK_SCAN_FIELDS = [
    "min_price", "max_price", "min_cap_usd", "max_cap_usd", "bt_min_win_rate",
    "fundamentals_caution_below", "fundamentals_reject_below", "fundamentals_de_reject",
    "confidence_caution_below", "confidence_reject_below",
    "confidence_atr_mult_target", "confidence_atr_mult_stop",
    "regime_headwind_caution_pct", "regime_headwind_reject_pct",
    "fundamentals_caution_above", "fundamentals_reject_above",
    # (B) bounded below only
    "breakout_volume_mult", "account_size", "vwap_deviation_pct",
]

# The plan's section 1 table. A path is a field name, or a tuple into a nested
# request-only model (DrawingIn.points[0].price, RecomputePlanRequest.final_stop.*).
TABLE: dict[type, list] = {
    AlertNotifyRequest: ["price", "referenceValue"],
    ArmRequest: ["portfolio_value", "regime_headwind_caution_pct", "regime_headwind_reject_pct",
                 "stop", "scan_stock_price", "structural_stop", "premium_stop_dollar"],
    StockOrderRequest: ["limit_price"],
    OptionOrderRequest: ["limit_price"],
    DrawingIn: [("points", 0, "price")],
    RecomputePlanRequest: ["delta", "spread", "stock_price", "strike", "premium",
                           "hold_min", "hold_max",
                           ("final_stop", "price"), ("final_stop", "structuralPrice"),
                           ("final_stop", "atrFloorPrice"), ("final_stop", "distanceDollar"),
                           ("final_stop", "atr")],
    StructuralStopRequest: ["stock_price", "strike", "premium"],
    FirstPassageRequest: ["delta", "stock_price", "strike", "premium", "invalidation_price",
                          "t1_pct", "t2_pct", "t3_pct", "hold_min", "hold_max"],
    ExitPlanRequest: ["entry_price", "strike", "premium"],
    JournalEntryCreate: ["entry_price", "exit_price", "position_size", "stop_loss",
                         "risk_dollars", "net_pnl"],
    PortfolioPositionCreate: ["stop", "structuralStop", "portfolioValue", "scanStockPrice",
                              "premiumStopDollar"],
    PortfolioPositionUpdate: ["stop", "structuralStop", "portfolioValue"],
    ClosePositionRequest: ["exitPrice"],
    ScanRequest: ["min_price", "max_price", "min_cap_usd", "max_cap_usd",
                  "confidence_atr_mult_target", "confidence_atr_mult_stop",
                  "fundamentals_caution_below", "fundamentals_reject_below",
                  "fundamentals_de_reject", "fundamentals_caution_above",
                  "fundamentals_reject_above", "regime_headwind_caution_pct",
                  "regime_headwind_reject_pct", "spread_width", "short_leg_delta",
                  "iv_rank_threshold", "iv_abs_threshold", "min_credit", "max_debit_pct"],
    StockScanRequest: _STOCK_SCAN_FIELDS,
    StockAnalysisRequest: _STOCK_SCAN_FIELDS,
    StockFirstPassageRequest: [("targets", 0), "stock_price", "stop_price"],
    # rr_ratios is already guarded by its own validator: only entry_price is new.
    StockExitPlanRequest: ["entry_price"],
}

# A finite value each field accepts. Everything not listed takes 1.0.
FINITE_OVERRIDE = {"breakout_volume_mult": 1.5}

CASES = [(model, path) for model, paths in TABLE.items() for path in paths]


def _case_id(case) -> str:
    model, path = case
    p = ".".join(str(x) for x in path) if isinstance(path, tuple) else path
    return f"{model.__name__}.{p}"


def _payload(model: type, path, value) -> dict:
    payload = copy.deepcopy(MINIMAL[model])
    keys = path if isinstance(path, tuple) else (path,)
    node = payload
    for k in keys[:-1]:
        node = node[k]
    node[keys[-1]] = value
    return payload


def test_table_has_the_inventoried_field_count():
    """section 1: 117 distinct (model, leaf) pairs accept a non-finite value;
    StockExitPlanRequest.rr_ratios is the one already guarded."""
    assert len(CASES) == 117 - 1


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
@pytest.mark.parametrize("case", CASES, ids=[_case_id(c) for c in CASES])
def test_non_finite_value_is_refused_as_finite_number(case, value):
    model, path = case
    with pytest.raises(ValidationError) as ei:
        model.model_validate(_payload(model, path, value))
    types = [e["type"] for e in ei.value.errors()]
    assert types == ["finite_number"], ei.value.errors()


@pytest.mark.parametrize("case", CASES, ids=[_case_id(c) for c in CASES])
def test_finite_value_still_validates(case):
    model, path = case
    leaf = path[-1] if isinstance(path, tuple) else path
    value = FINITE_OVERRIDE.get(leaf, 1.0)
    model.model_validate(_payload(model, path, value))
    model.model_validate(_payload(model, path, str(value)))  # lax str -> float kept


# ── Shared models: request-only subclasses, the shared parents unchanged ─────

def test_final_stop_in_is_a_request_only_subclass():
    import app.schemas as schemas
    final_stop_in = getattr(schemas, "FinalStopIn", None)
    assert final_stop_in is not None and issubclass(final_stop_in, FinalStopOut)
    assert final_stop_in.model_config.get("populate_by_name") is True
    assert final_stop_in.model_config.get("allow_inf_nan") is False
    ann = RecomputePlanRequest.model_fields["final_stop"].annotation
    assert final_stop_in in getattr(ann, "__args__", (ann,))
    # FinalStopOut itself (built by exit_plan.py and returned in responses) is unchanged.
    assert FinalStopOut.model_config.get("allow_inf_nan", True) is True
    assert math.isnan(FinalStopOut.model_validate({**FINAL_STOP, "price": float("nan")}).price)


def test_drawing_point_in_is_a_request_only_subclass():
    import app.routers.chart_drawings as cd
    point_in = getattr(cd, "DrawingPointIn", None)
    assert point_in is not None and issubclass(point_in, DrawingPoint)
    assert point_in.model_config.get("allow_inf_nan") is False
    assert DrawingIn.model_fields["points"].annotation == list[point_in]
    # DrawingPoint / DrawingOut unchanged: a row stored with a non-finite price still lists.
    assert DrawingPoint.model_config.get("allow_inf_nan", True) is True
    assert DrawingOut.model_fields["points"].annotation == list[DrawingPoint]
    out = DrawingOut.model_validate({
        "id": "d1", "symbol": "AAPL", "interval": "1D", "kind": "hline",
        "points": [{"time": 1, "price": float("nan")}], "color": "#fff", "width": 1,
        "text": None, "created_at": COMPUTED_AT,
    })
    assert math.isnan(out.points[0].price)


@pytest.mark.asyncio
async def test_recompute_plan_response_for_a_finite_final_stop_is_unchanged():
    """`contracts.py` echoes `req.final_stop` into a FinalStopOut-typed response
    field. A FinalStopIn there serialises exactly as the parent would."""
    import warnings

    req = RecomputePlanRequest.model_validate({**RECOMPUTE_BASE, "final_stop": FINAL_STOP})
    as_parent = req.model_copy(update={"final_stop": FinalStopOut.model_validate(FINAL_STOP)})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = (await contracts_mod.recompute_plan(req)).model_dump(mode="json")
        want = (await contracts_mod.recompute_plan(as_parent)).model_dump(mode="json")
    assert got == want
    assert got["exit"]["finalStop"] == FinalStopOut.model_validate(FINAL_STOP).model_dump(mode="json")

    # And through HTTP, the echoed block is exactly the parent's field set.
    resp = TestClient(create_app()).post(
        "/api/contracts/recompute-plan", json={**RECOMPUTE_BASE, "final_stop": FINAL_STOP},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["exit"]["finalStop"] == {
        **FinalStopOut.model_validate(FINAL_STOP).model_dump(mode="json"),
    }


# ── Internal construction path: auto-trade booking ───────────────────────────

@pytest_asyncio.fixture
async def booking_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield Session
    await engine.dispose()


@pytest.mark.asyncio
async def test_booking_refuses_a_non_finite_position_instead_of_writing_it(
    booking_session, monkeypatch,
):
    from app.data.ibkr_paper import OrderResult
    from app.models.portfolio import PortfolioPositionModel
    from app.services import auto_trade_booking as atb
    from app.services.auto_trader import ArmedStrategy, FiredOrder

    body = {**ARM_BASE, "broker": "ibkr_paper", "order_type": "LMT", "limit_price": 2.5,
            "stop": 180.0, "scan_stock_price": 190.0, "structural_stop": 178.0}
    strategy = ArmedStrategy(**ArmRequest(**body).model_dump())
    fired = FiredOrder(
        result=OrderResult("777", "Submitted", "ibkr_paper"),
        strategy=dataclasses.replace(strategy, structural_stop=float("nan")),
        attempt_id="attempt-t2",
    )
    monkeypatch.setattr(atb, "fetch_contract_quote_async", AsyncMock(return_value=None))
    monkeypatch.setattr(atb, "fetch_price_async", AsyncMock(return_value=None))
    alert = AsyncMock()
    monkeypatch.setattr(atb, "_alert_not_booked", alert)

    async with booking_session() as s:
        out = await atb.book_fired_order(fired, s)

    assert out.booked is False and out.rec_id is None
    assert "did not build" in out.error and "777" in out.error
    async with booking_session() as s:
        assert (await s.execute(select(PortfolioPositionModel))).scalars().all() == []
    alert.assert_awaited_once()
    args, kwargs = alert.await_args
    assert args[0] is fired and args[2] is True  # broker_live=True: the order is live


# ── Stored ScanRequest / StockScanRequest re-validation ──────────────────────

def _schedule_entry(entry_id: str, **request_extra) -> dict:
    return {
        "id": entry_id, "label": f"T2 {entry_id}", "mode": "options",
        "profile_id": "p1", "profile_name": "Profile", "profile_synced_at": COMPUTED_AT,
        "resolved_request": {"universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
                             "overrides": {}, **request_extra},
        "pattern": "fixed_time", "enabled": True, "days_of_week": [0, 1, 2, 3, 4],
        "fire_time": "09:00",
    }


def test_schedule_list_skips_an_entry_that_no_longer_validates(caplog):
    """T2(b): one legacy non-finite entry must not turn the whole list into a
    500. It is skipped with a warning naming its id, and stays in the store."""
    from app.services.scan_schedule_store import scan_schedule_store

    scan_schedule_store.upsert(_schedule_entry("t2-good", min_price=5.0))
    scan_schedule_store.upsert(_schedule_entry("t2-bad", min_price=float("nan")))
    try:
        with caplog.at_level(logging.WARNING, logger="app.routers.scan_schedule"):
            resp = TestClient(create_app(), raise_server_exceptions=False).get("/api/scan-schedule")
        assert resp.status_code == 200, resp.text
        ids = [e["id"] for e in resp.json()]
        assert "t2-good" in ids and "t2-bad" not in ids
        assert any("t2-bad" in r.getMessage() and r.levelno == logging.WARNING
                   for r in caplog.records)
        assert scan_schedule_store.get("t2-bad") is not None
    finally:
        scan_schedule_store.delete("t2-good")
        scan_schedule_store.delete("t2-bad")


@pytest.mark.asyncio
async def test_scheduler_records_a_failed_run_for_a_non_finite_entry(monkeypatch):
    """T2(a): refuse non-finite stored input before the core runs, then save
    and notify a classified failure without exposing the validation payload."""
    import app.database as dbmod
    from app.services import scan_schedule_scheduler as sss
    from app.services.scan_schedule_store import list_scheduled_scan_runs, scan_schedule_store
    from tests.conftest import _TestSession

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)
    core_calls = []

    async def _core(req, *a, **kw):
        core_calls.append(req)
        raise RuntimeError("scan core reached")

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _core)
    failure_notice = AsyncMock()
    success_notice = AsyncMock()
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", failure_notice)
    monkeypatch.setattr(sss, "_notify_scan_schedule_success", success_notice)

    secret_payload = "https://user:password@broker"
    scan_schedule_store.upsert(_schedule_entry(
        "t2-sched", min_price=float("inf"), horizon_preset=secret_payload))
    try:
        await sss._run_scheduled_entry("t2-sched")
        async with _TestSession() as db:
            runs = await list_scheduled_scan_runs(db, "t2-sched")
        assert core_calls == []
        assert len(runs) == 1 and runs[0].status == "error"
        assert runs[0].error == "scan_failed"
        failure_notice.assert_awaited_once_with("T2 t2-sched", "scan_failed")
        success_notice.assert_not_awaited()
        assert secret_payload not in runs[0].error
        assert secret_payload not in failure_notice.await_args.args[1]
        assert "inf" not in runs[0].error
    finally:
        scan_schedule_store.delete("t2-sched")


def test_scan_request_dump_json_round_trips():
    """T2(c): `scan.py` restores the last request from `model_dump_json()`
    output, which never carries a non-finite literal; a finite one round-trips."""
    req = ScanRequest.model_validate({
        **MINIMAL[ScanRequest], "min_price": 5.0, "max_price": 500.0,
        "regime_headwind_caution_pct": -15.0, "iv_abs_threshold": 40.0,
    })
    assert ScanRequest.model_validate_json(req.model_dump_json()) == req


# ── One HTTP check per router, through main.py's handler ─────────────────────

class _TripwireSession:
    """Stands in for the DB session: any use means the endpoint body ran."""

    def __getattr__(self, name):
        raise AssertionError(f"endpoint reached the DB ({name}): validation let the value through")


async def _tripwire_db():
    yield _TripwireSession()


def _raise_sync(*a, **kw):
    raise AssertionError("endpoint body ran: validation let the value through")


async def _raise_async(*a, **kw):
    raise AssertionError("endpoint body ran: validation let the value through")


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setattr(auto_trade_mod.auto_trader, "arm", _raise_sync)
    monkeypatch.setattr(broker_mod, "new_rec_id", _raise_sync)
    monkeypatch.setattr(contracts_mod, "build_trade_plan", _raise_sync)
    monkeypatch.setattr(portfolio_mod, "create_position", _raise_async)
    monkeypatch.setattr(scan_mod, "_execute_scan_core", _raise_async)
    monkeypatch.setattr(stock_scan_mod, "_execute_stock_scan_core", _raise_async)
    monkeypatch.setattr(stock_scan_mod, "fetch_candles_async", _raise_async)
    app = create_app()
    app.dependency_overrides[get_db] = _tripwire_db
    return TestClient(app, raise_server_exceptions=False)


HTTP_CASES = [
    ("post", "/api/alerts/notify", {**MINIMAL[AlertNotifyRequest], "price": "NaN"}, "price"),
    ("post", "/auto-trade/arm", {**ARM_BASE, "portfolio_value": "NaN"}, "portfolio_value"),
    ("post", "/broker/stock-order", {**MINIMAL[StockOrderRequest], "limit_price": "1e999"},
     "limit_price"),
    ("post", "/chart/drawings",
     {**MINIMAL[DrawingIn], "points": [{"time": 1_700_000_000, "price": "NaN"}]}, "price"),
    ("post", "/api/contracts/recompute-plan", {**RECOMPUTE_BASE, "delta": "NaN"}, "delta"),
    ("post", "/api/contracts/recompute-plan",
     {**RECOMPUTE_BASE, "final_stop": {**FINAL_STOP, "price": "NaN"}}, "price"),
    ("post", "/journal/entries", {**MINIMAL[JournalEntryCreate], "entry_price": "NaN"},
     "entry_price"),
    ("post", "/api/portfolio",
     {**MINIMAL[PortfolioPositionCreate], "stop": "NaN"}, "stop"),
    ("patch", "/api/portfolio/REC-1", {"stop": "NaN"}, "stop"),
    ("post", "/api/portfolio/REC-1/close", {"exitPrice": "NaN"}, "exitPrice"),
    ("post", "/api/scan", {**MINIMAL[ScanRequest], "min_price": "NaN"}, "min_price"),
    ("post", "/api/stock-scan", {**MINIMAL[StockScanRequest], "min_price": "NaN"}, "min_price"),
    ("post", "/api/stocks/exit-plan",
     {**MINIMAL[StockExitPlanRequest], "entry_price": "1e999"}, "entry_price"),
]


@pytest.mark.parametrize("method,url,body,field", HTTP_CASES,
                         ids=[f"{m} {u} {f}" for m, u, _, f in HTTP_CASES])
def test_http_string_non_finite_is_a_422(http, method, url, body, field):
    resp = getattr(http, method)(url, json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert [e["type"] for e in detail] == ["finite_number"], detail
    assert detail[0]["loc"][-1] == field
