"""Export a fixed, read-only snapshot of adjusted bars for resumable research.

Run from the repository root with --out NEW_DIRECTORY --end YYYY-MM-DD.
No ingestion, healing, provider fetching or strategy evaluation is performed.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A cold confidence_cache import creates its DB and purges expired rows. This
# standalone reader needs only its basis constant: isolate that import from the
# application's persisted cache. Already-loaded application cache state is left
# untouched. Restore the caller's environment even when an import fails.
_cache_env = "BAMENDJOU_CONFIDENCE_CACHE_DB"
_old_cache_env = os.environ.get(_cache_env)
_cold_cache = "app.data.confidence_cache" not in sys.modules
with tempfile.TemporaryDirectory(prefix="tuning-export-import-") as _import_tmp:
    try:
        if _cold_cache:
            os.environ[_cache_env] = str(Path(_import_tmp) / "confidence.db")
        from scripts.tune_horizons import HISTORY_START, REPO, _git_commit, select_cells
        from app.data.confidence_cache import BARS_BASIS_VERSION
        from app.services.horizon_tuning import basket, gates
        from app.services.horizon_tuning.cache import _gate_sources, ohlcv_hash, signal_sources
    finally:
        if _cold_cache:
            if _old_cache_env is None:
                os.environ.pop(_cache_env, None)
            else:
                os.environ[_cache_env] = _old_cache_env

PROBES = ("AAPL", "MSFT", "NVDA")


def _symbols(names: list[str]) -> list[str]:
    out = []
    for name in names:
        # A single portable filename component, including Windows reserved names.
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,9}", name)
                or name.endswith(".") or ".." in name
                or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                                                    *[f"COM{i}" for i in range(10)],
                                                    *[f"LPT{i}" for i in range(10)]}):
            raise ValueError(f"unsafe symbol {name!r}")
        name = name.upper()
        if name not in out:
            out.append(name)
    return out


def benchmark_mappings(cells) -> dict:
    from app.routers.stock_scan import _RS_BENCHMARK_PROXY
    from app.scoring.stock_scorer import resolve_rs_benchmark
    out = {}
    for h in sorted({gates.scoring_horizon_for(c.horizon) for c in cells}):
        name = resolve_rs_benchmark(h, None)
        out[h] = {"name": name, "proxy": _RS_BENCHMARK_PROXY.get(name.upper()) if name else None}
    return out


async def _begin_snapshot(conn, dialect: str) -> None:
    if dialect == "postgresql":
        await conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    elif dialect == "sqlite":
        # SQLAlchemy's logical transaction alone does not BEGIN a sqlite read snapshot.
        await conn.exec_driver_sql("BEGIN")
    else:
        raise ValueError(f"unsupported snapshot dialect: {dialect}")


async def _snapshot(engine, names, start, end):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.ohlcv_daily import OhlcvDailyModel as Row
    from app.services.historical_store import _read_bars
    out, sources = {}, {}
    async with engine.connect() as conn:
        try:
            await _begin_snapshot(conn, conn.dialect.name)
            async with AsyncSession(bind=conn, autoflush=False) as db:
                for symbol in names:
                    bars = await _read_bars(symbol, start, end, db)
                    if bars:
                        out[symbol] = bars
                        rows = (await db.execute(select(Row.source, Row.adj_factor, Row.fetched_at)
                                .where(Row.symbol == symbol, Row.date >= start, Row.date <= end))).all()
                        fetched = sorted(r.fetched_at.isoformat() for r in rows if r.fetched_at is not None)
                        sources[symbol] = {
                            "providers": sorted({r.source for r in rows if r.source is not None}),
                            "null_adjustment_factors": sum(r.adj_factor is None for r in rows),
                            "unknown_fetched_at": sum(r.fetched_at is None for r in rows),
                            "fetched_at_min": fetched[0] if fetched else None,
                            "fetched_at_max": fetched[-1] if fetched else None,
                        }
        finally:
            await conn.rollback()
    return out, sources


def _provenance() -> dict:
    # Only an explicit allowlist of non-secret research inputs; never the DB URL.
    paths = ["backend/scripts/export_tuning_bars.py", "backend/scripts/tune_horizons.py",
             "backend/app/services/historical_store.py", "backend/app/models/ohlcv_daily.py",
             "backend/app/services/horizon_tuning/basket.py", "backend/app/data/sector_map.py",
             "backend/app/data/sector_names.py", "backend/app/data/universe_presets.py",
             "backend/app/data/universe_exclusions.py", "backend/app/data/sp500.csv",
             "backend/app/data/sector_overrides.csv", "backend/config/universe_exclusions.yaml",
             "backend/config/strategy_params.yaml", "backend/config/scoring_rules.yaml"]
    hashes = {p: hashlib.sha256((REPO / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
              for p in paths if (REPO / p).is_file()}
    return {"git_commit": _git_commit(), "python": sys.version.split()[0],
            "bars_basis": BARS_BASIS_VERSION,
            "price_basis": "historical_store._read_bars: fully adjusted OHLC, raw volume; NULL factors unchanged",
            "source_hashes": hashes, "signal_sources": signal_sources(), "gate_sources": _gate_sources()}


def _write_json(path: Path, value) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return payload


def _publish(stage: Path, out: Path) -> None:
    if os.name == "nt":
        os.rename(stage, out)  # Windows refuses an existing destination, including empty dirs.
    elif sys.platform.startswith("linux"):
        # POSIX rename would replace an existing empty dir. Enforce NOREPLACE atomically.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(stage), -100, os.fsencode(out), 1):
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), str(out))
    else:
        raise ValueError("atomic non-overwriting directory publication unsupported on this platform")


async def export_bars(*, out: Path, end: date, start: date = HISTORY_START,
                      symbols: list[str] | None = None, cells=None, engine=None) -> dict:
    if start > end:
        raise ValueError("start must not follow end")
    out = Path(out).absolute()
    if out.name in ("", ".", "..") or os.path.lexists(out):
        raise FileExistsError(f"destination must be new: {out}")
    if not out.parent.is_dir():
        raise ValueError("destination parent must exist")
    union = _symbols(symbols if symbols is not None else basket.universe_union())
    trade = basket.trade_universe(union)
    fire = basket.fire_rate_universe(union)
    cells = cells if cells is not None else select_cells(None, None)
    benchmarks = benchmark_mappings(cells)
    proxies = _symbols([v["proxy"] for v in benchmarks.values() if v["proxy"]])
    requested = sorted(set(trade) | set(fire) | set(PROBES) | set(proxies))
    if engine is None:
        from app.database import engine
    bars, sources = await _snapshot(engine, requested, start, end)
    if not any(s in bars for s in trade):
        raise ValueError("no trade-universe symbol has stored bars")
    provenance = _provenance()
    manifest = {"schema": 1, "bounds": {"start": start.isoformat(), "end": end.isoformat(), "end_inclusive": True},
                "cells": [asdict(c) for c in cells],
                "universes": {"selected": union, "trade": trade, "fire": fire},
                "probes": list(PROBES), "benchmarks": benchmarks,
                "requested": requested, "available": sorted(bars),
                "missing": sorted(set(requested) - set(bars)), "files": {}, "provenance": provenance}
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent)).resolve()
    parent = out.parent.resolve()
    try:
        for symbol, series in sorted(bars.items()):
            name = f"{symbol}_candles.json"
            payload = _write_json(stage / name, series)
            manifest["files"][symbol] = {"file": name, "sha256": hashlib.sha256(payload).hexdigest(),
                "ohlcv_hash": ohlcv_hash(series), "count": len(series),
                "first": series[0]["time"], "last": series[-1]["time"], **sources[symbol]}
        _write_json(stage / "manifest.json", manifest)
        _publish(stage, out)
    finally:
        # Delete only our newly created sibling, never a computed output/user directory.
        if stage.exists():
            if stage.parent != parent or not stage.name.startswith(f".{out.name}.") or stage.is_symlink():
                raise RuntimeError("unsafe staging cleanup path")
            shutil.rmtree(stage)
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--end", type=date.fromisoformat, required=True)
    ap.add_argument("--start", type=date.fromisoformat, default=HISTORY_START)
    ap.add_argument("--symbols", help="fixed comma-separated universe restriction")
    ap.add_argument("--cells", default=None, help="same strategy/horizon filters as tune_horizons")
    ap.add_argument("--directions", default="Bullish,Bearish")
    args = ap.parse_args(argv)
    manifest = asyncio.run(export_bars(out=args.out, start=args.start, end=args.end,
        symbols=[s.strip() for s in args.symbols.split(",")] if args.symbols is not None else None,
        cells=select_cells(args.cells, args.directions)))
    print(f"exported {len(manifest['available'])} symbols to {args.out}; missing: {', '.join(manifest['missing']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
