"""TRADING-REVIEW-PHASE-C T11: the read-only evidence harness under scripts/evidence/.

Pure cores only; no database. The scripts are added to sys.path the same way
tests/test_retune_archived_basket.py does it.
"""
from datetime import date, timedelta
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "scripts" / "evidence"
sys.path.insert(0, str(REPO / "scripts"))

from app.scoring.signal_confidence import load_backtest_cfg  # noqa: E402

HARNESS_MODULES = ("__init__.py", "_bars.py", "bar_basis_check.py", "score_calibration.py")


def _bar(i, o, h, l, c, v=1_000):
    return {"time": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_basis_violations_counts_close_outside_range():
    from evidence.bar_basis_check import basis_violations

    bars = [
        _bar(0, 10.0, 11.0, 9.0, 10.5),
        _bar(1, 10.5, 11.5, 10.0, 12.0),   # close above high: the H1 mixed-basis signature
        _bar(2, 12.0, 12.5, 11.5, 12.2),
    ]
    out = basis_violations(bars)
    assert out["n"] == 3
    assert out["close_outside"] == 1
    assert out["open_outside"] == 0
    assert out["any_outside"] == 1
    assert out["share"] == pytest.approx(1 / 3)


def test_big_jumps_flags_split_sized_step_and_ignores_small_move():
    from evidence.bar_basis_check import big_jumps

    bars = [
        _bar(0, 10.0, 10.0, 10.0, 10.0),
        _bar(1, 10.3, 10.3, 10.3, 10.3),            # +3%: a real move
        _bar(2, 79.928, 79.928, 79.928, 79.928),    # x7.76: a missed reverse split
    ]
    jumps = big_jumps(bars, 0.40)
    assert len(jumps) == 1
    assert jumps[0]["time"] == bars[2]["time"]
    assert jumps[0]["ratio"] == pytest.approx(7.76)


class _Card:
    def __init__(self, status):
        self.status = status


def _even_pass_scorer(*, symbol, direction, horizon, bars, scoring_mode="options", **_):
    i = len(bars) - 1
    return _Card("PASS" if i % 2 == 0 else "REJECT")


def _uptrend(n=200):
    return [_bar(i, 100.0 + i, 100.5 + i, 99.5 + i, 100.0 + i) for i in range(n)]


def _greedy(candidates, gap):
    taken = []
    for i in candidates:
        if not taken or i >= taken[-1] + gap:
            taken.append(i)
    return taken


def test_calibrate_buckets_distinct_setups_with_reproducible_ci():
    from evidence.score_calibration import calibrate, confidence_counts, replay

    bars = {"UP": _uptrend()}
    cfg = load_backtest_cfg("Swing")
    n_days, min_samples = int(cfg["n_days"]), int(cfg["min_samples"])
    warmup, last = 60, len(bars["UP"]) - n_days

    first = calibrate(bars, "Swing", "Bullish", scorer=_even_pass_scorer)
    second = calibrate(bars, "Swing", "Bullish", scorer=_even_pass_scorer)
    assert first == second

    by_bucket = {s.bucket: s for s in first}
    expected_pass = _greedy([i for i in range(warmup, last) if i % 2 == 0], n_days)
    expected_reject = _greedy([i for i in range(warmup, last) if i % 2 == 1], n_days)
    assert by_bucket["PASS"].n == len(expected_pass)
    assert by_bucket["REJECT"].n == len(expected_reject)
    assert by_bucket["CAUTION"].n == 0
    assert by_bucket["ALL"].n == len(_greedy(list(range(warmup, last)), n_days))

    # Every bar of a steady up-trend reaches the +target barrier before the stop.
    win_r = float(cfg["atr_mult_target"]) / float(cfg["atr_mult_stop"])
    assert by_bucket["PASS"].mean_r > 0
    assert by_bucket["PASS"].mean_r == pytest.approx(win_r)
    assert by_bucket["PASS"].ci_low <= by_bucket["PASS"].mean_r <= by_bucket["PASS"].ci_high

    # The confidence replay's sample size both ways, against min_samples.
    counts = confidence_counts(
        {"UP": replay(bars["UP"], "Swing", "Bullish", scorer=_even_pass_scorer)}, "Swing",
    )
    assert len(counts) == 1
    c = counts[0]
    assert c.overlapping == len([i for i in range(warmup, last) if i % 2 == 0])
    assert c.non_overlapping == len(expected_pass)
    assert c.min_samples == min_samples


def test_no_harness_module_mentions_get_bars():
    present = {p.name for p in EVIDENCE.glob("*.py")}
    assert set(HARNESS_MODULES) <= present
    for path in sorted(EVIDENCE.glob("*.py")):
        assert "get_bars" not in path.read_text(encoding="utf-8"), path.name


# ── TRADING-REVIEW-PHASE-C T12: gate persistence and strategy matrix ─────────

class _Res:
    """Stub BacktestResult: only the fields the pure cores read."""

    def __init__(self, n_trades, expectancy):
        self.n_trades = n_trades
        self.expectancy = expectancy


def test_spearman_identical_reversed_and_tied_ranks():
    from evidence.gate_persistence import spearman

    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    # Ties take the average rank: x ranks [1, 2.5, 2.5, 4] against y ranks [1, 2, 3, 4]
    # give 4.5 / sqrt(4.5 * 5). Ordinal tie-breaking would give exactly 1.0.
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(4.5 / (4.5 * 5) ** 0.5)


def test_persistence_excludes_symbols_below_min_trades_in_either_half():
    from evidence.gate_persistence import persistence

    results_a = {"A": _Res(10, 1.0), "B": _Res(10, 2.0), "C": _Res(3, 5.0),
                 "D": _Res(8, 3.0), "F": _Res(9, 4.0)}
    results_b = {"A": _Res(6, 0.5), "B": _Res(7, 1.5), "C": _Res(9, -1.0),
                 "D": _Res(4, 2.0), "E": _Res(10, 1.0), "F": _Res(5, 3.0)}
    out = persistence(results_a, results_b, min_trades=5)
    # C is short in half A, D in half B, E is missing from half A.
    assert out.symbols == ["A", "B", "F"]
    assert out.n == 3
    assert out.rho == pytest.approx(1.0)
    assert out.band == pytest.approx(1.96 / (3 - 1) ** 0.5)


def test_pool_is_trade_weighted():
    from app.services.strategy_backtest import _MIN_TRADES
    from evidence.strategy_matrix import pool

    results = {"A": _Res(10, 1.0), "B": _Res(30, -1.0)}
    row = pool(results)
    assert row.n_trades == 40
    assert row.n_symbols == 2
    assert row.mean_trade_return_pct == pytest.approx((10 * 1.0 + 30 * -1.0) / 40)
    assert row.share_min_trades == pytest.approx(1.0)

    results["C"] = _Res(_MIN_TRADES - 1, 5.0)
    row = pool(results)
    assert row.n_trades == 40 + _MIN_TRADES - 1
    assert row.mean_trade_return_pct == pytest.approx(
        (10 * 1.0 + 30 * -1.0 + (_MIN_TRADES - 1) * 5.0) / (40 + _MIN_TRADES - 1))
    assert row.share_min_trades == pytest.approx(2 / 3)
    assert row.ci_low <= row.ci_high
    assert pool(results) == row       # fixed seed: reproducible CI


def test_both_scripts_pass_commission_to_run_strategy_backtest(monkeypatch):
    from evidence import gate_persistence, strategy_matrix

    calls = []

    def recorder(bars, **kw):
        calls.append({"n": len(bars), "first": bars[0]["time"], **kw})
        return _Res(0, 0.0)

    monkeypatch.setattr(gate_persistence, "run_strategy_backtest", recorder)
    monkeypatch.setattr(strategy_matrix, "run_strategy_backtest", recorder)
    costs = {"fee_pct": 0.002, "slippage_pct": 0.0005}
    bars = [_bar(i, 100.0, 101.0, 99.0, 100.0) for i in range(900)]

    gate_persistence.run_halves({"X": bars}, "pullback_ema", "Bullish", costs)
    assert len(calls) == 2
    assert all(c["commission"] == pytest.approx(0.0025) for c in calls)
    first, second = calls
    assert first["entry_start"] == date.fromisoformat(bars[0]["time"])
    assert first["n"] == 450
    # Second half: entries from the midpoint, behind WFO's 260-bar warm-up prefix.
    assert second["entry_start"] == date.fromisoformat(bars[450]["time"])
    assert second["first"] == bars[450 - 260]["time"]
    assert second["n"] == 450 + 260

    calls.clear()
    strategy_matrix.run_cell({"X": bars}, "pullback_ema", "Bullish", costs)
    assert len(calls) == 1
    assert calls[0]["commission"] == pytest.approx(0.0025)
    assert calls[0]["n"] == 900
    assert calls[0].get("entry_start") is None


# ── STOCKS-HORIZON-P0A A3: the harness skips the shared exclusion list ──────

import asyncio  # noqa: E402

# PXD is scope: scan, BIIB scope: evidence in backend/config/universe_exclusions.yaml.
_STORED = ["AAPL", "BIIB", "MSFT", "PXD"]


async def _fake_stored_symbols(*, session_factory=None):
    return list(_STORED)


def _stub_stored(monkeypatch):
    from evidence import _bars

    monkeypatch.setattr(_bars, "stored_symbols", _fake_stored_symbols)


def test_evidence_symbols_drops_both_scopes_from_stored_and_requested(monkeypatch):
    from evidence._bars import evidence_symbols

    _stub_stored(monkeypatch)
    kept, excluded = asyncio.run(evidence_symbols(None))
    assert kept == ["AAPL", "MSFT"]
    assert [(e.symbol, e.scope) for e in excluded] == [("BIIB", "evidence"), ("PXD", "scan")]

    kept, excluded = asyncio.run(evidence_symbols(["pxd", "NVDA"]))
    assert kept == ["NVDA"]
    assert [e.symbol for e in excluded] == ["PXD"]


def test_include_excluded_flag_keeps_every_symbol(monkeypatch):
    from evidence._bars import common_parser, evidence_symbols

    _stub_stored(monkeypatch)
    assert common_parser("x").parse_args([]).include_excluded is False
    assert common_parser("x").parse_args(["--include-excluded"]).include_excluded is True
    kept, excluded = asyncio.run(evidence_symbols(None, include_excluded=True))
    assert kept == _STORED
    assert excluded == []


def test_report_header_lists_exclusions_or_none():
    from app.data.universe_exclusions import Exclusion
    from evidence._bars import report_header

    kw = dict(symbols=["AAPL"], start="2020-01-01", end="2020-12-31", cost_model="n/a")
    excluded = [Exclusion("BIIB", "evidence", "r1"), Exclusion("PXD", "scan", "r2")]
    lines = report_header("T", excluded=excluded, **kw).splitlines()
    assert "- Excluded (universe_exclusions.yaml): 2 — BIIB (evidence), PXD (scan)" in lines
    assert "- Excluded (universe_exclusions.yaml): none" in report_header("T", **kw).splitlines()


class _StopAfterLoad(Exception):
    pass


@pytest.mark.parametrize("script", ["score_calibration", "gate_persistence", "strategy_matrix"])
def test_evidence_scripts_load_only_kept_symbols(monkeypatch, script):
    import importlib

    module = importlib.import_module(f"evidence.{script}")
    _stub_stored(monkeypatch)
    seen = []

    async def fake_load_bars(symbols, start, end, **_):
        seen.append(list(symbols))
        raise _StopAfterLoad

    monkeypatch.setattr(module, "load_bars", fake_load_bars)
    for argv, expected in (([], ["AAPL", "MSFT"]), (["--include-excluded"], _STORED)):
        seen.clear()
        args = module.common_parser("x").parse_args(argv)
        with pytest.raises(_StopAfterLoad):
            asyncio.run(module._main(args))
        assert seen == [expected]


def test_bar_basis_check_is_not_filtered(monkeypatch):
    from evidence import bar_basis_check

    seen = {}

    async def fake_load_bars(symbols, start, end, **_):
        seen["bars"] = list(symbols)
        return {s: [] for s in symbols}

    async def fake_load_basis_rows(symbols, **_):
        seen["rows"] = list(symbols)
        return {s: [] for s in symbols}

    async def fake_load_history_states(symbols, **_):
        assert list(symbols) == _STORED
        return {}

    monkeypatch.setattr(bar_basis_check, "stored_symbols", _fake_stored_symbols)
    monkeypatch.setattr(bar_basis_check, "load_bars", fake_load_bars)
    monkeypatch.setattr(bar_basis_check, "load_basis_rows", fake_load_basis_rows)
    monkeypatch.setattr(bar_basis_check, "load_history_states", fake_load_history_states)
    args = bar_basis_check.common_parser("x").parse_args([])
    report = asyncio.run(bar_basis_check._main(args))
    assert seen == {"bars": _STORED, "rows": _STORED}
    assert "- Excluded (universe_exclusions.yaml): none" in report.splitlines()
