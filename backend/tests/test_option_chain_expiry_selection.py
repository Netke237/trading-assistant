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


def test_an_expiry_exactly_at_the_floor_is_kept():
    # The validator rejects dte < min_dte, so an expiry AT the floor is valid
    # and must survive the filter (`>=`, not `>`).
    today = date(2026, 9, 29)
    dates = _dates(today, 199, 201, 263)
    assert _nearest_expiration_in_window(dates, (30, 400), today, min_dte_floor=201) == _dates(today, 201)[0]


# ── No hold window: the pick must respect the validator's min_dte ─────────────
#
# With no hold days the fetch took the first expiry of 21+ days whatever the
# contract rules said. A min_dte override of 45 then rejected every contract on
# that expiry as dte_too_short and the symbol silently dropped out of the scan.

import asyncio  # noqa: E402

import app.data.market as market  # noqa: E402
from app.data.market import _first_expiration_at_or_above, fetch_option_chain_async  # noqa: E402
from app.scoring.contract_validator import effective_min_dte, validate_contract  # noqa: E402


def test_no_window_pick_skips_expiries_below_a_45_day_floor():
    today = date(2026, 9, 29)
    dates = _dates(today, 7, 24, 31, 52, 80)
    assert _first_expiration_at_or_above(dates, today, None) == _dates(today, 24)[0]  # the old pick
    assert _first_expiration_at_or_above(dates, today, 45) == _dates(today, 52)[0]


def test_no_window_pick_keeps_an_expiry_exactly_at_the_floor():
    today = date(2026, 9, 29)
    assert _first_expiration_at_or_above(_dates(today, 24, 45, 80), today, 45) == _dates(today, 45)[0]


def test_no_window_pick_returns_none_when_nothing_reaches_the_floor():
    today = date(2026, 9, 29)
    assert _first_expiration_at_or_above(_dates(today, 7, 24, 31), today, 45) is None


def test_effective_min_dte_is_the_override_else_the_yaml():
    assert effective_min_dte(None) == 21
    assert effective_min_dte({}) == 21
    assert effective_min_dte({"min_dte": 45}) == 45
    assert effective_min_dte({"min_dte": "45"}) == 45  # cast as validate_contract casts it
    assert effective_min_dte({"max_delta": 0.6}) == 21


class _FakeTradier:
    """Answers the expirations and chains calls; records the chain expiry asked for."""

    def __init__(self, dates):
        self.dates = dates
        self.chain_expiries = []

    async def get(self, url, headers=None, params=None):
        if url.endswith("/expirations"):
            body = {"expirations": {"date": self.dates}}
        else:
            self.chain_expiries.append(params["expiration"])
            body = {"options": {"option": [{
                "symbol": "XOM", "option_type": "call", "strike": 110.0,
                "bid": 2.0, "ask": 2.2, "last": 2.1, "volume": 500, "open_interest": 900,
                "greeks": {"delta": 0.45, "theta": -0.04, "mid_iv": 0.3},
            }]}}

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return body
        return _R()


def test_fetch_with_a_45_day_min_dte_returns_contracts_the_validator_accepts(monkeypatch):
    today = date.today()
    dates = _dates(today, 24, 52, 80)
    monkeypatch.setattr(market, "_tradier_base", lambda: "https://sandbox.tradier.test")
    monkeypatch.setattr(market, "_headers", lambda *a, **k: {})
    monkeypatch.setitem(market._expirations_cache, "XOM", (dates, today.isoformat()))
    fake = _FakeTradier(dates)

    rules = {"min_dte": 45}
    chain = asyncio.run(fetch_option_chain_async(
        fake, "XOM", option_type="C", min_dte_floor=effective_min_dte(rules)))

    assert fake.chain_expiries == [_dates(today, 52)[0]]
    assert chain, "the fetch returned no contracts"
    assert all(c["dte"] >= 45 for c in chain)
    card = validate_contract({**chain[0], "symbol": "XOM"}, 80, overrides=rules)
    assert "dte_too_short" not in card.reject_reasons
