#!/usr/bin/env python3
"""Review-only WFO over an archived basket; never adopts parameters.

Run with backend Python 3.11. The production optimizer/OOS path is unchanged;
only independent training backtests execute in bounded, ordered workers.
"""
from __future__ import annotations
import argparse
from collections import deque
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import date
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import logging
import math
import multiprocessing
import os
from pathlib import Path
import sys
import time
import warnings
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'backend'))
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[_name] = '1'

from app.services import strategy_param_store as store
from app.services import strategy_param_optimizer as optimizer
from app.services import walk_forward as wf
from app.services import strategy_backtest as backtest
from app.services.strategy_backtest import BacktestResult, normalize_direction

_BASKET = {}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    # Fail on nonfinite values instead of making cached evidence look finite.
    text = json.dumps(value, indent=2, allow_nan=False)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text + '\n')
    temporary.replace(path)


def pin_snapshot(path, contents=None):
    store.CFG = Path(path)
    store._CACHE = None
    # Clear first, then freeze the parsed snapshot for the whole process. The
    # normal TTL must not reopen a changed file in an hours-long computation.
    contents = store.CFG.read_bytes() if contents is None else contents
    frozen = yaml.safe_load(contents)
    if not isinstance(frozen, dict):
        raise ValueError("Strategy snapshot must be a mapping")
    store._CACHE = (store.CFG, frozen, float('inf'))


def initialize_worker(snapshot, basket, contents=None):
    global _BASKET
    pin_snapshot(snapshot, contents)
    _BASKET = basket


def evaluate_job(job):
    strategy, direction, symbol, combo, fold, costs = job
    train_bars, n_scored = wf.slice_with_warmup(_BASKET[symbol], fold.train_start, fold.train_end)
    if n_scored < wf.MIN_SCORED_BARS or len(train_bars) < 100:
        return symbol, None, [], None
    failures = Diagnostics()
    with capture_failures(OOSFailures(failures)), warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter('always')
        try:
            # Net of per-leg costs, exactly as production train_fold (Phase C T4).
            result = wf.run_strategy_backtest(train_bars, strategy=strategy, direction=direction,
                                              params=combo, commission=wf.commission_for(costs),
                                              entry_start=fold.train_start)
        except Exception as exc:
            result = None
            failures.add('errors', [f'{symbol}: {type(exc).__name__}: {exc}'])
    for kind in failures.examples:
        failures.examples[kind] = [f'{symbol}: {message}' for message in failures.examples[kind]]
    return symbol, result, [f'{w.category.__name__}: {w.message}' for w in observed], failures.json()


def ordered_bounded_map(pool, fn, jobs, pending_limit):
    pending = deque()
    jobs = iter(jobs)
    for _ in range(pending_limit):
        try:
            pending.append(pool.submit(fn, next(jobs)))
        except StopIteration:
            break
    while pending:
        yield pending.popleft().result()
        try:
            pending.append(pool.submit(fn, next(jobs)))
        except StopIteration:
            pass


class Diagnostics:
    def __init__(self):
        self.counts = {'warnings': 0, 'errors': 0}
        self.examples = {'warnings': [], 'errors': []}

    def add(self, kind, messages):
        self.counts[kind] += len(messages)
        for message in messages:
            if len(self.examples[kind]) < 10:
                self.examples[kind].append(message)

    def merge(self, value):
        for kind in self.counts:
            self.counts[kind] += value['counts'][kind]
            for message in value['examples'][kind]:
                if len(self.examples[kind]) < 10:
                    self.examples[kind].append(message)

    def json(self):
        return {'counts': dict(self.counts), 'examples': self.examples}


class ParallelTrainer:
    def __init__(self, pool, *, workers=5, checkpoint_dir=None, identity=None, progress=None):
        self.pool = pool
        self.pending_limit = workers * 4
        self.checkpoint_dir = checkpoint_dir
        self.identity = identity
        self.progress = progress or (lambda *args: None)
        self.diagnostics = Diagnostics()
        self.fold_records = []

    def __call__(self, strategy, direction, basket_bars, fold, search_space, costs):
        key_inputs = {'identity': self.identity, 'strategy': strategy, 'direction': direction,
                      'fold': {k: v.isoformat() for k, v in asdict(fold).items()},
                      'search_space': list(search_space.items()), 'costs': costs,
                      'symbols': list(basket_bars)}
        key = digest(key_inputs)
        path = self.checkpoint_dir / f'{key}.json' if self.checkpoint_dir else None
        if path and path.exists():
            saved = json.loads(path.read_text())
            content_hash = saved.pop('content_sha256')
            if digest(saved) != content_hash:
                raise ValueError('Checkpoint content integrity mismatch')
            if saved['key'] != key or saved['inputs'] != json.loads(json.dumps(key_inputs)):
                raise ValueError('Checkpoint does not match immutable inputs')
            self.diagnostics.merge(saved['diagnostics'])
            results = {s: BacktestResult(**r) for s, r in saved['results'].items()}
            self.fold_records.append({'key': key, 'strategy': strategy, 'fold': key_inputs['fold'], 'winner': saved['winner'], 'resumed': True})
            self.progress(strategy, key, 'resumed')
            return saved['winner'], results
        local = Diagnostics()
        best, best_score, best_results = None, float('-inf'), {}
        self.progress(strategy, key, 'started')
        for index, combo in enumerate(wf.param_combos(search_space)):
            sharpes, combo_results = [], {}
            jobs = ((strategy, direction, symbol, combo, fold, costs) for symbol in basket_bars)
            for symbol, result, observed, error in ordered_bounded_map(self.pool, evaluate_job, jobs, self.pending_limit):
                local.add('warnings', observed)
                if error:
                    local.merge(error)
                if result is None:
                    continue
                combo_results[symbol] = result
                if result.n_trades > 0:
                    sharpes.append(result.sharpe)
            pooled = sum(sharpes) / len(sharpes) if sharpes else float('-inf')
            score = pooled - wf._complexity_penalty(combo, search_space) if sharpes else pooled
            if score > best_score:
                best_score, best, best_results = score, combo, combo_results
            self.progress(strategy, key, f'combination:{index + 1}')
        winner = best or {}
        saved = {'key': key, 'inputs': key_inputs, 'winner': winner,
                 'results': {s: asdict(r) for s, r in best_results.items()}, 'diagnostics': local.json()}
        if path:
            saved['content_sha256'] = digest(saved)
            write_json(path, saved)
        self.diagnostics.merge(local.json())
        self.fold_records.append({'key': key, 'strategy': strategy, 'fold': key_inputs['fold'], 'winner': winner, 'resumed': False})
        self.progress(strategy, key, 'completed')
        return winner, best_results


class OOSFailures(logging.Handler):
    def __init__(self, diagnostics):
        super().__init__()
        self.diagnostics = diagnostics

    def emit(self, record):
        message = record.getMessage()
        if message.startswith(('OOS backtest failed', 'Backtest failed')):
            self.diagnostics.add('errors', [message])


@contextmanager
def capture_failures(handler):
    loggers = (optimizer.logger, backtest.logger)
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels):
            logger.removeHandler(handler)
            logger.setLevel(level)


def load_archive(archive, symbols):
    basket, manifest = {}, {}
    for symbol in symbols:
        path = archive / f'{symbol}.json'
        bars = json.loads(path.read_text())
        if not bars:
            raise ValueError(f'{symbol}: empty archive')
        times = [date.fromisoformat(b['time']) for b in bars]
        if times != sorted(set(times)):
            raise ValueError(f'{symbol}: dates must be sorted and unique')
        wf.precompute_bar_dates(bars)
        basket[symbol] = bars
        manifest[symbol] = {'sha256': sha_file(path), 'rows': len(bars),
                            'first': times[0].isoformat(), 'last': times[-1].isoformat(),
                            'provider_alias': 'BRK-B' if symbol == 'BRK.B' else symbol}
    return basket, manifest


def run(args):
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Python 3.11 is required for numerical parity')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / 'strategy_params.snapshot.yaml'
    if not snapshot.exists():
        snapshot.write_bytes(store.CFG.read_bytes())
    snapshot_bytes = snapshot.read_bytes()
    pin_snapshot(snapshot, snapshot_bytes)
    cfg = store._load()
    configured_symbols = json.loads((args.archive / 'symbols.json').read_text())
    symbols = args.symbols or configured_symbols
    if len(symbols) != len(set(symbols)):
        raise ValueError('Duplicate selected symbols')
    basket, assets = load_archive(args.archive, symbols)
    direction = normalize_direction(cfg.get('direction', 'bullish'))
    windows, costs = cfg.get('windows', {}), cfg.get('costs', {})
    folds = wf.build_folds(max(min(b['_date'] for b in bars) for bars in basket.values()),
                          min(max(b['_date'] for b in bars) for bars in basket.values()),
                          train_months=windows.get('train_months', 12), test_months=windows.get('test_months', 3),
                          anchored=windows.get('type') == 'anchored')
    sources = {str(p.relative_to(REPO)): sha_file(p) for p in sorted((REPO / 'backend/app').rglob('*.py'))}
    sources[str(Path(__file__).relative_to(REPO))] = sha_file(Path(__file__))
    packages = {}
    for package in ('numpy', 'pandas', 'backtesting', 'scipy'):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = 'not-installed'
    identity = {'config_sha256': hashlib.sha256(snapshot_bytes).hexdigest(), 'assets': assets, 'sources': sources, 'packages': packages,
                'runtime': sys.version, 'selected_symbols': symbols, 'direction': direction}
    strategies = args.strategies or list(cfg.get('strategies', {}))
    grids = {strategy: store.get_search_space(strategy) for strategy in strategies}
    manifest = {'identity': identity, 'configured_symbols': configured_symbols, 'selected_symbols': symbols,
                'symbols_manifest_sha256': sha_file(args.archive / 'symbols.json'),
                'grids': grids, 'grid_combinations': {s: math.prod(len(v) for v in grid.values()) if grid else 0 for s, grid in grids.items()},
                'folds': [{k: v.isoformat() for k, v in asdict(f).items()} for f in folds],
                'costs': costs, 'windows': windows, 'workers': args.workers,
                'metrics': {'expectancy_sharpe': 'net of the per-leg commission (fee_pct + slippage_pct) charged on the entry and exit of every trade, the same as production train_fold',
                            'returns_consistency': 'net of the per-leg commission (fee_pct + slippage_pct) charged on the entry and exit of every trade, the same as production train_fold'}}
    write_json(output / 'manifest.json', manifest)
    checkpoints = output / 'checkpoints'
    checkpoints.mkdir(exist_ok=True)
    def progress(strategy, key, status):
        write_json(output / 'progress.json', {'strategy': strategy, 'fold_key': key, 'status': status,
                                             'identity_hash': digest(identity), 'updated_unix': time.time()})
    proposals, skipped = {}, {}
    original_train = optimizer.train_fold
    oos_diagnostics = Diagnostics()
    handler = OOSFailures(oos_diagnostics)
    try:
        with capture_failures(handler), ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn'),
                                 initializer=initialize_worker, initargs=(snapshot, basket, snapshot_bytes)) as pool:
            trainer = ParallelTrainer(pool, workers=args.workers, checkpoint_dir=checkpoints, identity=identity, progress=progress)
            optimizer.train_fold = trainer
            for strategy in strategies:
                search = store.get_search_space(strategy)
                if not search:
                    skipped[strategy] = 'unsupported empty search grid'
                    continue
                if not folds:
                    skipped[strategy] = 'no complete production folds'
                    continue
                with warnings.catch_warnings(record=True) as observed:
                    warnings.simplefilter('always')
                    proposal = optimizer._optimize_strategy_sync(strategy, direction, basket, folds, search, costs,
                                                               cfg.get('optimization', {}).get('min_trades', 20),
                                                               cfg.get('optimization', {}).get('min_consistency', .5),
                                                               cfg.get('optimization', {}).get('min_symbols', 3))
                oos_diagnostics.add('warnings', [f'{w.category.__name__}: {w.message}' for w in observed])
                if proposal is None:
                    skipped[strategy] = 'all production training-fold winners empty'
                else:
                    proposals[strategy] = proposal
                write_json(output / 'proposals.json', {'proposals': proposals, 'skipped': skipped,
                                                      'identity_hash': digest(identity), 'training_diagnostics': trainer.diagnostics.json(),
                                                      'oos_diagnostics': oos_diagnostics.json(), 'fold_records': trainer.fold_records})
            write_json(output / 'proposals.json', {'proposals': proposals, 'skipped': skipped,
                                                  'identity_hash': digest(identity), 'training_diagnostics': trainer.diagnostics.json(),
                                                  'oos_diagnostics': oos_diagnostics.json(), 'fold_records': trainer.fold_records})
            progress(None, None, 'completed')
    finally:
        optimizer.train_fold = original_train


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--symbols', nargs='+')
    parser.add_argument('--strategies', nargs='+')
    parser.add_argument('--workers', type=int, default=5, choices=range(1, 6))
    run(parser.parse_args())
