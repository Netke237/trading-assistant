"""NYSE session tests shared by the auto-trader and the chart alert path.

A4g (decision A4C-FOLLOWUPS-LOCKED-2026-09-24, part 4): guard (i)'s session test
moved here from ``auto_trader.py`` -- moved, not copied -- so 1D/1W chart alerts
can drop the forming daily/weekly bar with the same hours test the money gate
uses. ``auto_trader`` imports ``todays_bar_is_unclosed`` back under its old
private name ``_todays_bar_is_unclosed``, so its call site and the tests that
patch that name are unchanged.

The comments and docstring below were written in ``auto_trader.py`` and moved
verbatim: where they say "this file" or "this module" they mean
``auto_trader.py``, whose ``_market_is_open`` price probe is the name clash the
alias avoids, and whose ``_fetch_scan_window_bars`` is guard (i)'s call site.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta

from app.services.scheduling_tz import MARKET_TZ

# The scheduler's real NYSE-hours test, reused rather than re-implemented (guard
# (i); see `_todays_bar_is_unclosed`). Aliased because `_market_is_open` already
# lives in this file and means something entirely different -- a price probe --
# and confusing the two IS the defect this closes. Imported at MODULE level on
# purpose: an ImportError must be a loud startup failure, not a raise inside
# `_fetch_scan_window_bars`, which `_measure_trade_regime` catches into an
# abstain that FIRES UNGATED. No new failure mode at app level either --
# routers/strategy_watch.py already imports this module at startup.
#
# THE PRICE, STATED RATHER THAN LEFT TO BE MEASURED (round 1 finding F-8):
# 0.299s of marginal import time, and it pulls historical_store,
# notifications/dispatch, strategy_engine and strategy_watch_evaluator into
# THIS module's import graph. Inert under uvicorn, which imports all of them
# anyway -- but it is a new import-time failure surface for scripts and narrow
# test runs that previously needed none of it. The cheaper shape was a
# three-line hours test in `scheduling_tz.py`, which already owns MARKET_TZ and
# carries no chain; reusing the scheduler's ONE definition was preferred over a
# second copy of the boundaries, and that trade is the reason, not an oversight.
from app.services.strategy_watch_scheduler import _market_open as _market_session_open


# NYSE regular-session OPEN, in MARKET_TZ. The scheduler's `_market_open`
# answers "is the session in progress" and does not expose its boundaries, so
# the one boundary this file needs that it cannot ask for is named here.
_NYSE_OPEN = dtime(9, 30)


def todays_bar_is_unclosed(now: datetime | None = None) -> bool:
    """True while a bar dated TODAY is still being written.

    GUARD (i), decision AUTOTRADE-2B-CORE-F1-GUARD-I-SESSION-TEST-2026-09-21
    (Kenneth). Option A's end-trim justified itself with "on the fire path the
    market is provably open", and THAT PREMISE IS FALSE. `fire()` gates on
    `_market_is_open`, which is a PRICE-AVAILABILITY probe -- `fetch_price`
    serves close/previous_close around the clock (market.py:464/:474/:479) and
    that function's own docstring says the market "appears open". Neither fire
    path has an hours gate at all. So after 16:00 ET the unconditional trim was
    dropping a bar that had CLOSED, which the scan had seen: measured at 0.50%
    of Position fires flipping, including scan PASS -> gate ABSTAIN, and an
    abstain fires UNGATED (then at full armed quantity; since SIZING-4 at the
    min_mult floor when regime_sizing is on, full quantity only with it off).

    THE TEST IS REAL SESSION HOURS IN `MARKET_TZ`, NOT A PRICE PROBE, and it is
    the scheduler's existing one rather than a second copy: `_market_open`
    (strategy_watch_scheduler.py:23) is a weekday + 09:30-16:00 America/New_York
    wall-clock test, tracked via a real IANA zone so it stays correct across
    both the US's and the operator's own DST transition weeks.

    TWO CLAUSES, AND BOTH ARE LOAD-BEARING -- `_market_open` alone is not the
    whole question:
      - MID-SESSION (weekday 09:30-16:00) -- the case the decision names. The
        bar is provably still being written, with ONE EXCEPTION at the edge:
        `_market_open`'s upper bound is INCLUSIVE (`<= dtime(16, 0)`), so
        16:00:00.000000 reads unclosed and TRIMS a bar that has just closed,
        while 16:00:00.000001 reads complete and keeps it. The truth table pins
        16:00 as True because that is what the code does; the phrase "provably
        still being written" is false for that one microsecond-wide instant and
        true everywhere else in the clause. Left as-is rather than moved to `<`:
        the probability is ~0, and the alternative is a SECOND divergence from
        the scheduler's boundary for no measurable gain.
      - BEFORE THE OPEN (t < 09:30) -- `_market_open` reads False here, and
        reading that as "closed, so today's bar is complete" would KEEP a bar
        for a session that has not started. That is round 3's defect with the
        sign flipped, so pre-open trims exactly as it did before this guard.
    Everything else -- after 16:00 on a session day -- KEEPS today's bar,
    which is the whole point of the guard.

    `now` IS NORMALISED, NOT TRUSTED (round 1 finding F-3). An AWARE instant is
    converted to MARKET_TZ before either clause reads it, so a caller handing
    this UTC gets the same answer as one handing it New York -- without that
    conversion the same real instant reads False at NY 20:00 and True as the
    identical 00:00+00:00, because `now.time()` is a WALL-CLOCK read and does
    not care which wall. A NAIVE datetime RAISES rather than being guessed at:
    reading it as MARKET_TZ wall-clock and letting `.astimezone()` read it as
    the HOST's zone are both defensible and they differ, so the ambiguity is
    refused at the door. Consequence worth stating: the DST correctness claimed
    above is a property of THIS FUNCTION, not merely of its default branch.

    THE RAISE'S OWN RESIDUAL, because this file's exceptions are not free: it
    is thrown inside `_fetch_scan_window_bars`, whose caller
    `_measure_trade_regime` turns any fetch exception into a REFUSAL
    (RegimeDataUnavailableError, P3b; it used to abstain and fire ungated). So
    a naive argument would be a loud failure in a test run and a refused fire
    in production -- fail-closed, but every armed trade refused. It is
    unreachable today: the auto-trader's end-trim passes no argument and takes
    the `None` branch, and the A4g chart path (``completed_session_bars`` ->
    ``last_session_close`` / ``week_is_unclosed``) passes an AWARE instant
    (``datetime.fromtimestamp(as_of, MARKET_TZ)`` in chart_alerts.py). Both are
    pinned: the end-trim by the call-site test, the chart path by the A4g
    tests.
    A caller that ever wants to pass an instant must pass an aware one; the
    contract is enforced where enforcing it is cheap.

    RESIDUALS, NAMED RATHER THAN LEFT FOR THE NEXT READER TO FIND:
      - HALF DAYS. `_market_open` has no holiday calendar and no early-close
        table, so on the THREE sessions NYSE normally closes early at 13:00 ET
        (July 3rd or the observed 5th, the day after Thanksgiving, and Christmas
        Eve) a completed bar is still trimmed between 13:00 and 16:00. That is
        the OLD behaviour surviving on 3 days instead of 365, not a new defect.
      - FULL HOLIDAYS. `_market_open` reads True 09:30-16:00 on Thanksgiving,
        so a bar dated today would be trimmed -- but no session ran, so no
        feed emits one and `last_day >= today` is False. Inert.
      - WEEKENDS after 09:30 read "complete" here. Same reason: there is no
        bar dated a Saturday to keep or drop.
      - `date.today()` is the HOST's date while this test is the MARKET's, and
        they disagree for part of every day. Traced rather than waved at, and
        NEITHER LIMB IS CHANGED BY THIS GUARD:
          * host AHEAD of New York (the operator's own Europe/Berlin, +6):
            between the host's midnight and NY's, host-today is NY-TOMORROW, so
            `last_day >= today` is False and the end-trim is skipped before this
            function is ever called. EVERY OFFSET IN THIS BLOCK IS RELATIVE TO
            NEW YORK, NOT TO UTC -- so a UTC host is +4 in EDT and +5 in EST,
            and Berlin, at UTC+2 in summer, is +6. THAT WINDOW IS NY `[24:00 -
            offset, 24:00)`, so it lies wholly after the 16:00 close ONLY WHILE
            `24 - offset >= 16`, i.e. offset <= +8h. Berlin (+6) and a UTC host
            (+4/+5) satisfy it and are the deployments this ships on, so the
            limb holds HERE -- and it is NOT vacuous here either: on the UTC
            host this runs and tests on, that window is a real NY 20:00-24:00
            in EDT and 19:00-24:00 in EST -- four to five hours every evening,
            per the +4/+5 above -- in which the end-trim, and with it this whole
            session test, is never reached. Keeping the bar is the
            right answer throughout it, which is why the limb holds -- but
            it does not generalise to "host ahead of New York": at >= +9h (Tokyo
            is +13) the window reaches back INTO THE LIVE SESSION, where skipping
            the trim keeps a genuinely unclosed bar. The BEHAVIOUR there belongs
            to the `date.today()` anchor this diff scopes out; the BOUND is
            stated here because a load-bearing comment that overstates its own
            reach is this target's own definition of a defect.
          * host BEHIND New York (a US-west host, -3): between NY's midnight and
            the host's, host-today is NY-YESTERDAY, so the trim can act on
            NY-yesterday's COMPLETED bar. This test reads "unclosed" there
            (pre-open), so it drops that bar exactly as the unconditional trim
            did.
        That second limb is the host-date ANCHOR's residual, not this test's,
        and it is out of guard (i)'s scope -- the fix for it is anchoring
        `today` in MARKET_TZ, which is a change to the trim and belongs to
        whatever target takes it.
    """
    if now is None:
        now = datetime.now(MARKET_TZ)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(
            "todays_bar_is_unclosed needs an AWARE instant -- a naive datetime "
            "is read as MARKET_TZ wall-clock by one plausible reading and as the "
            "host's own zone by another, and the two disagree by the host's "
            "offset. Pass datetime.now(MARKET_TZ), or any aware instant."
        )
    else:
        now = now.astimezone(MARKET_TZ)
    if _market_session_open(now):
        return True
    return now.time() < _NYSE_OPEN


def week_is_unclosed(now: datetime | None = None) -> bool:
    """True while the current ET week's last session has not closed (A4g).

    Mon-Thu -> True. Friday -> ``todays_bar_is_unclosed(now)``, i.e. through
    16:00 ET, inclusive at the edge exactly as guard (i). Sat/Sun -> False.
    ``now`` is normalised the same way: aware -> MARKET_TZ, naive raises.
    Residual carried from guard (i): no holiday calendar, so a holiday Friday
    reads the week unclosed until 16:00.
    """
    now = _normalise(now, "week_is_unclosed")
    wd = now.weekday()
    if wd >= 5:
        return False
    if wd < 4:
        return True
    return todays_bar_is_unclosed(now)


_NYSE_CLOSE = dtime(16, 0)


def _normalise(now: datetime | None, who: str) -> datetime:
    if now is None:
        return datetime.now(MARKET_TZ)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"{who} needs an AWARE instant; pass datetime.now(MARKET_TZ).")
    return now.astimezone(MARKET_TZ)


def _close_on(day) -> datetime:
    return datetime.combine(day, _NYSE_CLOSE, tzinfo=MARKET_TZ)


def last_session_close(now: datetime | None = None) -> datetime:
    """The most recent 16:00 ET weekday close at which a daily bar is complete.

    Today's close when today is a weekday and ``todays_bar_is_unclosed(now)``
    is False (after 16:00); otherwise the previous weekday's close. The weekday
    is checked FIRST: guard (i) reads a weekend after 09:30 as "closed" (its
    WEEKENDS residual), and taking that as "today's close" would return a
    Saturday/Sunday 16:00 that no session had.
    """
    now = _normalise(now, "last_session_close")
    today = now.date()
    if now.weekday() < 5 and not todays_bar_is_unclosed(now):
        return _close_on(today)
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return _close_on(day)


def last_week_close(now: datetime | None = None) -> datetime:
    """The most recent Friday 16:00 ET close at which a weekly bar is complete:
    this week's Friday once ``week_is_unclosed(now)`` is False, else the
    previous week's Friday."""
    now = _normalise(now, "last_week_close")
    friday = now.date() + timedelta(days=4 - now.weekday())
    if week_is_unclosed(now):
        friday -= timedelta(days=7)
    return _close_on(friday)


def completed_session_bars(bars: list[dict], interval: str, now: datetime | None = None) -> list[dict]:
    """``bars`` without the trailing daily/weekly bar that is still forming at ``now`` (A4g).

    Interval ``daily``/``1D`` or ``weekly``/``1W`` only; any other interval
    returns ``bars`` unchanged (intraday completeness is
    ``completed_bars_for_interval``'s job).

    A bar is forming iff its ``time`` (unix seconds) is STRICTLY AFTER the last
    completed close instant (round 1 F1): every stamp convention in use --
    00:00 ET, 00:00 UTC, session open, session close; Monday or Friday for a
    week -- lies after the previous close and at or before its own, so this
    needs no calendar-date matching across zones. Only trailing bars can be
    forming, so only they are examined. An undatable LAST bar (``time`` not an
    int, or a bool) is dropped -- fail closed, that one bar only; the walk then
    stops at the next undatable bar rather than guessing. Order is preserved
    and ``bars`` is not mutated.
    """
    from app.data.market import normalize_interval

    norm = normalize_interval(interval)
    if norm == "daily":
        close = last_session_close(now)
    elif norm == "weekly":
        close = last_week_close(now)
    else:
        return bars
    cutoff = close.timestamp()
    out = list(bars)

    def _datable(b: dict) -> bool:
        t = b.get("time")
        return isinstance(t, int) and not isinstance(t, bool)

    if out and not _datable(out[-1]):
        out.pop()
    while out and _datable(out[-1]) and out[-1]["time"] > cutoff:
        out.pop()
    return out
