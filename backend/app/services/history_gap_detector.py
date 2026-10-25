"""Canonical NYSE trading calendar and history gap detector (#558).

Pure Python, zero-external-dependency implementation of canonical US equity
exchange trading days (NYSE/NASDAQ/AMEX), standard holidays, NYSE Rule 7.2
Saturday holiday exception, and historical unscheduled closures.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

# Explicit historical unscheduled closures
SPECIAL_CLOSURES: set[date] = {
    # 9/11 attacks
    date(2001, 9, 11),
    date(2001, 9, 12),
    date(2001, 9, 13),
    date(2001, 9, 14),
    # Ronald Reagan National Day of Mourning
    date(2004, 6, 11),
    # Gerald Ford National Day of Mourning
    date(2007, 1, 2),
    # Hurricane Sandy
    date(2012, 10, 29),
    date(2012, 10, 30),
    # George H.W. Bush National Day of Mourning
    date(2018, 12, 5),
    # Jimmy Carter National Day of Mourning (January 9, 2025)
    date(2025, 1, 9),
}


def compute_easter_sunday(year: int) -> date:
    """Compute Gregorian Easter Sunday using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


_HOLIDAYS_CACHE: dict[int, set[date]] = {}


def get_nyse_holidays_for_year(year: int) -> set[date]:
    """Compute all standard observed NYSE holidays falling within calendar year."""
    if year in _HOLIDAYS_CACHE:
        return _HOLIDAYS_CACHE[year]
    holidays: set[date] = set()

    # 1. New Year's Day (Jan 1)
    # Observed Monday if Jan 1 is Sunday.
    # Under NYSE Rule 7.2, if Jan 1 is Saturday, Friday Dec 31 is NOT a holiday.
    nyd = date(year, 1, 1)
    if nyd.weekday() < 5:  # Mon-Fri
        holidays.add(nyd)
    elif nyd.weekday() == 6:  # Sunday -> observed Monday Jan 2
        holidays.add(date(year, 1, 2))

    # 2. Martin Luther King Jr. Day (third Monday in January)
    first_mon_jan = 1 + (0 - date(year, 1, 1).weekday()) % 7
    holidays.add(date(year, 1, first_mon_jan + 14))

    # 3. Washington's Birthday / Presidents' Day (third Monday in February)
    first_mon_feb = 1 + (0 - date(year, 2, 1).weekday()) % 7
    holidays.add(date(year, 2, first_mon_feb + 14))

    # 4. Good Friday (Friday before Easter Sunday)
    easter = compute_easter_sunday(year)
    holidays.add(easter - timedelta(days=2))

    # 5. Memorial Day (last Monday in May)
    last_day_may = date(year, 5, 31)
    holidays.add(date(year, 5, 31 - last_day_may.weekday()))

    # 6. Juneteenth National Independence Day (June 19, effective 2022 onward)
    if year >= 2022:
        june19 = date(year, 6, 19)
        if june19.weekday() == 6:  # Sunday -> Monday
            holidays.add(date(year, 6, 20))
        elif june19.weekday() == 5:  # Saturday -> Friday
            holidays.add(date(year, 6, 18))
        else:
            holidays.add(june19)

    # 7. Independence Day (July 4)
    july4 = date(year, 7, 4)
    if july4.weekday() == 6:  # Sunday -> Monday
        holidays.add(date(year, 7, 5))
    elif july4.weekday() == 5:  # Saturday -> Friday
        holidays.add(date(year, 7, 3))
    else:
        holidays.add(july4)

    # 8. Labor Day (first Monday in September)
    first_mon_sep = 1 + (0 - date(year, 9, 1).weekday()) % 7
    holidays.add(date(year, 9, first_mon_sep))

    # 9. Thanksgiving Day (fourth Thursday in November)
    first_thu_nov = 1 + (3 - date(year, 11, 1).weekday()) % 7
    holidays.add(date(year, 11, first_thu_nov + 21))

    # 10. Christmas Day (December 25)
    dec25 = date(year, 12, 25)
    if dec25.weekday() == 6:  # Sunday -> Monday
        holidays.add(date(year, 12, 26))
    elif dec25.weekday() == 5:  # Saturday -> Friday
        holidays.add(date(year, 12, 24))
    else:
        holidays.add(dec25)

    _HOLIDAYS_CACHE[year] = holidays
    return holidays


def is_nyse_trading_day(d: date) -> bool:
    """Return True if the date is a canonical NYSE trading day, False otherwise."""
    # Weekends (Saturday=5, Sunday=6)
    if d.weekday() >= 5:
        return False
    # Explicit historical unscheduled closures
    if d in SPECIAL_CLOSURES:
        return False
    # Standard NYSE holidays
    if d in get_nyse_holidays_for_year(d.year):
        return False
    return True


def get_nyse_trading_days(start: date, end: date) -> list[date]:
    """Return all canonical NYSE trading days between start and end (inclusive)."""
    if start > end:
        return []
    trading_days: list[date] = []
    curr = start
    one_day = timedelta(days=1)
    while curr <= end:
        if is_nyse_trading_day(curr):
            trading_days.append(curr)
        curr += one_day
    return trading_days


def detect_history_gaps(
    symbol: str,
    dates: Iterable[date | str],
    start: date | None = None,
    end: date | None = None,
) -> list[date]:
    """Detect missing NYSE trading days within a symbol's date span or given window.

    Args:
        symbol: Ticker symbol (used for logging or future delisting lookups).
        dates: Collection of existing dates (can be `date` objects or 'YYYY-MM-DD' strings).
        start: Optional start date. If None, defaults to min(dates).
        end: Optional end date. If None, defaults to max(dates).

    Returns:
        List of missing trading days in chronological order.
    """
    parsed_dates: set[date] = set()
    for d in dates:
        if isinstance(d, str):
            parsed_dates.add(date.fromisoformat(d[:10]))
        elif isinstance(d, date):
            parsed_dates.add(d)

    effective_start = start if start is not None else (min(parsed_dates) if parsed_dates else None)
    effective_end = end if end is not None else (max(parsed_dates) if parsed_dates else None)

    if effective_start is None or effective_end is None or effective_start > effective_end:
        return []

    expected = get_nyse_trading_days(effective_start, effective_end)
    return [d for d in expected if d not in parsed_dates]
