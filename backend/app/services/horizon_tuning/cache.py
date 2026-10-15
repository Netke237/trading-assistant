"""Disk cache for signal series and gate masks — STOCKS-HORIZON-T1 H8.

Under ``backend/data/tuning_cache/`` (gitignored): ``signals/<key>.json`` and
``gates/<key>.json``, one file per key, written atomically (tmp + replace) so
parallel workers never read a half-written file.

**Signal key** = sha256 of: symbol, strategy, direction, the EFFECTIVE params
(after the ``exit:`` merge, or the merged multi shape; canonical JSON),
``SIGNAL_WINDOW_BARS``, ``BARS_BASIS_VERSION``, the OHLCV hash and
``SIGNAL_CACHE_VERSION``.

**Gate key** = sha256 of: symbol, direction, scoring horizon, the OHLCV hash,
``BARS_BASIS_VERSION``, the sha256 of ``scoring_rules.yaml``, the benchmark's
OHLCV hash (if any), the price bounds, and the source of ``stock_scorer.py``,
of ``routers/stock_scan.py::_direction_conviction_drop`` and of
``services/config_loader.py`` (which resolves the conviction floor).
"""
from __future__ import annotations

from dataclasses import asdict, fields
import hashlib
import inspect
import json
import math
import os
import uuid
from pathlib import Path

from app.data.confidence_cache import BARS_BASIS_VERSION
from app.services.horizon_tuning import gates as _gates
from app.services.horizon_tuning import signals as _signals
from app.services.horizon_tuning.signals import SignalPoint

# Bump whenever a signal function in strategy_engine.py changes what it
# returns. tests/test_horizon_tuning_core.py pins strategy_engine.py's source
# hash per version and fails with "bump SIGNAL_CACHE_VERSION" when it changes.
SIGNAL_CACHE_VERSION = 3

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "tuning_cache"

_OHLCV = ("time", "open", "high", "low", "close", "volume")


def _sha(text: str | bytes) -> str:
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _source_text(path: Path) -> bytes:
    """File bytes with LF line endings (a CRLF checkout hashes the same)."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def ohlcv_hash(bars: list[dict] | None) -> str | None:
    """sha256 over every bar's time, open, high, low, close and volume."""
    if bars is None:
        return None
    return _sha(_canonical([[b.get(k) for k in _OHLCV] for b in bars]))


def signal_sources() -> dict[str, str]:
    """Dynamic source identity for signal computation and research order semantics.

    Included in both disk-cache keys and CLI resume identities. A code change
    invalidates persisted research results even without a manual version bump.
    """
    from app.services import setup_entries, strategy_engine
    from app.services.horizon_tuning import simulate
    return {module.__name__: _sha(_source_text(Path(inspect.getfile(module))))
            for module in (strategy_engine, setup_entries, _signals, simulate)}


def signal_key(symbol: str, bars: list[dict], strategy: str, direction: str, params: dict | None) -> str:
    from app.services.strategy_backtest import normalize_direction
    from app.services.strategy_engine import SIGNAL_WINDOW_BARS
    return _sha(_canonical({
        "symbol": symbol.upper(),
        "strategy": strategy,
        "direction": normalize_direction(direction),
        "params": _signals.effective_params(strategy, params),
        "window": SIGNAL_WINDOW_BARS,
        "bars_basis": BARS_BASIS_VERSION,
        "ohlcv": ohlcv_hash(bars),
        "version": SIGNAL_CACHE_VERSION,
        "sources": signal_sources(),
    }))


def _gate_sources() -> dict[str, str]:
    from app.routers import stock_scan
    from app.scoring import stock_scorer
    from app.services import config_loader
    return {
        "scoring_rules": _sha(Path(stock_scorer.CONFIG_PATH).read_bytes()),
        "stock_scorer": _sha(_source_text(Path(inspect.getfile(stock_scorer)))),
        "conviction_drop": _sha(inspect.getsource(stock_scan._direction_conviction_drop).replace("\r\n", "\n")),
        "config_loader": _sha(_source_text(Path(inspect.getfile(config_loader)))),
    }


def gate_key(symbol: str, bars: list[dict], direction: str, scoring_horizon: str, *,
             min_price: float | None, max_price: float | None, benchmark: list[dict] | None) -> str:
    from app.services.strategy_backtest import normalize_direction
    return _sha(_canonical({
        "symbol": symbol.upper(),
        "direction": normalize_direction(direction),
        "scoring_horizon": scoring_horizon,
        "ohlcv": ohlcv_hash(bars),
        "bars_basis": BARS_BASIS_VERSION,
        "benchmark": ohlcv_hash(benchmark),
        "min_price": min_price,
        "max_price": max_price,
        **_gate_sources(),
    }))


def _write_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None   # unreadable or truncated: recompute and overwrite


class TuningCache:
    """Signal series and gate masks, read from disk or computed and written."""

    def __init__(self, root: Path | str = DEFAULT_CACHE_DIR):
        self.root = Path(root)
        self.hits = 0
        self.misses = 0

    def signal_series(self, symbol: str, bars: list[dict], strategy: str, direction: str,
                      params: dict | None) -> list[SignalPoint | None]:
        path = self.root / "signals" / f"{signal_key(symbol, bars, strategy, direction, params)}.json"
        cached = _read(path)
        if isinstance(cached, list) and len(cached) == len(bars):
            try:
                expected = {f.name for f in fields(SignalPoint)}
                if any(p is not None and (not isinstance(p, dict) or set(p) != expected) for p in cached):
                    raise ValueError("incomplete cached signal")
                series = [None if p is None else SignalPoint(**p) for p in cached]
                if any(p is not None and (type(p.market) is not bool or
                       type(p.setup_age) is not int or p.setup_age < 0 or
                       type(p.entry) not in (int, float) or type(p.stop) not in (int, float) or
                       type(p.target) not in (int, float) or
                       not all(math.isfinite(v) for v in (p.entry, p.stop, p.target)) or
                       (p.rr_multiple is not None and (type(p.rr_multiple) not in (int, float) or not math.isfinite(p.rr_multiple))))
                       for p in series):
                    raise ValueError("invalid cached signal fields")
            except (TypeError, ValueError):
                pass  # old or malformed event shape: recompute, never downgrade to limit
            else:
                self.hits += 1
                return series
        self.misses += 1
        series = _signals.signal_series(bars, strategy, direction, params)
        _write_atomic(path, [None if p is None else asdict(p) for p in series])
        return series

    def gate_mask(self, symbol: str, bars: list[dict], direction: str, scoring_horizon: str, *,
                  min_price: float | None, max_price: float | None,
                  benchmark: list[dict] | None) -> list[bool]:
        key = gate_key(symbol, bars, direction, scoring_horizon,
                       min_price=min_price, max_price=max_price, benchmark=benchmark)
        path = self.root / "gates" / f"{key}.json"
        cached = _read(path)
        if isinstance(cached, str) and len(cached) == len(bars):
            self.hits += 1
            return [ch == "1" for ch in cached]
        self.misses += 1
        mask = _gates.gate_mask(bars, direction, scoring_horizon,
                                min_price=min_price, max_price=max_price, benchmark=benchmark)
        _write_atomic(path, "".join("1" if m else "0" for m in mask))
        return mask
