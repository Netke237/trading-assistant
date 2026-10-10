"""Tuner report, adoption bar, full-universe re-check and the CLI
(STOCKS-HORIZON-T1 H10).

Synthetic data only: a planted signal function and an all-pass gate mask (as
in test_horizon_tuning_walk_forward.py); nothing reads the database.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.tseries.holiday import USFederalHolidayCalendar

import app.services.strategy_param_store as store
from app.services.horizon_tuning import basket, gates, report, signals
from app.services.horizon_tuning import walk_forward_cell as wfc
from app.services.horizon_tuning.walk_forward_cell import Cell, SymbolTrade, TradeStats
from app.services.strategy_backtest import TradeRecord
from app.services.strategy_param_store import get_tuning_config

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tune_horizons.py"


def _cli():
    spec = importlib.util.spec_from_file_location("tune_horizons_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── synthetic trades ─────────────────────────────────────────────────────────

def _t(symbol: str, ret: float, day: int = 0) -> SymbolTrade:
    d = date(2020, 1, 1).toordinal() + day
    return SymbolTrade(symbol, TradeRecord(date.fromordinal(d), date.fromordinal(d + 5),
                                           100.0, 100.0 + ret, ret, "target"))


_FIXED = [_t("A", 1.0), _t("A", 2.0), _t("A", -0.5), _t("B", -1.0), _t("B", 0.5),
          _t("C", 3.0), _t("D", -2.0), _t("D", 1.5), _t("D", 0.25), _t("E", 0.75)]


def _reference_cluster_ci(trades, resamples, seed, ci_level):
    """The plan's rule written out independently: group by symbol; each
    resample draws S symbols with replacement, concatenates all their trades
    and takes the trade-weighted mean."""
    by_sym: dict[str, list[float]] = {}
    for t in trades:
        by_sym.setdefault(t.symbol, []).append(t.trade.net_return_pct)
    syms = sorted(by_sym)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(resamples):
        pick = rng.integers(0, len(syms), size=len(syms))
        vals = [v for i in pick for v in by_sym[syms[i]]]
        means.append(sum(vals) / len(vals))
    tail = (1 - ci_level) / 2 * 100
    return float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail))


def test_cluster_bootstrap_is_pinned_with_seed_7():
    lo, hi = report.cluster_bootstrap_ci(_FIXED, resamples=2000, seed=7, ci_level=0.95)
    ref = _reference_cluster_ci(_FIXED, 2000, 7, 0.95)
    assert (lo, hi) == pytest.approx(ref, abs=1e-12)
    assert lo == pytest.approx(-0.06818181818181818, abs=1e-9)
    assert hi == pytest.approx(1.5416666666666667, abs=1e-9)
    # Deterministic: the same call gives the same bound.
    assert report.cluster_bootstrap_ci(_FIXED, resamples=2000, seed=7, ci_level=0.95) == (lo, hi)


def test_cluster_bootstrap_is_wider_than_a_per_trade_bootstrap_on_correlated_trades():
    rng = np.random.default_rng(1)
    trades = []
    for s in range(30):
        effect = rng.normal(0.2, 2.0)             # one shared move per symbol
        for k in range(12):
            trades.append(_t(f"S{s}", float(effect + rng.normal(0, 0.1)), k))
    clo, chi = report.cluster_bootstrap_ci(trades, resamples=2000, seed=7, ci_level=0.95)
    plo, phi = report.per_trade_bootstrap_ci(trades, resamples=2000, seed=7, ci_level=0.95)
    assert (chi - clo) > 2 * (phi - plo)


def test_bootstrap_of_no_trades_is_none():
    assert report.cluster_bootstrap_ci([], resamples=10, seed=7, ci_level=0.95) is None


# ── adoption bar ─────────────────────────────────────────────────────────────

def _recheck(oos, heldout, fire_rate=5.0):
    return report.Recheck(
        oos_trades={wfc.COST: oos, wfc.STRESS: oos},
        oos={wfc.COST: TradeStats.of(oos), wfc.STRESS: TradeStats.of(oos)},
        heldout_trades={wfc.COST: heldout, wfc.STRESS: heldout},
        heldout={wfc.COST: TradeStats.of(heldout), wfc.STRESS: TradeStats.of(heldout)},
        fire_rate=fire_rate, heldout_fire_rate=fire_rate, fires_by_symbol={},
        n_trade_symbols=30, n_fire_symbols=30,
        boundary_dropped={"oos": 0, "heldout": 0}, end_dropped={"oos": 0, "heldout": 0},
    )


def _passing_oos(n_symbols=25, per_symbol=4, ret=1.0):
    return [_t(f"S{s}", ret + 0.01 * k, k) for s in range(n_symbols) for k in range(per_symbol)]


SWING_BULL = Cell("pullback_ema", "Bullish", "Swing")


def test_a_cell_meeting_all_five_criteria_passes():
    v = report.adoption_verdict(SWING_BULL, _recheck(_passing_oos(), [_t("S0", 1.0)]), get_tuning_config())
    assert v.passes_bar and v.failed == [] and not v.blocked
    assert v.label == "passes"


@pytest.mark.parametrize("criterion,oos,heldout,fire", [
    # 1: CI lower bound <= 0 (mean > 0 but noisy across symbols); 100 trades, 25 symbols.
    ("oos_ci_lower", [_t(f"S{s}", (5.0 if s % 2 else -4.0) + 0.01 * k, k)
                      for s in range(25) for k in range(4)], [_t("S0", 1.0)], 5.0),
    # 2: held-out net expectancy <= 0.
    ("heldout_expectancy", _passing_oos(), [_t("S0", -1.0)], 5.0),
    # 3: 99 pooled OOS trades (25 symbols).
    ("min_oos_trades", _passing_oos()[:-1], [_t("S0", 1.0)], 5.0),
    # 4: 19 symbols (114 trades).
    ("min_symbols", _passing_oos(n_symbols=19, per_symbol=6), [_t("S0", 1.0)], 5.0),
    # 5: measured full-universe fire rate below the Swing floor (2.0).
    ("fire_rate", _passing_oos(), [_t("S0", 1.0)], 1.99),
])
def test_each_criterion_failing_alone_flips_the_verdict_and_is_named(criterion, oos, heldout, fire):
    v = report.adoption_verdict(SWING_BULL, _recheck(oos, heldout, fire), get_tuning_config())
    assert not v.passes_bar
    assert v.failed == [criterion]
    assert v.label == "fails"


def test_bearish_cells_are_blocked_whatever_the_verdict():
    v = report.adoption_verdict(Cell("pullback_ema", "Bearish", "Swing"),
                                _recheck(_passing_oos(), [_t("S0", 1.0)]), get_tuning_config())
    assert v.passes_bar and v.blocked and v.label == "blocked (P0B)"


def test_chance_count_over_bullish_cells_only():
    def verdict(passes):
        return report.Verdict(passes_bar=passes, failed=[] if passes else ["min_symbols"],
                              blocked=False, ci={})
    pairs = [(Cell("pullback_ema", "Bullish", h), verdict(i < 3))
             for i, h in enumerate(["Swing", "Position", "Quarterly", "SemiAnnual", "Annual"])]
    pairs += [(Cell("ma_crossover", "Bullish", h), verdict(False)) for h in ("Swing", "Annual")]
    pairs += [(Cell("ma_crossover", "Bearish", h), verdict(True)) for h in ("Swing", "Position")]
    cc = report.chance_count(pairs, ci_level=0.95)
    assert cc["bullish_cells_evaluated"] == 7
    assert cc["bullish_cells_passed"] == 3
    assert cc["expected_by_chance"] == pytest.approx(7 * 0.025 * 0.5)
    assert "0.025" in cc["formula"] and "0.5" in cc["formula"] and "approximation" in cc["formula"]


# ── full-universe re-check (planted edge) ────────────────────────────────────

_HOLIDAYS = set(d.date() for d in USFederalHolidayCalendar().holidays("2009-01-01", "2016-01-01"))
CAL = [d.date() for d in pd.bdate_range("2009-10-01", "2014-06-30") if d.date() not in _HOLIDAYS]


def _sawtooth(days):
    out = []
    for i, d in enumerate(days):
        p = i % 7
        if p == 0:
            o, h, lo, c = 100.2, 100.5, 99.5, 100.0
        else:
            o, h, lo, c = 100.0 + p - 1, 100.0 + p + 0.5, 100.0 + p - 1.2, 100.0 + p
        out.append({"time": d.isoformat(), "open": o, "high": h, "low": lo, "close": c,
                    "volume": float(i + 1)})
    return out


def _fake_fn(bars, *, direction, **p):
    """Fires on phase-0 bars (close 100); entry 100, stop 90, target +k%."""
    last = bars[-1]
    if last["close"] != 100.0:
        return None
    k = p.get("k", 5)
    return SimpleNamespace(entry_price=100.0, stop_price=90.0, target_price=100.0 * (1 + k / 100))


@pytest.fixture
def planted(monkeypatch):
    monkeypatch.setattr(signals, "_signal_fn", lambda strategy: _fake_fn)
    monkeypatch.setattr(gates, "gate_mask", lambda bars, *a, **k: [True] * len(bars))


def _config():
    cfg = copy.deepcopy(get_tuning_config())
    cfg["min_train_trades"] = 1
    cfg["fire_rate_floor_per_day"] = {h: 0.0 for h in cfg["fire_rate_floor_per_day"]}
    return cfg


def _tuned(sample):
    data = wfc.CellData(bars=sample, sectors={s: "Information Technology" for s in sample},
                        n_universe_by_sector={"Information Technology": len(sample)},
                        config=_config(), grid={"k": [3, 5]})
    return wfc.tune_cell(SWING_BULL, data)


def test_recheck_trades_every_trade_universe_symbol_and_counts_evidence_fires_only(planted):
    sample = {"S0": _sawtooth(CAL), "S1": _sawtooth(CAL)}
    res = _tuned(sample)
    assert res.final_params == {"k": 5} and res.folds
    universe = report.UniverseData(
        bars={**sample, "U2": _sawtooth(CAL), "EV": _sawtooth(CAL)},
        trade_universe=["S0", "S1", "U2"],
        fire_rate_universe=["S0", "S1", "U2", "EV"],
    )
    rc = report.full_universe_recheck(res, universe, _config())
    traded = {t.symbol for lst in (rc.oos_trades[wfc.COST], rc.oos_trades[wfc.STRESS],
                                   rc.heldout_trades[wfc.COST], rc.heldout_trades[wfc.STRESS])
              for t in lst}
    assert traded == {"S0", "S1", "U2"}                 # never the evidence-scope symbol
    assert rc.fires_by_symbol["EV"] > 0                  # but it fires
    assert set(rc.fires_by_symbol) == {"S0", "S1", "U2", "EV"}
    assert rc.n_trade_symbols == 3 and rc.n_fire_symbols == 4
    # Each symbol fires on 1 bar in 7: four symbols ~ 4/7 per scan day.
    assert rc.fire_rate == pytest.approx(4 / 7, rel=0.02)
    # The re-check's OOS for the sample symbols equals the sample's own OOS.
    sample_oos = [t for t in rc.oos_trades[wfc.COST] if t.symbol in sample]
    assert sorted(sample_oos, key=lambda t: (t.trade.entry_date, t.symbol)) == res.oos_trades[wfc.COST]
    assert rc.oos[wfc.COST].n_trades == len(res.oos_trades[wfc.COST]) * 3 // 2


def test_recheck_without_winners_is_empty(planted):
    sample = {"S0": _sawtooth(CAL)}
    data = wfc.CellData(bars=sample, sectors={"S0": "Information Technology"},
                        n_universe_by_sector={"Information Technology": 1},
                        config=dict(_config(), min_train_trades=10_000), grid={"k": [5]})
    res = wfc.tune_cell(SWING_BULL, data)
    rc = report.full_universe_recheck(
        res, report.UniverseData(bars=sample, trade_universe=["S0"], fire_rate_universe=["S0"]),
        _config())
    assert rc.oos[wfc.COST].n_trades == 0 and rc.fire_rate is None
    v = report.adoption_verdict(SWING_BULL, rc, _config())
    assert not v.passes_bar and "fire_rate" in v.failed and "min_oos_trades" in v.failed


# ── runtime projection ──────────────────────────────────────────────────────

def test_runtime_projection_counts_signals_gates_and_simulation():
    p = report.project_runtime(
        signal_ms_per_call=2.0, gate_ms_per_bar=10.0, sim_ms_per_window=1.0,
        signal_calls=1_000_000, gate_bars=100_000, sim_windows=3_600_000, workers=4)
    assert p["signals_h"] == pytest.approx(1_000_000 * 2.0 / 1000 / 4 / 3600)
    assert p["gates_h"] == pytest.approx(100_000 * 10.0 / 1000 / 4 / 3600)
    assert p["simulation_h"] == pytest.approx(3_600_000 * 1.0 / 1000 / 3600)   # in-process
    assert p["total_h"] == pytest.approx(p["signals_h"] + p["gates_h"] + p["simulation_h"])


# ── the CLI end to end ───────────────────────────────────────────────────────

@pytest.fixture
def cli_env(tmp_path, monkeypatch, planted):
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    for sym in ("AAA", "BBB", "BIIB"):      # BIIB: evidence scope in universe_exclusions.yaml
        (bars_dir / f"{sym}_candles.json").write_text(json.dumps(_sawtooth(CAL)), encoding="utf-8")
    monkeypatch.setattr(basket, "sector_of", lambda s: "Information Technology")
    monkeypatch.setattr(store, "get_tuning_config", _config)
    monkeypatch.setattr(store, "get_search_by_horizon", lambda strategy, direction, horizon: {"k": [3, 5]})
    out, data, cache = tmp_path / "out", tmp_path / "data", tmp_path / "cache"
    argv = ["--cells", "pullback_ema:Swing", "--directions", "Bullish,Bearish",
            "--symbols", "AAA,BBB,BIIB", "--bars-dir", str(bars_dir), "--workers", "1",
            "--out", str(out), "--data", str(data), "--cache-dir", str(cache)]
    return SimpleNamespace(argv=argv, out=out, data=data)


def test_end_to_end_writes_every_file_and_documented_column(cli_env, capsys):
    cli = _cli()
    assert cli.main(cli_env.argv) == 0
    printed = capsys.readouterr().out
    assert "projected runtime" in printed and "simulation" in printed and "gate" in printed

    md = (cli_env.out / "tuning_report.md").read_text(encoding="utf-8")
    summary = json.loads((cli_env.out / "tuning_summary.json").read_text(encoding="utf-8"))
    cells = sorted((cli_env.data / "cells").glob("*.json"))
    assert len(cells) == 2 and len(summary["cells"]) == 2

    for col in report.REPORT_COLUMNS:
        assert col in md, col
        for row in summary["cells"]:
            assert col in row, col
    for row in summary["cells"]:                         # no trade lists in the summary
        assert "oos_trade_list" not in row and "heldout_trade_list" not in row
    for needle in ("legacy Settings tuner has no time exit", "regime gate", "current_price",
                   report.basket.SAMPLE_LABEL, "survivorship", "0.05%", "0.2%", "Annual",
                   "git commit", "data range", "sample", "universe", "runtime",
                   "expected by chance"):
        assert needle in md, needle
    assert "blocked (P0B)" in md

    cell_json = json.loads(next(p for p in cells if "Bullish" in p.name).read_text(encoding="utf-8"))
    assert cell_json["sample"]["oos_trade_list"]["cost_per_leg"]
    assert cell_json["universe"]["oos_trade_list"]["cost_per_leg"]
    # BIIB (evidence scope): not in the sample, no trade anywhere, but it fires.
    assert "BIIB" not in summary["header"]["sample_symbols"]
    for side in ("sample", "universe"):
        for kind in ("oos_trade_list", "heldout_trade_list"):
            for lst in cell_json[side][kind].values():
                assert all(t["symbol"] != "BIIB" for t in lst)
    assert cell_json["universe"]["fires_by_symbol"]["BIIB"] > 0
    assert summary["header"]["fire_rate_universe_size"] == 3
    assert summary["header"]["trade_universe_size"] == 2


def test_resume_skips_a_finished_cell(cli_env, monkeypatch):
    cli = _cli()
    assert cli.main(cli_env.argv) == 0
    calls = []
    real = wfc.tune_cell
    monkeypatch.setattr(wfc, "tune_cell", lambda *a, **k: calls.append(a) or real(*a, **k))
    assert cli.main(cli_env.argv + ["--resume"]) == 0
    assert calls == []                                   # both cells skipped
    summary = json.loads((cli_env.out / "tuning_summary.json").read_text(encoding="utf-8"))
    assert len(summary["cells"]) == 2
    assert cli.main(cli_env.argv) == 0                   # without --resume: recomputed
    assert len(calls) == 2
