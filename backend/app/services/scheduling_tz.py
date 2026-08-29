"""Shared timezone constants/helpers for all background schedulers.

Two different kinds of "timezone" are used across the scheduler suite —
this module is the single source of truth for both:

- ``MARKET_TZ`` — the NYSE's own timezone, fixed, never user-configurable.
  Anything whose correctness depends on a real market event (session open/
  close) must use this, not the operator timezone below — Berlin and New
  York drift relative to each other by about a week twice a year, since the
  EU and US flip daylight saving on different dates.
- ``operator_zone()`` — the operator's own timezone (default
  ``Europe/Berlin``), configurable via ``scheduling.timezone`` in
  settings.yaml. Governs jobs that only need some quiet, convenient local
  hour (nightly ingestion/EDGAR/S&P 500/tuning, audit-log rotation) — they
  don't care what real-world event they're near, only that they don't
  compete with the operator or with market hours.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import yaml

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

MARKET_TZ = ZoneInfo("America/New_York")  # NYSE — never user-configurable

_DEFAULT_OPERATOR_TZ = "Europe/Berlin"

# This module's own private loader — a fifth, deliberately separate copy of
# the per-file-private-_load_settings() convention already used by
# routers/scan.py, services/portfolio_alert_monitor.py, and
# routers/risk_settings.py (each with slightly different fallback
# behavior). Reads only the scheduling.timezone key.
_SETTINGS_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
_SETTINGS_EXAMPLE_PATH = Path(__file__).parent.parent.parent / "config" / "settings.example.yaml"


def _load_settings() -> dict:
    path = _SETTINGS_PATH if _SETTINGS_PATH.exists() else _SETTINGS_EXAMPLE_PATH
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def operator_timezone_name() -> str:
    """The configured operator timezone name (IANA), default Europe/Berlin."""
    return str(_load_settings().get("scheduling", {}).get("timezone", _DEFAULT_OPERATOR_TZ))


def operator_zone() -> ZoneInfo:
    """The configured operator timezone as a ZoneInfo, default Europe/Berlin.

    Falls back to the default zone if the configured name is invalid, so a
    typo in settings.yaml degrades to "still runs, at the default hour's
    real meaning" rather than crashing every scheduler's configure() call.
    """
    name = operator_timezone_name()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(_DEFAULT_OPERATOR_TZ)


def get_or_rebuild_scheduler(
    current: "AsyncIOScheduler | None", current_tz_key: str | None,
) -> tuple["AsyncIOScheduler", str]:
    """Shared rebuild-on-operator-timezone-change logic for every
    AsyncIOScheduler-backed job in this codebase (tuning/ingestion/edgar/
    sp500/scan_schedule) — call from each module's own `_get()`:

        def _get() -> AsyncIOScheduler:
            global _scheduler, _scheduler_tz_key
            _scheduler, _scheduler_tz_key = get_or_rebuild_scheduler(_scheduler, _scheduler_tz_key)
            return _scheduler

    Rebuilds (shutdown-then-recreate) whenever the operator timezone setting
    changes, so a Settings-UI save takes effect immediately rather than only
    at next restart — the whole point of Part 1, Step 2.

    Also self-heals if the scheduler's own bound event loop has died or is
    no longer the one currently running: AsyncIOScheduler binds to
    "whichever event loop is running when .start() is first called" and
    stays bound to it for its lifetime; a scheduler surviving past that
    loop's lifetime would otherwise raise "Event loop is closed" on its next
    add_job() (this genuinely happens on every job (re)configure — e.g. a
    Settings save — not just once at startup). In a real single-worker
    uvicorn process there is exactly one event loop for the server's entire
    life, so this branch is inert there; it exists for any host environment
    that isn't that (per-request event loops, certain test harnesses,
    hypothetical future embeddings) rather than assuming it can never
    happen.
    """
    zone = operator_zone()
    zone_key = str(zone)
    try:
        running_loop: object | None = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    stale = False
    if current is not None:
        bound_loop = getattr(current, "_eventloop", None)
        if bound_loop is None or bound_loop.is_closed():
            stale = True
        elif running_loop is not None and bound_loop is not running_loop:
            stale = True

    if current is None or current_tz_key != zone_key or stale:
        if current is not None and current.running:
            try:
                current.shutdown(wait=False)
            except Exception:
                pass
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        current = AsyncIOScheduler(timezone=zone)
        current_tz_key = zone_key
        current.start()
    return current, current_tz_key
