"""Weekly read-only health check of the stored daily history (BG-SCHEDULE-MAINT).

Runs from ingestion_scheduler's weekly job (Sunday 03:00 operator time). It
writes nothing; it only reports, through the enabled notification channels:

- **Stale adjustment factors** (``find_stale_adjustment``): stored rows whose
  adj factors span fetch batches taken before a split/dividend. The repair,
  ``POST /api/data/refresh-adjustments``, stays a manual operator call on
  purpose: it rewrites each stale symbol's whole stored window and spends
  provider quota, which must not happen unattended.
- **Recent missing trading days**: NYSE trading days in the last
  ``RECENT_GAP_DAYS`` calendar days with no stored bar. Only the recent window
  is checked, so a failed nightly download shows up within a week while
  older, known holes do not repeat in every report.

Both checks cover only the nightly ingestion universe (``ingestion_universe``),
so symbols the nightly job deliberately skips are never reported as missing.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.ohlcv_daily import OhlcvDailyModel
from app.services.history_gap_detector import detect_history_gaps

logger = logging.getLogger(__name__)

RECENT_GAP_DAYS = 30
# Symbols listed per category in the notification; the rest are counted.
_LIST_LIMIT = 25


async def run_history_health_check(
    symbols: list[str] | None = None, today: date | None = None,
) -> dict[str, Any]:
    """Run both checks and return the report. ``symbols``/``today`` exist for tests."""
    from app.services.historical_store import find_stale_adjustment

    if symbols is None:
        from app.services.ingestion_job import ingestion_universe
        symbols = ingestion_universe()
    symbols = list(dict.fromkeys(symbols))
    today = today or date.today()
    window_start = today - timedelta(days=RECENT_GAP_DAYS)

    stale: list[dict[str, Any]] = []
    gaps: dict[str, list[str]] = {}
    no_history: list[str] = []

    async with AsyncSessionLocal() as db:
        if not symbols:
            return _report(symbols, None, stale, gaps, no_history)

        first_rows = await db.execute(
            select(OhlcvDailyModel.symbol, func.min(OhlcvDailyModel.date))
            .where(OhlcvDailyModel.symbol.in_(symbols))
            .group_by(OhlcvDailyModel.symbol)
        )
        first_date = {sym: d for sym, d in first_rows.all()}

        # The newest bar any universe symbol has is the end of the window: a
        # symbol behind it missed a night. Using the calendar instead would flag
        # every symbol on days whose bar has not settled yet.
        newest = (await db.execute(
            select(func.max(OhlcvDailyModel.date)).where(OhlcvDailyModel.symbol.in_(symbols))
        )).scalar()

        recent_rows = await db.execute(
            select(OhlcvDailyModel.symbol, OhlcvDailyModel.date)
            .where(OhlcvDailyModel.symbol.in_(symbols), OhlcvDailyModel.date >= window_start)
        )
        recent: dict[str, set[date]] = {}
        for sym, d in recent_rows.all():
            recent.setdefault(sym, set()).add(d)

        for sym in symbols:
            first = first_date.get(sym)
            if first is None:
                no_history.append(sym)
                continue
            report = await find_stale_adjustment(sym, db)
            if report is not None:
                stale.append({"symbol": sym, "reasons": report.reasons,
                              "earliest": report.earliest.isoformat()})
            if newest is None:
                continue
            start = max(window_start, first)
            if start > newest:
                continue
            missing = detect_history_gaps(sym, recent.get(sym, set()), start=start, end=newest)
            if missing:
                gaps[sym] = [d.isoformat() for d in missing]

    return _report(symbols, newest, stale, gaps, no_history)


def _report(symbols, newest, stale, gaps, no_history) -> dict[str, Any]:
    return {
        "symbols_checked": len(symbols),
        "window_end": newest.isoformat() if newest else None,
        "stale_adjustments": stale,
        "recent_gaps": gaps,
        "no_history": no_history,
    }


def has_findings(report: dict[str, Any]) -> bool:
    return bool(report["stale_adjustments"] or report["recent_gaps"] or report["no_history"])


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:_LIST_LIMIT])
    extra = len(items) - _LIST_LIMIT
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def format_report(report: dict[str, Any]) -> str:
    lines = [f"Checked {report['symbols_checked']} symbols "
             f"(gap window: last {RECENT_GAP_DAYS} days, up to {report['window_end']})."]
    if report["stale_adjustments"]:
        syms = [s["symbol"] for s in report["stale_adjustments"]]
        lines.append(f"Stale adjustment factors: {len(syms)} — {_listed(syms)}. "
                     "Repair manually with POST /api/data/refresh-adjustments.")
    if report["recent_gaps"]:
        syms = sorted(report["recent_gaps"])
        missing = sum(len(v) for v in report["recent_gaps"].values())
        lines.append(f"Missing recent bars: {missing} across {len(syms)} symbols — {_listed(syms)}.")
    if report["no_history"]:
        lines.append(f"No stored history: {len(report['no_history'])} — {_listed(report['no_history'])}.")
    return "\n".join(lines)


async def run_and_notify(today: date | None = None) -> dict[str, Any]:
    """The weekly job: run the check, notify only when something is wrong."""
    report = await run_history_health_check(today=today)
    text = format_report(report)
    if not has_findings(report):
        logger.info("history_health: clean — %s", text)
        return report
    logger.warning("history_health: findings — %s", text)
    try:
        import html
        from app.services.notifications.dispatch import notify_enabled_channels
        await notify_enabled_channels(
            "Weekly history health check: action needed",
            text,
            "<b>Weekly history health check</b>\n" + html.escape(text),
        )
    except Exception:
        logger.error("history_health: notification failed", exc_info=True)
    return report
