from datetime import date, timedelta

from app.data.market import _nearest_expiration_in_window


def _d(days_out: int) -> str:
    return (date.today() + timedelta(days=days_out)).isoformat()


def test_picks_the_date_closest_to_window_centre():
    today = date.today()
    dates = [_d(10), _d(35), _d(60), _d(95), _d(200)]
    # window 30-90, centre 60 -> exact match at index 2
    result = _nearest_expiration_in_window(dates, (30, 90), today)
    assert result == dates[2]


def test_excludes_dates_outside_the_window():
    today = date.today()
    dates = [_d(10), _d(200)]
    # neither date is inside 30-90
    assert _nearest_expiration_in_window(dates, (30, 90), today) is None


def test_annual_window_finds_a_far_dated_expiry():
    today = date.today()
    dates = [_d(30), _d(90), _d(180), _d(365), _d(500)]
    # window 330-400, centre 365 -> exact match
    result = _nearest_expiration_in_window(dates, (330, 400), today)
    assert result == dates[3]


def test_empty_dates_returns_none():
    assert _nearest_expiration_in_window([], (30, 90), date.today()) is None
