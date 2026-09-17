"""VWAP must be session-anchored, and therefore independent of how much history
the caller loaded. Before this, _calc_vwap accumulated across the whole array,
so widening the chart lookback silently moved every reading and every alert
compared against it."""
from __future__ import annotations

from app.services.indicator_compute import _calc_vwap

# 09:30, 10:30, 11:30 ET on 2024-01-02, then the same three on 2024-01-03.
_DAY1 = [1704205800, 1704209400, 1704213000]
_DAY2 = [1704292200, 1704295800, 1704299400]


def _series(times, base=100.0):
    highs, lows, closes, vols = [], [], [], []
    for i, _ in enumerate(times):
        closes.append(base + i)
        highs.append(base + i + 1)
        lows.append(base + i - 1)
        vols.append(1000.0 + i * 10)
    return highs, lows, closes, vols


def test_vwap_resets_at_the_session_boundary():
    times = _DAY1 + _DAY2
    highs, lows, closes, vols = _series(times)
    out = _calc_vwap(highs, lows, closes, vols, times)

    # First bar of day 2 has had its accumulator reset, so VWAP == its own
    # typical price, not a blend with day 1.
    i = len(_DAY1)
    typical = (highs[i] + lows[i] + closes[i]) / 3
    assert out[i]['value'] == round(typical, 4)


def test_vwap_is_independent_of_how_much_history_is_loaded():
    """The actual regression guard: the last session's values must be identical
    whether or not earlier sessions were passed in."""
    long_times = _DAY1 + _DAY2
    lh, ll, lc, lv = _series(long_times)
    long_out = _calc_vwap(lh, ll, lc, lv, long_times)

    sh, sl, sc, sv = _series(long_times)
    n = len(_DAY1)
    short_out = _calc_vwap(sh[n:], sl[n:], sc[n:], sv[n:], _DAY2)

    assert [p['value'] for p in long_out[n:]] == [p['value'] for p in short_out]


def test_daily_bars_keep_the_running_total():
    """Date-string bars (daily/weekly) have no intraday session to anchor to;
    they must keep the original behaviour rather than degenerating to one bar."""
    times = ['2024-01-02', '2024-01-03', '2024-01-04']
    highs, lows, closes, vols = _series(times)
    out = _calc_vwap(highs, lows, closes, vols, times)

    last_typical = (highs[-1] + lows[-1] + closes[-1]) / 3
    assert out[-1]['value'] != round(last_typical, 4)  # blended, not reset
