"""P3a item 12: an Intraday scan drops a name whose 15-min regime bars could not
be had, whenever the auto-trader's fire would refuse it -- the YAML regime gate
enabled, the regime filter on, or regime sizing on (decisions
P3A-INTRADAY-REGIME-FETCH-REFUSES-2026-09-25 and
P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25). A short series still abstains.

Config is swapped IN MEMORY (`_load_full_scoring_cfg` patched); nothing is
written to backend/config.
"""
from __future__ import annotations

import copy
import time

import pytest

from app.routers import stock_scan as ss
from app.schemas.stock_scan import PositionCardOut, StockAnalysisRequest, StockScanRequest
from tests.test_a5c_analysis_scan_drop_flags import (
    PREFIX, _firing_signal, _offline, _signal_stub,
)

_REAL_CFG = copy.deepcopy(ss._load_full_scoring_cfg())
_MIN_OBS = _REAL_CFG["regime"]["intraday"]["min_obs"]


def _completed(n: int) -> list[dict]:
    # Unix-int starts a year in the past: every bar is complete.
    t0 = int(time.time()) - 365 * 86400
    return [{"time": t0 + i * 900, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 10_000} for i in range(n)]


def _forming() -> list[dict]:
    return [{"time": int(time.time()), "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 10_000}]


def _raises(*a, **k):
    raise RuntimeError("tradier down")


def _cfg(monkeypatch, *, gate: bool = True, sizing: bool = True):
    cfg = copy.deepcopy(_REAL_CFG)
    cfg["regime_gate"]["enabled"] = gate
    cfg["regime_sizing"]["enabled"] = sizing
    monkeypatch.setattr(ss, "_load_full_scoring_cfg", lambda: cfg)


def _counting(bars_or_fn):
    calls = []

    def _fetch(*a, **k):
        calls.append(a)
        if callable(bars_or_fn):
            return bars_or_fn(*a, **k)
        return list(bars_or_fn)
    return _fetch, calls


async def _scan(**kw):
    req = StockScanRequest(universe=["TEST"], **{"direction": "Bullish", "horizon": "Intraday",
                                                 "strategy": "pullback_ema", **kw})
    return await ss._process_stock("TEST", req, "scan-1", {"TEST": {"last": 130.0}}, [],
                                   fund_gate=None)


def _is_regime_drop(result) -> bool:
    return isinstance(result, dict) and result.get("reason", "").startswith(
        "regime data unavailable:")


# ── the drop ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fetch", [_raises, [], _forming()], ids=["raises", "empty", "forming-only"])
async def test_the_shipped_gate_alone_drops_a_name_with_no_regime_bars(monkeypatch, fetch):
    """B1: the UI never sends regime_filter; the YAML gate (shipped on) is what
    makes the fire measure, so it alone must make the scan drop."""
    _offline(monkeypatch, intraday=fetch if callable(fetch) else fetch)
    _cfg(monkeypatch, gate=True, sizing=False)
    result = await _scan(regime_filter=False)
    assert _is_regime_drop(result), result
    assert result["reason"].startswith("regime data unavailable: no completed 15-min bars for TEST")
    if fetch is _raises:
        assert "tradier down" in result["reason"]
    assert ss.classify_stock_rejection(result["reason"]) == "failed_history"


@pytest.mark.parametrize("gate,filt,sizing,dropped", [
    (False, False, False, False),   # nothing measures -> the fire never fetches
    (False, True, False, True),     # filter only (stricter than the fire)
    (False, False, True, True),     # sizing only
    (True, False, False, True),     # gate only
])
async def test_the_drop_follows_when_the_measurement_is_used(monkeypatch, gate, filt, sizing, dropped):
    _offline(monkeypatch, intraday=_raises)
    _signal_stub(monkeypatch, "pullback_ema", _firing_signal("pullback_ema"))
    _cfg(monkeypatch, gate=gate, sizing=sizing)
    result = await _scan(regime_filter=filt)
    assert _is_regime_drop(result) is dropped, result


async def test_a_short_series_still_abstains_and_is_floor_sized(monkeypatch):
    _offline(monkeypatch, intraday=_completed(_MIN_OBS - 1), bt_passes=True)
    _signal_stub(monkeypatch, "pullback_ema", _firing_signal("pullback_ema"))
    _cfg(monkeypatch, gate=True, sizing=True)
    result = await _scan()
    assert isinstance(result, PositionCardOut), result
    assert result.sizing_basis == "floor:unmeasured"


async def test_a_non_vwap_intraday_scan_measures_on_one_fetch(monkeypatch):
    """Round 4 F1: the regime must not reuse the EMPTY default of a signal fetch
    that never ran for a non-VWAP strategy."""
    fetch, calls = _counting(_completed(_MIN_OBS + 10))
    _offline(monkeypatch, intraday=fetch, bt_passes=True)
    _signal_stub(monkeypatch, "pullback_ema", _firing_signal("pullback_ema"))
    _cfg(monkeypatch, gate=True, sizing=True)
    result = await _scan()
    assert isinstance(result, PositionCardOut), result
    assert result.sentiment is not None
    assert result.sizing_basis == "measured"
    assert len(calls) == 1


async def test_a_daily_horizon_is_unaffected(monkeypatch):
    fetch, calls = _counting(_raises)
    _offline(monkeypatch, intraday=fetch)
    _signal_stub(monkeypatch, "pullback_ema", None)
    _cfg(monkeypatch, gate=True, sizing=True)
    result = await _scan(horizon="Swing")
    assert not _is_regime_drop(result), result
    assert calls == [], "a daily-regime, non-VWAP scan fetches no 15-min bars"


async def test_analysis_flags_the_same_drop(monkeypatch):
    _offline(monkeypatch, intraday=_raises)
    _cfg(monkeypatch, gate=True, sizing=False)
    req = StockAnalysisRequest(symbol="TEST", direction="Bullish", horizon="Intraday",
                               strategy="pullback_ema")
    core = await ss._analyze_core("TEST", req)
    flags = [g for g in core.gate_flags if g["gate"] == "regime_data"]
    assert len(flags) == 1 and flags[0]["status"] == "REJECT"
    assert flags[0]["detail"].startswith(PREFIX + "regime data unavailable: no completed 15-min bars for TEST")
    assert "tradier down" in flags[0]["detail"]
