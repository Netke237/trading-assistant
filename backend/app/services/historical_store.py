"""Persistent OHLCV daily history store backed by the application database.

Design:
- get_bars(symbol, start, end)      : DB-first lookup; fetches the delta via Alpaca → Tiingo → yfinance.
- prefetch_universe(symbols, years) : Rate-limited background job that pre-fills the table.
- get_prefetch_status()             : Returns the current prefetch job state.

Bars are written with an upsert (INSERT OR REPLACE for SQLite) so re-running the prefetch
is always safe and idempotent.

Only SETTLED daily rows are ever stored (WATCH-RULE-BAR-PARITY plan 2.10, decisions
PARTIAL-ROW / Q-F): a row for day ``d`` is written only once ``now >= 16:00 ET on d + 2 h`` (18:00 ET).
During session D, Alpaca and Tiingo may return D's forming bar; before this rule it was
upserted and, because ``get_bars``' staleness test never looks at D again from D+1, stayed in
the store for good. Rows written before the rule (``fetched_at`` earlier than their own
settle instant, "provisional") are re-fetched once they have settled ("heal").
``get_bars``' fetch rule itself is unchanged (Q-H): a stale symbol first read before D's
settle stores through D-1 and D arrives with the nightly ingestion or the first call on D+1.
"""
from __future__ import annotations

import asyncio
import logging
import os as _os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _dialect_insert():
    """Return the correct dialect-specific insert for the current DATABASE_URL."""
    url = _os.environ.get("DATABASE_URL", "sqlite")
    if "postgresql" in url:
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert

from app.database import AsyncSessionLocal
# scheduling_tz, not market_session: market_session imports strategy_watch_scheduler, which
# would make an import cycle with this module (plan 2.10, round 3).
from app.services.scheduling_tz import MARKET_TZ
from app.data.tiingo import fetch_historical_candles
from app.models.ohlcv_daily import OhlcvDailyModel, OhlcvHistoryStateModel
from app.services.history_basis import verified_boundary
from app.scoring.signal_confidence import compute_confidence
from app.data.confidence_cache import (
    cache_key as conf_cache_key, generation as conf_generation, get_cached,
    invalidate_symbol, set_cached,
)

logger = logging.getLogger(__name__)

# ── Prefetch progress state (module-level singleton) ─────────────────────────

_prefetch_state: dict[str, Any] = {
    "status":         "idle",   # idle | running | completed | error
    "total":          0,
    "done":           0,
    "failed":         0,
    "current_symbol": None,
    "elapsed_secs":   0,
    "started_at":     None,
}
_prefetch_task: asyncio.Task | None = None

# ── Clock + settle rule (plan 2.10) ─────────────────────────────────────────

# A daily row is stored only this long after its session's 16:00 ET close: 18:00 ET, late
# enough for Tiingo's end-of-day bar (published ~17:30 ET) when Alpaca is missing or fails
# (decision SETTLE-2H-2026-09-29; was 30 min). Half-days (13:00 close) settle at 18:00 too.
_SETTLE = timedelta(hours=2)
_SESSION_CLOSE = dtime(16, 0)

# One heal attempt per (symbol, provisional date) per this interval, so a halted,
# delisted or provider-missing day costs four attempts a day, not one per call.
_HEAL_RETRY = timedelta(hours=6)
_heal_next_attempt: dict[tuple[str, date], datetime] = {}


def _utcnow() -> datetime:
    """The one clock of this module (tests patch this alone)."""
    return datetime.now(timezone.utc)


def _host_today() -> date:
    """The host's calendar date, exactly what ``date.today()`` gave, read from ``_utcnow``."""
    return _utcnow().astimezone().date()


def _session_close(d: date) -> datetime:
    return datetime.combine(d, _SESSION_CLOSE, tzinfo=MARKET_TZ)


def is_settled(d: date, now: datetime) -> bool:
    """True once day ``d``'s daily bar is final: ``now >= 16:00 ET on d + _SETTLE``."""
    return now >= _session_close(d) + _SETTLE


def last_settle_boundary(now: datetime | None = None) -> datetime:
    """The latest ``close(d) + _SETTLE <= now`` over weekdays ``d`` (``now``
    defaults to ``_utcnow()``). A daily row can enter the store only at such a
    boundary, so a cache of get_bars rows keyed by it changes exactly when a
    new row can exist (WATCH-RULE-BAR-PARITY 2.3). No holiday calendar: a
    holiday's boundary simply adds no row."""
    now = _utcnow() if now is None else now
    d = now.astimezone(MARKET_TZ).date()
    while d.weekday() >= 5 or not is_settled(d, now):
        d -= timedelta(days=1)
    return _session_close(d) + _SETTLE


def _as_utc(dt: datetime) -> datetime:
    """Normalise a stored ``fetched_at``: SQLite hands back the UTC wall clock naive,
    PostgreSQL an aware value."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_provisional(d: date, fetched_at: datetime) -> bool:
    """A row fetched before its own settle instant may hold a forming bar."""
    return _as_utc(fetched_at) < _session_close(d) + _SETTLE


# ── Trading-day helpers ───────────────────────────────────────────────────────

def most_recent_trading_day() -> date:
    """Return the most recent US market close date (Mon–Fri, no holiday check).

    On weekends returns the preceding Friday. During live market hours today
    is returned (data may still be updating).
    """
    today = _host_today()
    weekday = today.weekday()   # 0=Mon … 6=Sun
    if weekday == 5:             # Saturday → Friday
        return today - timedelta(days=1)
    if weekday == 6:             # Sunday → Friday
        return today - timedelta(days=2)
    return today


def _prev_trading_day() -> date:
    """Return the last fully completed trading day (one session before today)."""
    d = most_recent_trading_day() - timedelta(days=1)
    while d.weekday() >= 5:  # skip Saturday (5) and Sunday (6)
        d -= timedelta(days=1)
    return d


# ── Internal helpers ──────────────────────────────────────────────────────────

def _bar_date(bar: dict) -> date:
    return date.fromisoformat(bar["time"][:10])


async def _store_bars(symbol: str, bars: list[dict], db: AsyncSession) -> set[date]:
    """Upsert a list of OHLCV bar dicts for `symbol` into the DB; return the dates stored.

    Bars may include multi-basis fields (adj_factor, split_factor, div_cash, source);
    if absent they default to None so legacy rows keep their tiingo_legacy backfill.

    Every bar whose day has not settled (``is_settled``) is dropped first, so no writer
    (``get_bars``, ``ingestion_job``) can store a forming daily bar.
    """
    if not bars:
        return set()
    now = _utcnow()
    settled = [b for b in bars if is_settled(_bar_date(b), now)]
    if len(settled) != len(bars):
        logger.debug(
            "historical_store: %s — dropped %d unsettled bar(s) before storing",
            symbol, len(bars) - len(settled),
        )
    bars = settled
    if not bars:
        return set()
    rows = [
        {
            "symbol":       symbol,
            "date":         _bar_date(b),
            "open":         b["open"],
            "high":         b["high"],
            "low":          b["low"],
            "close":        b["close"],
            "volume":       b["volume"],
            "adj_factor":   b.get("adj_factor"),
            "split_factor": b.get("split_factor"),
            "div_cash":     b.get("div_cash"),
            "source":       b.get("source"),
            "fetched_at":   now,
        }
        for b in bars
    ]
    insert = _dialect_insert()
    # Twelve binds per row: keep each statement below asyncpg's 32,767 limit.
    # No commits here: both provider segments and every chunk share the caller's transaction.
    for offset in range(0, len(rows), 500):
        stmt = insert(OhlcvDailyModel).values(rows[offset:offset + 500])
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "open":         stmt.excluded.open,
                "high":         stmt.excluded.high,
                "low":          stmt.excluded.low,
                "close":        stmt.excluded.close,
                "volume":       stmt.excluded.volume,
                "adj_factor":   stmt.excluded.adj_factor,
                "split_factor": stmt.excluded.split_factor,
                "div_cash":     stmt.excluded.div_cash,
                "source":       stmt.excluded.source,
                "fetched_at":   stmt.excluded.fetched_at,
            },
        )
        await db.execute(stmt)
    return {r["date"] for r in rows}


async def _read_bars(
    symbol: str, start: date, end: date, db: AsyncSession
) -> list[dict]:
    """Read all stored bars for `symbol` between `start` and `end` (inclusive).

    Returns fully adjusted OHLC (each raw price × adj_factor; volume raw).
    If adj_factor is NULL (legacy tiingo_legacy rows), all four prices are returned as-is.
    """
    result = await db.execute(
        select(OhlcvDailyModel)
        .where(
            OhlcvDailyModel.symbol == symbol,
            OhlcvDailyModel.date >= start,
            OhlcvDailyModel.date <= end,
        )
        .order_by(OhlcvDailyModel.date)
    )
    rows = result.scalars().all()
    out = []
    for row in rows:
        adj = float(row.adj_factor) if row.adj_factor is not None else None

        def _px(raw) -> float:
            x = float(raw)
            return round(x * adj, 6) if adj is not None else x

        out.append({
            "time":   row.date.isoformat(),
            "open":   _px(row.open),
            "high":   _px(row.high),
            "low":    _px(row.low),
            "close":  _px(row.close),
            "volume": int(row.volume),
        })
    return out


async def _last_stored_date(symbol: str, db: AsyncSession) -> date | None:
    """Return the most recent date stored for `symbol`, or None if no data."""
    result = await db.execute(
        select(func.max(OhlcvDailyModel.date))
        .where(OhlcvDailyModel.symbol == symbol)
    )
    return result.scalar_one_or_none()


async def _heal_date(
    symbol: str, start: date, end: date, now: datetime, db: AsyncSession
) -> date | None:
    """Earliest provisional (legacy) row in ``[start, end]`` that has now settled, or None."""
    result = await db.execute(
        select(OhlcvDailyModel.date, OhlcvDailyModel.fetched_at)
        .where(
            OhlcvDailyModel.symbol == symbol,
            OhlcvDailyModel.date >= start,
            OhlcvDailyModel.date <= end,
        )
    )
    candidates = [
        d for d, fetched_at in result.all()
        if fetched_at is not None and _is_provisional(d, fetched_at) and is_settled(d, now)
    ]
    return min(candidates) if candidates else None


def _claim_heal_attempt(symbol: str, heal: date, now: datetime) -> bool:
    """True (and records the attempt) unless this pair was attempted within _HEAL_RETRY."""
    key = (symbol, heal)
    nxt = _heal_next_attempt.get(key)
    if nxt is not None and now < nxt:
        return False
    if len(_heal_next_attempt) > 4096:
        for k in [k for k, v in _heal_next_attempt.items() if v <= now]:
            del _heal_next_attempt[k]
    _heal_next_attempt[key] = now + _HEAL_RETRY
    return True


def _yfinance_fetch(symbol: str, start: date, end: date) -> list[dict]:
    """yfinance daily bars — last-resort fallback. Returns adj prices (adj_factor=1.0)."""
    try:
        import io
        import contextlib
        import yfinance as yf
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            df = yf.download(
                symbol,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=True,
            )
        if df is None or df.empty:
            return []
        import pandas as pd
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        rows = []
        for ts, row in df.iterrows():
            rows.append({
                "time":         ts.strftime("%Y-%m-%d"),
                "open":         round(float(row["Open"]),  4),
                "high":         round(float(row["High"]),  4),
                "low":          round(float(row["Low"]),   4),
                "close":        round(float(row["Close"]), 4),
                "volume":       int(row["Volume"]),
                "adj_factor":   1.0,
                "split_factor": 1.0,
                "div_cash":     0.0,
                "source":       "yfinance",
            })
        return rows
    except Exception as exc:
        logger.debug("_yfinance_fetch: failed for %s — %s", symbol, exc)
        return []


async def _fetch_chain(
    symbol: str,
    start: date,
    end: date,
    accept: Callable[[str, list[dict]], Awaitable[bool]] | None = None,
    providers: tuple[str, ...] = ("alpaca", "tiingo", "yfinance"),
) -> list[dict] | None:
    """Provider chain Alpaca → Tiingo → yfinance; the first accepted result wins.

    ``accept(name, bars)`` decides success (and may store); by default any non-empty
    list is accepted. A provider error, including one raised by ``accept``, is logged
    and the next provider is tried. Only ``providers`` are tried, always in that fixed
    order. Returns the accepted bars, or None.
    """
    async def _ok(name: str, bars: list[dict]) -> bool:
        return await accept(name, bars) if accept is not None else bool(bars)

    # 1. Alpaca (primary)
    if "alpaca" in providers:
        try:
            from app.data.alpaca import fetch_daily_bars_single, get_alpaca_client
            alpaca_client = await get_alpaca_client()
            if alpaca_client is not None:
                new_bars = await fetch_daily_bars_single(
                    symbol, start, end, client=alpaca_client
                )
                if await _ok("Alpaca", new_bars):
                    return new_bars
        except Exception as exc:
            logger.warning("historical_store: Alpaca fetch failed for %s — %s", symbol, exc)

    # 2. Tiingo fallback
    if "tiingo" in providers:
        try:
            new_bars = await fetch_historical_candles(symbol, start, end)
            if await _ok("Tiingo", new_bars):
                return new_bars
        except Exception as exc:
            logger.warning("historical_store: Tiingo fetch failed for %s — %s", symbol, exc)

    # 3. yfinance last resort
    if "yfinance" in providers:
        try:
            new_bars = await asyncio.to_thread(_yfinance_fetch, symbol, start, end)
            if await _ok("yfinance", new_bars):
                return new_bars
        except Exception as exc:
            logger.warning(
                "historical_store: yfinance fetch failed for %s — %s", symbol, exc
            )
    return None


# ── Stale adjustment factors (TRADING-REVIEW-PHASE-C T3) ─────────────────────
#
# ``adj_factor`` is the provider's adjClose/close AS OF THE FETCH DATE, so rows stored in
# earlier fetch batches keep the factor they had then. No single signature catches every
# stale series, so a symbol is flagged if any rule holds:
#   jump              adjusted close moves > _JUMP_THRESHOLD close-to-close (missed split,
#                     or a real crash — re-fetching a real crash is harmless)
#   pre_action_fetch  a row was fetched (ET date) before a later row's dividend/split date
#   batch_step        consecutive rows from different fetch dates differ in factor
#   mixed_basis       NULL-factor rows next to factored rows, or more than one source
# Residual (not detectable): a dividend-only staleness on a yfinance-only or Alpaca-sourced
# series between nightly refreshes; its effect is about one dividend.

_JUMP_THRESHOLD = 0.40
_FACTOR_STEP_TOL = 1e-4


@dataclass(frozen=True)
class StaleReport:
    reasons: list[str]   # subset of jump, pre_action_fetch, batch_step, mixed_basis
    earliest: date       # earliest stored date that may be on a stale basis


def _f(x) -> float | None:
    return float(x) if x is not None else None


def _fetch_date(fetched_at: datetime) -> date:
    """The market (ET) date of a stored ``fetched_at``."""
    return _as_utc(fetched_at).astimezone(MARKET_TZ).date()


def stale_reasons(rows, verified_seam: dict | None = None) -> StaleReport | None:
    """Pure stale-basis rules over one symbol's stored rows, ordered by date.

    Each row is ``(date, close, adj_factor, split_factor, div_cash, source, fetched_at)``
    with raw ``close``. A verified seam exempts only its exact source partition
    and that boundary's batch step. Returns None when no rule holds.
    """
    rows = list(rows)
    if not rows:
        return None
    boundary = verified_boundary(rows, verified_seam)
    first = rows[0][0]
    flagged: dict[str, date] = {}

    def _flag(reason: str, d: date) -> None:
        if reason not in flagged or d < flagged[reason]:
            flagged[reason] = d

    # (b) the latest dividend/split date; any earlier row fetched before it is stale.
    action_dates = [
        r[0] for r in rows
        if (r[4] is not None and float(r[4]) != 0.0)
        or (r[3] is not None and float(r[3]) != 1.0)
    ]
    if action_dates:
        last_action = max(action_dates)
        for r in rows:
            if r[0] < last_action and r[6] is not None and _fetch_date(r[6]) < last_action:
                _flag("pre_action_fetch", r[0])
                break  # rows are date-ordered: the first hit is the earliest

    # (d) more than one source.
    if boundary is None and len({r[5] for r in rows if r[5] is not None}) > 1:
        _flag("mixed_basis", first)

    for index, (prev, nxt) in enumerate(zip(rows, rows[1:]), start=1):
        p_adj, n_adj = _f(prev[2]), _f(nxt[2])
        # (a) unexplained jump in the adjusted close.
        p_close = float(prev[1]) * (p_adj if p_adj is not None else 1.0)
        n_close = float(nxt[1]) * (n_adj if n_adj is not None else 1.0)
        if p_close > 0 and abs(n_close / p_close - 1.0) > _JUMP_THRESHOLD:
            _flag("jump", first)
        # (d) NULL-factor row next to a factored row.
        if (p_adj is None) != (n_adj is None):
            _flag("mixed_basis", first)
        # (c) factor step at a fetch-batch boundary.
        if (
            index != boundary
            and p_adj is not None and n_adj is not None and p_adj != 0
            and prev[6] is not None and nxt[6] is not None
            and _fetch_date(prev[6]) != _fetch_date(nxt[6])
            and abs(n_adj / p_adj - 1.0) > _FACTOR_STEP_TOL
        ):
            _flag("batch_step", first)

    if not flagged:
        return None
    order = ("jump", "pre_action_fetch", "batch_step", "mixed_basis")
    return StaleReport(
        reasons=[r for r in order if r in flagged],
        earliest=min(flagged.values()),
    )


async def find_stale_adjustment(symbol: str, db: AsyncSession) -> StaleReport | None:
    """Apply ``stale_reasons`` to every stored row of ``symbol``."""
    result = await db.execute(
        select(
            OhlcvDailyModel.date,
            OhlcvDailyModel.close,
            OhlcvDailyModel.adj_factor,
            OhlcvDailyModel.split_factor,
            OhlcvDailyModel.div_cash,
            OhlcvDailyModel.source,
            OhlcvDailyModel.fetched_at,
        )
        .where(OhlcvDailyModel.symbol == symbol)
        .order_by(OhlcvDailyModel.date)
    )
    state = await db.get(OhlcvHistoryStateModel, symbol)
    return stale_reasons(result.all(), state.verified_seam() if state else None)


async def _fetch_window(symbol: str, start: date, end: date) -> list[dict]:
    """Default refresh fetch: the provider chain over ``[start, end]``. The ``+1`` day is
    request slack (as get_bars' heal) so each provider's ``end`` inclusivity is moot."""
    bars = await _fetch_chain(symbol, start, end + timedelta(days=1)) or []
    return [b for b in bars if _bar_date(b) <= end]


async def refresh_adjustments(
    symbols: list[str],
    fetch: Callable[[str, date, date], Awaitable[list[dict]]] | None = None,
    on_refreshed: Callable[[str], None] | None = None,
) -> dict:
    """Re-fetch and upsert the whole stored window of every stale symbol. Never deletes.

    An empty ``symbols`` list means every symbol in ``ohlcv_daily``. ``fetch`` exists for
    tests; production uses the same coherent prefix/suffix writer as ingestion.
    ``on_refreshed`` is called once per refreshed symbol, right after its confidence
    eviction; the endpoint passes the stock-scan backtest-cache eviction (a service
    must not import a router; TRADING-REVIEW-PHASE-C-HYGIENE T6).
    """
    stale: list[dict] = []
    refreshed: list[str] = []
    failed: list[str] = []
    async with AsyncSessionLocal() as db:
        if not symbols:
            res = await db.execute(
                select(OhlcvDailyModel.symbol).distinct().order_by(OhlcvDailyModel.symbol)
            )
            symbols = [s for (s,) in res.all()]
        for symbol in symbols:
            report = await find_stale_adjustment(symbol, db)
            if report is None:
                continue
            stale.append({
                "symbol":   symbol,
                "reasons":  report.reasons,
                "earliest": report.earliest.isoformat(),
            })
            span = await db.execute(
                select(func.min(OhlcvDailyModel.date), func.max(OhlcvDailyModel.date))
                .where(OhlcvDailyModel.symbol == symbol)
            )
            first, last = span.one()
            try:
                if fetch is None:
                    from app.services.history_backfill import update_history
                    # Release the read transaction before the coherent writer opens its own.
                    await db.rollback()
                    result = await update_history(symbol, first, last, force_backfill=True)
                    stored = result.stored
                else:
                    from app.services.history_basis import history_lock
                    from app.services.history_backfill import _validated, HistorySeamMismatch
                    from app.services.bars_changed import notify_bars_changed
                    from app.models.ohlcv_daily import OhlcvHistoryStateModel
                    async with history_lock(symbol):
                        required = set((await db.execute(select(OhlcvDailyModel.date).where(
                            OhlcvDailyModel.symbol == symbol,
                            OhlcvDailyModel.date >= first, OhlcvDailyModel.date <= last
                        ))).scalars().all())
                        required = {d for d in required if is_settled(d, _utcnow())}
                        bars = await fetch(symbol, first, last)
                        candidate = _validated(bars, first, last)
                        if not candidate or not required <= set(candidate):
                            raise HistorySeamMismatch("refresh omits stored settled dates")
                        stored = await _store_bars(symbol, list(candidate.values()), db)
                        state = await db.get(OhlcvHistoryStateModel, symbol)
                        if state is not None:
                            state.seam_date = state.old_source = state.seam_signature = None
                            state.floor_requested_start = state.floor_date = None
                            state.floor_provider = state.floor_checked_at = None
                        await db.commit()
                        notify_bars_changed(symbol)
            except Exception as exc:
                await db.rollback()
                logger.warning(
                    "historical_store: adjustment refresh failed for %s — %s", symbol, exc
                )
                failed.append(symbol)
                continue
            if not stored:
                logger.warning(
                    "historical_store: adjustment refresh for %s stored no bars", symbol
                )
                failed.append(symbol)
                continue
            logger.info(
                "historical_store: refreshed adjustment factors for %s (%s..%s, %d bars, %s)",
                symbol, first, last, len(stored) if isinstance(stored, set) else stored, ",".join(report.reasons),
            )
            # The coherent writer already notified cache owners after commit.
            if on_refreshed is not None:
                on_refreshed(symbol)
            refreshed.append(symbol)
    return {
        "checked":   len(symbols),
        "stale":     stale,
        "refreshed": refreshed,
        "failed":    failed,
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def get_bars(symbol: str, start: date, end: date) -> list[dict]:
    from app.services.history_basis import history_lock
    async with history_lock(symbol):
        return await _get_bars_locked(symbol, start, end)


async def _get_bars_locked(symbol: str, start: date, end: date) -> list[dict]:
    """Return OHLCV bars for `symbol` from `start` to `end`.

    Algorithm:
    1. Check the DB for the last stored date (fetch rule unchanged, Q-H).
    2. Find the earliest legacy provisional row in range that has settled (heal).
    3. Stale: fetch ``min(last+1, heal) .. end``. Not stale but healing: fetch
       ``heal .. end + 1 day`` (the ``+1`` makes the request independent of each
       provider's ``end`` inclusivity). Providers Alpaca → Tiingo → yfinance: first
       success wins, where success is any non-empty list, or — when healing — the heal
       date actually stored with a new ``fetched_at``. A single-provider symbol
       (``basis_provider`` tiingo/yfinance) asks only its own provider, so no other
       provider's rows are appended to its series between nightly runs.
    4. Return all bars from the DB in the requested range.
    Only settled rows are stored (``_store_bars``). Falls back gracefully: if all
    providers fail and DB has partial data, returns what's there.
    """
    async with AsyncSessionLocal() as db:
        last = await _last_stored_date(symbol, db)
        now = _utcnow()

        stale = (last is None) or (last < min(end, _prev_trading_day()))
        heal = await _heal_date(symbol, start, end, now, db)
        if heal is not None and not _claim_heal_attempt(symbol, heal, now):
            heal = None

        fetch_start: date | None = None
        fetch_end = end
        if stale:
            fetch_start = (last + timedelta(days=1)) if last else start
            if heal is not None:
                fetch_start = min(fetch_start, heal)
        elif heal is not None:
            fetch_start, fetch_end = heal, end + timedelta(days=1)

        if fetch_start is not None:
            if heal is not None:
                logger.info(
                    "historical_store: healing provisional row %s for %s (fetch %s..%s)",
                    heal, symbol, fetch_start, fetch_end,
                )

            async def _try(name: str, new_bars: list[dict]) -> bool:
                if not new_bars:
                    return False
                # Nothing past the caller's `end` (the heal-only `+1` day is request slack).
                in_range = [b for b in new_bars if _bar_date(b) <= end]
                try:
                    stored_dates = await _store_bars(symbol, in_range, db)
                    await db.commit()
                except Exception:
                    # Discard earlier chunks before the provider chain retries this session.
                    await db.rollback()
                    raise
                if stored_dates:
                    from app.services.bars_changed import notify_bars_changed
                    notify_bars_changed(symbol)
                logger.debug(
                    "historical_store: %s stored %d bars for %s",
                    name, len(stored_dates), symbol,
                )
                if heal is not None:
                    return heal in stored_dates
                return True

            state = await db.get(OhlcvHistoryStateModel, symbol)
            basis = state.basis_provider if state is not None else None
            providers = (basis,) if basis in ("tiingo", "yfinance") else ("alpaca", "tiingo", "yfinance")
            stored = (await _fetch_chain(
                symbol, fetch_start, fetch_end, accept=_try, providers=providers
            )) is not None
            if heal is not None and not stored:
                logger.warning(
                    "historical_store: no provider returned provisional row %s for %s; "
                    "next attempt after %s", heal, symbol, now + _HEAL_RETRY,
                )

        return await _read_bars(symbol, start, end, db)


# ── Background prefetch ───────────────────────────────────────────────────────

async def _run_prefetch(symbols: list[str], years: int, delay_secs: float) -> None:
    """Background coroutine: sequentially fetch full history for each symbol."""
    global _prefetch_state
    start_time = time.monotonic()
    fetch_end   = date.today()
    fetch_start = fetch_end - timedelta(days=years * 365)

    _prefetch_state.update({
        "status":         "running",
        "total":          len(symbols),
        "done":           0,
        "failed":         0,
        "current_symbol": None,
        "started_at":     datetime.now(timezone.utc).isoformat(),
    })

    try:
        for symbol in symbols:
            _prefetch_state["current_symbol"] = symbol
            _prefetch_state["elapsed_secs"]   = round(time.monotonic() - start_time, 1)
            try:
                # Captured before the read: a refresh evicting this symbol after it
                # makes set_cached drop the confidence computed below (audit R2-F1).
                _bars_gen = conf_generation()
                bars = await get_bars(symbol, fetch_start, fetch_end)
                _prefetch_state["done"] += 1
                if bars:
                    # Warm both live paths' "no override" cache-key shape: the
                    # options path (routers/scan.py) and the stocks path
                    # (routers/stock_scan.py) both key/compute confidence with
                    # atr_mult_target=atr_mult_stop=None ("default" sentinel) unless
                    # the caller supplies a per-scan ATR override (Settings' per-
                    # horizon confidenceGate.atrMult, or a Step-3 panel override) —
                    # the prefetch has no way to know those ahead of a request, so
                    # it only warms the no-override baseline. The only distinction
                    # between the two live paths' baseline keys is scoring_mode
                    # ("stock" vs "options"), which still applies materially
                    # different scoring rules and must stay separate.
                    _variants = ("stock", "options")
                    _combos = [
                        (conf_cache_key(symbol, _d, _h, scoring_mode=_mode), _d, _h, _mode)
                        for _d in ("Bullish", "Bearish")
                        for _h in ("Intraday", "Swing", "Position")
                        for _mode in _variants
                        if get_cached(conf_cache_key(symbol, _d, _h, scoring_mode=_mode)) is None
                    ]
                    if _combos:
                        _conf_tasks = [
                            asyncio.to_thread(
                                compute_confidence, bars,
                                direction=_d, horizon=_h, scoring_mode=_mode,
                            )
                            for _, _d, _h, _mode in _combos
                        ]
                        _conf_results = await asyncio.gather(
                            *_conf_tasks, return_exceptions=True
                        )
                        for (_ck, _d, _h, _mode), _res in zip(_combos, _conf_results):
                            if isinstance(_res, BaseException):
                                logger.debug(
                                    "prefetch: confidence pre-warm failed %s/%s/%s/%s — %s",
                                    symbol, _d, _h, _mode, _res,
                                )
                            else:
                                await set_cached(_ck, {
                                    "confidence": _res.confidence,
                                    "sample_size": _res.sample_size,
                                }, bars_generation=_bars_gen)
            except Exception as exc:
                logger.warning("historical_store prefetch: %s failed — %s", symbol, exc)
                _prefetch_state["failed"] += 1
            # Rate-limit: respect Tiingo's free-tier daily quota.
            await asyncio.sleep(delay_secs)

        _prefetch_state.update({
            "status":         "completed",
            "current_symbol": None,
            "elapsed_secs":   round(time.monotonic() - start_time, 1),
        })
        logger.info(
            "historical_store prefetch complete: %d done, %d failed in %.0fs",
            _prefetch_state["done"], _prefetch_state["failed"], _prefetch_state["elapsed_secs"],
        )
    except Exception as exc:
        _prefetch_state.update({
            "status":         "error",
            "current_symbol": None,
            "elapsed_secs":   round(time.monotonic() - start_time, 1),
        })
        logger.error("historical_store prefetch crashed: %s", exc, exc_info=True)


def prefetch_universe(symbols: list[str], years: int = 5, delay_secs: float = 0.5) -> None:
    """Start (or restart) the background prefetch job.

    delay_secs=0.5 → ~2 req/s.  For Tiingo free tier (500 req/day), pre-fetching
    250 symbols per session stays within quota.  Set delay_secs=0.1 for paid plans.
    """
    global _prefetch_task, _prefetch_state
    if _prefetch_state.get("status") == "running":
        logger.warning("historical_store: prefetch already running — ignoring new request")
        return
    _prefetch_task = asyncio.create_task(
        _run_prefetch(symbols, years, delay_secs)
    )


def get_prefetch_status() -> dict:
    """Return a copy of the current prefetch state."""
    return dict(_prefetch_state)
