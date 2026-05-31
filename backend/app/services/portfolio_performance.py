# backend/app/services/portfolio_performance.py
"""Pure, DB-free helpers for portfolio realized-P&L math and calendar bucketing.

Kept side-effect free so they unit-test deterministically. The router layer
feeds these plain dicts (already read from the DB).
"""
from __future__ import annotations

from datetime import date, timedelta


def realized_pnl(entry_price: float, exit_price: float, qty: int) -> tuple[float, float]:
    """Long-premium realized P&L: (exit - entry) * 100 * qty. Percent guards entry==0."""
    dollar = round((exit_price - entry_price) * 100 * qty, 2)
    pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0
    return dollar, pct


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d[:10])
    except (ValueError, TypeError):
        return None


def bucket_realized_by_calendar(
    rows: list[dict], today: date, week_starts_monday: bool = True
) -> dict[str, float]:
    """Sum realized_pnl_dollar into today / this-week / this-month / this-year buckets.

    Calendar periods (not rolling): week = Mon..Sun containing `today`, month = 1st
    of `today`'s month onward, year = Jan 1 of `today`'s year onward.
    """
    if week_starts_monday:
        week_start = today - timedelta(days=today.weekday())
    else:
        week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    out = {"today": 0.0, "week": 0.0, "month": 0.0, "year": 0.0}
    for r in rows:
        d = _parse(r.get("exit_date", ""))
        if d is None:
            continue
        amt = float(r.get("realized_pnl_dollar", 0.0))
        if d == today:
            out["today"] += amt
        if week_start <= d <= today:
            out["week"] += amt
        if month_start <= d <= today:
            out["month"] += amt
        if year_start <= d <= today:
            out["year"] += amt
    return {k: round(v, 2) for k, v in out.items()}


def cumulative_curve(rows: list[dict]) -> list[dict]:
    """Cumulative realized P&L, one point per distinct exit date, ascending by date."""
    by_day: dict[str, float] = {}
    for r in rows:
        d = _parse(r.get("exit_date", ""))
        if d is None:
            continue
        key = d.isoformat()
        by_day[key] = by_day.get(key, 0.0) + float(r.get("realized_pnl_dollar", 0.0))
    running = 0.0
    curve: list[dict] = []
    for day in sorted(by_day):
        running = round(running + by_day[day], 2)
        curve.append({"date": day, "value": running})
    return curve
