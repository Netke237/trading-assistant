"""TUNER-RECHECK-WINDOW Task 3: strategy-specific runtime projections.

The projection (``--probe`` and the run's preflight) weights each
``(strategy, direction)`` pair's sample-grid and re-check signal calls with
that pair's own measured cost and sums the durations; it never averages costs
across strategies. An ordinary fold winner is counted only on the eligible
bars of its fold's test-entry window (warm-up applied), the final parameters
on the full series of every trade- and fire-rate-universe symbol, a setup
winner on full series (an upper bound). Expected numbers below are written out
independently from the calendars, never read back from the model.
"""
from __future__ import annotations

import bisect
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import app.services.strategy_param_store as store
from app.services.horizon_tuning import basket, gates, report, signals
from app.services.horizon_tuning import walk_forward_cell as wfc
from app.services.strategy_param_store import get_tuning_config
from tests.test_horizon_tuning_report import CAL, _config, _sawtooth
from tests.test_horizon_tuning_report import planted as planted  # noqa: F401  (fixture)
from tests.test_tuner_recheck_window import (
    _assert_same_recheck, _calendar_bars, _full_recheck_reference, _param_value, _planted,
    _planted_universe, _result,
)
from tests.test_tuner_recheck_window import planted as planted_recheck  # noqa: F401  (fixture)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tune_horizons.py"
H = 3_600_000.0          # ms per hour


def _cli():
    spec = importlib.util.spec_from_file_location("tune_horizons_projection", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _full(n: int) -> int:
    return max(0, n - 59)


def _window(dates, entry) -> int:
    """Eligible signal bars of one entry window: [bisect_left(e0), bisect_left(e1))
    from the 60th bar on (the generator's warm-up)."""
    lo, hi = bisect.bisect_left(dates, entry[0]), bisect.bisect_left(dates, entry[1])
    return max(0, hi - max(lo, 59))


# Deterministic, deliberately disparate per-pair costs.
SIG = {("pullback_ema", "Bullish"): 0.5, ("pullback_ema", "Bearish"): 7.0,
       ("ma_crossover", "Bullish"): 2.0, ("ma_crossover", "Bearish"): 0.25,
       ("breakout_setup", "Bullish"): 4.0}
SIM = {("pullback_ema", "Bullish"): 0.25, ("pullback_ema", "Bearish"): 3.0,
       ("ma_crossover", "Bullish"): 1.5, ("ma_crossover", "Bearish"): 0.75,
       ("breakout_setup", "Bullish"): 2.5}
GATE = {"Bullish": 0.125, "Bearish": 2.0}


def _fake_timings(mod, monkeypatch, seen=None):
    seen = seen if seen is not None else []

    def sig(bars, strategy, direction, *a, **k):
        seen.append(("signal", strategy, direction))
        return SIG[(strategy, direction)]

    def sim(bars, strategy, direction, *a, **k):
        seen.append(("sim", strategy, direction))
        return SIM[(strategy, direction)]

    def gate(bars, direction, *a, **k):
        seen.append(("gate", direction))
        return GATE[direction]
    monkeypatch.setattr(mod, "_time_signal_ms", sig)
    monkeypatch.setattr(mod, "_time_sim_ms", sim)
    monkeypatch.setattr(mod, "_time_gate_ms", gate)
    return seen


# ── the window count is the generator's own ─────────────────────────────────

@pytest.mark.parametrize("span", [(0, 10), (0, 59), (0, 60), (50, 70), (59, 62), (300, 345), (600, 700),
                                  (619, 620), (620, 700)])
def test_entry_window_calls_equal_the_generators_strategy_invocations(span, monkeypatch):
    bars = _calendar_bars()
    dates = wfc.bar_dates(bars)
    ext = [*dates, *(date.fromordinal(dates[-1].toordinal() + i) for i in range(1, 100))]
    entry = (ext[span[0]], ext[span[1]])
    calls = []
    monkeypatch.setattr(signals, "_signal_fn",
                        lambda _: lambda b, **kw: calls.append(len(b)) or None)
    window = (bisect.bisect_left(dates, entry[0]), bisect.bisect_left(dates, entry[1]))
    signals.signal_series(bars, "pullback_ema", "Bullish", {}, window=window)
    cli = _cli()
    assert cli._entry_window_calls(dates, entry) == len(calls) == _window(dates, entry)


def test_model_counts_the_recheck_calls_actually_made_and_parity_holds(planted_recheck, monkeypatch):
    """Distinct winner requests per fold (cold, no cache): the model's winner and
    final calls are exactly the ordinary strategy invocations of the re-check,
    which equals the independent full-series reference; the old full-span
    model counted far more."""
    calls = Counter()

    def recording(bars, *, direction, **params):
        calls[_param_value(params)] += 1
        return _planted(bars, direction=direction, **params)
    monkeypatch.setattr(signals, "_signal_fn", lambda _: recording)
    cfg = get_tuning_config()
    res = _result()                      # winners k=1, 2, 1 on windows A, B, B: three distinct requests
    u = _planted_universe()
    got = report.full_universe_recheck(res, u, cfg)
    actual = sum(calls.values())
    _assert_same_recheck(got, _full_recheck_reference(res, u, cfg), res, cfg)

    cli = _cli()
    cell = res.cell
    trade_dates = {s: wfc.bar_dates(u.bars[s]) for s in u.trade_universe}
    lengths = [len(u.bars[s]) for s in sorted(set(u.trade_universe) | set(u.fire_rate_universe))]
    work = cli._work([cell], n_sample=1, sample_calls_by_pair={}, trade_dates=trade_dates,
                     final_bars=lengths, folds_by_horizon={"Swing": [f.fold for f in res.folds]},
                     valid_by_cell={cell: 3})
    pair = work["pairs"][(cell.strategy, cell.direction)]
    folds = [f.fold for f in res.folds]
    winner = sum(_window(d, f.test_entry) for d in trade_dates.values() for f in folds)
    final = sum(_full(len(u.bars[s])) for s in ("Z", "A", "LATE", "GAP", "EV"))    # EV: evidence only
    assert pair["winner_calls"] == winner
    assert pair["final_calls"] == final
    assert pair["winner_calls"] + pair["final_calls"] == actual
    legacy = (min(3, 3) + 1) * sum(_full(len(u.bars[s])) for s in u.trade_universe)
    assert pair["legacy_recheck_calls"] == legacy
    assert pair["winner_calls"] + pair["final_calls"] < legacy


# ── the pure model: pairs, setup spans, evidence-only work, workers ──────────

def _fold(i, entry):
    return wfc.CellFold(i, entry[0], entry[1], entry[0], entry[1], entry, entry)


def test_each_pair_weighted_by_its_own_cost_and_workers_divide_only_pool_work():
    cli = _cli()
    dates = wfc.bar_dates(_calendar_bars(400))
    short = wfc.bar_dates(_calendar_bars(300, start=100))
    folds = {"Swing": [_fold(0, (dates[200], dates[250])), _fold(1, (dates[250], dates[330]))],
             "Position": [_fold(0, (dates[30], dates[90]))]}
    cells = [wfc.Cell("pullback_ema", "Bullish", "Swing"), wfc.Cell("pullback_ema", "Bearish", "Swing"),
             wfc.Cell("ma_crossover", "Bullish", "Position"), wfc.Cell("breakout_setup", "Bullish", "Swing")]
    valid = {cells[0]: 4, cells[1]: 1, cells[2]: 2, cells[3]: 1}
    trade_dates = {"T1": dates, "T2": short}
    lengths = [400, 300, 250]           # the third symbol is evidence-only (fire-rate universe)
    sample_calls = {("pullback_ema", "Bullish"): 1000, ("pullback_ema", "Bearish"): 300,
                    ("ma_crossover", "Bullish"): 70, ("breakout_setup", "Bullish"): 11}
    work = cli._work(cells, n_sample=2, sample_calls_by_pair=sample_calls, trade_dates=trade_dates,
                     final_bars=lengths, folds_by_horizon=folds, valid_by_cell=valid)
    pairs = work["pairs"]
    final = _full(400) + _full(300) + _full(250)
    swing_win = sum(_window(d, f.test_entry) for d in (dates, short) for f in folds["Swing"])
    pos_win = sum(_window(d, f.test_entry) for d in (dates, short) for f in folds["Position"])
    trade_full = _full(400) + _full(300)
    # Ordinary winners: entry windows only (Position's window lies inside the warm-up on T1
    # and before T2's history). Setup winners: full series x min(folds, valid).
    assert pos_win == 90 - 59
    assert pairs[("pullback_ema", "Bullish")]["winner_calls"] == swing_win
    assert pairs[("pullback_ema", "Bearish")]["winner_calls"] == swing_win
    assert pairs[("ma_crossover", "Bullish")]["winner_calls"] == pos_win
    assert pairs[("breakout_setup", "Bullish")]["winner_calls"] == min(2, 1) * trade_full
    for p in pairs.values():
        assert p["final_calls"] == final                    # includes the evidence-only symbol
    for pair, n in sample_calls.items():
        assert pairs[pair]["sample_calls"] == n
    sims = {pair: valid[c] * 2 * len(folds[c.horizon]) + 2 * len(folds[c.horizon]) * 3 + 2 * 2
            + 2 * len(folds[c.horizon]) * 2 + 2 * 2 for c in cells for pair in [(c.strategy, c.direction)]}
    for pair, n in sims.items():
        assert pairs[pair]["sim_windows"] == n
    # Gate masks: one per symbol, direction and scoring horizon.
    scoring = {d: {gates.scoring_horizon_for(c.horizon) for c in cells if c.direction == d}
               for d in ("Bullish", "Bearish")}
    assert work["gate_bars"] == {d: len(s) * sum(lengths) for d, s in scoring.items()}

    for workers in (1, 4):
        proj = cli._project(work, signal_ms=SIG, sim_ms=SIM, gate_ms=GATE, workers=workers)
        total = 0.0
        for pair, p in pairs.items():
            calls = p["sample_calls"] + p["winner_calls"] + p["final_calls"]
            sig_h = calls * SIG[pair] / workers / H
            sim_h = p["sim_windows"] * SIM[pair] / H              # in-process: never divided
            assert proj["pairs"][pair]["signals_h"] == pytest.approx(sig_h, rel=1e-12)
            assert proj["pairs"][pair]["simulation_h"] == pytest.approx(sim_h, rel=1e-12)
            total += sig_h + sim_h
        gate_h = sum(work["gate_bars"][d] * GATE[d] / workers / H for d in work["gate_bars"])
        assert proj["gates_h"] == pytest.approx(gate_h, rel=1e-12)
        assert proj["total_h"] == pytest.approx(total + gate_h, rel=1e-12)
        assert proj["total_h"] == pytest.approx(proj["signals_h"] + proj["gates_h"] + proj["simulation_h"])


def test_no_folds_or_no_valid_combination_has_no_recheck_work():
    cli = _cli()
    dates = wfc.bar_dates(_calendar_bars(400))
    a, b = wfc.Cell("pullback_ema", "Bullish", "Swing"), wfc.Cell("pullback_ema", "Bullish", "Position")
    work = cli._work([a, b], n_sample=1, sample_calls_by_pair={("pullback_ema", "Bullish"): 5},
                     trade_dates={"T": dates}, final_bars=[400],
                     folds_by_horizon={"Swing": [], "Position": [_fold(0, (dates[100], dates[200]))]},
                     valid_by_cell={a: 3, b: 0})
    p = work["pairs"][("pullback_ema", "Bullish")]
    assert (p["winner_calls"], p["final_calls"]) == (0, 0)     # no fold winner -> no final params
    assert p["sim_windows"] == 0 and p["sample_calls"] == 5
    assert work["gate_bars"] == {"Bullish": 400}                # cell a still prewarms its sample


def test_empty_work_projects_zero():
    cli = _cli()
    work = cli._work([], n_sample=0, sample_calls_by_pair={}, trade_dates={}, final_bars=[],
                     folds_by_horizon={}, valid_by_cell={})
    proj = cli._project(work, signal_ms={}, sim_ms={}, gate_ms={}, workers=3)
    assert proj["total_h"] == 0 and proj["pairs"] == {}


# ── the run's preflight ──────────────────────────────────────────────────────

class _Stop(Exception):
    pass


@pytest.fixture
def run_env(tmp_path, monkeypatch, planted):
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    bars = {"AAA": _sawtooth(CAL), "BBB": _sawtooth(CAL[150:]), "BIIB": _sawtooth(CAL[40:-30])}
    for sym, b in bars.items():          # BIIB: evidence scope (fires, never trades)
        (bars_dir / f"{sym}_candles.json").write_text(json.dumps(b), encoding="utf-8")
    monkeypatch.setattr(basket, "sector_of", lambda s: "Information Technology")
    monkeypatch.setattr(store, "get_tuning_config", _config)
    monkeypatch.setattr(store, "get_search_by_horizon", lambda strategy, direction, horizon: {"k": [3, 5]})
    argv = ["--symbols", "AAA,BBB,BIIB", "--bars-dir", str(bars_dir), "--out", str(tmp_path / "out"),
            "--data", str(tmp_path / "data"), "--cache-dir", str(tmp_path / "cache")]
    return bars, argv, tmp_path


def _expected_run(bars, cells, workers):
    cfg = _config()
    trade, sample = ["AAA", "BBB"], ["AAA", "BBB"]
    cal = wfc.cell_calendar({s: wfc.bar_dates(bars[s]) for s in sample}, held_out_months=cfg["held_out_months"])
    lengths = [len(b) for b in bars.values()]
    hours, gate_dirs = 0.0, {}
    for c in cells:
        folds = wfc.cell_folds(cal, c.horizon, cfg)[0]
        valid = sum(1 for k in (3, 5) if wfc.invalid_reason(c.strategy, c.direction, {"k": k}) is None)
        sample_calls = valid * sum(_full(len(bars[s])) for s in sample)
        winner = sum(_window(wfc.bar_dates(bars[s]), f.test_entry) for s in trade for f in folds)
        final = sum(_full(n) for n in lengths)
        sim = valid * 2 * len(folds) + 2 * len(folds) * 3 + 2 * 2 + 2 * len(folds) * 2 + 2 * 2
        pair = (c.strategy, c.direction)
        hours += (sample_calls + winner + final) * SIG[pair] / workers / H + sim * SIM[pair] / H
        gate_dirs.setdefault(c.direction, set()).add(gates.scoring_horizon_for(c.horizon))
    hours += sum(len(s) * sum(lengths) * GATE[d] / workers / H for d, s in gate_dirs.items())
    return hours


def test_run_preflight_weights_each_pending_pair_with_its_own_cost(run_env, monkeypatch, capsys):
    bars, argv, _ = run_env
    cli = _cli()
    seen = _fake_timings(cli, monkeypatch)
    captured = {}

    def stop(p, workers):
        captured.update(p, workers=workers)
        raise _Stop
    monkeypatch.setattr(cli, "_print_projection", stop)
    with pytest.raises(_Stop):
        cli.main([*argv, "--cells", "pullback_ema:Swing,ma_crossover:Swing", "--directions", "Bullish,Bearish",
                  "--workers", "3"])
    cells = cli.select_cells("pullback_ema:Swing,ma_crossover:Swing", "Bullish,Bearish")
    assert captured["total_h"] == pytest.approx(_expected_run(bars, cells, 3), rel=1e-9)
    assert {x[1:] for x in seen if x[0] == "signal"} == {(c.strategy, c.direction) for c in cells}
    assert {x[1:] for x in seen if x[0] == "sim"} == {(c.strategy, c.direction) for c in cells}
    assert {x[1] for x in seen if x[0] == "gate"} == {"Bullish", "Bearish"}


def test_resumed_run_with_no_pending_cell_projects_zero_without_timing(run_env, monkeypatch):
    bars, argv, tmp = run_env
    argv = [*argv, "--cells", "pullback_ema:Swing", "--workers", "1"]
    cli = _cli()
    assert cli.main(argv) == 0
    first = json.loads((tmp / "out" / "tuning_summary.json").read_text(encoding="utf-8"))
    assert first["header"]["projected_h"] > 0
    seen = _fake_timings(cli, monkeypatch)
    assert cli.main([*argv, "--resume"]) == 0
    assert seen == []                                       # no unrelated strategy timed
    summary = json.loads((tmp / "out" / "tuning_summary.json").read_text(encoding="utf-8"))
    assert summary["header"]["projected_h"] == 0
    assert summary["cells"] == first["cells"]
    for key in ("git_commit", "data_range", "sample_size", "trade_universe_size", "fire_rate_universe_size",
                "runtime_s", "projected_h", "tuning"):
        assert key in summary["header"], key
    assert "projected 0.00 h" in (tmp / "out" / "tuning_report.md").read_text(encoding="utf-8")


# ── the probe ────────────────────────────────────────────────────────────────

UNION = ["AAA", "BBB", "BIIB"]


@pytest.fixture
def probe_env(tmp_path, monkeypatch):
    for sym in ("X", "Y"):
        (tmp_path / f"{sym}_candles.json").write_text(json.dumps(_sawtooth(CAL[:300])), encoding="utf-8")
    monkeypatch.setattr(basket, "universe_union", lambda: list(UNION))
    monkeypatch.setattr(store, "get_search_by_horizon", lambda strategy, direction, horizon: {"k": [3, 5]})
    return tmp_path


def _expected_probe(cells, *, end, bars_per_symbol, workers):
    cfg = get_tuning_config()
    days = [d.date() for d in pd.bdate_range(end=end, periods=bars_per_symbol)]
    cal = wfc.cell_calendar({"X": days}, held_out_months=cfg["held_out_months"])
    n_sample = cfg["basket"]["per_sector"] * 11
    n_trade, n_fire = len(basket.trade_universe(UNION)), len(basket.fire_rate_universe(UNION))
    out = {}
    for c in cells:
        folds = wfc.cell_folds(cal, c.horizon, cfg)[0]
        pair = (c.strategy, c.direction)
        winner = (min(len(folds), 2) * n_trade * _full(bars_per_symbol) if c.strategy == "breakout_setup"
                  else n_trade * sum(_window(days, f.test_entry) for f in folds))
        out[pair] = {"sample_calls": 2 * n_sample * _full(bars_per_symbol), "winner_calls": winner,
                     "final_calls": n_fire * _full(bars_per_symbol),
                     "legacy_recheck_calls": (min(len(folds), 2) + 1) * n_trade * _full(bars_per_symbol),
                     "sim_windows": 2 * n_sample * len(folds) + n_sample * len(folds) * 3 + 2 * n_sample
                     + n_trade * len(folds) * 2 + 2 * n_trade}
    hours = sum((p["sample_calls"] + p["winner_calls"] + p["final_calls"]) * SIG[k] / workers / H
                + p["sim_windows"] * SIM[k] / H for k, p in out.items())
    dirs = {c.direction for c in cells}
    hours += sum(n_fire * bars_per_symbol * GATE[d] / workers / H for d in dirs)   # Swing only
    return out, hours


def test_probe_uses_the_exported_end_date_and_per_pair_costs(probe_env, monkeypatch, capsys):
    (probe_env / "manifest.json").write_text(json.dumps(
        {"schema": 1, "bounds": {"start": "2000-01-01", "end": "2024-03-28", "end_inclusive": True}}),
        encoding="utf-8")
    cli = _cli()
    _fake_timings(cli, monkeypatch)
    cells = cli.select_cells("pullback_ema:Swing,breakout_setup:Swing", "Bullish,Bearish")
    cells = [c for c in cells if (c.strategy, c.direction) in SIG]
    summary = cli.probe(["X", "Y"], probe_env, 3, 1500, cells)
    out = capsys.readouterr().out
    pairs, hours = _expected_probe(cells, end=date(2024, 3, 28), bars_per_symbol=1500, workers=3)
    assert summary["assumptions"]["end"] == "2024-03-28"
    assert "export manifest" in summary["assumptions"]["end_source"] and "2024-03-28" in out
    for pair, expected in pairs.items():
        got = summary["pairs"]["|".join(pair)]
        for key, value in expected.items():
            assert got[key] == value, (pair, key)
        assert got["signal_ms_per_call"] == pytest.approx(SIG[pair]) and got["sim_ms_per_window"] == SIM[pair]
    assert summary["projection"]["total_h"] == pytest.approx(hours, rel=1e-9)
    ordinary = summary["pairs"]["pullback_ema|Bullish"]
    assert ordinary["winner_calls"] + ordinary["final_calls"] < ordinary["legacy_recheck_calls"]
    assert summary["totals"]["new_recheck_calls"] == sum(p["winner_calls"] + p["final_calls"] for p in pairs.values())
    assert summary["totals"]["legacy_recheck_calls"] == sum(p["legacy_recheck_calls"] for p in pairs.values())
    assert "(3 cells," in out


def test_probe_without_manifest_labels_its_assumed_end(probe_env, monkeypatch, capsys):
    cli = _cli()
    _fake_timings(cli, monkeypatch)
    cells = cli.select_cells("pullback_ema:Swing", "Bullish")
    summary = cli.probe(["X"], probe_env, 1, 800, cells)
    out = capsys.readouterr().out
    assert summary["assumptions"]["end_source"].startswith("assumed")
    assert "assumed" in out and "800 bars" in out


def test_probe_with_no_selected_cell_times_nothing(probe_env, monkeypatch):
    cli = _cli()
    seen = _fake_timings(cli, monkeypatch)
    summary = cli.probe(["X"], probe_env, 3, 800, [])
    assert seen == [] and summary["projection"]["total_h"] == 0 and summary["pairs"] == {}


def test_probe_json_records_command_identity_and_fixtures(probe_env, monkeypatch, tmp_path):
    cli = _cli()
    _fake_timings(cli, monkeypatch)
    path = tmp_path / "probe-summary.json"
    argv = ["--probe", "--symbols", "X,Y", "--bars-dir", str(probe_env), "--workers", "3",
            "--bars-per-symbol", "900", "--cells", "pullback_ema:Swing", "--directions", "Bullish",
            "--probe-json", str(path)]
    assert cli.main(argv) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["command"][-len(argv):] == argv
    assert data["python"].startswith("3.11")
    assert set(data["code"]) >= {"git_commit", "sources"}
    fx = data["fixtures"]["X"]
    raw = (probe_env / "X_candles.json").read_bytes()
    import hashlib
    assert fx["sha256"] == hashlib.sha256(raw).hexdigest() and fx["bars"] == 300
    assert data["workers"] == 3 and "pullback_ema|Bullish" in data["pairs"]
