"""COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD: bar builders shared by the momentum tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DAY = 86400


def et_ts(d: date, h: int, m: int) -> int:
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=ET).timestamp())


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def weekdays_before(end: date, n: int) -> list[date]:
    """The n weekdays strictly before `end`, oldest first."""
    out, d = [], end - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def bar(t, close, *, open_=None, volume=1000):
    o = close if open_ is None else open_
    return {"time": t, "open": o, "high": max(o, close) + 0.5, "low": min(o, close) - 0.5,
            "close": close, "volume": volume}


def osc_closes(n: int, base: float = 100.0) -> list[float]:
    """Alternating closes (RSI ~50, MACD ~ its signal); the last one is DOWN."""
    closes = [base + (i % 2) for i in range(n)]
    if closes[-1] > closes[-2]:
        closes = [base + ((i + 1) % 2) for i in range(n)]
    return closes


def with_last(closes: list[float], delta: float) -> list[float]:
    return closes + [closes[-1] + delta]


def daily_bars(closes: list[float], *, volumes=None, opens=None, t0: int = 1_600_000_000) -> list[dict]:
    """Bars one day apart (1D momentum ignores the session filter)."""
    return [bar(t0 + i * DAY, c,
                open_=None if opens is None else opens[i],
                volume=1000 if volumes is None else volumes[i])
            for i, c in enumerate(closes)]


HOURLY_SLOTS = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]


def session_times(days: list[date], slots) -> list[int]:
    return [et_ts(d, h, m) for d in days for (h, m) in slots]


def intraday_bars(times: list[int], closes: list[float], volumes=None, opens=None) -> list[dict]:
    return [bar(t, c, open_=None if opens is None else opens[i],
                volume=1000 if volumes is None else volumes[i])
            for i, (t, c) in enumerate(zip(times, closes))]
