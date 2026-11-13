"""CLI gap detector tool for inspecting ohlcv_daily for missing trading days (#559).

Queries ohlcv_daily for stored trading dates, compares against canonical NYSE
trading days via app.services.history_gap_detector.detect_history_gaps, and
reports missing bars.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Sequence

# Ensure backend directory is in sys.path for standalone script execution
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.ohlcv_daily import OhlcvDailyModel as M
from app.services.history_gap_detector import detect_history_gaps


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for the history gap detector CLI."""
    parser = argparse.ArgumentParser(
        description="Inspect ohlcv_daily for missing canonical NYSE trading days.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional list of symbols to inspect (e.g. --symbols AAPL,MSFT or --symbols AAPL MSFT). "
        "Defaults to all symbols in DB if omitted.",
    )
    parser.add_argument(
        "--start",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Clamp evaluation window start (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Clamp evaluation window end (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default=None,
        help="Path to output structured JSON gap report.",
    )
    parser.add_argument(
        "--no-exit-code",
        action="store_true",
        default=False,
        help="Exit with 0 even if gaps are found (default exits 1 on gaps).",
    )
    return parser


def _clean_symbols(symbols_arg: Sequence[str] | None) -> list[str] | None:
    if symbols_arg is None:
        return None
    cleaned: list[str] = []
    for item in symbols_arg:
        for s in item.split(","):
            s = s.strip().upper()
            if s:
                cleaned.append(s)
    return cleaned if cleaned else None


async def detect_database_gaps(
    session: AsyncSession,
    symbols: Sequence[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Inspect ohlcv_daily in the given database session and return a gap report."""
    target_symbols = _clean_symbols(symbols)

    symbol_dates: dict[str, set[date]] = defaultdict(set)
    if target_symbols is None:
        stmt = select(M.symbol, M.date).order_by(M.symbol, M.date)
        result = await session.execute(stmt)
        rows = result.all()
        for sym, d in rows:
            symbol_dates[sym].add(d)
        target_symbols = sorted(symbol_dates.keys())
    else:
        if not target_symbols:
            return {
                "total_symbols_scanned": 0,
                "symbols_with_gaps": 0,
                "total_missing_bars": 0,
                "gaps_by_date": {},
                "symbol_gaps": {},
            }
        stmt = (
            select(M.symbol, M.date)
            .where(M.symbol.in_(target_symbols))
            .order_by(M.symbol, M.date)
        )
        result = await session.execute(stmt)
        rows = result.all()
        for sym in target_symbols:
            symbol_dates[sym] = set()
        for sym, d in rows:
            if sym in symbol_dates:
                symbol_dates[sym].add(d)

    symbol_gaps: dict[str, list[str]] = {}
    gaps_by_date: dict[str, int] = defaultdict(int)

    for sym in target_symbols:
        stored = symbol_dates.get(sym, set())
        if not stored:
            continue
        sym_min = min(stored)
        sym_max = max(stored)
        eval_start = max(sym_min, start) if start is not None else sym_min
        eval_end = min(sym_max, end) if end is not None else sym_max

        if eval_start > eval_end:
            continue

        missing = detect_history_gaps(sym, stored, start=eval_start, end=eval_end)
        if missing:
            iso_dates = [d.isoformat() for d in missing]
            symbol_gaps[sym] = iso_dates
            for iso_d in iso_dates:
                gaps_by_date[iso_d] += 1

    total_missing_bars = sum(len(v) for v in symbol_gaps.values())
    sorted_gaps_by_date = dict(sorted(gaps_by_date.items()))

    return {
        "total_symbols_scanned": len(target_symbols),
        "symbols_with_gaps": len(symbol_gaps),
        "total_missing_bars": total_missing_bars,
        "gaps_by_date": sorted_gaps_by_date,
        "symbol_gaps": symbol_gaps,
    }


def format_summary_table(report: dict[str, Any]) -> str:
    """Format gap report into a human-readable text table."""
    lines: list[str] = [
        "=" * 78,
        "OHLCV History Gap Detection Report",
        "=" * 78,
        f"Total symbols scanned: {report['total_symbols_scanned']}",
        f"Symbols with gaps:     {report['symbols_with_gaps']}",
        f"Total missing bars:    {report['total_missing_bars']}",
    ]

    if report["total_missing_bars"] == 0:
        lines.append("-" * 78)
        lines.append("Status: CLEAN (No missing NYSE trading days detected)")
        lines.append("=" * 78)
        return "\n".join(lines)

    lines.append("-" * 78)
    lines.append("Top Missing Dates:")
    lines.append(f"{'Date':<14} {'Missing Symbols':<16}")
    sorted_dates = sorted(
        report["gaps_by_date"].items(),
        key=lambda item: (-item[1], item[0]),
    )
    for d_str, count in sorted_dates[:15]:
        lines.append(f"{d_str:<14} {count:<16}")
    if len(sorted_dates) > 15:
        lines.append(f"... and {len(sorted_dates) - 15} more date(s)")

    lines.append("-" * 78)
    lines.append("Sample Symbols With Gaps:")
    lines.append(f"{'Symbol':<10} {'Missing Bars':<14} {'Sample Dates'}")
    for sym, missing_dates in list(report["symbol_gaps"].items())[:20]:
        sample = ", ".join(missing_dates[:3])
        if len(missing_dates) > 3:
            sample += f" (+{len(missing_dates) - 3} more)"
        lines.append(f"{sym:<10} {len(missing_dates):<14} {sample}")
    if len(report["symbol_gaps"]) > 20:
        lines.append(f"... and {len(report['symbol_gaps']) - 20} more symbol(s)")

    lines.append("=" * 78)
    return "\n".join(lines)


async def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI execution routine."""
    parser = build_parser()
    args = parser.parse_args(argv)

    symbols = _clean_symbols(args.symbols)

    async with AsyncSessionLocal() as session:
        report = await detect_database_gaps(
            session=session,
            symbols=symbols,
            start=args.start,
            end=args.end,
        )

    table = format_summary_table(report)
    print(table)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote JSON report to: {out_path.resolve()}")

    if report["total_missing_bars"] > 0 and not args.no_exit_code:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
