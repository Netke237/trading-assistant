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


# ── The pick must respect the validator's floor ───────────────────────────────
#
# Only one expiry is fetched per symbol. When the centre-nearest listed expiry
# sat below the contract validator's floor (dte_window.widened_min_dte, never
# under hold_max + 1), every contract came back dte_too_short and the WHOLE
# symbol was rejected, even though a valid expiry was listed. Both cases below
# are the calendars that did it.

from app.scoring.dte_window import widened_min_dte  # noqa: E402


def _dates(today, *dtes):
    return [(today + timedelta(days=n)).isoformat() for n in dtes]


def test_custom_15_200_hold_skips_an_expiry_below_the_201_floor():
    today = date(2026, 9, 29)
    # Custom 15-200d at multiplier 2: window (30, 400), centre 215, floor 201.
    floor = widened_min_dte(30, 200)
    assert floor == 201
    dates = _dates(today, 199, 263, 381)
    assert _nearest_expiration_in_window(dates, (30, 400), today) == _dates(today, 199)[0]  # the old pick
    assert _nearest_expiration_in_window(dates, (30, 400), today, min_dte_floor=floor) == _dates(today, 263)[0]


def test_intraday_on_a_wednesday_skips_fridays_2_day_weekly():
    today = date(2026, 9, 30)  # a Wednesday
    floor = widened_min_dte(1, 2)  # Intraday: window (1, 4), hold_max 2
    assert floor == 3
    dates = _dates(today, 2, 9, 16)
    assert _nearest_expiration_in_window(dates, (1, 4), today) == _dates(today, 2)[0]  # the old pick
    # Nothing in [3, 4]; the tolerance margin reaches 14, so next Friday (9d).
    assert _nearest_expiration_in_window(dates, (1, 4), today, min_dte_floor=floor) == _dates(today, 9)[0]


def test_no_floor_keeps_the_old_behaviour():
    today = date(2026, 9, 29)
    dates = _dates(today, 199, 263)
    assert (_nearest_expiration_in_window(dates, (30, 400), today, min_dte_floor=None)
            == _nearest_expiration_in_window(dates, (30, 400), today))


def test_nothing_at_or_above_the_floor_returns_none():
    today = date(2026, 9, 29)
    assert _nearest_expiration_in_window(_dates(today, 150, 199), (30, 400), today, min_dte_floor=201) is None
