"""Targeted backfill of missing Alpaca OHLCV daily bars using Alpaca SIP (#560).

Connects to Postgres, identifies symbols missing target dates (2021-04-19, 2021-10-25, 2022-03-08),
queries Alpaca SIP bars, computes exact adjustment factor, pins fetched_at to surrounding
retained rows to satisfy batch_step staleness invariant, and atomically inserts rows per symbol.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Sequence

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as database
from app.data.alpaca import AlpacaClient, get_alpaca_client
from app.models.ohlcv_daily import OhlcvDailyModel as M

logger = logging.getLogger(__name__)

DEFAULT_TARGET_DATES = [
    date(2021, 4, 19),
    date(2021, 10, 25),
    date(2022, 3, 8),
]


def get_session_factory():
    """Return database async session factory."""
    if hasattr(database, "get_session_factory"):
        return database.get_session_factory()
    return database.AsyncSessionLocal


def get_engine():
    """Return database async engine."""
    if hasattr(database, "get_engine"):
        return database.get_engine()
    return database.engine


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Targeted backfill of missing Alpaca OHLCV daily bars using Alpaca SIP.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate backfill without writing to database.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional symbol list to backfill (e.g. --symbols AAPL,MSFT or --symbols AAPL MSFT).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of symbols with gaps to process.",
    )
    parser.add_argument(
        "--dates",
        type=str,
        default="2021-04-19,2021-10-25,2022-03-08",
        help="Comma-separated target dates (YYYY-MM-DD) to check for holes.",
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


def compute_adj_factor(raw_close: float, adj_close: float) -> float:
    """Compute exact adj_factor = round(adj_close / raw_close, 8)."""
    if raw_close == 0:
        return 1.0
    return round(float(adj_close) / float(raw_close), 8)


def validate_candidate_bar(bar: dict[str, Any]) -> bool:
    """Validate that candidate bar has valid positive OHLCV and high >= low."""
    try:
        o = float(bar.get("open", 0))
        h = float(bar.get("high", 0))
        l = float(bar.get("low", 0))
        c = float(bar.get("close", 0))
        v = float(bar.get("volume", 0))
    except (TypeError, ValueError):
        return False

    if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v <= 0:
        return False
    if h < l:
        return False
    return True


async def verify_alpaca_sip_access(client: AlpacaClient) -> bool:
    """Verify that client credentials are valid and entitled to query Alpaca SIP feed."""
    if client is None:
        return False
    if getattr(client, "feed", None) != "sip":
        return False
    try:
        probe_date = date(2022, 3, 8)
        bars = await client.fetch_raw(["SPY"], start=probe_date, end=probe_date, feed="sip")
        if getattr(client, "feed", None) != "sip":
            return False
        return bool(bars.get("SPY"))
    except Exception as exc:
        logger.error("Alpaca SIP entitlement verification failed: %s", exc)
        return False


async def find_target_date_gaps(
    session: AsyncSession,
    target_dates: Sequence[date],
    symbols: Sequence[str] | None = None,
    limit: int | None = None,
) -> dict[str, list[date]]:
    """Identify target dates that are missing within each symbol's stored date range."""
    stmt = select(M.symbol, M.date).order_by(M.symbol, M.date)
    target_symbols = _clean_symbols(symbols)
    if target_symbols:
        stmt = stmt.where(M.symbol.in_(target_symbols))

    result = await session.execute(stmt)
    rows = result.all()

    symbol_dates: dict[str, set[date]] = defaultdict(set)
    for sym, d in rows:
        symbol_dates[sym].add(d)

    gaps: dict[str, list[date]] = {}
    for sym in sorted(symbol_dates.keys()):
        dates = symbol_dates[sym]
        if not dates:
            continue
        min_d = min(dates)
        max_d = max(dates)

        missing_for_sym = [
            td for td in target_dates
            if min_d <= td <= max_d and td not in dates
        ]
        if missing_for_sym:
            gaps[sym] = missing_for_sym
            if limit is not None and len(gaps) >= limit:
                break

    return gaps


async def find_surrounding_retained_row(
    session: AsyncSession,
    symbol: str,
    target_date: date,
) -> M | None:
    """Find closest retained row for symbol before or after target_date."""
    # Preceding row
    stmt_prev = (
        select(M)
        .where(M.symbol == symbol, M.date < target_date)
        .order_by(M.date.desc())
        .limit(1)
    )
    prev_row = (await session.execute(stmt_prev)).scalars().first()
    if prev_row is not None:
        return prev_row

    # Following row
    stmt_next = (
        select(M)
        .where(M.symbol == symbol, M.date > target_date)
        .order_by(M.date.asc())
        .limit(1)
    )
    next_row = (await session.execute(stmt_next)).scalars().first()
    return next_row


async def backfill_symbol(
    session: AsyncSession,
    client: AlpacaClient,
    symbol: str,
    missing_dates: Sequence[date],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Safely backfill missing dates for a single symbol from Alpaca SIP bars."""
    inserted = 0
    would_insert = 0
    backfilled_dates: list[date] = []

    for target_date in sorted(missing_dates):
        # 1. Verify surrounding retained row
        surrounding = await find_surrounding_retained_row(session, symbol, target_date)
        if surrounding is None:
            logger.warning("No surrounding row found for %s near %s; skipping", symbol, target_date)
            continue

        # Strict single-source rule: refuse to splice Alpaca bars into foreign provider series
        if surrounding.source != "alpaca":
            logger.warning(
                "Strict single-source rule: %s surrounding row has source %s (not alpaca). Refusing to splice Alpaca bars.",
                symbol,
                surrounding.source,
            )
            return {
                "symbol": symbol,
                "skipped": True,
                "reason": "foreign_source",
                "inserted": 0,
                "would_insert": 0,
            }

        # 2. Query Alpaca SIP bars
        raw_dict = await client.fetch_raw([symbol], start=target_date, end=target_date, feed="sip")
        adj_dict = await client.fetch_adj([symbol], start=target_date, end=target_date, feed="sip")

        raw_bars = raw_dict.get(symbol, [])
        adj_bars = adj_dict.get(symbol, [])

        target_iso = target_date.isoformat()
        raw_bar = next((b for b in raw_bars if b.get("t", "")[:10] == target_iso), None)
        if not raw_bar:
            logger.warning("Alpaca returned no SIP bar for %s on %s", symbol, target_date)
            continue

        adj_bar = next((b for b in adj_bars if b.get("t", "")[:10] == target_iso), None)

        # 3. Validate candidate bar
        open_val = float(raw_bar.get("o", 0) or 0)
        high_val = float(raw_bar.get("h", 0) or 0)
        low_val = float(raw_bar.get("l", 0) or 0)
        close_val = float(raw_bar.get("c", 0) or 0)
        vol_val = int(raw_bar.get("v", 0) or 0)

        candidate = {
            "open": open_val,
            "high": high_val,
            "low": low_val,
            "close": close_val,
            "volume": vol_val,
        }
        if not validate_candidate_bar(candidate):
            logger.warning("Invalid candidate bar for %s on %s: %s", symbol, target_date, candidate)
            continue

        # 4. Compute adj_factor
        if not adj_bar:
            logger.warning("Alpaca returned no adjusted SIP bar for %s on %s; skipping", symbol, target_date)
            continue
        adj_c = adj_bar.get("c")
        if adj_c is None or float(adj_c) <= 0:
            logger.warning("Alpaca returned invalid adjusted close %s for %s on %s; skipping", adj_c, symbol, target_date)
            continue
        adj_close = float(adj_c)
        adj_factor = compute_adj_factor(close_val, adj_close)

        # 5. Build model with pinned fetched_at
        new_row = M(
            symbol=symbol,
            date=target_date,
            open=open_val,
            high=high_val,
            low=low_val,
            close=close_val,
            volume=vol_val,
            adj_factor=adj_factor,
            split_factor=1.0,
            div_cash=0.0,
            source="alpaca",
            fetched_at=surrounding.fetched_at,
        )

        if dry_run:
            would_insert += 1
        else:
            session.add(new_row)
            inserted += 1
        backfilled_dates.append(target_date)

    return {
        "symbol": symbol,
        "skipped": False,
        "inserted": inserted,
        "would_insert": would_insert,
        "dates": backfilled_dates,
    }


async def run_backfill(
    session_factory: Any,
    client: AlpacaClient,
    symbols: Sequence[str] | None = None,
    target_dates: Sequence[date] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute backfill across universe or target symbols."""
    dates_to_check = target_dates if target_dates is not None else DEFAULT_TARGET_DATES

    async with session_factory() as session:
        target_gaps = await find_target_date_gaps(
            session=session,
            target_dates=dates_to_check,
            symbols=symbols,
            limit=limit,
        )

    symbols_backfilled = 0
    symbols_skipped = 0
    total_inserted = 0
    total_would_insert = 0

    for sym, missing in target_gaps.items():
        async with session_factory() as session:
            try:
                res = await backfill_symbol(
                    session=session,
                    client=client,
                    symbol=sym,
                    missing_dates=missing,
                    dry_run=dry_run,
                )
                if res.get("skipped"):
                    symbols_skipped += 1
                else:
                    if not dry_run:
                        await session.commit()
                        total_inserted += res.get("inserted", 0)
                        if res.get("inserted", 0) > 0:
                            symbols_backfilled += 1
                    else:
                        total_would_insert += res.get("would_insert", 0)
                        if res.get("would_insert", 0) > 0:
                            symbols_backfilled += 1
            except Exception as exc:
                await session.rollback()
                logger.error("Error backfilling %s: %s", sym, exc)
                symbols_skipped += 1

    return {
        "total_symbols_scanned": len(symbols) if symbols else len(target_gaps),
        "symbols_with_gaps": len(target_gaps),
        "symbols_backfilled": symbols_backfilled,
        "symbols_skipped": symbols_skipped,
        "total_rows_inserted": total_inserted,
        "total_rows_would_insert": total_would_insert,
        "dry_run": dry_run,
    }


async def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    symbols = _clean_symbols(args.symbols)
    target_dates = [date.fromisoformat(d.strip()) for d in args.dates.split(",") if d.strip()]

    print("=" * 78)
    print("Alpaca SIP Holes Backfill")
    print("=" * 78)
    print(f"Target dates:   {[d.isoformat() for d in target_dates]}")
    print(f"Dry run mode:   {args.dry_run}")
    if symbols:
        print(f"Target symbols: {len(symbols)} symbol(s) specified")
    if args.limit:
        print(f"Symbol limit:   {args.limit}")

    client = await get_alpaca_client(feed="sip")
    if client is None:
        print("ERROR: No Alpaca credentials configured in credential store.")
        return 1

    print("Validating Alpaca SIP entitlement...")
    sip_ok = await verify_alpaca_sip_access(client)
    if not sip_ok:
        print("ERROR: Alpaca SIP verification failed (HTTP 403 or non-SIP subscription).")
        print("Refusing to proceed with backfill.")
        return 1
    print("Alpaca SIP entitlement verified successfully.")

    session_factory = get_session_factory()
    stats = await run_backfill(
        session_factory=session_factory,
        client=client,
        symbols=symbols,
        target_dates=target_dates,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    print("-" * 78)
    print("Backfill Summary Statistics:")
    print(f"Symbols with gaps:     {stats['symbols_with_gaps']}")
    print(f"Symbols backfilled:    {stats['symbols_backfilled']}")
    print(f"Symbols skipped:       {stats['symbols_skipped']}")
    if args.dry_run:
        print(f"Rows would insert:     {stats['total_rows_would_insert']} (dry run — no writes)")
    else:
        print(f"Rows inserted:         {stats['total_rows_inserted']}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(main()))
