# backend/tests/test_portfolio_performance.py
from datetime import date

from app.services.portfolio_performance import (
    realized_pnl, bucket_realized_by_calendar, cumulative_curve,
)


def test_realized_pnl_long_premium():
    # entry 1.00, exit 1.50, 2 contracts -> (1.50-1.00)*100*2 = 100.0, +50%
    dollar, pct = realized_pnl(entry_price=1.00, exit_price=1.50, qty=2)
    assert dollar == 100.0
    assert pct == 50.0


def test_realized_pnl_loss_and_zero_entry_guard():
    dollar, pct = realized_pnl(entry_price=2.00, exit_price=1.00, qty=1)
    assert dollar == -100.0
    assert pct == -50.0
    # entry 0 must not divide-by-zero
    d2, p2 = realized_pnl(entry_price=0.0, exit_price=1.0, qty=1)
    assert d2 == 100.0
    assert p2 == 0.0


def test_bucket_realized_by_calendar():
    today = date(2026, 5, 31)  # a Sunday
    rows = [
        {"exit_date": "2026-05-31", "realized_pnl_dollar": 100.0},  # today, this week, month, year
        {"exit_date": "2026-05-25", "realized_pnl_dollar": 50.0},   # this month + year, this week (Mon 25th)
        {"exit_date": "2026-04-10", "realized_pnl_dollar": 25.0},   # this year only
        {"exit_date": "2025-12-31", "realized_pnl_dollar": 999.0},  # last year -> excluded everywhere
    ]
    b = bucket_realized_by_calendar(rows, today=today, week_starts_monday=True)
    assert b["today"] == 100.0
    assert b["week"] == 150.0     # 31st + 25th (week Mon 25 -> Sun 31)
    assert b["month"] == 150.0    # May rows
    assert b["year"] == 175.0     # 2026 rows


def test_cumulative_curve_sorted_and_running_total():
    rows = [
        {"exit_date": "2026-05-31", "realized_pnl_dollar": 100.0},
        {"exit_date": "2026-04-10", "realized_pnl_dollar": 25.0},
        {"exit_date": "2026-04-10", "realized_pnl_dollar": 5.0},  # same day collapses
    ]
    curve = cumulative_curve(rows)
    assert curve == [
        {"date": "2026-04-10", "value": 30.0},
        {"date": "2026-05-31", "value": 130.0},
    ]
