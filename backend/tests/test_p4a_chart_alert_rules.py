"""P4a -- chart alert rules, backend half: B1 refresh on a new close (Q14),
B2 catch-up of every unseen closed candle (Q14), B3 crosses with a None previous
value, R1-2 an aware last_triggered_at in the cooldown check, B4 A4g items.

Plan: docs/superpowers/plans/2026-09-26-p4a-chart-alert-rules-plan.md
"""
from __future__ import annotations

import time
from datetime import datetime, time as dtime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.alert_evaluator import (
    AlertRuleInput, ConditionGroup, IndicatorCondition, PriceCondition,
    evaluate_rules, is_cooldown_passed,
)


def _rule(conditions, cooldown_minutes=0, last_triggered_at=None, rid='rule-1'):
    return AlertRuleInput(
        id=rid, name='T', symbol='AAPL', interval='15min', enabled=True,
        group=ConditionGroup(logic='AND', conditions=conditions),
        cooldown_minutes=cooldown_minutes, expiry_date=None,
        created_at='2024-01-01T00:00:00', last_triggered_at=last_triggered_at,
    )


# ── B3: crosses with a None previous value ────────────────────────────────────

@pytest.mark.parametrize('op', ['crosses_above', 'crosses_below'])
def test_b3_crosses_on_the_first_post_warmup_bar_is_not_met_and_the_batch_survives(op):
    candle = {'time': 't2', 'open': 1, 'high': 1, 'low': 1, 'close': 50, 'volume': 1}
    series = [{'time': 't1', 'value': None}, {'time': 't2', 'value': 50}]
    crosses = _rule([IndicatorCondition(kind='indicator', indicator='RSI', operator=op, value=40)], rid='x')
    other = _rule([PriceCondition(kind='price', operator='>', value=10)], rid='y')
    out = evaluate_rules([crosses, other], candle, [candle], {'RSI': series}, [], datetime.now())
    assert [r['rule_id'] for r in out] == ['y']


# ── R1-2: an aware stamp in the cooldown check ────────────────────────────────

def test_r12_z_stamp_inside_the_cooldown_blocks_without_raising():
    now = datetime.now()
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
    assert is_cooldown_passed(_rule([], cooldown_minutes=60, last_triggered_at=stamp), now) is False


def test_r12_z_stamp_outside_the_cooldown_passes():
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat().replace('+00:00', 'Z')
    assert is_cooldown_passed(_rule([], cooldown_minutes=60, last_triggered_at=stamp), datetime.now()) is True


def test_r12_the_servers_own_naive_stamps_behave_as_before():
    now = datetime.now()
    assert is_cooldown_passed(_rule([], 60, (now - timedelta(minutes=5)).isoformat()), now) is False
    assert is_cooldown_passed(_rule([], 60, (now - timedelta(minutes=90)).isoformat()), now) is True


def test_r12_a_triggered_rule_with_a_z_stamp_does_not_abort_the_batch():
    candle = {'time': 't', 'open': 1, 'high': 1, 'low': 1, 'close': 50, 'volume': 1}
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
    cooled = _rule([PriceCondition(kind='price', operator='>', value=10)], 60, stamp, rid='cooled')
    other = _rule([PriceCondition(kind='price', operator='>', value=10)], rid='other')
    out = evaluate_rules([cooled, other], candle, [candle], {}, [], datetime.now())
    assert [r['rule_id'] for r in out] == ['other']


# ── B1: refresh on a new close ────────────────────────────────────────────────

def _bars(newest_time: int, n: int = 3, span: int = 60):
    return [{'time': newest_time - span * (n - 1 - i), 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}
            for i in range(n)]


def test_b1_due_instant_passed_since_fetch_refreshes():
    from app.data import chart_cache as cc
    T = 1_000_000_000
    assert cc._needs_refresh('15min', _bars(T, span=900), fetched_at=T + 100, now_wall=T + 901, max_age=None)


def test_b1_fetched_after_both_due_instants_is_quiet(monkeypatch):
    from app.data import chart_cache as cc
    import app.data.market as market
    monkeypatch.setattr(market, 'intraday_feed_lag_seconds', lambda: 900)
    T = 1_000_000_000
    assert not cc._needs_refresh('1min', _bars(T), fetched_at=T + 2000, now_wall=T + 5000, max_age=None)


def test_r11_sandbox_1min_refreshes_at_span_before_its_ttl(monkeypatch):
    from app.data import chart_cache as cc
    import app.data.market as market
    monkeypatch.setattr(market, 'intraday_feed_lag_seconds', lambda: 900)
    T = 1_000_000_000
    # fetched 10s into the real-time forming bar; the TTL (900s) is far away
    assert cc._needs_refresh('1min', _bars(T), fetched_at=T + 10, now_wall=T + 61, max_age=None)
    # the delayed instant is a second chance
    assert cc._needs_refresh('1min', _bars(T), fetched_at=T + 70, now_wall=T + 961, max_age=None)


def test_r21_max_age_refreshes_after_a_refetch_that_returned_no_newer_bar():
    from app.data import chart_cache as cc
    T = 1_000_000_000
    # fetched after both due instants (no newer bar came back); one span later:
    assert cc._needs_refresh('1min', _bars(T), fetched_at=T + 65, now_wall=T + 125, max_age=60)
    assert not cc._needs_refresh('1min', _bars(T), fetched_at=T + 65, now_wall=T + 100, max_age=60)


def test_b1_daily_has_no_due_instant_rule():
    from app.data import chart_cache as cc
    T = 1_000_000_000
    assert not cc._needs_refresh('daily', _bars(T, span=86400), fetched_at=T + 1, now_wall=T + 10 ** 6, max_age=None)


@pytest.mark.asyncio
async def test_b1_the_cache_refetches_only_for_a_refresh_on_close_caller(monkeypatch):
    from app.data import chart_cache as cc
    cc._INTRADAY_CACHE.clear()
    now = int(time.time())
    newest = now - 950                          # a 15min bar that closed 50s ago
    fetch = []

    def _fetch(symbol, interval, days):
        fetch.append(1)
        return _bars(newest, span=900)
    monkeypatch.setattr(cc, 'fetch_intraday_candles', _fetch)
    rows, fetched_at = await cc.get_intraday_with_fetched_at('AAPL', '15min')
    assert len(fetch) == 1
    # pretend the entry was fetched before the newest bar closed
    key = next(iter(cc._INTRADAY_CACHE))
    r, exp = cc._INTRADAY_CACHE[key]
    cc._INTRADAY_CACHE[key] = (r, exp - 200)     # fetched 200s earlier -> before the due instant
    await cc.get_intraday_with_fetched_at('AAPL', '15min')
    assert len(fetch) == 1                      # the chart page: TTL only
    await cc.get_intraday_with_fetched_at('AAPL', '15min', refresh_on_close=True)
    assert len(fetch) == 2                      # the scheduler: refetched
    cc._INTRADAY_CACHE.clear()


# ── B2: every unseen closed candle, oldest first ──────────────────────────────

async def _run_tick(monkeypatch, candles, *, last_seen=None, fail_on=None):
    import app.services.chart_alert_scheduler as sched
    import app.routers.chart_alerts as chart_alerts

    class _Result:
        def all(self):
            return [('AAPL', '15min')]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, q):
            return _Result()

    calls = []

    async def _evaluate(symbol, interval, closed, view, signals, as_of=None):
        calls.append((closed['time'], [c['time'] for c in view]))
        if fail_on is not None and closed['time'] == fail_on:
            raise RuntimeError('boom')
        return []

    monkeypatch.setattr(sched, 'AsyncSessionLocal', lambda: _Session())
    monkeypatch.setattr(sched, 'get_intraday_with_fetched_at', AsyncMock(return_value=(candles, candles[-1]['time'] + 60)))
    monkeypatch.setattr(chart_alerts, 'evaluate_and_notify_for_symbol', _evaluate)
    monkeypatch.setattr(chart_alerts, 'closed_candle_structure', lambda *a, **k: [])
    sched._last_seen_candle.clear()
    if last_seen is not None:
        sched._last_seen_candle[('AAPL', '15min')] = last_seen
    await sched._tick()
    return calls, sched._last_seen_candle.get(('AAPL', '15min'))


def _c(times):
    return [{'time': t, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1} for t in times]


@pytest.mark.asyncio
async def test_b2_two_candles_closing_between_ticks_are_both_evaluated_oldest_first(monkeypatch):
    candles = _c([100, 200, 300, 400])                  # 400 forming; 200 and 300 unseen
    calls, seen = await _run_tick(monkeypatch, candles, last_seen=100)
    assert [t for t, _ in calls] == [200, 300]
    assert calls[0][1] == [100, 200]                    # the older one: truncated at it
    assert calls[1][1] == [100, 200, 300, 400]          # the newest: full list, as before
    assert seen == 300


@pytest.mark.asyncio
async def test_b2_first_sighting_evaluates_only_the_newest(monkeypatch):
    calls, _ = await _run_tick(monkeypatch, _c([100, 200, 300, 400]))
    assert [t for t, _ in calls] == [300]


@pytest.mark.asyncio
async def test_b2_more_than_three_unseen_evaluates_the_newest_three_and_warns(monkeypatch, caplog):
    calls, _ = await _run_tick(monkeypatch, _c([100, 200, 300, 400, 500, 600, 700]), last_seen=100)
    assert [t for t, _ in calls] == [400, 500, 600]
    assert any('5 unseen closed candles' in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_b2_nothing_new_evaluates_nothing(monkeypatch):
    calls, _ = await _run_tick(monkeypatch, _c([100, 200, 300]), last_seen=200)
    assert calls == []


@pytest.mark.asyncio
async def test_b2_an_older_candle_that_raises_does_not_stop_the_newer_one_and_is_not_retried(monkeypatch):
    candles = _c([100, 200, 300, 400])
    calls, seen = await _run_tick(monkeypatch, candles, last_seen=100, fail_on=200)
    assert [t for t, _ in calls] == [200, 300]
    assert seen == 300
    import app.services.chart_alert_scheduler as sched
    assert sched._candles_to_evaluate(('AAPL', '15min'), candles) == []


# ── B4: A4g round-2 items ─────────────────────────────────────────────────────

def _ts(y, m, d, hh, mm=0, tz=timezone.utc):
    return int(datetime(y, m, d, hh, mm, tzinfo=tz).timestamp())


def test_b4_1_two_forming_copies_of_one_session_are_both_dropped():
    from app.services.market_session import completed_session_bars, MARKET_TZ
    now = datetime(2026, 6, 10, 12, 0, tzinfo=MARKET_TZ)            # Wed mid-session
    bars = [{'time': _ts(2026, 6, 9, 0)},                            # yesterday (complete)
            {'time': _ts(2026, 6, 10, 0)},                           # today, yfinance stamp
            {'time': _ts(2026, 6, 10, 13, 30)}]                      # today, IBKR open stamp
    assert completed_session_bars(bars, 'daily', now=now) == bars[:1]


def test_b4_2_two_undatable_tail_bars_drop_only_the_last():
    from app.services.market_session import completed_session_bars, MARKET_TZ
    now = datetime(2026, 6, 10, 12, 0, tzinfo=MARKET_TZ)
    bars = [{'time': _ts(2026, 6, 8, 0)}, {'time': 'x'}, {'time': None}]
    assert completed_session_bars(bars, 'daily', now=now) == bars[:2]


def test_b4_7_nyse_close_mirrors_the_session_rules_upper_bound():
    from app.services import market_session as ms
    from app.services.strategy_watch_scheduler import _market_open
    assert ms._NYSE_CLOSE == dtime(16, 0)
    wed = lambda h, m, s=0: datetime(2026, 6, 10, h, m, s, tzinfo=ms.MARKET_TZ)
    assert _market_open(wed(16, 0)) is True
    assert _market_open(wed(16, 0, 1)) is False


# ── R2-1: the scheduler's max_age choice ──────────────────────────────────────

def test_r21_max_age_is_one_span_during_the_session(monkeypatch):
    import app.services.chart_alert_scheduler as sched
    import app.services.market_session as ms
    monkeypatch.setattr(ms, '_market_session_open', lambda now=None: True)
    sched._last_newest_bar.clear()
    assert sched._max_age_for(('AAPL', '1min'), '1min', time.time()) == 60.0


def test_r21_no_max_age_outside_the_session_with_a_stale_newest_bar(monkeypatch):
    import app.services.chart_alert_scheduler as sched
    import app.services.market_session as ms
    import app.data.market as market
    monkeypatch.setattr(ms, '_market_session_open', lambda now=None: False)
    monkeypatch.setattr(market, 'intraday_feed_lag_seconds', lambda: 0)
    now = time.time()
    sched._last_newest_bar[('AAPL', '1min')] = int(now) - 3600
    assert sched._max_age_for(('AAPL', '1min'), '1min', now) is None
    sched._last_newest_bar[('AAPL', '1min')] = int(now) - 60     # recent: still refreshing
    assert sched._max_age_for(('AAPL', '1min'), '1min', now) == 60.0
    assert sched._max_age_for(('AAPL', '1D'), '1D', now) is None
    sched._last_newest_bar.clear()


@pytest.mark.asyncio
async def test_b2_advance_before_evaluate_a_failing_newest_candle_is_not_retried(monkeypatch):
    # One attempt per candle: evaluate_and_notify_for_symbol dispatches before
    # its commit, so a retry after a failure could re-send Gmail/Telegram.
    candles = _c([100, 200, 300])
    calls, seen = await _run_tick(monkeypatch, candles, last_seen=100, fail_on=200)
    assert [t for t, _ in calls] == [200]
    assert seen == 200
