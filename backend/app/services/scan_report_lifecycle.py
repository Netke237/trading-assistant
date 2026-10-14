"""Dispatch-owned evidence; transport/broker payloads are never rewritten.

The durable boundary is a typed projection, including every duplicate envelope
path. Free text is unavailable, rather than a credential-bearing log channel.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, asdict, is_dataclass
import logging
import math
import re

from fastapi import HTTPException
from app.database import AsyncSessionLocal
from app.services import scan_reports

log = logging.getLogger(__name__)
HEADERS = ('X-Scan-Report-Run-Id', 'X-Scan-Report-Generation', 'X-Scan-Report-Persistence')
_TICKER = re.compile(r'[A-Z][A-Z0-9.\-^]{0,14}\Z')
_KEY = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,80}\Z')
_NUMBER = r'-?\d+(?:\.\d+)?'
_STRATEGIES = {'pullback_ema', 'breakout_base', 'ma_crossover', 'mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap', 'mean_reversion_multi'}
_DOMAINS = {
    'direction': {'Bullish', 'Bearish'},
    'horizon': {'Intraday', 'Swing', 'Position'},
    'horizon_preset': {'Intraday', 'Swing', 'Position', 'Weekly', 'Monthly', 'Quarterly', 'SemiAnnual', 'Annual', 'Custom'},
    'params_horizon': {'Intraday', 'Swing', 'Position', 'Weekly', 'Monthly', 'Quarterly', 'SemiAnnual', 'Annual'},
    'category': set(scan_reports.CATEGORIES), 'strategy': _STRATEGIES,
    'mean_reversion_variants': {'mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap', 'mean_reversion_vwap_daily'},
    'variants': {'mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap', 'mean_reversion_vwap_daily'},
    'state': {'IDLE', 'SCANNING', 'COMPLETED', 'FAILED', 'PARTIAL', 'CANCELLED', 'Bull', 'Bear', 'Choppy', 'Trending', 'Mean-reverting'},
    'status': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA', 'Unvalidated'},
    'stock_status': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'finalStatus': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'method': {'crossover', 'additive', 'relative_strength', 'Markov', 'HMM', 'markov', 'hmm', 'fixed', 'structural'},
    'trend_method': {'crossover', 'additive', 'relative_strength'},
    'ma_type': {'EMA', 'SMA'}, 'additive_ma_type': {'EMA', 'SMA'}, 'pullback_ma_type': {'EMA', 'SMA'},
    'timeframe': {'15min', 'daily', '1d', '1D', 'weekly', '1W'},
    'params_source': {'tuned', 'baseline'}, 'next_event_label': {'earnings', 'dividend'},
    'right': {'C', 'P', 'call', 'put'}, 'sizing_basis': {'off', 'measured', 'floor:unmeasured'},
    'stockConfidence': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'contractConfidence': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'raw_status': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'before': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'after': {'PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA'},
    'orderType': {'Limit', 'Market', 'Stop'},
    'report_persistence': {'saved', 'unavailable'},
    'trendDir': {'up', 'flat', 'down'}, 'rrModel': {'Heston repriced', 'BS repriced (IV-derived)', 'Delta approximation'},
    'tpMethod': {'ladder', 'monte_carlo', 'exit_plan_2r', 'exit_plan_3r'},
    'pickedMethod': {'arithmetic', 'monte_carlo', 'ladder', 'barrier_race'},
    'pickedStopBasis': {'stock', 'premium'}, 'alignment': {'Aligned', 'Diverging', 'Unavailable'},
    'iv_basis': {'rank', 'absolute', 'none'}, 'basis': {'rank', 'absolute', 'none'},
    'outcome': {'blocked', 'aggregate'}, 'scoring_mode': {'stock', 'options'},
    'rounding': {'python_round_ties_to_even'}, 'stability': {'Stable', 'Fragile'},
    'source': {'broker', 'manual', 'final_stop', 'flat_fallback'}, 'sentiment': {'bull', 'bear', 'neutral'},
    'stopSource': {'structural', 'atr_widened'}, 'structuralSource': {'order_block', 'swing_low', 'swing_high'},
    'rrRiskBasis': {'premium_stop', 'stock_stop', 'full_premium'},
    'targetSource': {'structural_snap', 'arithmetic', 'flat_fallback', 'capped'},
    'action': {'BUY', 'SELL'}, 'spreadType': {'single', 'bear_put', 'bear_call'},
    'stopCostStatus': {'PASS', 'CAUTION'},

    'trend': {'up', 'flat', 'down'},
    'name': {'trend', 'pullback', 'trigger', 'event', 'vol', 'regime', 'fundamentals', 'confidence'},
    'gate': {'regime', 'fundamentals', 'confidence', 'backtest', 'earnings', 'bearish'},
}
# Fixed scanner field names only. Values are separately typed below.
_OVERRIDE_KEYS = set('''weight_trend weight_pullback weight_trigger weight_event weight_vol fast_ema slow_ema trend_method additive_ma_period additive_ma_type additive_slope_lookback additive_adx_period additive_adx_pass additive_adx_caution additive_price_max additive_slope_max additive_adx_max rs_period rs_pass_threshold rs_caution_threshold rs_benchmark rsi_period rsi_floor rsi_ceiling rsi_pass_min rsi_pass_max rsi_caution_min rsi_caution_max ma_type event_reject_days event_caution_days macd_fast macd_slow macd_signal swing_high_lookback_bars atr_caution_max volume_lookback_bars volume_multiplier vol_atr_period vol_pass_pct vol_caution_pct shortlist_max_candidates min_stock_score min_delta max_delta min_dte max_dte min_open_interest min_volume max_spread_pct max_spread_abs max_bid_ask_spread_pct min_bid iv_abs_pass_max iv_rank_pass_max rr_bullish_invalidation_pct rr_bearish_invalidation_pct max_iv_rank max_iv_abs preferred_dte_min preferred_dte_max preferred_volume_min preferred_oi_min preferred_spread_pct_max rr_target_r_multiple rr_method rr_min_rr rr_stop_pct rr_target_pct rr_atr_mult_stop rr_atr_mult_target atr_compression_ratio atr_avg_lookback range_atr_mult range_lookback_bars vol_compression_ratio resistance_proximity_pct swing_lookback require_trend fib_enabled fib_swing_lookback fib_levels fib_tolerance_pct impulse_min_pct retracement_recency_bars ema_filter_period'''.split())
# Full-match domain templates: a prefix is never sufficient to trust text.
_REASON_PATTERNS = [
    r'(?:no market data|no price data|no option chain|insufficient history|insufficient intraday history|regime headwind)',
    rf'(?:Pre-screen|Score gate): score {_NUMBER} rejected',
    rf'confidence gate REJECT: {_NUMBER}% < {_NUMBER}%',
    rf'price filter \(\${_NUMBER} [<>] \${_NUMBER} (?:min|max)\)',
    rf'cap filter \(\${_NUMBER}B [<>] \${_NUMBER}B (?:min|max)\)',
    rf'REJECT score={_NUMBER}',
    r'direction_conviction_unmeasured: no trend measurement for (?:Bullish|Bearish) (?:Intraday|Swing|Position)',
    r'regime data unavailable: no completed 15-min bars for [A-Z][A-Z0-9.\-^]{0,14}',
    rf'price \${_NUMBER} [<>] (?:min|max)',
    rf'direction_conviction: trend {_NUMBER} < {_NUMBER} for (?:Bullish|Bearish) (?:Intraday|Swing|Position)',
    rf'Shortlist cap: (?:PASS|CAUTION|REJECT) score {_NUMBER} contract {_NUMBER} ranked \d+ of \d+ \(cap \d+\)',
    rf'Shortlist cap: (?:PASS|CAUTION|REJECT) score {_NUMBER} confidence (?:{_NUMBER}%|n/a) ranked \d+ of \d+ \(cap \d+\)',
    r'contracts rejected: no_live_quote\(\d+\)',
    r'no (?:' + '|'.join(sorted(_STRATEGIES)) + r') setup',
]


def _dump(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else asdict(value) if is_dataclass(value) else deepcopy(value)


def _safe_key(key):
    return isinstance(key, str) and bool(_KEY.fullmatch(key)) and key.lower() not in scan_reports.FORBIDDEN_KEYS and not any(p in key.lower() for p in ('password', 'token', 'secret', 'credential', 'api_key', 'authorization'))


def _safe_string(key, value):
    if key in _DOMAINS:
        return value in _DOMAINS[key]
    if key in {'symbol', 'symbols', 'accepted_symbols', 'expanded_symbols', 'dispatched_symbols', 'rs_benchmark', 'benchmark'}:
        return bool(_TICKER.fullmatch(value))
    if key == 'universe':
        from app.data.universe_presets import PRESET_UNIVERSES, SECTOR_ETF_TO_NAME
        return bool(_TICKER.fullmatch(value)) or value in PRESET_UNIVERSES or value in {'SECTOR:'+s for s in SECTOR_ETF_TO_NAME}
    if key in {'scan_id', 'previous_run_id', 'report_run_id'}:
        return bool(re.fullmatch(r'[a-fA-F0-9\-]{8,64}', value))
    if key == 'timestamp':
        return bool(re.fullmatch(r'\d{4}-\d\d-\d\dT[\d:.+Z\-]{8,30}', value))
    if key in {'reason', 'detail'}:
        return any(re.fullmatch(p, value) for p in _REASON_PATTERNS)
    return False


def project(value, *, path='', unavailable=None, key=''):
    """Retain typed measured values and known domain strings, never free text."""
    unavailable = unavailable if unavailable is not None else []
    value = _dump(value)
    if value is None or isinstance(value, bool):
        return value
    if (isinstance(value, int) or isinstance(value, float) and math.isfinite(value)):
        return value
    if isinstance(value, str) and _safe_string(key, value):
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            p = f'{path}.{k}' if _safe_key(k) else f'{path}.[unavailable_field]'
            if not _safe_key(k) or (key in {'overrides', 'params_override'} and k not in _OVERRIDE_KEYS):
                unavailable.append(p)
                continue
            projected = project(v, path=p, unavailable=unavailable, key=k)
            if projected is not _OMIT:
                out[k] = projected
            else:
                if path.startswith('result') and isinstance(v, str):
                    out[k] = 'diagnostic_unavailable' if k == 'reason' else ''
                out[k+'_unavailable'] = True
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for i, v in enumerate(value):
            projected = project(v, path=f'{path}[{i}]', unavailable=unavailable, key=key)
            if projected is not _OMIT:
                out.append(projected)
        return out
    unavailable.append(path)
    return _OMIT


_OMIT = object()


_TERMINAL_CODES = {
    'accepted': {'candidate_returned'}, 'excluded': {'scan_policy'},
    'no_data': {'missing_history', 'insufficient_history', 'missing_price', 'insufficient_intraday_history', 'regime_data_unavailable', 'trend_unmeasured'},
    'error': {'history_fetch_failed', 'signal_processing_failed', 'regime_fetch_failed', 'data_processing_failed', 'unsupported_strategy'},
    'no_setup': {'setup_not_returned', 'fib_level_not_returned'},
    'filtered': {'ema_side', 'price_min', 'price_max', 'score_status', 'score_min', 'direction_conviction', 'regime_headwind', 'backtest_gate', 'confidence_gate', 'shortlist_cap'},
}
_TERMINAL_NUMBERS = {'current_close', 'ema_value', 'ema_period', 'price', 'min_price', 'max_price', 'score', 'min_stock_score', 'trend_score', 'min_trend', 'confidence', 'confidence_reject_below', 'cap', 'rank', 'original_count', 'sample_size', 'win_rate', 'n_trades', 'min_trades', 'min_win_rate'}


def project_terminal_record(symbol, terminal, code, *, observations=None, thresholds=None):
    """Dedicated finite-domain projection; never route terminal text through project."""
    if not isinstance(symbol, str) or not _TICKER.fullmatch(symbol) or not isinstance(terminal, str) or terminal not in _TERMINAL_CODES or not isinstance(code, str) or code not in _TERMINAL_CODES[terminal]:
        return None
    record = dict(symbol=symbol, terminal=terminal, code=code)
    for name, values in (('observations', observations), ('thresholds', thresholds)):
        safe = {}
        if isinstance(values, dict):
            for key, value in values.items():
                if key in _TERMINAL_NUMBERS and isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value)):
                    safe[key] = value
                elif key in {'direction', 'strategy', 'status'} and isinstance(value, str) and value in _DOMAINS[key]:
                    safe[key] = value
                elif key == 'passes_gate' and isinstance(value, bool):
                    safe[key] = value
        if safe:
            record[name] = safe
    return record


@dataclass
class Collector:
    request: dict
    unavailable: list[str] = field(default_factory=list)
    expanded: list | None = None
    dispatched: list | None = None
    excluded: list | None = None
    observations: list = field(default_factory=list)
    data_failures: list = field(default_factory=list)
    no_data: bool = False
    terminal_enabled: bool = False
    terminal_inputs: list[str] | None = None
    terminal_resolution_available: bool = True
    terminal_evaluated: list[str] = field(default_factory=list)
    terminal_records: dict = field(default_factory=dict)
    terminal_conflicts: set[str] = field(default_factory=set)

    def terminal_snapshot(self, *, interrupted=False):
        if not self.terminal_enabled or self.terminal_inputs is None:
            return None
        if not self.terminal_resolution_available and not self.terminal_records and not self.terminal_evaluated:
            return None
        records = [deepcopy(self.terminal_records[x]) for x in self.terminal_inputs if x in self.terminal_records and x not in self.terminal_conflicts and not (interrupted and self.terminal_records[x]['terminal'] == 'accepted')]
        recorded = {r['symbol'] for r in records}
        unknown = [x for x in self.terminal_inputs if x not in recorded]
        counts = {x: 0 for x in ('accepted', 'excluded', 'no_data', 'error_count', 'no_setup', 'filtered')}
        for record in records:
            counts['error_count' if record['terminal'] == 'error' else record['terminal']] += 1
        counts.update(input=len(self.terminal_inputs) if self.terminal_resolution_available else None,
                      evaluated=len(self.terminal_evaluated) if self.terminal_resolution_available else None)
        excluded = {r['symbol'] for r in records if r['terminal'] == 'excluded'}
        stages_match = set(self.terminal_evaluated) == set(self.terminal_inputs) - excluded
        result = dict(version=1, resolution_available=self.terminal_resolution_available, complete=self.terminal_resolution_available and not unknown and stages_match and not interrupted and not self.terminal_conflicts,
                      input_symbols=list(self.terminal_inputs), evaluated_symbols=list(self.terminal_evaluated),
                      outcomes=records, counts=counts, unknown_symbols=unknown)
        if self.terminal_conflicts:
            result['diagnostic_unavailable'] = True
        return result

    def inputs(self):
        return dict(request=deepcopy(self.request), expanded_symbols=deepcopy(self.expanded),
                    dispatched_symbols=deepcopy(self.dispatched), excluded=deepcopy(self.excluded),
                    resolution_available=self.dispatched is not None,
                    input_fields_unavailable=list(self.unavailable),
                    configuration_observations=deepcopy(self.observations),
                    configuration_unavailable=['stock_scorer._load_config', 'contract_validator._load_config', 'signal_confidence.load_backtest_cfg', 'strategy_engine.internal_configuration', 'provider_internal_settings'],
                    effective_configuration_complete=False)


_collector: ContextVar[Collector | None] = ContextVar('scan_report_collector', default=None)


def current_collector():
    return _collector.get()


def observe_resolution(expanded, dispatched, excluded):
    c = current_collector()
    if c is None:
        return
    if c.terminal_enabled:
        c.terminal_resolution_available = all(isinstance(x, str) and _TICKER.fullmatch(x) for x in expanded)
        c.terminal_inputs = list(dict.fromkeys(x for x in expanded if isinstance(x, str) and _TICKER.fullmatch(x)))
        for item in excluded:
            symbol = item.get('symbol') if isinstance(item, dict) else item.symbol
            observe_terminal(symbol, 'excluded', 'scan_policy')
    c.expanded = project(expanded, key='expanded_symbols', path='expanded_symbols', unavailable=c.unavailable)
    c.dispatched = project(dispatched, key='dispatched_symbols', path='dispatched_symbols', unavailable=c.unavailable)
    c.excluded = []
    for item in excluded:
        symbol = item.get('symbol') if isinstance(item, dict) else item.symbol
        safe = project(symbol, key='symbol', path='excluded.symbol', unavailable=c.unavailable)
        if safe is not _OMIT:
            c.excluded.append(dict(symbol=safe, reason='excluded_by_scan_policy', reason_unavailable=True))


def observe_evaluation(symbol):
    c = current_collector()
    if c is not None and c.terminal_enabled and c.terminal_inputs is not None and symbol in c.terminal_inputs and symbol not in c.terminal_evaluated:
        c.terminal_evaluated.append(symbol)


def observe_terminal(symbol, terminal, code, *, observations=None, thresholds=None):
    c = current_collector()
    if c is None or not c.terminal_enabled:
        return
    context = {key: c.request[key] for key in ('strategy', 'direction') if key in c.request}
    record = project_terminal_record(symbol, terminal, code, observations={**context, **(observations or {})}, thresholds=thresholds)
    if record is None or c.terminal_inputs is None or symbol not in c.terminal_inputs:
        return
    previous = c.terminal_records.get(symbol)
    if previous is not None and previous != record:
        c.terminal_conflicts.add(symbol)
    elif previous is None:
        c.terminal_records[symbol] = record


def observe_configuration(source, values, *, symbol=None):
    c = current_collector()
    if c is None:
        return
    projected = project(values, path=source, unavailable=c.unavailable)
    observation = {'source': source, 'values': None if projected is _OMIT else projected}
    if symbol is not None:
        safe = project(symbol, key='symbol', path=source+'.symbol', unavailable=c.unavailable)
        if safe is not _OMIT:
            observation['symbol'] = safe
    if observation not in c.observations:
        c.observations.append(observation)


def observe_data_failure(symbol):
    c = current_collector()
    if c is not None and isinstance(symbol, str) and _TICKER.fullmatch(symbol):
        c.data_failures.append({'symbol': symbol, 'code': 'data_processing_failed'})


def observe_no_data():
    c = current_collector()
    if c is not None:
        c.no_data = True


def persisted_result(result):
    unavailable = []
    projected = project(result, path='result', unavailable=unavailable)
    c = current_collector()
    if c is not None and isinstance(projected, dict):
        failed = {x['symbol'] for x in c.data_failures}
        excluded = {x['symbol'] for x in c.excluded or []}
        for row in projected.get('rejected', []):
            if row.get('symbol') in failed:
                row.update(reason='data_processing_failed', reason_unavailable=True)
            elif row.get('symbol') in excluded:
                row.update(reason='excluded_by_scan_policy', reason_unavailable=True)
    return {'candidates': projected, 'fields_unavailable': unavailable} if isinstance(projected, list) else {**projected, 'fields_unavailable': unavailable}


def _metadata(run, persistence):
    return dict(report_run_id=run['run_id'], report_generation=run['generation'], report_persistence=persistence)


def _headers(run, persistence):
    return dict(zip(HEADERS, (run['run_id'], str(run['generation']), persistence)))


async def _finish(run, **kwargs):
    async with AsyncSessionLocal() as db:
        return await scan_reports.finish_run(db, run['run_id'], **kwargs)


async def recover_interrupted():
    async with AsyncSessionLocal() as db:
        return await scan_reports.recover_interrupted(db)


def _partial_diagnostics(c):
    if not c.terminal_evaluated and not c.terminal_records:
        return None
    terminal = c.terminal_snapshot(interrupted=True)
    return {'terminal_outcomes': terminal} if terminal is not None else None


async def run_reported_scan(request, *, category, trigger, callback, response=None):
    unavailable = []
    frozen = project(request, path='request', unavailable=unavailable)
    c = Collector(request=frozen, unavailable=unavailable, terminal_enabled=category in {'prebreakout', 'fib', 'pullback'})
    token = _collector.set(c)
    run = None
    try:
        try:
            async with AsyncSessionLocal() as db:
                run = await scan_reports.begin_run(db, category=category, trigger=trigger, inputs=c.inputs())
        except (scan_reports.ScanReportStorageError, ValueError, TypeError):
            log.error('scan report begin unavailable')
            raise HTTPException(503, 'Scan report storage unavailable', headers={HEADERS[2]: 'unavailable'}) from None
        try:
            result = await callback()
        except asyncio.CancelledError:
            try:
                await asyncio.shield(_finish(run, status='cancelled', error_code='cancelled', inputs=c.inputs(), diagnostics=_partial_diagnostics(c), promote_usable=False))
            except (scan_reports.ScanReportStorageError, ValueError, TypeError):
                log.error('scan report cancellation save unavailable')
            raise
        except Exception as exc:
            persistence = 'saved'
            try:
                await _finish(run, status='failed', error_code='scan_failed', inputs=c.inputs(), diagnostics=_partial_diagnostics(c), promote_usable=False)
            except (scan_reports.ScanReportStorageError, ValueError, TypeError):
                persistence = 'unavailable'
                log.error('scan report failure save unavailable')
            if isinstance(exc, HTTPException):
                exc.headers = {**(exc.headers or {}), **_headers(run, persistence)}
                raise
            raise HTTPException(500, 'Scan failed', headers=_headers(run, persistence)) from None
        try:
            snapshot = persisted_result(result)
        except (ValueError, TypeError, OverflowError):
            log.error('scan report serialization unavailable')
            if response is not None:
                response.headers.update(_headers(run, 'unavailable'))
            return result.model_copy(update=_metadata(run, 'unavailable')) if hasattr(result, 'model_copy') else result
        if not isinstance(result, list):
            snapshot.update(_metadata(run, 'saved'))
        pipeline = snapshot.get('pipeline')
        diagnostics = None
        if pipeline is not None:
            diagnostics = dict(pipeline=pipeline, rejected=snapshot.get('rejected', []),
                               accepted_symbols=[x['symbol'] for x in snapshot.get('candidates', []) if 'symbol' in x],
                               fields_unavailable=snapshot['fields_unavailable'], data_failures=deepcopy(c.data_failures))
        elif isinstance(result, list):
            diagnostics = dict(accepted_symbols=[x['symbol'] for x in snapshot['candidates'] if 'symbol' in x],
                               excluded=deepcopy(c.excluded), stage_counts_available=False,
                               rejection_reasons_available=False, data_failures=deepcopy(c.data_failures),
                               fields_unavailable=snapshot['fields_unavailable'])
        terminal = c.terminal_snapshot()
        if terminal is not None:
            diagnostics = {**(diagnostics or {}), 'terminal_outcomes': terminal}
        status = 'failed' if getattr(result, 'state', None) == 'FAILED' else 'no_data' if c.no_data else 'complete'
        persistence = 'saved'
        try:
            await _finish(run, status=status, error_code='scan_failed' if status == 'failed' else 'no_data' if status == 'no_data' else None,
                          diagnostics=diagnostics, result=snapshot, inputs=c.inputs())
        except (scan_reports.ScanReportStorageError, ValueError, TypeError):
            persistence = 'unavailable'
            log.error('scan report terminal save unavailable')
        if response is not None:
            response.headers.update(_headers(run, persistence))
        if hasattr(result, 'model_copy'):
            result = result.model_copy(update=_metadata(run, persistence))
        return result
    finally:
        _collector.reset(token)
