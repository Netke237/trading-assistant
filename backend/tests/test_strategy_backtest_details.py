"""Original engine evidence; never reconstruct equity from closed trades."""
from dataclasses import asdict
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

import app.services.strategy_backtest as service
import app.services.strategy_engine as engine


def bars(freq="D"):
    return [dict(time=t.isoformat(), open=100., high=101., low=99., close=100., volume=1000.)
            for t in pd.date_range("2024-01-01", periods=150, freq=freq, tz="UTC")]


def signal(monkeypatch, direction="Bullish"):
    def one_shot(data, **kw):
        if len(data) != 101:
            return None
        return SimpleNamespace(entry_price=100., stop_price=90. if direction == "Bullish" else 110.,
                               target_price=110. if direction == "Bullish" else 90.)
    monkeypatch.setattr(engine, "pullback_ema_signal", one_shot)


@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
@pytest.mark.parametrize("freq", ["D", "15min"])
def test_same_invocation_parity_costs_fills(monkeypatch, direction, freq):
    signal(monkeypatch, direction)
    data = bars(freq)
    data[103].update(high=111., low=89.)
    kw = dict(strategy="pullback_ema", direction=direction, commission=.002, min_trades=1)
    aggregate, legacy = service.run_strategy_backtest_trades(data, **kw)
    from backtesting import Backtest
    original = Backtest.run
    calls = []
    def capture(self, **kwargs):
        stats = original(self, **kwargs)
        calls.append(stats)
        return stats
    monkeypatch.setattr(Backtest, "run", capture)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert len(calls) == 1
    assert detail.status == "success"
    assert asdict(detail.summary) == asdict(aggregate)
    tr = detail.trades[0]
    actual = calls[0]["_trades"].iloc[0]
    assert tr.entry_time == pd.Timestamp(actual.EntryTime).timestamp()
    assert tr.exit_time == pd.Timestamp(actual.ExitTime).timestamp()
    assert tr.entry_price == actual.EntryPrice
    assert tr.exit_price == actual.ExitPrice
    assert tr.net_return_pct == legacy[0].net_return_pct == actual.ReturnPct * 100
    assert tr.exit_reason == "unknown"  # engine does not record stop/target reasons
    assert detail.equity[-1].equity == calls[0]["_equity_curve"].Equity.iloc[-1]
    assert detail.equity[-1].strategy_index - 100 == pytest.approx(aggregate.total_return_pct)
    assert detail.initial_equity == 100000
    assert detail.configuration["commission"] == .002
    assert detail.configuration["order_size"] == 1 - 2 ** -52
    assert detail.candles[101].time == tr.entry_time


def test_zero_trades_and_open_position_are_successful(monkeypatch):
    monkeypatch.setattr(engine, "pullback_ema_signal", lambda *a, **k: None)
    empty = service.run_strategy_backtest_detailed(bars(), strategy="pullback_ema", direction="Bullish")
    assert empty.status == "success" and not empty.trades and not empty.open_positions
    assert len(empty.equity) == 150 and empty.equity[-1].strategy_index == 100
    signal(monkeypatch)
    data = bars()
    data[-1].update(close=105., high=106.)
    opened = service.run_strategy_backtest_detailed(data, strategy="pullback_ema", direction="Bullish", commission=.002)
    assert opened.status == "success" and opened.summary.n_trades == 0
    assert not opened.trades and len(opened.open_positions) == 1
    assert opened.open_positions[0].entry_time == pd.Timestamp(data[101]["time"]).timestamp()
    assert opened.equity[-1].equity > opened.initial_equity
    assert opened.equity[-1].strategy_index - 100 == pytest.approx(opened.summary.total_return_pct)


def test_entry_start_window_baseline_and_gross_long_benchmark(monkeypatch):
    signal(monkeypatch, "Bearish")
    data = bars()
    data[-1].update(close=105., high=106.)
    kw = dict(strategy="pullback_ema", direction="Bearish", entry_start=date(2024, 4, 1), commission=.002)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert detail.summary == service.run_strategy_backtest(data, **kw)
    assert detail.candles[0].time == pd.Timestamp("2024-04-01", tz="UTC").timestamp()
    assert len(detail.candles) == len(detail.equity) == 59
    assert len(detail.input_candles) == 150
    assert detail.equity[0].strategy_index == detail.equity[0].benchmark_index == 100
    assert detail.equity[-1].benchmark_index == 105
    assert detail.equity[-1].strategy_index - 100 == pytest.approx(detail.summary.total_return_pct)


@pytest.mark.parametrize("problem,status", [("short", "insufficient_history"), ("strategy", "unsupported"),
    ("nan", "invalid_input"), ("time", "invalid_input"), ("order", "invalid_input"),
    ("direction", "invalid_input"), ("undated", "invalid_input"), ("failure", "failed")])
def test_explicit_non_success(monkeypatch, problem, status):
    data = bars()
    kw = dict(strategy="pullback_ema", direction="Bullish")
    if problem == "short": data = data[:50]
    if problem == "strategy": kw["strategy"] = "unsupported"
    if problem == "direction": kw["direction"] = "wrong"
    if problem == "nan": data[10]["close"] = float("nan")
    if problem == "time": data[10]["time"] = "nonsense"
    if problem == "order": data.reverse()
    if problem == "undated":
        for bar in data: bar.pop("time")
    if problem == "failure":
        monkeypatch.setattr(engine, "pullback_ema_signal", lambda *a, **k: 1 / 0)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert detail.status == status and detail.reason
    assert not detail.equity and not detail.trades


def test_details_detach_inputs_and_preserve_time_exit_reason(monkeypatch):
    signal(monkeypatch)
    data = bars()
    detail = service.run_strategy_backtest_detailed(data, strategy="pullback_ema", direction="Bullish", hold_max_days=2)
    assert detail.trades[0].exit_reason == "time"
    assert detail.configuration["hold_max_days"] == 2
    assert len({t.id for t in detail.trades}) == len(detail.trades)
    data[0]["close"] = 900
    assert detail.candles[0].close == 100


def test_optional_capture_failure_preserves_aggregate(monkeypatch):
    signal(monkeypatch)
    data = bars()
    kw = dict(strategy="pullback_ema", direction="Bullish", hold_max_days=2, commission=.002)
    expected = service.run_strategy_backtest(data, **kw)
    def failure(*args, **kwargs):
        raise ValueError("broken evidence")
    monkeypatch.setattr(service, "collect_details", failure)
    captured = []
    actual = service.run_strategy_backtest(data, **kw, detail_collector=captured)
    assert actual == expected
    assert captured[0].status == "invalid_evidence"
    assert captured[0].summary == expected


def test_empty_history_and_empty_evaluation_window(monkeypatch):
    assert service.run_strategy_backtest_detailed([], strategy="pullback_ema", direction="Bullish").status == "insufficient_history"
    monkeypatch.setattr(engine, "pullback_ema_signal", lambda *a, **k: None)
    detail = service.run_strategy_backtest_detailed(bars(), strategy="pullback_ema", direction="Bullish", entry_start=date(2030, 1, 1))
    assert detail.status == "invalid_evidence" and not detail.equity


def test_naive_and_offset_timestamps_keep_actual_instant(monkeypatch):
    signal(monkeypatch)
    data = bars("15min")
    for bar in data:
        bar["time"] = pd.Timestamp(bar["time"]).tz_convert("Europe/Berlin").isoformat()
    aware = service.run_strategy_backtest_detailed(data, strategy="pullback_ema", direction="Bullish")
    assert aware.open_positions[0].entry_time == pd.Timestamp(data[101]["time"]).timestamp()
    for bar in data:
        bar["time"] = pd.Timestamp(bar["time"]).tz_localize(None).isoformat()
    naive = service.run_strategy_backtest_detailed(data, strategy="pullback_ema", direction="Bullish")
    assert naive.open_positions[0].entry_time == aware.open_positions[0].entry_time + 3600


def test_nonfinite_engine_equity_is_unavailable(monkeypatch):
    monkeypatch.setattr(engine, "pullback_ema_signal", lambda *a, **k: None)
    from backtesting import Backtest
    original = Backtest.run
    def corrupt(self, **kw):
        stats = original(self, **kw)
        stats["_equity_curve"].iloc[10, 0] = float("inf")
        return stats
    monkeypatch.setattr(Backtest, "run", corrupt)
    detail = service.run_strategy_backtest_detailed(bars(), strategy="pullback_ema", direction="Bullish")
    assert detail.status == "invalid_evidence" and not detail.equity
