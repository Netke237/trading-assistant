"""MACD-EMA-LAG: the standard-rule 'macd'/'macd_signal' indicators.

_calc_macd used _ema_values, which stored result[i] BEFORE folding values[i]
in (every value trailed its bar by one) and zero-padded the warm-up (the line
equalled the price for bars 12-25, polluting the signal line for dozens of
bars). It now reads the textbook EMA and reports the warm-up as None, which
alert_evaluator._evaluate_condition already treats as "not met".
"""
from __future__ import annotations

import random
from types import SimpleNamespace as NS

import pytest

import app.services.indicator_compute as ic
from app.services.alert_evaluator import _evaluate_condition


def _ref_ema(values, period):
    """Independent textbook EMA (SMA seed at period-1), written out longhand."""
    out = [None] * len(values)
    if len(values) < period:
        return out
    out[period - 1] = sum(values[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def _ref_macd(closes, fast=12, slow=26, signal=9):
    f, s = _ref_ema(closes, fast), _ref_ema(closes, slow)
    line = [None if a is None or b is None else a - b for a, b in zip(f, s)]
    sig = [None] * (slow - 1) + _ref_ema(line[slow - 1:], signal)
    return line, sig


def _walk(seed, n):
    rnd = random.Random(seed)
    c, out = 100.0, []
    for _ in range(n):
        c += rnd.uniform(-2, 2)
        out.append(c)
    return out


def _series(closes):
    return [{"time": i, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 100}
            for i, c in enumerate(closes)]


def _ind(candles, name):
    return ic.compute_indicators_for_conditions(candles, [{"kind": "indicator", "indicator": name}])[name]


@pytest.mark.parametrize("seed", range(5))
def test_matches_the_textbook_macd(seed):
    closes = _walk(seed, 120)
    got = ic._calc_macd(closes, list(range(120)), 12, 26, 9)
    line, sig = _ref_macd(closes)
    assert got["macd"] == pytest.approx(line)
    assert got["signal"] == pytest.approx(sig)
    assert got["histogram"] == pytest.approx([None if a is None or b is None else a - b
                                              for a, b in zip(line, sig)])


def test_warm_up_is_none_not_zero_or_price():
    """Mutation: zero-pad the warm-up (the old line equalled the price on 12-25)."""
    closes = _walk(11, 60)
    out = ic._calc_macd(closes, list(range(60)), 12, 26, 9)
    assert out["macd"][:25] == [None] * 25 and out["macd"][25] is not None
    assert out["signal"][:33] == [None] * 33 and out["signal"][33] is not None
    assert out["histogram"][:33] == [None] * 33


@pytest.mark.parametrize("n", [0, 1, 25, 26, 33, 34])
def test_short_histories(n):
    closes = _walk(2, n)
    out = ic._calc_macd(closes, list(range(n)), 12, 26, 9)
    assert len(out["macd"]) == len(out["signal"]) == len(out["histogram"]) == n
    assert sum(v is not None for v in out["macd"]) == max(0, n - 25)
    assert sum(v is not None for v in out["signal"]) == max(0, n - 33)


def test_the_bar_is_folded_in_at_its_own_index():
    """Mutation: store result[i] before folding values[i] in (one-bar lag)."""
    closes = [100.0] * 60
    spiked = closes[:-1] + [130.0]
    flat = ic._calc_macd(closes, list(range(60)), 12, 26, 9)
    hit = ic._calc_macd(spiked, list(range(60)), 12, 26, 9)
    assert flat["macd"][-1] == pytest.approx(0.0)
    assert hit["macd"][-1] > 0          # the spike moves the line on its own bar
    assert hit["macd"][:-1] == flat["macd"][:-1]


@pytest.mark.parametrize("seed", range(5))
def test_standard_rule_agrees_with_composite_momentum(seed):
    """One MACD on one set of bars: the standard rule and _macd_last_two agree."""
    closes = _walk(100 + seed, 201)
    std = ic._calc_macd(closes, list(range(201)), 12, 26, 9)
    (l0, s0), (l1, s1) = ic._macd_last_two(closes)
    assert (std["macd"][-2], std["signal"][-2], std["macd"][-1], std["signal"][-1]) == \
        pytest.approx((l0, s0, l1, s1))


def test_compute_dispatch_serves_the_fixed_series():
    candles = _series(_walk(5, 80))
    line, sig = _ref_macd([c["close"] for c in candles])
    for name in ("macd", "macd_line"):
        assert [p["value"] for p in _ind(candles, name)] == pytest.approx(line)
    assert [p["value"] for p in _ind(candles, "macd_signal")] == pytest.approx(sig)
    assert [p["time"] for p in _ind(candles, "macd_signal")] == list(range(80))


@pytest.mark.parametrize("name", ["signal", "macd_sig", "", "a"])
def test_only_the_exact_name_serves_macd_signal(name):
    """Mutation: `lower in ('macd_signal')` -- a substring test, not a tuple."""
    out = ic.compute_indicators_for_conditions(_series(_walk(5, 80)),
                                               [{"kind": "indicator", "indicator": name}])
    assert name not in out


def test_warm_up_never_fires_and_never_raises():
    """The old zero-padded line read as the price during warm-up, so 'macd > 50'
    fired on bars 12-25 of a $100 stock. Now those bars are not met."""
    candles = _series([100.0 + 0.1 * i for i in range(40)])
    ind = {"macd": _ind(candles, "macd"), "macd_signal": _ind(candles, "macd_signal")}
    for name, warm_up in (("macd", 25), ("macd_signal", 33)):
        for i in range(warm_up):
            for op in (">", "<", "crosses_above", "crosses_below"):
                cond = NS(kind="indicator", indicator=name, operator=op, value=50.0)
                met, _ = _evaluate_condition(cond, candles[i], ind, [], i)
                assert met is False, (i, name, op)


def test_macd_crossing_zero_fires_on_the_crossing_bar():
    """A downtrend then a sharp reversal: 'macd crosses_above 0' fires on the
    first bar whose (unlagged) MACD is above zero, and on no other bar."""
    closes = [200.0 - i for i in range(60)] + [140.0 + 4 * i for i in range(1, 30)]
    candles = _series(closes)
    ind = {"macd": _ind(candles, "macd")}
    line, _ = _ref_macd(closes)
    first_pos = next(i for i in range(26, len(line)) if line[i] > 0)
    cond = NS(kind="indicator", indicator="macd", operator="crosses_above", value=0.0)
    fired = [i for i in range(len(candles)) if _evaluate_condition(cond, candles[i], ind, [], i)[0]]
    assert fired == [first_pos]
