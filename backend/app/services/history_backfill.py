"""Stage a whole retained symbol on a coherent adjusted basis, then commit atomically."""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.ohlcv_daily import OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs
from app.services.bars_changed import notify_bars_changed
from app.services.history_basis import history_lock, seam_signature

logger = logging.getLogger(__name__)


class HistorySeamMismatch(ValueError):
    def __init__(self, message: str, ratio: float | None = None):
        super().__init__(message)
        self.ratio = ratio


@dataclass(frozen=True)
class HistoryUpdateResult:
    stored: int
    backfilled: bool
    floor_reached: bool


def _validated(bars, start, end):
    out = {}
    for bar in bars or []:
        d = hs._bar_date(bar)
        if not start <= d <= end or not hs.is_settled(d, hs._utcnow()):
            continue
        if d in out:
            raise HistorySeamMismatch("duplicate provider date")
        for field in ("open", "high", "low", "close", "adj_factor"):
            value = float(bar.get(field) or 0)
            if not math.isfinite(value) or value <= 0:
                raise HistorySeamMismatch(f"invalid {field} on {d}")
        if bar.get("source") not in {"alpaca", "tiingo", "yfinance"}:
            raise HistorySeamMismatch("unknown adjustment basis")
        out[d] = bar
    if len({b["source"] for b in out.values()}) > 1:
        raise HistorySeamMismatch("provider reply mixes sources")
    return dict(sorted(out.items()))


async def _fetch_fallback(symbol, start, end, accept=None):
    """Skip Alpaca; a rejected Tiingo window proceeds to adjusted yfinance."""
    from app.data.tiingo import fetch_historical_candles
    last_error = None
    for provider in ("tiingo", "yfinance"):
        try:
            if provider == "tiingo":
                bars = await fetch_historical_candles(symbol, start,
                                              end + timedelta(days=1), strict_adjustments=True)
            else:
                bars = await asyncio.to_thread(hs._yfinance_fetch, symbol, start,
                                              end + timedelta(days=1))
            candidate = _validated(bars, start, end)
            if not candidate:
                continue
            if accept is not None:
                accept(candidate)
            return list(candidate.values())
        except Exception as exc:
            last_error = exc
            logger.warning("history: %s window rejected for %s: %s", provider, symbol, exc)
    if isinstance(last_error, HistorySeamMismatch):
        raise last_error
    return []


async def update_history(symbol: str, start: date, end: date, *,
                         alpaca_bars: list[dict] | None = None,
                         force_backfill: bool = False) -> HistoryUpdateResult:
    """No bar or proof changes become visible until both provider segments validate."""
    async with history_lock(symbol):
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(select(M).where(
                M.symbol == symbol, M.date >= start, M.date <= end
            ).order_by(M.date))).scalars().all()
            required = {r.date for r in existing if hs.is_settled(r.date, hs._utcnow())}
            state = await db.get(State, symbol)
            if alpaca_bars is None:
                from app.data.alpaca import fetch_daily_bars_single, get_alpaca_client
                client = await get_alpaca_client()
                try:
                    alpaca_bars = (await fetch_daily_bars_single(
                        symbol, start, end + timedelta(days=1), client=client,
                        strict_adjustments=True)) if client is not None else []
                except Exception:
                    alpaca_bars = []
            current = _validated(alpaca_bars, start, end)
            if current and any(b["source"] != "alpaca" for b in current.values()):
                raise HistorySeamMismatch("current reply is not Alpaca")
            old = {}
            observed = None
            reused_floor = False
            seam = min(current) if current else None
            if current:
                older_required = {d for d in required if d < seam}
                missing_prefix = seam > start + timedelta(days=7)
                if state and missing_prefix and not older_required and not force_backfill:
                    reused_floor = bool(
                        state.floor_requested_start and start >= state.floor_requested_start
                        and state.floor_date == (min(required) if required else None) == seam
                        and state.floor_checked_at
                        and timedelta(0) <= hs._utcnow() - hs._as_utc(state.floor_checked_at)
                        <= timedelta(days=30))
                if older_required or (missing_prefix and not reused_floor):
                    if len(current) < 5:
                        raise HistorySeamMismatch("fewer than five settled Alpaca overlap dates")
                    overlap_end = list(current)[4]

                    def accept(candidate):
                        common = sorted(set(candidate) & set(current))
                        if len(common) < 5:
                            raise HistorySeamMismatch("fewer than five shared dates")
                        for d in common:
                            adjusted = Decimal(str(candidate[d]["close"])) * Decimal(str(candidate[d]["adj_factor"]))
                            reference = Decimal(str(current[d]["close"])) * Decimal(str(current[d]["adj_factor"]))
                            ratio = adjusted / reference
                            if abs(ratio - 1) > Decimal("0.005"):
                                raise HistorySeamMismatch(f"adjusted seam differs on {d}", float(ratio))
                        if not older_required <= set(candidate):
                            raise HistorySeamMismatch("fallback omits existing older dates")

                    fallback = _validated(await _fetch_fallback(symbol, start, overlap_end, accept), start, overlap_end)
                    accept(fallback)
                    old = {d: b for d, b in fallback.items() if d < seam}
                    observed = (min(fallback), next(iter(fallback.values()))["source"])
            else:
                def accept(candidate):
                    if not required <= set(candidate):
                        raise HistorySeamMismatch("full-window fallback omits existing dates")
                old = _validated(await _fetch_fallback(symbol, start, end, accept), start, end)
                if not old:
                    raise ValueError("no usable full-window history")
                accept(old)
                observed = (min(old), next(iter(old.values()))["source"])
            candidate_dates = set(old) | set(current)
            if not candidate_dates or not required <= candidate_dates:
                raise HistorySeamMismatch("current suffix omits existing retained dates")
            stored = await hs._store_bars(symbol, list(old.values()), db)
            stored |= await hs._store_bars(symbol, list(current.values()), db)
            if stored != candidate_dates:
                raise HistorySeamMismatch("not every staged date was stored")
            if state is None:
                state = State(symbol=symbol)
                db.add(state)
            state.seam_date = state.old_source = state.seam_signature = None
            if old and current:
                pair = (await db.execute(select(M.date, M.close, M.adj_factor, M.split_factor,
                    M.div_cash, M.source, M.fetched_at).where(
                    M.symbol == symbol, M.date.in_([max(old), seam])
                ).order_by(M.date))).all()
                state.seam_date = seam
                state.old_source = next(iter(old.values()))["source"]
                state.seam_signature = seam_signature(*pair)
            if observed:
                state.floor_requested_start = start
                state.floor_date, state.floor_provider = observed
                state.floor_checked_at = hs._utcnow()
            await db.commit()
            notify_bars_changed(symbol)
            return HistoryUpdateResult(
                stored=len(stored),
                backfilled=bool(required and min(candidate_dates) < min(required)),
                floor_reached=reused_floor or bool(observed and observed[0] > start + timedelta(days=7)),
            )
