"""Isolated explicit daily simulation. This module never updates a scan or trading state."""
import asyncio
import copy
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

from app.data.confidence_cache import BARS_BASIS_VERSION
from app.services.historical_store import get_bars as get_historical_bars
from app.services.strategy_backtest import run_strategy_backtest_detailed
from app.services.strategy_backtest_details import source_frame
from app.services import backtest_artifacts


async def run_fresh(request, db):
    try:
        # The engine uses up to 400 daily bars for signals. Include warmup,
        # but freeze and display only the requested evaluation window.
        bars = copy.deepcopy(await get_historical_bars(
            request.symbol, request.start - timedelta(days=1000), request.end))
        _, times, _ = source_frame(bars) if bars else (None, [], False)
        if not bars:
            return {'status': 'insufficient_history', 'artifact': None}
        from datetime import datetime, timezone
        start = datetime.combine(request.start, datetime.min.time(), timezone.utc).timestamp()
        end = datetime.combine(request.end, datetime.min.time(), timezone.utc).timestamp()
        # The engine's dated-bar parser preserves ISO dates; avoid its legacy
        # numeric time interpretation on the explicit daily endpoint.
        selected = [(dict(b, time=datetime.fromtimestamp(t, timezone.utc).isoformat()), t)
                    for b, t in zip(bars, times) if t < end]
        bars = [b for b, _ in selected]
        from app.services.strategy_engine import bars_needed
        if (sum(t < start for _, t in selected) < max(100, bars_needed(request.strategy, request.params))
                or not any(start <= t < end for _, t in selected)):
            return {'status': 'insufficient_history', 'artifact': None}
        detail = await asyncio.to_thread(
            run_strategy_backtest_detailed, bars, strategy=request.strategy,
            direction=request.direction, params=copy.deepcopy(request.params),
            commission=request.commission, entry_start=request.start, entry_end=request.end,
            hold_max_days=request.hold_max_days, min_trades=request.min_trades,
            min_win_rate=request.min_win_rate)
        if detail.status != 'success':
            return {'status': detail.status, 'artifact': None}
        fixed = ('initial_cash', 'order_size', 'margin', 'spread', 'exclusive_orders',
                 'trade_on_close', 'finalize_trades', 'sizing')
        if (detail.effective_params != request.params
                or any(detail.configuration.get(key) != getattr(request, key) for key in fixed)):
            return {'status': 'invalid_evidence', 'artifact': None}
        fingerprint = hashlib.sha256(json.dumps(
            dict(bars=bars, request=request.model_dump(mode='json'), basis=BARS_BASIS_VERSION,
                 engine=detail.engine_contract_version), sort_keys=True, allow_nan=False).encode()).hexdigest()
        identity = dict(scan_id=str(uuid4()), report_run_id=None, symbol=request.symbol,
                        strategy=request.strategy, direction=request.direction,
                        horizon='Explicit daily window', interval='1d',
                        bars_basis_version=BARS_BASIS_VERSION, input_hash=fingerprint,
                        engine_contract_version=detail.engine_contract_version)
        artifact = await backtest_artifacts.save_artifact(db, detail=detail, identity=identity,
                                                         provenance='fresh')
        return {'status': 'success', 'artifact': artifact}
    except asyncio.CancelledError:
        raise
    except backtest_artifacts.ArtifactStorageError:
        return {'status': 'storage_unavailable', 'artifact': None}
    except Exception:
        return {'status': 'failed', 'artifact': None}
