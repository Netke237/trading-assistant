"""Financial parity for the local archive harness; no production changes."""
import importlib.util
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import asdict
from datetime import date, timedelta
import json
import multiprocessing
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('retune_archived_basket', REPO / 'scripts/retune_archived_basket.py')
harness = importlib.util.module_from_spec(spec)
import sys
sys.path.insert(0, str(REPO / 'scripts'))
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)
from app.services import walk_forward as wf, strategy_param_optimizer as optimizer
from app.services.strategy_backtest import BacktestResult


class InlinePool:
    def submit(self, fn, arg):
        future = Future()
        try:
            future.set_result(fn(arg))
        except Exception as exc:
            future.set_exception(exc)
        return future


def result(sharpe, trades=1):
    return BacktestResult('fake', 'Bullish', trades, .5, 1.125, 2.75, .123456789,
                          sharpe, None, False, 'unmodified')


def bars(marker, count=400):
    return [dict(time=(date(2020, 1, 1) + timedelta(days=i)).isoformat(), close=marker)
            for i in range(count)]


@pytest.mark.parametrize('case', ['no_trades', 'exceptions', 'tie', 'ordered_sum', 'penalty'])
def test_fake_train_parity_guards_exclusion_order_penalty_ties(monkeypatch, case):
    basket = {'FIRST': bars(1), 'SECOND': bars(2), 'THIRD': bars(3), 'SHORT': bars(99, 10), 'MISSING': []}
    for data in basket.values():
        wf.precompute_bar_dates(data)
    fold = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
    calls = []
    def fake(data, *, strategy, direction, params, entry_start):
        marker = data[0]['close']
        assert marker != 99
        assert entry_start == fold.train_start
        calls.append((marker, params['p']))
        if case == 'exceptions' and marker == 2:
            raise ValueError('exclude this symbol')
        if case == 'ordered_sum':
            score = {1: 1e16, 2: -1e16, 3: 1.0}[marker]
        else:
            score = 2.0
        return result(score, trades=0 if case == 'no_trades' else 1)
    monkeypatch.setattr(wf, 'run_strategy_backtest', fake)
    search = {'p': [False, True]} if case != 'penalty' else {'p': [1, 2, 3]}
    expected = wf.train_fold('fake', 'Bullish', basket, fold, search, {'fee_pct': .001})
    original_calls = list(calls)
    calls.clear()
    monkeypatch.setattr(harness, '_BASKET', basket)
    trainer = harness.ParallelTrainer(InlinePool())
    actual = trainer('fake', 'Bullish', basket, fold, search, {'fee_pct': .001})
    assert actual == expected
    assert calls == original_calls
    if case == 'tie':
        assert actual[0] == {'p': False}
    if case == 'penalty':
        assert actual[0] == {'p': 2}
    if case == 'exceptions':
        assert trainer.diagnostics.counts['errors'] == 2
        assert list(actual[1]) == ['FIRST', 'THIRD']
    if case == 'no_trades':
        assert actual == ({}, {})


def test_checkpoint_exact_roundtrip_and_identity_change(monkeypatch, tmp_path):
    basket = {'FIRST': bars(1)}
    wf.precompute_bar_dates(basket['FIRST'])
    fold = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
    monkeypatch.setattr(harness, '_BASKET', basket)
    calls = []
    def fake(*args, **kwargs):
        calls.append(1)
        return result(.12345678901234567)
    monkeypatch.setattr(wf, 'run_strategy_backtest', fake)
    identity = {'data_hash': 'a', 'snapshot_hash': 'b', 'source_hash': 'c'}
    trainer = harness.ParallelTrainer(InlinePool(), checkpoint_dir=tmp_path, identity=identity)
    first = trainer('fake', 'Bullish', basket, fold, {'p': [1]}, {})
    second = trainer('fake', 'Bullish', basket, fold, {'p': [1]}, {})
    assert first == second
    assert len(calls) == 1
    changed = harness.ParallelTrainer(InlinePool(), checkpoint_dir=tmp_path, identity={**identity, 'data_hash': 'changed'})
    assert changed('fake', 'Bullish', basket, fold, {'p': [1]}, {}) == first
    assert len(calls) == 2
    assert len(list(tmp_path.glob('*.json'))) == 2


def test_checkpoint_refuses_nonfinite_result_without_altering_it(monkeypatch, tmp_path):
    basket = {'FIRST': bars(1)}
    wf.precompute_bar_dates(basket['FIRST'])
    fold = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
    value = result(1)
    value.expectancy = float('nan')
    monkeypatch.setattr(harness, '_BASKET', basket)
    monkeypatch.setattr(wf, 'run_strategy_backtest', lambda *args, **kwargs: value)
    trainer = harness.ParallelTrainer(InlinePool(), checkpoint_dir=tmp_path, identity={})
    with pytest.raises(ValueError, match='JSON compliant'):
        trainer('fake', 'Bullish', basket, fold, {'p': [1]}, {})
    assert not list(tmp_path.glob('*.json'))


def test_real_data_process_train_and_production_proposal_exact_parity(tmp_path):
    # Run exact financial parity on the authorized captured daily bars.
    archive = Path('/workspace/retuning/2026-10-03')
    if not (archive / 'AAPL.json').exists():
        pytest.skip('authorized archive not available')
    basket, manifest = harness.load_archive(archive, ['AAPL'])
    snapshot = tmp_path / 'snapshot.yaml'
    from app.services import strategy_param_store as store
    previous, cache = store.CFG, store._CACHE
    snapshot.write_bytes(previous.read_bytes())
    harness.pin_snapshot(snapshot)
    fold = wf.build_folds(date(2023, 10, 3), date(2026, 10, 2), train_months=12, test_months=3)[0]
    search = {'fast': [10, 20], 'slow': [50], 'lookback': [5], 'atr_target_mult': [3]}
    costs = {'fee_pct': .001, 'slippage_pct': .001}
    original_train = optimizer.train_fold
    try:
        expected = wf.train_fold('ma_crossover', 'Bullish', basket, fold, search, costs)
        expected_proposal = optimizer._optimize_strategy_sync('ma_crossover', 'Bullish', basket, [fold], search, costs, 20, .5)
        assert expected[0]
        assert expected_proposal is not None
        # Importable module path allows spawn to reproduce the worker initializer.
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn'),
                                 initializer=harness.initialize_worker, initargs=(snapshot, basket)) as pool:
            trainer = harness.ParallelTrainer(pool, workers=2)
            actual = trainer('ma_crossover', 'Bullish', basket, fold, search, costs)
            assert actual == expected
            optimizer.train_fold = trainer
            actual_proposal = optimizer._optimize_strategy_sync('ma_crossover', 'Bullish', basket, [fold], search, costs, 20, .5)
        assert actual_proposal == expected_proposal
    finally:
        optimizer.train_fold = original_train
        store.CFG, store._CACHE = previous, cache


def test_parent_and_worker_snapshot_freezes_exit_config_before_ttl_reads(tmp_path):
    from app.services import strategy_param_store as store
    previous, cache = store.CFG, store._CACHE
    snapshot = tmp_path / 'snapshot.yaml'
    snapshot.write_text('strategies:\n  fake:\n    exit:\n      target: 3\n')
    try:
        harness.pin_snapshot(snapshot)
        assert store.get_exit('fake') == {'target': 3}
        snapshot.write_text('strategies:\n  fake:\n    exit:\n      target: 999\n')
        assert store.get_exit('fake') == {'target': 3}
        harness.initialize_worker(snapshot, {})
        assert store.get_exit('fake') == {'target': 999}
        snapshot.write_text('strategies: {}\n')
        assert store.get_exit('fake') == {'target': 999}
    finally:
        store.CFG, store._CACHE = previous, cache


def test_corrupted_checkpoint_refuses_resume(monkeypatch, tmp_path):
    basket = {'FIRST': bars(1)}
    wf.precompute_bar_dates(basket['FIRST'])
    fold = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
    monkeypatch.setattr(harness, '_BASKET', basket)
    monkeypatch.setattr(wf, 'run_strategy_backtest', lambda *args, **kwargs: result(.5))
    trainer = harness.ParallelTrainer(InlinePool(), checkpoint_dir=tmp_path, identity={})
    trainer('fake', 'Bullish', basket, fold, {'p': [1]}, {})
    path = next(tmp_path.glob('*.json'))
    saved = json.loads(path.read_text())
    saved['results']['FIRST']['sharpe'] = 100
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='integrity'):
        trainer('fake', 'Bullish', basket, fold, {'p': [1]}, {})


def test_production_swallowed_backtest_failure_is_counted_in_training(monkeypatch, tmp_path):
    from backtesting import Backtest
    from app.services import strategy_backtest
    data = [dict(time=(date(2020, 1, 1) + timedelta(days=i)).isoformat(), open=100+i*.1, high=102+i*.1, low=98+i*.1, close=100+i*.1, volume=1000) for i in range(400)]
    basket = {'BROKEN': data}
    wf.precompute_bar_dates(data)
    monkeypatch.setattr(harness, '_BASKET', basket)
    def fail(*args, **kwargs):
        raise RuntimeError('actual Backtest.run failure')
    monkeypatch.setattr(Backtest, 'run', fail)
    fold = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
    search = {'fast': [10], 'slow': [50], 'lookback': [5]}
    expected = wf.train_fold('ma_crossover', 'Bullish', basket, fold, search, {})
    trainer = harness.ParallelTrainer(InlinePool(), checkpoint_dir=tmp_path, identity={})
    assert trainer('ma_crossover', 'Bullish', basket, fold, search, {}) == expected == ({}, {})
    assert trainer.diagnostics.counts['errors'] == 1
    assert 'actual Backtest.run failure' in trainer.diagnostics.examples['errors'][0]
    resumed = harness.ParallelTrainer(InlinePool(), checkpoint_dir=tmp_path, identity={})
    assert resumed('ma_crossover', 'Bullish', basket, fold, search, {}) == expected
    assert resumed.diagnostics.counts['errors'] == 1
    assert 'actual Backtest.run failure' in resumed.diagnostics.examples['errors'][0]


def test_production_swallowed_oos_failure_is_counted(monkeypatch):
    from backtesting import Backtest
    from app.services import strategy_backtest
    data = [dict(time=(date(2020, 1, 1) + timedelta(days=i)).isoformat(), open=100+i*.1, high=102+i*.1, low=98+i*.1, close=100+i*.1, volume=1000) for i in range(400)]
    basket = {'BROKEN': data}
    wf.precompute_bar_dates(data)
    fold = wf.Fold(date(2020, 3, 1), date(2020, 10, 1), date(2020, 10, 1), date(2021, 1, 1))
    monkeypatch.setattr(optimizer, 'train_fold', lambda *args: ({'fast': 10, 'slow': 50, 'lookback': 5}, {'BROKEN': result(.5)}))
    def fail(*args, **kwargs):
        raise RuntimeError('actual OOS Backtest.run failure')
    monkeypatch.setattr(Backtest, 'run', fail)
    diagnostics = harness.Diagnostics()
    handler = harness.OOSFailures(diagnostics)
    old_handlers = list(strategy_backtest.logger.handlers)
    old_level = strategy_backtest.logger.level
    with harness.capture_failures(handler):
        proposal = optimizer._optimize_strategy_sync('ma_crossover', 'Bullish', basket, [fold], {'fast': [10]}, {}, 20, .5)
    assert strategy_backtest.logger.handlers == old_handlers
    assert strategy_backtest.logger.level == old_level
    assert proposal['oos_metrics']['n_trades'] == 0
    assert diagnostics.counts['errors'] == 1
    assert 'actual OOS Backtest.run failure' in diagnostics.examples['errors'][0]
