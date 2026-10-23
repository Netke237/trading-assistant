"""DECISION-23 H-2 (H3): one WARNING per scan naming the worst ACCEPTED Heston fit.

An accepted fit (`method == "heston_grid"`) logs nothing in `heston_cache`, so
nothing recorded how poor an accepted fit was. `_execute_scan_core` now
collects every fit that actually reaches a card and, after the per-symbol
gather, logs one line with the count, the worst relative RMSE (symbol, strike
count, longest DTE of the calibrated chain) and the median.

These tests drive the real `_execute_scan_core` -> `_process_symbol` path with
the market data, scoring and calibration mocked per symbol (the same seams
`test_scan_endpoint.py`'s Heston wiring tests and
`test_scan_schedule_entry.py`'s core test patch). `calibrate_heston` is keyed
by the symbol's price, because it is called with `(heston_chain, price, r)` and
never sees the symbol.

Invariant G4: the line is log-only. The last test compares the scan result
with the collector on against the same scan with it disabled.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from app.models.heston import CalibrationResult, HestonParams

_PARAMS = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)

_CANDLES = [
    {"time": f"2026-0{i // 10 + 1}-{i % 28 + 1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]


def _contract(strike: float, dte: int, price: float = 2.50, delta: float = 0.45) -> dict:
    return {"strike": strike, "expiry": "2026-06-20", "price": price, "spread": 0.20,
            "delta": delta, "theta": -0.05, "ivRank": 55, "dte": dte,
            "right": "C", "volume": 500}


# symbol -> (price, chain, calibration outcome). An outcome is a
# CalibrationResult, an Exception to raise, or ("late", CalibrationResult) for
# a fit that only completes after the scan's calibration timeout.
def _accepted(rmse: float) -> CalibrationResult:
    return CalibrationResult(params=_PARAMS, rmse=rmse, method="heston_grid")


_ACCEPTED = {
    # 3 strikes, longest 60 DTE.
    "AAA": (100.0, [_contract(100, 30), _contract(105, 45), _contract(110, 60)],
            _accepted(0.10)),
    # 5 calibrated strikes, longest 120 DTE. The sixth contract (365 DTE) is
    # outside the delta band, so it never reaches `heston_chain` and must not
    # count towards either number.
    "BBB": (200.0, [_contract(200, 30), _contract(205, 30), _contract(210, 45),
                    _contract(215, 90), _contract(220, 120),
                    _contract(260, 365, price=0.30, delta=0.02)],
            _accepted(0.40)),
    # 4 strikes, longest 60 DTE.
    "CCC": (300.0, [_contract(300, 30), _contract(305, 30), _contract(310, 45),
                    _contract(315, 60)],
            _accepted(0.25)),
}

_NOT_ACCEPTED = {
    # Rejected by the flat-BS gate: a worse rmse than every accepted fit, so
    # counting it would change the worst symbol.
    "DDD": (400.0, [_contract(400, 30), _contract(405, 45), _contract(410, 400)],
            CalibrationResult(params=_PARAMS, rmse=0.90, method="bs_flat")),
    "EEE": (500.0, [_contract(500, 30), _contract(505, 45), _contract(510, 400)],
            CalibrationResult(params=_PARAMS, rmse=float("inf"), method="bs_fallback")),
    "FFF": (600.0, [_contract(600, 30), _contract(605, 45), _contract(610, 400)],
            RuntimeError("calibration boom")),
    # A genuine heston_grid fit that arrives after the timeout: abandoned, so
    # it never reaches the card and must not be counted either.
    "GGG": (700.0, [_contract(700, 30), _contract(705, 45), _contract(710, 400)],
            ("late", _accepted(0.95))),
}

_TIMEOUT_S = 0.5
_SUMMARY = "Heston accepted fits"


def _stock_card(symbol, direction, horizon, *_a, **_kw):
    from app.scoring.stock_scorer import RuleResult, StockScoreCard
    # A measured, strong trend, so the scan's direction-conviction floor keeps
    # every name and the Heston block is reached.
    trend = RuleResult(name="trend", status="PASS", score=90, detail={})
    return StockScoreCard(symbol=symbol, direction=direction, horizon=horizon,
                          score=75, status="PASS", rules=[trend])


def _contract_card(contract, stock_score, overrides=None, **_kw):
    from app.scoring.contract_validator import ContractScoreBreakdown, ContractScoreCard
    return ContractScoreCard(
        contract_id=f"X|{contract['strike']}|{contract['expiry']}|C",
        symbol="X", strike=float(contract["strike"]), expiry=contract["expiry"],
        is_call=True, score=70, status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )


def _plan(*_a, heston_params=None, **_kw):
    """A canned plan whose label follows the calibration verdict, so a card
    shows whether an accepted fit reached it."""
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.trade_plan import TradePlan
    return TradePlan(
        entry=EntryAssessment(limit_price=2.50, max_fill=2.53, order_type="Limit",
                              quality_status="PASS"),
        invalidation_price=180.0, premium_stop=1.5, time_stop_days=12,
        target_price=200.0, targets=[], rr_ratio=2.5,
        rr_model="Heston repriced" if heston_params is not None else "Delta approximation",
        target_price_raw=200.0, invalidation_price_raw=180.0,
        rr_risk_basis="premium_stop", target_source="arithmetic",
        stock_stop_loss=None, stock_stop_loss_at=None,
        reprice_years=(45 - 7) / 365.0,
    )


async def _run_scan(universe: dict, *, collector: bool = True):
    """Run `_execute_scan_core` over `universe`; returns the ScanResult.

    `collector=False` routes every `_process_symbol` call through
    `heston_fits=None`, the comparison run for G4."""
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession

    by_symbol = universe
    by_price = {price: outcome for price, _chain, outcome in universe.values()}
    release = threading.Event()
    late_finished = threading.Event()

    def _calibrate(heston_chain, price, r):
        outcome = by_price[price]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):
            release.wait(10.0)
            late_finished.set()
            return outcome[1]
        return outcome

    async def _price(client, symbol, *_a, **_kw):
        return by_symbol[symbol][0]

    async def _chain(client, symbol, *_a, **_kw):
        return [dict(c) for c in by_symbol[symbol][1]]

    real_process = scan_module._process_symbol

    async def _process_without_collector(*args, **kwargs):
        kwargs["heston_fits"] = None
        return await real_process(*args, **kwargs)

    patches = [
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_CANDLES)),
        patch("app.routers.scan.fetch_price_async", side_effect=_price),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", side_effect=_stock_card),
        patch("app.routers.scan.fetch_option_chain_async", side_effect=_chain),
        patch("app.routers.scan.validate_contract", side_effect=_contract_card),
        patch("app.routers.scan.build_trade_plan", side_effect=_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=_calibrate),
        patch("app.routers.scan._HESTON_CALIBRATION_TIMEOUT_S", _TIMEOUT_S),
        patch("app.routers.scan.get_tradier_creds",
              return_value=("tok", "https://example.invalid")),
        patch("app.routers.scan.fetch_quotes", return_value={}),
        patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])),
        patch("app.routers.scan.get_fundamentals", AsyncMock(return_value=None)),
    ]
    if not collector:
        patches.append(patch("app.routers.scan._process_symbol", _process_without_collector))

    has_late = any(isinstance(o, tuple) for _p, _c, o in universe.values())
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            async with _TestSession() as db:
                req = scan_module.ScanRequest(universe=list(universe), direction="Bullish",
                                              horizon="Swing", overrides={})
                result = await scan_module._execute_scan_core(req, db, previous_result=None)
        finally:
            # Let the abandoned calibration finish inside this event loop, so
            # its executor callback does not land on a closed loop.
            release.set()
            if has_late:
                for _ in range(200):
                    if late_finished.is_set():
                        break
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
    return result


def _summary_lines(caplog) -> list[logging.LogRecord]:
    return [rec for rec in caplog.records
            if rec.name == "app.routers.scan" and _SUMMARY in rec.getMessage()]


def _labels(result) -> dict:
    return {c.symbol: c.rrModel for c in result.candidates}


@pytest.mark.asyncio
async def test_one_warning_names_the_worst_accepted_fit(caplog):
    universe = {**_ACCEPTED, **_NOT_ACCEPTED}
    with caplog.at_level(logging.WARNING, logger="app.routers.scan"):
        result = await _run_scan(universe)

    # The scenario is what the test claims: the three accepted fits reached
    # their cards, and none of the others did.
    labels = _labels(result)
    for symbol in _ACCEPTED:
        assert labels.get(symbol) == "Heston repriced", labels
    for symbol in _NOT_ACCEPTED:
        assert labels.get(symbol) == "Delta approximation", labels

    lines = _summary_lines(caplog)
    assert len(lines) == 1, [rec.getMessage() for rec in lines]
    assert lines[0].levelno == logging.WARNING
    assert lines[0].getMessage() == (
        f"SCAN {result.scan_id} Heston accepted fits: 3; worst rel-RMSE 0.4000 on BBB "
        f"(5 strikes, longest 120 DTE); median rel-RMSE 0.2500"
    )


@pytest.mark.asyncio
async def test_no_accepted_fit_logs_no_summary_line(caplog):
    with caplog.at_level(logging.WARNING, logger="app.routers.scan"):
        result = await _run_scan(dict(_NOT_ACCEPTED))

    labels = _labels(result)
    assert set(labels) == set(_NOT_ACCEPTED), labels
    assert all(label == "Delta approximation" for label in labels.values()), labels
    assert _summary_lines(caplog) == []


@pytest.mark.asyncio
async def test_the_summary_is_log_only(caplog):
    """G4: cards, labels and rejections are the same with the collector on and
    with it disabled; only the log differs."""
    universe = {**_ACCEPTED, **_NOT_ACCEPTED}
    with caplog.at_level(logging.WARNING, logger="app.routers.scan"):
        with_collector = await _run_scan(universe, collector=True)
    assert len(_summary_lines(caplog)) == 1
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.routers.scan"):
        without_collector = await _run_scan(universe, collector=False)
    assert _summary_lines(caplog) == []

    def _scrub(node):
        # `exit.finalStop.computedAt` is a wall-clock stamp taken per card, so
        # two runs differ there whatever the collector does.
        if isinstance(node, dict):
            return {k: _scrub(v) for k, v in node.items() if k != "computedAt"}
        if isinstance(node, list):
            return [_scrub(v) for v in node]
        return node

    def _comparable(result) -> dict:
        dumped = result.model_dump()
        for volatile in ("scan_id", "timestamp"):
            dumped.pop(volatile, None)
        return _scrub(dumped)

    assert with_collector.candidates, "the comparison must cover real cards"
    assert _comparable(with_collector) == _comparable(without_collector)
