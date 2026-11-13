"""Tests for canonical NYSE trading calendar and history gap detector (#558)."""
from __future__ import annotations

from datetime import date
import pytest

from app.services.history_gap_detector import (
    is_nyse_trading_day,
    get_nyse_trading_days,
    detect_history_gaps,
    compute_easter_sunday,
)


def test_compute_easter_sunday_butchers_algorithm():
    # Known Gregorian Easter dates
    assert compute_easter_sunday(2008) == date(2008, 3, 23)
    assert compute_easter_sunday(2011) == date(2011, 4, 24)
    assert compute_easter_sunday(2021) == date(2021, 4, 4)
    assert compute_easter_sunday(2022) == date(2022, 4, 17)
    assert compute_easter_sunday(2023) == date(2023, 4, 9)
    assert compute_easter_sunday(2024) == date(2024, 3, 31)
    assert compute_easter_sunday(2025) == date(2025, 4, 20)
    assert compute_easter_sunday(2026) == date(2026, 4, 5)


def test_standard_nyse_holidays_recognized_as_non_trading_days():
    # New Year's Day
    assert not is_nyse_trading_day(date(2021, 1, 1))  # Friday
    assert not is_nyse_trading_day(date(2023, 1, 2))  # Monday observed (Jan 1 Sunday)
    assert not is_nyse_trading_day(date(2024, 1, 1))  # Monday

    # Martin Luther King Jr. Day (3rd Monday in January)
    assert not is_nyse_trading_day(date(2021, 1, 18))
    assert not is_nyse_trading_day(date(2022, 1, 17))
    assert not is_nyse_trading_day(date(2023, 1, 16))
    assert not is_nyse_trading_day(date(2024, 1, 15))

    # Washington's Birthday / Presidents' Day (3rd Monday in February)
    assert not is_nyse_trading_day(date(2021, 2, 15))
    assert not is_nyse_trading_day(date(2022, 2, 21))
    assert not is_nyse_trading_day(date(2023, 2, 20))
    assert not is_nyse_trading_day(date(2024, 2, 19))

    # Good Friday (Friday before Easter Sunday)
    assert not is_nyse_trading_day(date(2021, 4, 2))
    assert not is_nyse_trading_day(date(2022, 4, 15))
    assert not is_nyse_trading_day(date(2023, 4, 7))
    assert not is_nyse_trading_day(date(2024, 3, 29))
    assert not is_nyse_trading_day(date(2025, 4, 18))
    assert not is_nyse_trading_day(date(2026, 4, 3))

    # Memorial Day (Last Monday in May)
    assert not is_nyse_trading_day(date(2021, 5, 31))
    assert not is_nyse_trading_day(date(2022, 5, 30))
    assert not is_nyse_trading_day(date(2023, 5, 29))
    assert not is_nyse_trading_day(date(2024, 5, 27))

    # Juneteenth (June 19, observed 2022 onward)
    # In 2021: not yet observed by NYSE
    assert is_nyse_trading_day(date(2021, 6, 18))
    # 2022: June 19 was Sunday, observed Monday June 20
    assert not is_nyse_trading_day(date(2022, 6, 20))
    # 2023: June 19 was Monday
    assert not is_nyse_trading_day(date(2023, 6, 19))
    # 2024: June 19 was Wednesday
    assert not is_nyse_trading_day(date(2024, 6, 19))

    # Independence Day (July 4)
    assert not is_nyse_trading_day(date(2021, 7, 5))  # Observed Monday (July 4 Sunday)
    assert not is_nyse_trading_day(date(2022, 7, 4))  # Monday
    assert not is_nyse_trading_day(date(2023, 7, 4))  # Tuesday
    assert not is_nyse_trading_day(date(2024, 7, 4))  # Thursday

    # Labor Day (1st Monday in September)
    assert not is_nyse_trading_day(date(2021, 9, 6))
    assert not is_nyse_trading_day(date(2022, 9, 5))
    assert not is_nyse_trading_day(date(2023, 9, 4))
    assert not is_nyse_trading_day(date(2024, 9, 2))

    # Thanksgiving Day (4th Thursday in November)
    assert not is_nyse_trading_day(date(2021, 11, 25))
    assert not is_nyse_trading_day(date(2022, 11, 24))
    assert not is_nyse_trading_day(date(2023, 11, 23))
    assert not is_nyse_trading_day(date(2024, 11, 28))

    # Christmas Day (Dec 25)
    assert not is_nyse_trading_day(date(2021, 12, 24))  # Observed Friday (Dec 25 Saturday)
    assert not is_nyse_trading_day(date(2022, 12, 26))  # Observed Monday (Dec 25 Sunday)
    assert not is_nyse_trading_day(date(2023, 12, 25))  # Monday
    assert not is_nyse_trading_day(date(2024, 12, 25))  # Wednesday


def test_nyse_rule_7_2_saturday_new_years_day():
    # Under NYSE Rule 7.2, when Jan 1 falls on a Saturday, Friday Dec 31
    # is NOT observed as a holiday because it marks the end of the yearly accounting period.
    # Therefore, Friday Dec 31, 2021 is a normal trading day!
    assert is_nyse_trading_day(date(2021, 12, 31)) is True
    # Similarly, Jan 1, 2011 was a Saturday; Friday Dec 31, 2010 was a normal trading day.
    assert is_nyse_trading_day(date(2010, 12, 31)) is True


def test_historical_unscheduled_closures():
    # 9/11 attacks (closed 2001-09-11 through 2001-09-14)
    assert not is_nyse_trading_day(date(2001, 9, 11))
    assert not is_nyse_trading_day(date(2001, 9, 12))
    assert not is_nyse_trading_day(date(2001, 9, 13))
    assert not is_nyse_trading_day(date(2001, 9, 14))
    # Monday 2001-09-17 reopened
    assert is_nyse_trading_day(date(2001, 9, 17)) is True

    # Ronald Reagan National Day of Mourning: 2004-06-11
    assert not is_nyse_trading_day(date(2004, 6, 11))

    # Gerald Ford National Day of Mourning: 2007-01-02
    assert not is_nyse_trading_day(date(2007, 1, 2))

    # Hurricane Sandy: 2012-10-29 and 2012-10-30
    assert not is_nyse_trading_day(date(2012, 10, 29))
    assert not is_nyse_trading_day(date(2012, 10, 30))
    # Reopened Wednesday 2012-10-31
    assert is_nyse_trading_day(date(2012, 10, 31)) is True

    # George H.W. Bush National Day of Mourning: 2018-12-05
    assert not is_nyse_trading_day(date(2018, 12, 5))

    # Jimmy Carter National Day of Mourning: 2025-01-09
    assert not is_nyse_trading_day(date(2025, 1, 9))


def test_carter_national_day_of_mourning_is_non_trading_day():
    assert not is_nyse_trading_day(date(2025, 1, 9))


def test_key_problematic_trading_days():
    # All 3 problem days from #535 must be confirmed as legitimate NYSE trading days
    assert is_nyse_trading_day(date(2021, 4, 19)) is True  # Monday
    assert is_nyse_trading_day(date(2021, 10, 25)) is True  # Monday
    assert is_nyse_trading_day(date(2022, 3, 8)) is True  # Tuesday


def test_weekends_are_not_trading_days():
    # Saturday
    assert not is_nyse_trading_day(date(2022, 3, 5))
    # Sunday
    assert not is_nyse_trading_day(date(2022, 3, 6))


def test_get_nyse_trading_days():
    # Spanning year end 2021 to 2022:
    # 2021-12-30 (Thu): Trading day
    # 2021-12-31 (Fri): Trading day (Rule 7.2)
    # 2022-01-01 (Sat): Weekend
    # 2022-01-02 (Sun): Weekend
    # 2022-01-03 (Mon): Trading day
    # 2022-01-04 (Tue): Trading day
    days = get_nyse_trading_days(date(2021, 12, 30), date(2022, 1, 4))
    expected = [
        date(2021, 12, 30),
        date(2021, 12, 31),
        date(2022, 1, 3),
        date(2022, 1, 4),
    ]
    assert days == expected

    # Inverted range returns empty list
    assert get_nyse_trading_days(date(2022, 1, 4), date(2021, 12, 30)) == []


def test_detect_history_gaps_finds_missing_days():
    # Missing 2022-03-08
    stored_dates = [
        date(2022, 3, 4),  # Friday
        date(2022, 3, 7),  # Monday
        # missing 2022-03-08 Tuesday
        date(2022, 3, 9),  # Wednesday
        date(2022, 3, 10), # Thursday
    ]
    gaps = detect_history_gaps("SRE", stored_dates)
    assert gaps == [date(2022, 3, 8)]


def test_detect_history_gaps_clean_series_has_no_gaps():
    complete_dates = [
        date(2022, 3, 7),
        date(2022, 3, 8),
        date(2022, 3, 9),
        date(2022, 3, 10),
    ]
    gaps = detect_history_gaps("AAPL", complete_dates)
    assert gaps == []


def test_detect_history_gaps_with_string_dates():
    str_dates = ["2021-10-22", "2021-10-26"]  # Friday to Tuesday (skips weekend 23-24, missing Monday 25)
    gaps = detect_history_gaps("SRE", str_dates)
    assert gaps == [date(2021, 10, 25)]


def test_detect_history_gaps_with_explicit_range():
    stored = {date(2021, 4, 20)}
    # 2021-04-19 is Monday, 2021-04-20 is Tuesday, 2021-04-21 is Wednesday
    gaps = detect_history_gaps(
        "SRE",
        stored,
        start=date(2021, 4, 19),
        end=date(2021, 4, 21),
    )
    assert gaps == [date(2021, 4, 19), date(2021, 4, 21)]


def test_detect_history_gaps_empty_dates():
    # No dates and no bounds -> empty
    assert detect_history_gaps("SRE", []) == []

    # No dates but explicit bounds -> all trading days in range
    gaps = detect_history_gaps(
        "SRE", [], start=date(2022, 3, 7), end=date(2022, 3, 8)
    )
    assert gaps == [date(2022, 3, 7), date(2022, 3, 8)]
