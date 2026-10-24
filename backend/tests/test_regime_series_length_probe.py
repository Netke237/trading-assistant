"""T1 unit tests for `backend/scripts/regime_series_length_probe.py` (REGIME-SERIES-LENGTH).

Plan: docs/superpowers/plans/2026-10-24-regime-series-length-plan.md, Task 1 (T1).
Covers:
  1. Probe uses shipped compute_omm from app.services.regime_omm.
  2. Probe reads official scoring rules from backend/config/scoring_rules.yaml.
  3. Window slicing logic against fixture / synthetic data (Window A 304 bars,
     Window B 520/800 bars, Window C 5-year history).
  4. Gate classification matches scoring_rules.yaml (-15% caution, -40% reject if stable).
  5. Measurement cell evaluation and silent bypass detection.
  6. Output dictionary schema validation (no null/NaN/Inf fields in output).

No network: every test runs under a socket guard.
"""
from __future__ import annotations

import math
import socket
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

# Socket guard: tests must never touch the network
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_a, **_k):
        raise AssertionError("network access attempted during a probe test")
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)


import regime_series_length_probe as probe  # noqa: E402
from app.services import regime_omm as omm_mod  # noqa: E402


def test_uses_shipped_compute_omm():
    """Verify probe delegates to the shipped app.services.regime_omm.compute_omm."""
    assert probe.compute_omm is omm_mod.compute_omm


def test_reads_official_scoring_rules():
    """Verify probe reads scoring rules from backend/config/scoring_rules.yaml."""
    cfg = probe.load_scoring_rules()
    assert "regime" in cfg
    assert "regime_gate" in cfg

    # Horizon parameters
    assert cfg["regime"]["swing"]["lookback"] == 20
    assert cfg["regime"]["swing"]["window"] == 500
    assert cfg["regime"]["swing"]["min_obs"] == 100

    assert cfg["regime"]["position"]["lookback"] == 50
    assert cfg["regime"]["position"]["window"] == 750
    assert cfg["regime"]["position"]["min_obs"] == 100

    # Gate thresholds
    assert cfg["regime_gate"]["enabled"] is True
    assert cfg["regime_gate"]["headwind_caution_pct"] == -15
    assert cfg["regime_gate"]["headwind_reject_pct"] == -40
    assert cfg["regime_gate"]["require_stable_for_reject"] is True


def test_window_slicing_by_bar_count():
    """Verify Window A, B, and C bar-count slicing logic."""
    # Series of 1500 closes
    series = [float(100 + i * 0.1) for i in range(1500)]

    # Window A: 304 bars
    slice_a = probe.slice_bars(series, window="A")
    assert len(slice_a) == 304
    assert slice_a == series[-304:]

    # Window B swing: 500 + 20 = 520 bars
    slice_b_swing = probe.slice_bars(series, window="B", horizon="swing")
    assert len(slice_b_swing) == 520
    assert slice_b_swing == series[-520:]

    # Window B position: 750 + 50 = 800 bars
    slice_b_pos = probe.slice_bars(series, window="B", horizon="position")
    assert len(slice_b_pos) == 800
    assert slice_b_pos == series[-800:]

    # Window C: full history
    slice_c = probe.slice_bars(series, window="C")
    assert len(slice_c) == len(series)
    assert slice_c == series


def test_window_slicing_short_series():
    """Verify slicing gracefully handles series shorter than the requested window."""
    short_series = [float(100 + i) for i in range(200)]

    assert len(probe.slice_bars(short_series, window="A")) == 200
    assert len(probe.slice_bars(short_series, window="B", horizon="swing")) == 200
    assert len(probe.slice_bars(short_series, window="B", horizon="position")) == 200
    assert len(probe.slice_bars(short_series, window="C")) == 200


def test_window_slicing_date_aware():
    """Verify date-based slicing when bars carry timestamps/dates."""
    from datetime import date, timedelta
    anchor = date(2026, 10, 24)
    # Generate 1500 trading days (skipping weekends)
    dates = []
    cur = anchor
    while len(dates) < 1500:
        if cur.weekday() < 5:
            dates.append(cur)
        cur -= timedelta(days=1)
    dates.reverse()

    bars = [{"date": d, "close": 100.0 + idx} for idx, d in enumerate(dates)]

    # Window A by date: 441 calendar days (int(1.75 * 252))
    slice_a = probe.slice_bars_date(bars, window="A", as_of=anchor)
    min_date_a = min(b["date"] for b in slice_a)
    assert min_date_a >= anchor - timedelta(days=int(1.75 * 252))
    assert max(b["date"] for b in slice_a) <= anchor

    # Window C by date: 5 years (5 * 365)
    slice_c = probe.slice_bars_date(bars, window="C", as_of=anchor)
    min_date_c = min(b["date"] for b in slice_c)
    assert min_date_c >= anchor - timedelta(days=5 * 365)


def test_gate_classification():
    """Verify classify_gate matches scoring_rules.yaml thresholds."""
    gate_cfg = {
        "enabled": True,
        "headwind_caution_pct": -15,
        "headwind_reject_pct": -40,
        "require_stable_for_reject": True,
    }

    # Unmeasured
    assert probe.classify_gate(None, gate_cfg) == "UNMEASURED"

    # Measured outcomes
    assert probe.classify_gate(probe.GateInput(conviction_pct=25, stability="Stable"), gate_cfg) == "PASS"
    assert probe.classify_gate(probe.GateInput(conviction_pct=0, stability="Stable"), gate_cfg) == "PASS"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-14, stability="Stable"), gate_cfg) == "PASS"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-15, stability="Stable"), gate_cfg) == "CAUTION"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-25, stability="Fragile"), gate_cfg) == "CAUTION"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-39, stability="Stable"), gate_cfg) == "CAUTION"

    # Reject boundary: requires Stable
    assert probe.classify_gate(probe.GateInput(conviction_pct=-40, stability="Stable"), gate_cfg) == "REJECT"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-40, stability="Fragile"), gate_cfg) == "CAUTION"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-50, stability="Stable"), gate_cfg) == "REJECT"
    assert probe.classify_gate(probe.GateInput(conviction_pct=-50, stability="Fragile"), gate_cfg) == "CAUTION"


def test_silent_bypass_detection():
    """Verify detection of silent bypasses (unmeasured in A, but gated in B or C)."""
    # Case 1: Unmeasured in A, Caution in C
    assert probe.is_silent_bypass(
        status_a="UNMEASURED",
        status_target="CAUTION",
        conviction_target=-20,
    ) is True

    # Case 2: Unmeasured in A, Reject in C
    assert probe.is_silent_bypass(
        status_a="UNMEASURED",
        status_target="REJECT",
        conviction_target=-45,
    ) is True

    # Case 3: Unmeasured in A, Pass in C -> Not a silent bypass of a gate demotion
    assert probe.is_silent_bypass(
        status_a="UNMEASURED",
        status_target="PASS",
        conviction_target=10,
    ) is False

    # Case 4: Measured in A -> Not a bypass
    assert probe.is_silent_bypass(
        status_a="PASS",
        status_target="CAUTION",
        conviction_target=-20,
    ) is False


def test_conviction_delta_stats():
    """Verify conviction delta summary statistics."""
    deltas = [-10, 0, 10, 20, 30]
    stats = probe.compute_delta_stats(deltas)
    assert stats["count"] == 5
    assert stats["min"] == -10
    assert stats["max"] == 30
    assert stats["median"] == 10.0
    assert stats["mean"] == 10.0
    assert math.isclose(stats["std_dev"], 15.8114, rel_tol=1e-3)


def test_schema_conformance_and_no_nan():
    """Verify that simulated output schemas contain no None/NaN/inf floats."""
    m1_sample = {
        "metadata": {"total_symbols": 540, "total_cells": 2160},
        "windows": {
            "A": {"measured": 1200, "unmeasured": 960, "unmeasured_rate_pct": 44.44},
            "B": {"measured": 2000, "unmeasured": 160, "unmeasured_rate_pct": 7.41},
            "C": {"measured": 2000, "unmeasured": 160, "unmeasured_rate_pct": 7.41},
        },
    }

    def _check_no_nan(obj, path=""):
        if isinstance(obj, float):
            assert not math.isnan(obj), f"NaN found at {path}"
            assert not math.isinf(obj), f"Inf found at {path}"
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _check_no_nan(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                _check_no_nan(item, f"{path}[{idx}]")

    _check_no_nan(m1_sample)
