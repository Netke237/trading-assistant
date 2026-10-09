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


def test_custom_15_200_hold_skips_an_expiry_below_the_221_floor():
    today = date(2026, 9, 29)
    # Custom 15-200d at multiplier 2: window (30, 400), centre 215, floor 201.
    floor = widened_min_dte(221, 200)
    assert floor == 221
    dates = _dates(today, 199, 263, 381)
    assert _nearest_expiration_in_window(dates, (30, 400), today) == _dates(today, 199)[0]  # the old pick
    assert _nearest_expiration_in_window(dates, (30, 400), today, min_dte_floor=floor) == _dates(today, 263)[0]


def test_intraday_on_a_wednesday_skips_expiries_under_23_days():
    today = date(2026, 9, 30)
    # hold2 + buffer21 sets floor23; ideal span35 gives window23-58.
    floor = widened_min_dte(23, 2)
    assert floor == 23
    dates = _dates(today, 2, 9, 23, 44)
    assert _nearest_expiration_in_window(dates, (23, 58), today, min_dte_floor=floor) == _dates(today, 44)[0]


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


# ── No hold window: the pick must respect the validator's DTE limits ────────
#
# With no hold days the fetch took the first expiry of 21+ days whatever the
# contract rules said. A min_dte override of 45 then rejected every contract on
# that expiry as dte_too_short and the symbol silently dropped out of the scan.

import asyncio  # noqa: E402

import pytest  # noqa: E402

import app.data.market as market  # noqa: E402
from app.data.market import (  # noqa: E402
    _DEFAULT_MIN_DTE_FLOOR, _pick_expiration_without_window, fetch_option_chain, fetch_option_chain_async,
)
from app.scoring.contract_validator import _load_config, effective_dte_limits, validate_contract  # noqa: E402

_TODAY = date(2026, 9, 29)


def _pick(limits, *dtes):
    return _pick_expiration_without_window(_dates(_TODAY, *dtes), _TODAY, limits)


def test_no_window_pick_skips_expiries_below_a_45_day_min_dte():
    assert _pick(None, 7, 24, 31, 52, 80) == _dates(_TODAY, 24)[0]  # the old pick
    assert _pick((45, 21, 60, 90), 7, 24, 31, 52, 80) == _dates(_TODAY, 52)[0]


def test_no_window_pick_keeps_an_expiry_exactly_at_min_dte():
    assert _pick((45, 21, 60, 90), 24, 45, 80) == _dates(_TODAY, 45)[0]


def test_no_window_pick_never_goes_above_max_dte():
    # min_dte 85 against the YAML max_dte 90: the first expiry >= 85 is 108,
    # every contract of which the validator rejects as dte_too_long.
    assert _pick((85, 21, 60, 90), 80, 108, 171) is None
    assert _pick((45, 21, 60, 50), 24, 52) is None
    assert _pick((45, 21, 60, 90), 24, 90, 108) == _dates(_TODAY, 90)[0]  # exactly at max_dte is kept


def test_no_window_pick_returns_none_when_nothing_is_in_range():
    assert _pick((45, 21, 60, 90), 7, 24, 31) is None
    assert _pick((45, 21, 60, 90)) is None


def test_lowering_min_dte_still_prefers_the_preferred_band():
    # min_dte 5 lets a weekly pass the hard check; the pick still keeps the
    # old 21+ choice, the shortest expiry inside the preferred band.
    assert _pick((5, 21, 60, 90), 6, 13, 24, 52) == _dates(_TODAY, 24)[0]
    # Nothing in the band is in range: the in-range expiry closest to it, not
    # the shortest (which scores worst and decays fastest).
    assert _pick((5, 21, 60, 20), 6, 13, 24) == _dates(_TODAY, 13)[0]


def test_no_window_pick_respects_preferred_dte_max():
    # A narrow 40-45 band: 39 is 1 day off it, 80 is 35 days off.
    assert _pick((21, 40, 45, 90), 39, 80) == _dates(_TODAY, 39)[0]
    # Equally far either side: the shorter one.
    assert _pick((21, 40, 45, 90), 35, 50) == _dates(_TODAY, 35)[0]
    # ... whatever order the listing comes in.
    assert _pick_expiration_without_window(
        list(reversed(_dates(_TODAY, 35, 50))), _TODAY, (21, 40, 45, 90)) == _dates(_TODAY, 35)[0]


def test_no_window_pick_takes_the_nearest_expiry_inside_the_band():
    assert _pick((21, 21, 60, 90), 7, 24, 31, 59, 80) == _dates(_TODAY, 24)[0]


def test_shipped_rules_pick_what_the_old_fixed_21_picked():
    limits = effective_dte_limits(None)
    for dtes in [(7, 24, 31), (3, 21, 49), (10, 20, 22), (1, 2), (7, 75, 88), (7, 61, 120)]:
        assert _pick(limits, *dtes) == _pick(None, *dtes), dtes
    # The one difference: the old pick could land past max_dte 90, where every
    # contract was rejected dte_too_long. Nothing is fetched instead.
    assert _pick(None, 7, 100) == _dates(_TODAY, 100)[0]
    assert _pick(limits, 7, 100) is None


def test_no_window_pick_does_not_trust_the_listing_order():
    dates = list(reversed(_dates(_TODAY, 7, 24, 52, 80)))
    assert _pick_expiration_without_window(dates, _TODAY, (45, 21, 60, 90)) == _dates(_TODAY, 52)[0]


def test_a_malformed_listing_entry_fails_only_the_rules_path():
    # The legacy (no rules) pick stops at the first 21+ day expiry, as the old
    # code did; with rules every entry is parsed and the bad one raises.
    dates = _dates(_TODAY, 31) + ["zzzz-bad"]
    assert _pick_expiration_without_window(dates, _TODAY, None) == _dates(_TODAY, 31)[0]
    with pytest.raises(ValueError):
        _pick_expiration_without_window(dates, _TODAY, (21, 21, 60, 90))


def test_default_floor_is_the_yaml_min_dte():
    assert _DEFAULT_MIN_DTE_FLOOR == _load_config()["hard_reject"]["min_dte"]


def test_effective_dte_limits_are_the_overrides_else_the_yaml():
    cfg = _load_config()
    yaml = (cfg["hard_reject"]["min_dte"], cfg["soft_rank"]["preferred_dte_min"],
            cfg["soft_rank"]["preferred_dte_max"], cfg["hard_reject"]["max_dte"])
    assert effective_dte_limits(None) == yaml == (21, 21, 60, 90)
    assert effective_dte_limits({}) == yaml
    assert effective_dte_limits({"max_delta": 0.6}) == yaml
    assert effective_dte_limits({"min_dte": 45}) == (45, 21, 60, 90)
    assert effective_dte_limits({"min_dte": "45", "max_dte": 60.9}) == (45, 21, 60, 60)  # cast as validate_contract casts
    assert effective_dte_limits({"preferred_dte_min": 30, "preferred_dte_max": 45}) == (21, 30, 45, 90)


class _FakeTradier:
    """Answers the expirations and chains calls; records the chain expiry asked for."""

    def __init__(self, dates, quote_stamp_ms=None):
        self.dates = dates
        self.chain_expiries = []
        # NO-LIVE-QUOTE: bid_date/ask_date for the row, so a test that grades
        # it can make the quote live (no stamps reads `stale`).
        self.quote_stamp_ms = quote_stamp_ms

    def get(self, url, headers=None, params=None, **_):
        if url.endswith("/expirations"):
            body = {"expirations": {"date": self.dates}}
        else:
            self.chain_expiries.append(params["expiration"])
            row = {
                "symbol": "XOM", "option_type": "call", "strike": 110.0,
                "bid": 2.0, "ask": 2.2, "last": 2.1, "volume": 500, "open_interest": 900,
                "greeks": {"delta": 0.45, "theta": -0.04, "mid_iv": 0.3},
            }
            if self.quote_stamp_ms is not None:
                row["bid_date"] = row["ask_date"] = self.quote_stamp_ms
            body = {"options": {"option": [row]}}

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return body
        return _R()


class _AsyncFakeTradier(_FakeTradier):
    async def get(self, url, headers=None, params=None, **_):
        return _FakeTradier.get(self, url, headers=headers, params=params)


def _patch_tradier(monkeypatch):
    monkeypatch.setattr(market, "_tradier_base", lambda: "https://sandbox.tradier.test")
    monkeypatch.setattr(market, "_headers", lambda *a, **k: {})


def test_async_fetch_with_a_45_day_min_dte_returns_contracts_the_validator_accepts(monkeypatch):
    import app.services.market_session as _session

    today = date.today()
    dates = _dates(today, 24, 52, 80)
    _patch_tradier(monkeypatch)
    monkeypatch.setitem(market._expirations_cache, "XOM", (dates, today.isoformat()))
    # NO-LIVE-QUOTE NLQ-2: the validator now rejects a row whose quote is not
    # live WITHOUT judging its DTE, which would make the DTE assertion below
    # pass vacuously. So the row is made live (in session, a 5-second-old
    # two-sided quote) and the test asserts it is.
    _now_s = 1_791_216_001.0
    monkeypatch.setattr(_session, "_market_session_open", lambda *a, **k: True)
    monkeypatch.setattr(market, "_now", lambda: _now_s)
    fake = _AsyncFakeTradier(dates, quote_stamp_ms=int((_now_s - 5) * 1000))

    rules = {"min_dte": 45}
    chain = asyncio.run(fetch_option_chain_async(
        fake, "XOM", option_type="C", dte_limits=effective_dte_limits(rules)))

    assert fake.chain_expiries == [_dates(today, 52)[0]]
    assert chain, "the fetch returned no contracts"
    assert chain[0]["quoteLive"] is True, chain[0]
    card = validate_contract({**chain[0], "symbol": "XOM"}, 80, overrides=rules)
    assert "no_live_quote" not in card.reject_reasons
    assert not {"dte_too_short", "dte_too_long"} & set(card.reject_reasons), card.reject_reasons


def test_async_fetch_asks_for_no_chain_when_no_expiry_is_in_range(monkeypatch):
    today = date.today()
    dates = _dates(today, 24, 108)
    _patch_tradier(monkeypatch)
    monkeypatch.setitem(market._expirations_cache, "XOM", (dates, today.isoformat()))
    fake = _AsyncFakeTradier(dates)
    assert asyncio.run(fetch_option_chain_async(fake, "XOM", dte_limits=(45, 21, 60, 90))) == []
    assert fake.chain_expiries == []


def test_sync_fetch_uses_the_same_no_window_pick(monkeypatch):
    today = date.today()
    fake = _FakeTradier(_dates(today, 24, 52, 80))
    _patch_tradier(monkeypatch)
    monkeypatch.setattr(market.httpx, "get", fake.get)
    assert fetch_option_chain("XOM", dte_limits=(45, 21, 60, 90))
    assert fake.chain_expiries == [_dates(today, 52)[0]]


# ── NO-LIVE-QUOTE NLQ-1 (plan 3a, test T3): every row's quote liveness ──────
#
# Both builders, run through the same fake Tradier: every emitted row carries
# quoteState / quoteLive / quoteAgeS and never bid / ask (scan.py's bearish
# spread builder reads those off raw chain rows -- adding them would switch an
# unaudited path on); a row with no ask is dropped (it used to be kept at the
# last price with a fabricated 0.0 spread); price and spread are unchanged for
# every kept row; the session flag and `now` are read once per fetch; the
# sandbox feed lag is applied.

import app.services.market_session as market_session  # noqa: E402

_Q_NOW = 1_791_216_001.0   # 2026-10-05 12:00:01 ET (the in-session Step 0 capture)


def _stamp(age_s):
    return int((_Q_NOW - age_s) * 1000)


def _opt(strike, bid, ask, *, last=None, bd=None, ad=None, right="call"):
    o = {"symbol": f"XOM-{strike}", "option_type": right, "strike": float(strike),
         "bid": bid, "ask": ask, "last": last, "volume": 500, "open_interest": 900,
         "implied_volatility": 0.3, "greeks": {"delta": 0.45, "theta": -0.04}}
    if bd is not None:
        o["bid_date"] = bd
    if ad is not None:
        o["ask_date"] = ad
    return o


_Q_CHAIN = [
    _opt(100, 2.0, 2.2, last=2.1, bd=_stamp(4), ad=_stamp(9)),          # two-sided, seconds old
    _opt(105, 0.0, 0.41, last=0.3, bd=_stamp(4), ad=_stamp(9)),         # no bid
    _opt(110, 0.0, 0.0, last=1.5, bd=_stamp(4), ad=_stamp(9)),          # no ask, a last price: dropped
    _opt(115, 0.5, 0.0, last=0.0),                                      # no ask, no last: dropped
    _opt(120, 1.0, 1.3, bd=_stamp(7200), ad=_stamp(5400)),              # two-sided, 90 min old
    _opt(125, 1.0, 1.3),                                                # two-sided, no stamps
    _opt(130, 0.7, 0.9, bd=_stamp(2400), ad=_stamp(3600)),              # fresher side 40 min old
    _opt(100, 3.0, 3.2, bd=_stamp(4), ad=_stamp(4), right="put"),       # other right: not emitted
]


class _QuoteFake:
    def __init__(self, dates, options):
        self.dates, self.options = dates, options

    def get(self, url, headers=None, params=None, **_):
        body = ({"expirations": {"date": self.dates}} if url.endswith("/expirations")
                else {"options": {"option": [dict(o) for o in self.options]}})

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return body
        return _R()


class _AsyncQuoteFake(_QuoteFake):
    async def get(self, url, headers=None, params=None, **_):
        return _QuoteFake.get(self, url, headers=headers, params=params)


class _Counted:
    def __init__(self, *values):
        self.values, self.calls = list(values), 0

    def __call__(self, *a, **k):
        self.calls += 1
        return self.values[min(self.calls, len(self.values)) - 1]


def _run_builder(which, monkeypatch, *, base="https://api.tradier.com", session=(True,), now=(_Q_NOW,),
                 options=_Q_CHAIN):
    """Run one builder offline; returns (rows, session_counter, clock_counter)."""
    today = date.today()
    dates = _dates(today, 45)
    monkeypatch.setattr(market, "_tradier_base", lambda: base)
    monkeypatch.setattr(market, "_headers", lambda *a, **k: {})
    monkeypatch.setattr("app.data.ibkr.fetch_iv_metrics_ibkr", lambda *a, **k: None)
    monkeypatch.setattr("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", lambda *a, **k: None)
    monkeypatch.setattr(market, "_yf_iv_for_chain", lambda *a, **k: {})
    session_fn, clock = _Counted(*session), _Counted(*now)
    monkeypatch.setattr(market_session, "_market_session_open", session_fn)
    monkeypatch.setattr(market, "_now", clock)
    if which == "sync":
        monkeypatch.setattr(market.httpx, "get", _QuoteFake(dates, options).get)
        rows = fetch_option_chain("XOM", option_type="C", dte_limits=(21, 21, 60, 90))
    else:
        rows = asyncio.run(fetch_option_chain_async(
            _AsyncQuoteFake(dates, options), "XOM", option_type="C", dte_limits=(21, 21, 60, 90)))
    return rows, session_fn, clock


_BUILDERS = pytest.mark.parametrize("which", ["sync", "async"])


@_BUILDERS
def test_every_row_carries_the_quote_keys_and_never_bid_or_ask(which, monkeypatch):
    rows, _, _ = _run_builder(which, monkeypatch)
    assert rows
    for r in rows:
        assert {"quoteState", "quoteLive", "quoteAgeS"} <= set(r), r
        assert r["quoteLive"] is (r["quoteState"] == "live")
        assert "bid" not in r and "ask" not in r, r


@_BUILDERS
def test_rows_with_no_ask_are_dropped(which, monkeypatch):
    rows, _, _ = _run_builder(which, monkeypatch)
    assert sorted(r["strike"] for r in rows) == [100, 105, 120, 125, 130]
    assert all(r["spread"] > 0 for r in rows), "no row may carry a fabricated 0.0 spread"


@_BUILDERS
def test_price_and_spread_are_unchanged_for_kept_rows(which, monkeypatch):
    rows, _, _ = _run_builder(which, monkeypatch)
    got = {r["strike"]: (r["price"], r["spread"]) for r in rows}
    assert got == {
        100: (2.1, 0.2),
        105: (0.2, 0.41),     # bid 0: price = ask/2 (round(0.205, 2) == 0.2), spread = ask
        120: (1.15, 0.3),
        125: (1.15, 0.3),
        130: (0.8, 0.2),
    }


@_BUILDERS
def test_quote_states_in_session(which, monkeypatch):
    rows, _, _ = _run_builder(which, monkeypatch)
    got = {r["strike"]: (r["quoteState"], r["quoteAgeS"]) for r in rows}
    assert got == {
        100: ("live", 4.0),
        105: ("one_sided", 4.0),
        120: ("stale", 5400.0),
        125: ("stale", None),
        130: ("stale", 2400.0),
    }


@_BUILDERS
def test_quote_states_outside_the_session(which, monkeypatch):
    rows, _, _ = _run_builder(which, monkeypatch, session=(False,))
    got = {r["strike"]: r["quoteState"] for r in rows}
    assert got == {100: "session_closed", 105: "one_sided", 120: "session_closed",
                   125: "session_closed", 130: "session_closed"}
    assert not any(r["quoteLive"] for r in rows)


@_BUILDERS
def test_session_flag_and_now_are_read_once_per_fetch(which, monkeypatch):
    # A second read would see the session closed and the clock an hour on.
    rows, session_fn, clock = _run_builder(which, monkeypatch, session=(True, False),
                                           now=(_Q_NOW, _Q_NOW + 3600))
    assert session_fn.calls == 1
    assert clock.calls == 1
    states = {r["strike"]: r["quoteState"] for r in rows}
    assert states[100] == "live"
    assert all(r["quoteAgeS"] in (4.0, 5400.0, 2400.0, None) for r in rows)


@_BUILDERS
def test_the_sandbox_feed_lag_is_applied(which, monkeypatch):
    # 15-minute-delayed quotes: 40 minutes on the wall clock is 25 in the feed's.
    rows, _, _ = _run_builder(which, monkeypatch, base="https://sandbox.tradier.com")
    got = {r["strike"]: (r["quoteState"], r["quoteAgeS"]) for r in rows}
    assert got[130] == ("live", 1500.0)
    assert got[100] == ("live", -896.0)
    assert got[120] == ("stale", 4500.0)
