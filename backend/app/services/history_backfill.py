"""Stage a whole retained symbol on a coherent adjusted basis, then commit atomically.

``update_history`` classifies the symbol once, inside its ``history_lock`` and its one
transaction, before anything is written (``history_incremental.classify_nightly_symbol``,
plan ``docs/superpowers/plans/2026-10-19-history-incremental-nightly-plan.md`` 2.2-2.6), and
takes the matching branch:

- ``SUFFIX_ONLY``: tonight's Alpaca bars only; the stored prefix stays byte-identical.
- ``RESCALE``: every prefix ``adj_factor`` times Alpaca's ratio ``r_A`` (8 dp, half-even),
  those rows' ``fetched_at`` = now, tonight's suffix; F (``floor_checked_at``) unchanged.
- ``CONFIRM`` / ``REVALIDATE`` / ``FULL``: the full prefix path (the code before this phase).
  ``CONFIRM`` / ``REVALIDATE`` with no usable provider reply are written ``SUFFIX_ONLY``.
- Single-provider symbols: ``SINGLE_PROVIDER_CURRENT`` (nothing), the anchored recent window
  (Tiingo basis only, 2.6 steps 3-5) or the full window (``_single_provider_locked``).

``tiingo_allowed=False`` (pass 1 of the nightly, 2.7) writes nothing and returns
``action="deferred"`` whenever the classification needs a Tiingo request.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import bindparam, select, update

from app.database import AsyncSessionLocal
from app.models.ohlcv_daily import OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs
from app.services import history_incremental as hi
from app.services.bars_changed import notify_bars_changed
from app.services.history_basis import history_lock, seam_signature

logger = logging.getLogger(__name__)
K = hi.NightlyKind


class HistorySeamMismatch(ValueError):
    def __init__(self, message: str, ratio: float | None = None):
        super().__init__(message)
        self.ratio = ratio


class SingleProviderRefused(ValueError):
    """Every single-provider candidate was refused; rows and state are untouched."""


@dataclass(frozen=True)
class HistoryUpdateResult:
    stored: int
    backfilled: bool
    floor_reached: bool
    provider: str | None = None
    # The executed ``NightlyAction.kind`` value, or "deferred" (tiingo_allowed=False and the
    # classification needs Tiingo; nothing written). ``reason``: the classifier's reason;
    # "confirm_retry" / "revalidate_no_reply" for a CONFIRM / REVALIDATE written SUFFIX_ONLY;
    # for "deferred", the deferred kind's value.
    action: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RebuildResult:
    provider: str
    rows_before: int
    rows_after: int
    first_date_before: date | None
    first_date_after: date
    last_date_after: date
    backfilled: bool
    floor_reached: bool


_MAX_GAP = timedelta(days=7)
_IDENTITY_DATES = 5
_IDENTITY_TOLERANCE = Decimal("0.005")


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


def _dec(value) -> Decimal:
    return Decimal(str(value))


async def _single_provider_locked(db, symbol, start, end, providers) -> RebuildResult:
    """Replace the whole window from one provider; any refusal leaves rows and state untouched."""
    from app.data.tiingo import fetch_historical_candles
    existing = [(r.date, r.close, r.adj_factor, r.source) for r in (await db.execute(select(M).where(
        M.symbol == symbol, M.date >= start, M.date <= end).order_by(M.date))).scalars().all()]
    required = {d for d, *_ in existing if hs.is_settled(d, hs._utcnow())}
    reasons = []
    for provider in providers:
        try:
            if provider == "tiingo":
                bars = await fetch_historical_candles(symbol, start, end + timedelta(days=1),
                                                      strict_adjustments=True)
            else:
                bars = await asyncio.to_thread(hs._yfinance_fetch, symbol, start,
                                               end + timedelta(days=1))
            candidate = _validated(bars, start, end)
            if not candidate:
                raise ValueError("no settled bars in the window")
            if any(b["source"] != provider for b in candidate.values()):
                raise ValueError("reply is not from the requested provider")
            dates = list(candidate)
            for a, b in zip(dates, dates[1:]):
                if b - a > _MAX_GAP:
                    raise ValueError(f"internal gap {a} to {b}")
            shared = [row for row in existing if row[3] != provider and row[0] in candidate]
            for d, close, factor, source in shared[-_IDENTITY_DATES:]:
                bar = candidate[d]
                if provider == "tiingo" and source in {"alpaca", "tiingo"}:
                    ratio = _dec(bar["close"]) / _dec(close)
                else:
                    ratio = (_dec(bar["close"]) * _dec(bar["adj_factor"])) / (_dec(close) * _dec(factor or 1))
                if abs(ratio - 1) > _IDENTITY_TOLERANCE:
                    raise ValueError(f"close differs from stored {source} on {d} (ratio {float(ratio):.4f})")
            if not required <= set(candidate):
                raise ValueError("reply omits existing stored dates")
            stored = await hs._store_bars(symbol, list(candidate.values()), db)
            if stored != set(candidate):
                raise ValueError("not every candidate date was stored")
            state = await db.get(State, symbol)
            if state is None:
                state = State(symbol=symbol)
                db.add(state)
            now = hs._utcnow()
            state.basis_provider, state.basis_rebuilt_at = provider, now
            state.window_verified_through, state.window_verified_at = dates[-1], now
            state.seam_date = state.old_source = state.seam_signature = None
            state.floor_requested_start = start
            state.floor_date, state.floor_provider = dates[0], provider
            state.floor_checked_at = now
            await db.commit()
        except Exception as exc:
            await db.rollback()
            reasons.append(f"{provider}: {exc}")
            logger.warning("history: single-provider %s refused for %s: %s", provider, symbol, exc)
            continue
        notify_bars_changed(symbol)
        first_before = existing[0][0] if existing else None
        return RebuildResult(
            provider=provider, rows_before=len(existing), rows_after=len(candidate),
            first_date_before=first_before, first_date_after=dates[0], last_date_after=dates[-1],
            backfilled=first_before is None or dates[0] < first_before,
            floor_reached=dates[0] > start + timedelta(days=7),
        )
    raise SingleProviderRefused("; ".join(reasons))


async def rebuild_single_provider(symbol: str, start: date, end: date) -> RebuildResult:
    """Rebuild a symbol's window from Tiingo, or yfinance if Tiingo is refused."""
    async with history_lock(symbol):
        async with AsyncSessionLocal() as db:
            return await _single_provider_locked(db, symbol, start, end, ("tiingo", "yfinance"))


# ── Incremental branches (HISTORY-INCREMENTAL-NIGHTLY B2) ───────────────────

_Q8 = Decimal("0.00000001")                 # Numeric(12, 8): the stored adj_factor precision
_TIINGO_KINDS = {K.FULL, K.CONFIRM, K.REVALIDATE}
_RETRY_AS_SUFFIX = {K.CONFIRM: "confirm_retry", K.REVALIDATE: "revalidate_no_reply"}


def _rescaled(factor, ratio) -> Decimal:
    """``factor`` x ``ratio`` at the stored 8-dp precision, rounded half-even."""
    return (Decimal(str(factor)) * Decimal(str(ratio))).quantize(_Q8, rounding=ROUND_HALF_EVEN)


def _row_tuples(rows) -> list[tuple]:
    """Stored rows in the ``stale_reasons`` tuple shape the classifier reads."""
    return [(r.date, r.close, r.adj_factor, r.split_factor, r.div_cash, r.source, r.fetched_at)
            for r in rows]


def _first_after_floor(rows, start: date) -> bool:
    """``floor_reached`` for a write that fetched no prefix: the stored series starts more
    than a week after ``start`` (what the full path reports from the same provider floor)."""
    return bool(rows) and rows[0][0] > start + timedelta(days=7)


def _deferred(action: hi.NightlyAction) -> HistoryUpdateResult:
    return HistoryUpdateResult(stored=0, backfilled=False, floor_reached=False,
                               action="deferred", reason=action.kind.value)


async def _rescale_rows(db, symbol: str, rows, ratio, now) -> None:
    """Multiply each ``(date, adj_factor)`` row's stored factor by ``ratio``; its
    ``fetched_at`` becomes ``now``. No commit: part of the caller's transaction."""
    if not rows:
        return
    if any(factor is None for _, factor in rows):
        raise ValueError("a row to rescale has no adj_factor")
    table = M.__table__
    stmt = (update(table)
            .where(table.c.symbol == bindparam("b_symbol"), table.c.date == bindparam("b_date"))
            .values(adj_factor=bindparam("b_factor"), fetched_at=bindparam("b_fetched")))
    await db.execute(stmt, [{"b_symbol": symbol, "b_date": d, "b_factor": _rescaled(factor, ratio),
                             "b_fetched": now} for d, factor in rows])


async def _seam_signature_now(db, symbol: str, last_prefix: date, seam: date) -> str:
    """The seam signature over the stored pair (last prefix row, seam row), read back after
    the write exactly as the full path reads it."""
    pair = (await db.execute(select(M.date, M.close, M.adj_factor, M.split_factor,
        M.div_cash, M.source, M.fetched_at).where(
        M.symbol == symbol, M.date.in_([last_prefix, seam])
    ).order_by(M.date))).all()
    return seam_signature(*pair)


async def _write_kept_prefix(db, symbol: str, start: date, end: date, state, rows, alpaca_bars, *,
                             ratio=None, action: str, reason: str) -> HistoryUpdateResult:
    """``SUFFIX_ONLY`` (``ratio`` None) and ``RESCALE`` (plan 2.3, 2.4).

    The verified stored prefix is kept: untouched (raw, factor, ``fetched_at``), or every
    prefix factor times ``ratio`` with ``fetched_at`` = now. Tonight's Alpaca suffix is
    written, the seam signature recomputed; seam, old source and floor fields (F) stay.
    One commit, then ``notify_bars_changed``.
    """
    current = _validated(alpaca_bars, start, end)
    seam = min(current)
    if seam != state.seam_date:
        raise HistorySeamMismatch("seam moved since classification")
    prefix = [(r[0], r[2]) for r in rows if r[0] < seam]
    if not prefix:
        raise HistorySeamMismatch("no stored prefix to keep")
    now = hs._utcnow()
    retained = {r[0] for r in rows if r[0] >= seam and hs.is_settled(r[0], now)}
    if not retained <= set(current):
        raise HistorySeamMismatch("current suffix omits existing retained dates")
    if ratio is not None:
        await _rescale_rows(db, symbol, prefix, ratio, now)
    stored = await hs._store_bars(symbol, list(current.values()), db)
    if stored != set(current):
        raise HistorySeamMismatch("not every staged date was stored")
    state.seam_signature = await _seam_signature_now(db, symbol, prefix[-1][0], seam)
    await db.commit()
    notify_bars_changed(symbol)
    return HistoryUpdateResult(stored=len(stored), backfilled=False,
                               floor_reached=_first_after_floor(rows, start),
                               action=action, reason=reason)


async def _write_window(db, symbol: str, start: date, end: date, window_start: date, reply, *,
                        ratio, rows, action: str, reason: str,
                        prior: str | None = None) -> HistoryUpdateResult:
    """2.6 step 5: upsert the recent window (and, with ``ratio``, rescale every row dated
    before it, ``fetched_at`` = now), then advance the window anchor. One transaction; any
    failure rolls it back and refuses with rows and state untouched."""
    try:
        candidate = _validated(reply, window_start, end)
        if not candidate:
            raise ValueError("no settled bars in the window")
        now = hs._utcnow()
        if ratio is not None:
            older = (await db.execute(select(M.date, M.adj_factor).where(
                M.symbol == symbol, M.date >= start, M.date < window_start
            ).order_by(M.date))).all()
            await _rescale_rows(db, symbol, older, ratio, now)
        stored = await hs._store_bars(symbol, list(candidate.values()), db)
        if stored != set(candidate):
            raise ValueError("not every candidate date was stored")
        state = await db.get(State, symbol)
        state.window_verified_through, state.window_verified_at = max(candidate), now
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("history: single-provider tiingo window refused for %s: %s", symbol, exc)
        detail = f"tiingo: {exc}" if prior is None else f"{prior}; rescale fallback: {exc}"
        raise SingleProviderRefused(detail) from exc
    notify_bars_changed(symbol)
    return HistoryUpdateResult(stored=len(stored), backfilled=False,
                               floor_reached=_first_after_floor(rows, start), provider="tiingo",
                               action=action, reason=reason)


async def _single_provider_recent_locked(db, symbol: str, start: date, end: date, state, rows,
                                         params: hi.IncrementalParams, now) -> HistoryUpdateResult:
    """2.6 steps 3-5 for a Tiingo-basis symbol whose window anchor is usable.

    One Tiingo request for ``window_verified_through - anchor_overlap_days .. end`` (through
    the same ``fetch_historical_candles(..., strict_adjustments=True)`` call as the full path,
    so the usage ledger counts it). Unchanged anchor rows: the window is upserted. A uniform
    ratio under D1-a: the full-window ``_single_provider_locked``; if that is refused, the
    rows before the window are rescaled by the ratio with the window upsert (the fallback).
    Under D1-b the rescale directly. Anything else: the full-window path. A refused request
    or write leaves rows and state untouched (``SingleProviderRefused``).
    """
    from app.data.tiingo import fetch_historical_candles
    window_start = hi.single_provider_window_start(state, params)
    try:
        reply = await fetch_historical_candles(symbol, window_start, end + timedelta(days=1),
                                               strict_adjustments=True)
    except Exception as exc:
        await db.rollback()
        logger.warning("history: single-provider tiingo window refused for %s: %s", symbol, exc)
        raise SingleProviderRefused(f"tiingo: {exc}") from exc
    verdict = hi.classify_single_provider_window(state, rows, reply, now, end=end, params=params)
    if verdict.kind is K.SINGLE_PROVIDER_FULL:
        # Nothing is written before this call; its own rollback on refusal leaves the
        # session clean, and the fallback below re-reads what it rescales.
        try:
            r = await _single_provider_locked(db, symbol, start, end, ("tiingo",))
        except SingleProviderRefused as refused:
            if verdict.ratio is None:
                raise
            return await _write_window(db, symbol, start, end, window_start, reply,
                                       ratio=verdict.ratio, rows=rows,
                                       action=K.SINGLE_PROVIDER_RECENT.value,
                                       reason="window_event_fallback", prior=str(refused))
        return HistoryUpdateResult(stored=r.rows_after, backfilled=r.backfilled,
                                   floor_reached=r.floor_reached, provider=r.provider,
                                   action=verdict.kind.value, reason=verdict.reason)
    return await _write_window(db, symbol, start, end, window_start, reply, ratio=verdict.ratio,
                               rows=rows, action=verdict.kind.value, reason=verdict.reason)


async def update_history(symbol: str, start: date, end: date, *,
                         alpaca_bars: list[dict] | None = None,
                         force_backfill: bool = False,
                         params: hi.IncrementalParams | None = None,
                         revalidate: bool = False,
                         tiingo_allowed: bool = True) -> HistoryUpdateResult:
    """No bar or proof changes become visible until both provider segments validate.

    ``params``: the incremental parameters (default: ``load_params`` defaults). ``revalidate``:
    the caller selected this symbol for revalidation tonight. ``tiingo_allowed=False``: a
    classification that needs a Tiingo request writes nothing and returns ``"deferred"``.
    """
    params = hi.load_params(None) if params is None else params
    async with history_lock(symbol):
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(select(M).where(
                M.symbol == symbol, M.date >= start, M.date <= end
            ).order_by(M.date))).scalars().all()
            required = {r.date for r in existing if hs.is_settled(r.date, hs._utcnow())}
            state = await db.get(State, symbol)
            rows = _row_tuples(existing)
            now = hs._utcnow()
            if state is not None and state.basis_provider in {"tiingo", "yfinance"}:
                action = hi.classify_nightly_symbol(state, rows, None, start, now, end=end,
                                                    params=params, force_backfill=force_backfill)
                if action.kind is K.SINGLE_PROVIDER_CURRENT:
                    return HistoryUpdateResult(stored=0, backfilled=False,
                                               floor_reached=_first_after_floor(rows, start),
                                               provider=state.basis_provider,
                                               action=action.kind.value, reason=action.reason)
                if not tiingo_allowed and state.basis_provider == "tiingo":
                    return _deferred(action)
                if action.kind is K.SINGLE_PROVIDER_RECENT:
                    return await _single_provider_recent_locked(db, symbol, start, end, state,
                                                                rows, params, now)
                r = await _single_provider_locked(db, symbol, start, end, (state.basis_provider,))
                return HistoryUpdateResult(stored=r.rows_after, backfilled=r.backfilled,
                                           floor_reached=r.floor_reached, provider=r.provider,
                                           action=action.kind.value, reason=action.reason)
            if alpaca_bars is None:
                from app.data.alpaca import fetch_daily_bars_single, get_alpaca_client
                client = await get_alpaca_client()
                try:
                    alpaca_bars = (await fetch_daily_bars_single(
                        symbol, start, end + timedelta(days=1), client=client,
                        strict_adjustments=True)) if client is not None else []
                except Exception:
                    alpaca_bars = []
            action = hi.classify_nightly_symbol(state, rows, alpaca_bars, start, now, end=end,
                                                params=params, force_backfill=force_backfill,
                                                revalidate=revalidate)
            if action.kind in _TIINGO_KINDS and not tiingo_allowed:
                return _deferred(action)
            if action.kind in (K.SUFFIX_ONLY, K.RESCALE):
                return await _write_kept_prefix(db, symbol, start, end, state, rows, alpaca_bars,
                                                ratio=action.ratio, action=action.kind.value,
                                                reason=action.reason)
            # FULL, CONFIRM, REVALIDATE: the full prefix path below.
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

                    reply = await _fetch_fallback(symbol, start, overlap_end, accept)
                    if not reply and action.kind in _RETRY_AS_SUFFIX:
                        # No usable reply (both providers refused or empty): the prefix
                        # is still trusted, so tonight is SUFFIX_ONLY; retried next night.
                        return await _write_kept_prefix(
                            db, symbol, start, end, state, rows, alpaca_bars,
                            action=K.SUFFIX_ONLY.value, reason=_RETRY_AS_SUFFIX[action.kind])
                    fallback = _validated(reply, start, overlap_end)
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
                action=action.kind.value, reason=action.reason,
            )
