"""Tiingo usage ledger: all four free-tier limits, enforced from a persisted log.

Every Tiingo HTTP attempt that reaches Tiingo (any status, 429 retries
included) is recorded in `provider_request_log`. Before each attempt the
ledger is checked and the attempt is refused, unsent, when one of the limits
would be exceeded (plan 2026-10-19-history-incremental-nightly, section 4):

- requests in the last 60 min    < requests_per_hour
- requests in the last 24 h      < requests_per_day   (rolling)
- a symbol not seen in 31 days   only while distinct symbols in 31 days < symbols_per_month
- response bytes in 31 days      < bytes_per_month

The nightly (caller "nightly") stops at limit - nightly_reserve, leaving the
reserve for daytime scans; on-demand callers and the health probe may use the
full limit. A refusal surfaces to callers as `ProviderUnavailable`.

Assumptions, stated:
- **Single backend process.** Check-and-record runs under one `asyncio.Lock`
  held across the check, the HTTP attempt and the insert, so a nightly and an
  on-demand caller cannot both take the last slot. That lock is per process:
  the deployment runs one uvicorn worker. More workers would need a database
  lock instead.
- **A ledger outage never blocks data.** If the ledger cannot be read or
  written (database down, migration not applied), the attempt is admitted
  unchecked and the error is logged; the governor's in-memory pacing and
  symbol budget still apply. An invalid config is different: it refuses every
  attempt, naming the offending key, until the config is fixed.
- The ledger starts empty at deploy and cannot see earlier requests; Tiingo's
  own account page stays authoritative.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import delete, func, select

from app.data.governor import ProviderUnavailable
from app.database import AsyncSessionLocal
from app.models.provider_usage import ProviderRequestLog as Log
from app.services.scheduling_tz import _load_settings

logger = logging.getLogger(__name__)

PROVIDER = "tiingo"
CALLERS = ("nightly", "on_demand", "probe")
RETENTION = timedelta(days=40)

WINDOWS = {
    "requests_per_hour": timedelta(hours=1),
    "requests_per_day":  timedelta(days=1),
    "symbols_per_month": timedelta(days=31),
    "bytes_per_month":   timedelta(days=31),
}
DEFAULT_LIMITS = {"requests_per_hour": 50, "requests_per_day": 1000,
                  "symbols_per_month": 500, "bytes_per_month": 1_000_000_000}
DEFAULT_RESERVE = {"requests_per_day": 100, "symbols_per_month": 25,
                   "bytes_per_month": 100_000_000}

_CALLER: contextvars.ContextVar[str] = contextvars.ContextVar("tiingo_caller", default="on_demand")


@dataclass
class RunUsage:
    """The attempts recorded inside one `run_usage()` block (and the tasks it creates)."""
    requests: int = 0
    bytes: int = 0
    unrecorded: bool = False     # the ledger failed to record at least one attempt


_RUN_USAGE: contextvars.ContextVar[RunUsage | None] = contextvars.ContextVar(
    "tiingo_run_usage", default=None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Caller context ──────────────────────────────────────────────────────────

def current_caller() -> str:
    return _CALLER.get()


@contextlib.contextmanager
def caller(name: str):
    """Run the block (and any task created inside it) as `name`."""
    if name not in CALLERS:
        raise ValueError(f"unknown tiingo caller {name!r}")
    token = _CALLER.set(name)
    try:
        yield
    finally:
        _CALLER.reset(token)


@contextlib.contextmanager
def run_usage():
    """Tally the attempts recorded inside the block, for a run's own counters.

    The tally is one mutable object in a context variable: tasks created inside the block
    copy the context and add to the same tally; code running in any other task (endpoints,
    schedulers, other jobs on the same caller) never sees it.
    """
    usage = RunUsage()
    token = _RUN_USAGE.set(usage)
    try:
        yield usage
    finally:
        _RUN_USAGE.reset(token)


# ── Config ──────────────────────────────────────────────────────────────────

class TiingoBudgetConfigError(ValueError):
    """`data_providers.tiingo` in settings.yaml is invalid; the message names the key."""


@dataclass(frozen=True)
class TiingoLimits:
    limits: dict = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    reserve: dict = field(default_factory=lambda: dict(DEFAULT_RESERVE))

    def stop_at(self, key: str, caller_name: str) -> int:
        held_back = self.reserve.get(key, 0) if caller_name == "nightly" else 0
        return self.limits[key] - held_back


def _mapping(value, key: str) -> dict:
    if not isinstance(value, dict):
        raise TiingoBudgetConfigError(f"{key} must be a mapping")
    return value


def _int(block: dict, key: str, path: str, minimum: int) -> int:
    if key not in block:
        raise TiingoBudgetConfigError(f"{path}.{key} is missing")
    value = block[key]
    if type(value) is not int or value < minimum:
        raise TiingoBudgetConfigError(f"{path}.{key} must be an integer >= {minimum}, got {value!r}")
    return value


def load_limits(settings: dict | None = None) -> TiingoLimits:
    """Validated limits from settings.yaml; free-tier defaults when the block is absent."""
    settings = _load_settings() if settings is None else settings
    providers = settings.get("data_providers") if isinstance(settings, dict) else None
    if providers is None:
        return TiingoLimits()
    block = _mapping(providers, "data_providers").get("tiingo")
    if block is None:
        return TiingoLimits()
    path = "data_providers.tiingo"
    block = _mapping(block, path)
    limits = {key: _int(block, key, path, 1) for key in DEFAULT_LIMITS}
    if "nightly_reserve" not in block:
        raise TiingoBudgetConfigError(f"{path}.nightly_reserve is missing")
    reserve_block = _mapping(block["nightly_reserve"], f"{path}.nightly_reserve")
    reserve = {}
    for key in DEFAULT_RESERVE:
        reserve[key] = _int(reserve_block, key, f"{path}.nightly_reserve", 0)
        if reserve[key] >= limits[key]:
            raise TiingoBudgetConfigError(
                f"{path}.nightly_reserve.{key} must be below {path}.{key} "
                f"({reserve[key]} >= {limits[key]})")
    return TiingoLimits(limits, reserve)


# ── Ledger ──────────────────────────────────────────────────────────────────

class BudgetRefused(BaseException):
    """An attempt refused by the ledger, raised from inside the governor's call.

    Deliberately a BaseException: `Governor.call` books every `Exception` from
    the request as a provider failure (breaker count, status "down") and
    retries `RateLimited`. A refusal is neither, so it must pass through
    untouched. It never leaves this package's callers: `tiingo` and the probe
    convert it to `ProviderUnavailable` / a degraded status at once.
    """


_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_lock() -> asyncio.Lock:
    """The process lock, bound to the running loop (one loop in production)."""
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


async def _usage(now: datetime, symbol: str | None) -> tuple[dict, bool]:
    """Used amount per limit, and whether `symbol` was seen in the 31-day window."""
    def since(key):
        return (Log.provider == PROVIDER, Log.requested_at >= now - WINDOWS[key])

    async with AsyncSessionLocal() as db:
        async def scalar(stmt) -> int:   # SUM(bigint) is a Decimal on Postgres
            return int((await db.execute(stmt)).scalar() or 0)

        used = {
            "requests_per_hour": await scalar(select(func.count()).where(*since("requests_per_hour"))),
            "requests_per_day": await scalar(select(func.count()).where(*since("requests_per_day"))),
            "symbols_per_month": await scalar(select(func.count(func.distinct(Log.symbol))).where(
                *since("symbols_per_month"), Log.symbol.is_not(None))),
            "bytes_per_month": await scalar(select(func.sum(Log.response_bytes)).where(
                *since("bytes_per_month"))),
        }
        seen = symbol is not None and await scalar(select(func.count()).where(
            *since("symbols_per_month"), Log.symbol == symbol)) > 0
    return used, seen


def _first_exhausted(limits: TiingoLimits, used: dict, caller_name: str,
                     new_symbol: bool) -> str | None:
    for key in DEFAULT_LIMITS:
        if key == "symbols_per_month" and not new_symbol:
            continue
        stop = limits.stop_at(key, caller_name)
        if used[key] >= stop:
            return f"tiingo {key} budget exhausted ({used[key]}/{stop})"
    return None


async def _refusal(symbol: str | None, caller_name: str, now: datetime, *,
                   new_symbol: bool = False) -> str | None:
    try:
        limits = load_limits()
    except TiingoBudgetConfigError as exc:
        logger.error("tiingo_budget: invalid config, refusing — %s", exc)
        return f"tiingo budget config invalid: {exc}"
    try:
        used, seen = await _usage(now, symbol)
    except Exception as exc:
        logger.error("tiingo_budget: ledger unreadable, request admitted unchecked — %s", exc)
        return None
    return _first_exhausted(limits, used, caller_name,
                            new_symbol or (symbol is not None and not seen))


async def _record(symbol: str | None, resp, caller_name: str, now: datetime) -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add(Log(provider=PROVIDER, requested_at=now, symbol=symbol,
                       response_bytes=len(resp.content), status_code=int(resp.status_code),
                       caller=caller_name))
            await db.commit()
    except Exception as exc:
        logger.error("tiingo_budget: ledger write failed, request not recorded — %s", exc)
        usage = _RUN_USAGE.get()
        if usage is not None:
            usage.unrecorded = True
        return
    usage = _RUN_USAGE.get()
    if usage is not None:
        usage.requests += 1
        usage.bytes += len(resp.content)


async def ensure_room(symbol: str | None, caller_name: str | None = None) -> None:
    """Fast pre-check outside the governor: raise ProviderUnavailable when refused,
    so a refused call neither waits for nor spends the governor's pacing."""
    reason = await _refusal(symbol, caller_name or current_caller(), _utcnow())
    if reason:
        raise ProviderUnavailable(reason)


async def send_recorded(symbol: str | None, send: Callable[[], Awaitable], *,
                        caller_name: str | None = None):
    """Check, send one HTTP attempt and record it, atomically under the lock.

    Raises BudgetRefused (nothing sent, nothing recorded) when a limit would be
    exceeded. The attempt is recorded whatever its status; an attempt whose
    `send()` raises (no reply from Tiingo) is not.
    """
    caller_name = caller_name or current_caller()
    async with _get_lock():
        now = _utcnow()
        reason = await _refusal(symbol, caller_name, now)
        if reason:
            raise BudgetRefused(reason)
        resp = await send()
        await _record(symbol, resp, caller_name, now)
        return resp


async def exhausted_limit() -> str | None:
    """The first limit an on-demand caller with a new symbol would hit, if any."""
    return await _refusal(None, "on_demand", _utcnow(), new_symbol=True)


async def probe(send: Callable[[], Awaitable]) -> tuple[object | None, str | None]:
    """Send the health probe through the ledger as caller "probe".

    Returns (response, None), (response, exhausted-limit detail) or
    (None, refusal) — never raises BudgetRefused.
    """
    try:
        resp = await send_recorded(None, send, caller_name="probe")
    except BudgetRefused as exc:
        return None, str(exc)
    return resp, await exhausted_limit()


def _window_label(span: timedelta) -> str:
    if span >= timedelta(days=2):
        return f"rolling {span.days} d"
    return f"rolling {int(span.total_seconds() // 3600)} h"


async def usage_summary() -> dict:
    """Read-only view of the four limits, for the ingestion status endpoint.

    Per limit: `used` (the same ledger query the admission check runs),
    `limit`, `nightly_stop_at` (limit - nightly reserve; the limit itself where
    there is no reserve) and `window`. Raises TiingoBudgetConfigError on an
    invalid config and the database error when the ledger cannot be read.
    """
    limits = load_limits()
    used, _ = await _usage(_utcnow(), None)
    return {key: {"used": used[key], "limit": limits.limits[key],
                  "nightly_stop_at": limits.stop_at(key, "nightly"),
                  "window": _window_label(WINDOWS[key])}
            for key in DEFAULT_LIMITS}


async def prune_usage(older_than: timedelta = RETENTION) -> int:
    """Delete ledger rows older than `older_than` (40 days); returns the count."""
    cutoff = _utcnow() - older_than
    async with AsyncSessionLocal() as db:
        result = await db.execute(delete(Log).where(Log.requested_at < cutoff))
        await db.commit()
        return result.rowcount
