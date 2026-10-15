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


@pytest.mark.parametrize('freq', ['15min', '1min'])
@pytest.mark.parametrize('direction', ['Bullish', 'Bearish'])
@pytest.mark.parametrize('fraction', [0., .25])
@pytest.mark.parametrize('same_bar', [False, True])
def test_numeric_source_epochs_use_actual_engine_bar_positions(monkeypatch, freq, direction, fraction, same_bar):
    signal(monkeypatch, direction)
    data = bars(freq)
    for bar in data:
        bar['time'] = int(pd.Timestamp(bar['time']).timestamp()) if not fraction else pd.Timestamp(bar['time']).timestamp() + fraction
    data[101 if same_bar else 103].update(high=111., low=89.)
    if same_bar:
        # Force a market entry in the real engine: production limit orders defer
        # ambiguous same-bar contingent fills to the next matching candle.
        from backtesting import Strategy
        order_name = 'buy' if direction == 'Bullish' else 'sell'
        original_order = getattr(Strategy, order_name)
        def market_order(self, *, size=1 - 2 ** -52, **kwargs):
            kwargs['size'] = size
            kwargs['limit'] = None
            return original_order(self, **kwargs)
        monkeypatch.setattr(Strategy, order_name, market_order)
    kw = dict(strategy='pullback_ema', direction=direction, commission=.002, min_trades=1)
    expected, legacy = service.run_strategy_backtest_trades(data, **kw)
    from backtesting import Backtest
    original = Backtest.run
    calls = []
    def capture(self, **kwargs):
        stats = original(self, **kwargs)
        calls.append(stats)
        return stats
    monkeypatch.setattr(Backtest, 'run', capture)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert len(calls) == 1
    assert detail.status == 'success', detail.reason
    assert asdict(detail.summary) == asdict(expected)
    assert [c.time for c in detail.input_candles] == [b['time'] for b in data]
    assert [e.time for e in detail.equity] == [b['time'] for b in data]
    actual = calls[0]['_trades'].iloc[0]
    trade = detail.trades[0]
    assert trade.entry_time == data[int(actual.EntryBar)]['time']
    assert trade.exit_time == data[int(actual.ExitBar)]['time']
    assert (actual.EntryBar == actual.ExitBar) == same_bar
    assert trade.commission == actual.Commission > 0
    assert trade.size == actual.Size
    assert trade.entry_price == actual.EntryPrice
    assert trade.exit_price == actual.ExitPrice
    assert trade.net_return_pct == actual.ReturnPct * 100 == legacy[0].net_return_pct
    assert detail.equity[-1].equity == calls[0]['_equity_curve'].Equity.iloc[-1]


@pytest.mark.parametrize('direction', ['Bullish', 'Bearish'])
def test_numeric_source_open_position_preserves_mtm_and_aggregate(monkeypatch, direction):
    signal(monkeypatch, direction)
    data = bars('1min')
    for bar in data:
        bar['time'] = pd.Timestamp(bar['time']).timestamp()
    data[-1].update(close=105., high=106.)
    kw = dict(strategy='pullback_ema', direction=direction, commission=.002)
    expected = service.run_strategy_backtest(data, **kw)
    from backtesting import Backtest
    original = Backtest.run
    calls = []
    def capture(self, **kwargs):
        stats = original(self, **kwargs)
        calls.append(stats)
        return stats
    monkeypatch.setattr(Backtest, 'run', capture)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert len(calls) == 1
    assert detail.status == 'success', detail.reason
    assert detail.summary == expected
    actual = calls[0]['_strategy'].trades[0]
    assert detail.open_positions[0].entry_time == data[actual.entry_bar]['time']
    assert detail.open_positions[0].size == actual.size
    assert detail.open_positions[0].entry_price == actual.entry_price
    assert detail.open_positions[0].unrealized_pnl == actual.pl
    assert detail.equity[-1].equity == calls[0]['_equity_curve'].Equity.iloc[-1]
    from app.services.strategy_backtest_details import ENGINE_CONTRACT_VERSION
    assert detail.engine_contract_version == ENGINE_CONTRACT_VERSION == 'backtesting-0.6.6-v2'
    assert 'legacy engine timestamp interpretation unchanged' in detail.time_basis
    assert not detail.trades and detail.summary.n_trades == 0
    assert detail.equity[-1].strategy_index - 100 == pytest.approx(expected.total_return_pct)


@pytest.mark.parametrize('guard', [dict(entry_start=date(2024, 1, 1)),
    dict(entry_end=date(2024, 1, 2)), dict(hold_max_days=2)])
def test_numeric_source_legacy_timing_guard_mismatch_unavailable(monkeypatch, guard):
    signal(monkeypatch)
    data = bars('15min')
    for bar in data:
        bar['time'] = pd.Timestamp(bar['time']).timestamp()
    kw = dict(strategy='pullback_ema', direction='Bullish', **guard)
    expected = service.run_strategy_backtest(data, **kw)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert detail.status == 'invalid_evidence'
    assert detail.summary == expected
    assert 'timing' in detail.reason


@pytest.mark.parametrize('problem', ['reverse', 'mixed', 'duplicate'])
def test_numeric_source_invalid_chronology_and_mixed_basis(monkeypatch, problem):
    data = bars('1min')
    for bar in data:
        bar['time'] = pd.Timestamp(bar['time']).timestamp()
    if problem == 'reverse': data.reverse()
    if problem == 'mixed': data[10]['time'] = '2024-01-01T00:10:00Z'
    if problem == 'duplicate': data[10]['time'] = data[9]['time']
    detail = service.run_strategy_backtest_detailed(data, strategy='pullback_ema', direction='Bullish')
    assert detail.status == 'invalid_input'


def test_equity_index_is_checked_before_source_positional_mapping(monkeypatch):
    from backtesting import Backtest
    original = Backtest.run
    def corrupt(self, **kw):
        stats = original(self, **kw)
        stats['_equity_curve'].index = stats['_equity_curve'].index + pd.Timedelta(seconds=1)
        return stats
    monkeypatch.setattr(Backtest, 'run', corrupt)
    data = bars('15min')
    for bar in data:
        bar['time'] = pd.Timestamp(bar['time']).timestamp()
    detail = service.run_strategy_backtest_detailed(data, strategy='pullback_ema', direction='Bullish')
    assert detail.status == 'invalid_evidence'
    assert 'timestamp mismatch' in detail.reason


@pytest.mark.parametrize('strategy,params,expected', [
    ('pullback_ema', {}, {'ma_type': 'EMA', 'require_reversal': False, 'ema_period': 50}),
    ('pullback_ema', {'ma_type': 'SMA', 'require_reversal': True, 'ema_period': 25},
     {'ma_type': 'SMA', 'require_reversal': True, 'ema_period': 25}),
    ('ma_crossover', {}, {'lookback': 10, 'fast': 20, 'slow': 50}),
    ('ma_crossover', {'lookback': 4}, {'lookback': 4, 'fast': 20, 'slow': 50}),
])
def test_complete_effective_signature_defaults_and_overrides(strategy, params, expected):
    data = bars()
    kw = dict(strategy=strategy, direction='Bearish', params=params,
              min_trades=7, min_win_rate=.61)
    aggregate = service.run_strategy_backtest(data, **kw)
    detail = service.run_strategy_backtest_detailed(data, **kw)
    assert detail.status == 'success', detail.reason
    assert detail.summary == aggregate
    assert all(detail.effective_params[key] == value for key, value in expected.items())
    assert detail.effective_params['current_price'] is None
    assert 'bars' not in detail.effective_params and 'direction' not in detail.effective_params
    assert detail.configuration['min_trades'] == 7
    assert detail.configuration['min_win_rate'] == .61
    assert detail.configuration['min_expectancy'] == service._MIN_EXPECTANCY
    assert detail.configuration['signal_window_bars'] == engine.SIGNAL_WINDOW_BARS


def test_multi_effective_defaults_are_resolved_per_selected_variant_and_detached():
    params = dict(variants=['pullback_ema', 'ma_crossover'], min_confirmations=2,
                  variant_params={'pullback_ema': {'ma_type': 'SMA'}, 'ma_crossover': {'lookback': 3}})
    kw = dict(strategy='mean_reversion_multi', direction='Bullish', params=params)
    aggregate = service.run_strategy_backtest(bars(), **kw)
    detail = service.run_strategy_backtest_detailed(bars(), **kw)
    assert detail.status == 'success', detail.reason
    assert detail.summary == aggregate
    actual = detail.effective_params
    assert actual['variants'] == params['variants']
    assert actual['min_confirmations'] == 2
    assert actual['variant_params']['pullback_ema']['ma_type'] == 'SMA'
    assert actual['variant_params']['pullback_ema']['require_reversal'] is False
    assert actual['variant_params']['ma_crossover']['lookback'] == 3
    assert actual['variant_params']['ma_crossover']['slow'] == 50
    assert set(actual['variant_params']) == set(params['variants'])
    params['variants'].clear()
    params['variant_params']['ma_crossover']['slow'] = 999
    assert actual['variants'] == ['pullback_ema', 'ma_crossover']
    assert actual['variant_params']['ma_crossover']['slow'] == 50


def test_intraday_signal_window_configuration_is_actual_engine_window():
    detail = service.run_strategy_backtest_detailed(bars('15min'), strategy='mean_reversion_vwap', direction='Bullish')
    assert detail.status == 'success'
    assert detail.configuration['signal_window_bars'] == service._INTRADAY_SIGNAL_WINDOW


def test_metadata_signature_failure_is_optional_evidence_failure(monkeypatch):
    import app.services.strategy_backtest_details as details
    expected = service.run_strategy_backtest(bars(), strategy='pullback_ema', direction='Bullish')
    def fail(*a, **kw):
        raise ValueError('unreadable signal signature')
    monkeypatch.setattr(details, 'complete_effective_params', fail, raising=False)
    captured = []
    actual = service.run_strategy_backtest(bars(), strategy='pullback_ema', direction='Bullish', detail_collector=captured)
    assert actual == expected
    assert captured[0].status == 'invalid_evidence'
    assert captured[0].summary == expected
