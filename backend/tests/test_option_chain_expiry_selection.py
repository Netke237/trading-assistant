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


def test_excludes_dates_outside_the_window_and_its_tolerance():
    today = date.today()
    dates = [_d(10), _d(200)]
    # neither date is inside 30-90, nor within the default 10-day tolerance
    assert _nearest_expiration_in_window(dates, (30, 90), today) is None


def test_falls_back_to_nearest_expiry_within_tolerance_when_window_is_empty():
    today = date.today()
    # Reproduces the Semi-annual (180-210d) gap: AAPL/GOOGL/ABT/ADBE all list
    # a monthly expiry at 179d and the next one at 214d, straddling the
    # window by 1 and 4 days respectively — previously this returned None
    # and killed every symbol's chain fetch outright.
    dates = [_d(151), _d(179), _d(214), _d(242)]
    result = _nearest_expiration_in_window(dates, (180, 210), today)
    assert result == _d(179)  # 179 (16d from centre 195) beats 214 (19d away)


def test_tolerance_fallback_still_returns_none_when_nothing_is_close_enough():
    today = date.today()
    dates = [_d(10), _d(500)]
    # window 180-210 with default 10d tolerance -> checks 170-220, neither qualifies
    assert _nearest_expiration_in_window(dates, (180, 210), today) is None


def test_annual_window_finds_a_far_dated_expiry():
    today = date.today()
    dates = [_d(30), _d(90), _d(180), _d(365), _d(500)]
    # window 330-400, centre 365 -> exact match
    result = _nearest_expiration_in_window(dates, (330, 400), today)
    assert result == dates[3]


def test_empty_dates_returns_none():
    assert _nearest_expiration_in_window([], (30, 90), date.today()) is None
