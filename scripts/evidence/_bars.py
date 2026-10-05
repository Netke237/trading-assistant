"""Shared, SELECT-only bar loader and report header for the evidence harness.

Bars come only from ``historical_store._read_bars`` through
``app.database.AsyncSessionLocal``: one ordered SELECT per symbol, fully adjusted OHLC
(T1), volume raw. Nothing here fetches from a provider or writes to the database; each
session is rolled back, never committed.

The database is whatever ``DATABASE_URL`` names (environment variable, or a ``.env``
file in the current directory). Run from the repo root with the backend venv
(Python 3.11).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

from app.data import confidence_cache  # noqa: E402

# T2 adds BARS_BASIS_VERSION; until it lands the header says the basis is unversioned.
BARS_BASIS_VERSION = getattr(confidence_cache, "BARS_BASIS_VERSION", "unversioned")


def _session_factory(session_factory=None):
    if session_factory is not None:
        return session_factory
    from app.database import AsyncSessionLocal, engine
    # DEBUG=true (the repo-root .env sets it) turns on SQL echo to stdout, which would
    # interleave with the markdown report this harness prints there.
    engine.echo = False
    return AsyncSessionLocal


async def load_bars(
    symbols: Iterable[str], start: date, end: date, *, session_factory=None,
) -> dict[str, list[dict]]:
    """Read each symbol's stored bars in ``[start, end]`` with ``_read_bars`` (SELECT only)."""
    from app.services.historical_store import _read_bars

    factory = _session_factory(session_factory)
    out: dict[str, list[dict]] = {}
    async with factory() as db:
        try:
            for symbol in symbols:
                out[symbol] = await _read_bars(symbol, start, end, db)
        finally:
            await db.rollback()
    return out


async def stored_symbols(*, session_factory=None) -> list[str]:
    """Every symbol in ``ohlcv_daily`` (SELECT DISTINCT), sorted."""
    from sqlalchemy import select
    from app.models.ohlcv_daily import OhlcvDailyModel

    factory = _session_factory(session_factory)
    async with factory() as db:
        try:
            result = await db.execute(select(OhlcvDailyModel.symbol).distinct())
            return sorted(r[0] for r in result.all())
        finally:
            await db.rollback()


async def load_basis_rows(
    symbols: Iterable[str], *, session_factory=None,
) -> dict[str, list[tuple]]:
    """Each symbol's full stored row set in the shape ``historical_store.stale_reasons``
    takes: ``(date, close, adj_factor, split_factor, div_cash, source, fetched_at)``,
    raw close, ordered by date. SELECT only."""
    from sqlalchemy import select
    from app.models.ohlcv_daily import OhlcvDailyModel as M

    factory = _session_factory(session_factory)
    out: dict[str, list[tuple]] = {}
    async with factory() as db:
        try:
            for symbol in symbols:
                result = await db.execute(
                    select(M.date, M.close, M.adj_factor, M.split_factor,
                           M.div_cash, M.source, M.fetched_at)
                    .where(M.symbol == symbol)
                    .order_by(M.date)
                )
                out[symbol] = [tuple(r) for r in result.all()]
        finally:
            await db.rollback()
    return out


def git_commit() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
            timeout=10, check=True,
        ).stdout.strip()
        return sha or "unknown"
    except Exception:
        return "unknown"


def loaded_range(bars_by_symbol: dict[str, list[dict]]) -> tuple[str, str] | None:
    """First and last bar date actually loaded across all symbols, or None."""
    times = [b["time"] for bars in bars_by_symbol.values() for b in bars]
    if not times:
        return None
    return min(times), max(times)


def report_header(
    title: str,
    *,
    symbols: Iterable[str],
    start: date | str,
    end: date | str,
    cost_model: str,
    loaded: tuple[str, str] | None = None,
    extra: dict[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    """Markdown header every harness report starts with."""
    symbols = list(symbols)
    now = now or datetime.now(timezone.utc)
    shown = ", ".join(symbols) if len(symbols) <= 30 else (
        ", ".join(symbols[:30]) + f", ... ({len(symbols) - 30} more)"
    )
    lines = [
        f"# {title}",
        "",
        f"- Git commit: `{git_commit()}`",
        f"- Generated (UTC): {now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- Symbols ({len(symbols)}): {shown or 'none'}",
        f"- Date range requested: {start} .. {end}",
        f"- Date range loaded: {f'{loaded[0]} .. {loaded[1]}' if loaded else 'no bars'}",
        f"- BARS_BASIS_VERSION: `{BARS_BASIS_VERSION}`",
        f"- Cost model: {cost_model}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def emit(report: str, out: str | None) -> None:
    """Print the report and, with ``--out``, also write it to that path."""
    print(report)
    if out:
        Path(out).write_text(report + "\n", encoding="utf-8")


def common_parser(description: str) -> argparse.ArgumentParser:
    """Arguments every harness script takes."""
    parser = argparse.ArgumentParser(
        description=description,
        epilog="Read-only: SELECTs stored bars from DATABASE_URL (env or ./.env); "
               "never fetches or writes.",
    )
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="symbols to read (default: every symbol in ohlcv_daily)")
    parser.add_argument("--start", type=date.fromisoformat, default=date(1990, 1, 1),
                        help="first bar date, YYYY-MM-DD (default 1990-01-01)")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today(),
                        help="last bar date, YYYY-MM-DD (default today)")
    parser.add_argument("--out", default=None, help="also write the markdown report here")
    return parser
