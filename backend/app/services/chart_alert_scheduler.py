# backend/app/services/chart_alert_scheduler.py
"""Background loop that evaluates chart-drawn alert rules even when no chart
is open in a browser. Mirrors the candle-close evaluation chart.py's
websocket already does, but runs unconditionally on a configurable cadence.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import yaml
from sqlalchemy import select

from app.data.chart_cache import get_intraday, get_intraday_with_fetched_at
from app.database import AsyncSessionLocal
from app.models.alert import AlertRuleModel

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'
_DEFAULT_CHECK_INTERVAL = 60  # seconds

# (symbol, interval) -> last-seen closed-candle time, so a tick only
# re-evaluates once per newly-closed candle rather than on every poll.
_last_seen_candle: dict[tuple[str, str], str] = {}

# (symbol, interval) -> `time` of the newest bar the previous tick fetched; read
# by `_max_age_for` to keep refreshing while that bar is recent (P4a R2-1).
_last_newest_bar: dict[tuple[str, str], int] = {}

# P4a B2: at most this many unseen closed candles are evaluated per pair per
# tick (the newest ones). After downtime, alerts on hours-old candles are noise.
MAX_CATCH_UP_CANDLES = 3


def _max_age_for(key: tuple[str, str], interval: str, now_wall: float) -> float | None:
    """P4a R2-1: `max_age` for the cache -- one bar span for an intraday interval
    while the regular session is open OR the newest bar the previous tick saw is
    recent (`now - time <= 2*span + lag + 60`); else None (TTL + due instants),
    so the scheduler stays quiet overnight and on weekends."""
    from app.data.market import (
        _INTERVAL_COMPLETION_SECONDS, _TRADIER_INTRADAY_INTERVALS,
        intraday_feed_lag_seconds, normalize_interval,
    )
    from app.services.market_session import _market_session_open

    norm = normalize_interval(interval)
    span = _INTERVAL_COMPLETION_SECONDS.get(norm)
    if span is None:
        return None
    # NO argument: it reads datetime.now(MARKET_TZ) (plan G).
    if _market_session_open():
        return float(span)
    newest = _last_newest_bar.get(key)
    lag = intraday_feed_lag_seconds() if norm in _TRADIER_INTRADAY_INTERVALS else 0
    if newest is not None and now_wall - newest <= 2 * span + lag + 60:
        return float(span)
    return None


def _load_check_interval_seconds() -> int:
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            return max(15, int(cfg.get('alert_delivery', {}).get('checkIntervalSeconds', _DEFAULT_CHECK_INTERVAL)))
    except (TypeError, ValueError, OSError):
        logger.debug('Could not load checkIntervalSeconds', exc_info=True)
    return _DEFAULT_CHECK_INTERVAL


async def _tick() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AlertRuleModel.symbol, AlertRuleModel.interval)
            .where(AlertRuleModel.enabled == True)  # noqa: E712
            .distinct()
        )
        pairs = result.all()

    # P4a code round 1: a pair with no enabled rule drops its markers, so when a
    # rule for it is created or re-enabled later it is a first sighting (newest
    # closed candle only) -- not a catch-up over candles from before the rule.
    _prune_markers({(s, i) for s, i in pairs})

    if not pairs:
        return

    from app.routers.chart_alerts import closed_candle_structure, evaluate_and_notify_for_symbol

    for symbol, interval in pairs:
        key = (symbol, interval)
        try:
            candles, fetched_at = await get_intraday_with_fetched_at(
                symbol, interval, refresh_on_close=True,
                max_age=_max_age_for(key, interval, time.time()),
            )
            if not candles or len(candles) < 2:
                continue
            _t = candles[-1].get('time')
            if isinstance(_t, int) and not isinstance(_t, bool):
                _last_newest_bar[key] = _t
            ht_candles = None
            for idx in _candles_to_evaluate(key, candles):
                closed = candles[idx]
                # P4a B2: advance BEFORE evaluating -- one attempt per candle.
                # evaluate_and_notify_for_symbol dispatches Gmail/Telegram before
                # its commit, so a retry after a failed commit would re-send.
                _last_seen_candle[key] = closed['time']
                # The newest closed candle keeps today's call (the full list,
                # forming bar included). An OLDER one gets the list truncated at
                # it, so no regime model, indicator or structure reads a later bar.
                view = candles if idx == len(candles) - 2 else candles[:idx + 1]
                try:
                    if interval == '1h' and ht_candles is None:
                        ht_candles = await get_intraday(symbol, '1D')
                    # A4e: structure for the alert decision stops at the closed candle.
                    signals = await asyncio.to_thread(closed_candle_structure, view, closed, interval, symbol, ht_candles)
                    await evaluate_and_notify_for_symbol(symbol, interval, closed, view, signals, as_of=fetched_at)
                except Exception:
                    # Per candle (P4a F): a failure on an older candle does not
                    # stop the newer ones in this tick.
                    logger.warning('chart alert background check failed for %s [%s] candle %s',
                                   symbol, interval, closed.get('time'), exc_info=True)
        except Exception:
            logger.warning('chart alert background check failed for %s [%s]', symbol, interval, exc_info=True)


def _prune_markers(active: set[tuple[str, str]]) -> None:
    for markers in (_last_seen_candle, _last_newest_bar):
        for key in [k for k in markers if k not in active]:
            del markers[key]


def _candles_to_evaluate(key: tuple[str, str], candles: list[dict]) -> list[int]:
    """P4a B2 (decision Q14): indices of the closed candles (`candles[:-1]`) not
    yet evaluated for `key`, oldest first -- every one newer than the last seen,
    not only `candles[-2]`, so a snapshot that advanced by more than one bar
    skips none. First sighting of a key: the newest closed candle only (as
    before). More than MAX_CATCH_UP_CANDLES: the newest of them, and one
    WARNING naming how many were not evaluated.

    Residuals (plan B2/E/F): `_last_seen_candle` is in memory, so a restart
    evaluates only the newest; a bar that appears later with an OLDER time than
    one already evaluated is not evaluated.
    """
    newest = len(candles) - 2
    last = _last_seen_candle.get(key)
    if last is None:
        return [newest]
    if candles[newest].get('time') == last:
        return []
    unseen = [i for i in range(newest + 1) if _is_after(candles[i].get('time'), last)]
    if len(unseen) > MAX_CATCH_UP_CANDLES:
        logger.warning(
            'chart alert catch-up for %s [%s]: %d unseen closed candles, evaluating the newest %d',
            key[0], key[1], len(unseen), MAX_CATCH_UP_CANDLES,
        )
        unseen = unseen[-MAX_CATCH_UP_CANDLES:]
    return unseen


def _is_after(t: object, last: object) -> bool:
    try:
        return t > last  # type: ignore[operator]
    except TypeError:
        return False


async def run_chart_alert_scheduler() -> None:
    """Long-running loop started in app lifespan. Evaluates chart-drawn alert
    rules on a configurable cadence, independent of any open chart tab.

    Known limitation: if a browser also has this exact symbol+interval chart
    open at the same time, both paths may evaluate the same newly-closed
    candle within moments of each other. The rule's own cooldown_minutes
    (default 60) makes a duplicate notification rare and low-cost even so.
    """
    logger.info('Chart alert background scheduler started (default interval=%ds)', _DEFAULT_CHECK_INTERVAL)
    rules_migrated = False
    while True:
        # A4f-rules: move stored HMM_intraday composite rules off '1D'/'1W' before
        # this tick evaluates anything. Once per server start; a failure (e.g. the
        # DB not up yet) is logged and retried next iteration until one run succeeds.
        if not rules_migrated:
            try:
                from app.routers import chart_alerts as _chart_alerts
                await _chart_alerts.migrate_hmm_intraday_rule_intervals()
                rules_migrated = True
            except Exception:
                logger.error('A4f: HMM_intraday rule interval migration failed; retrying next tick', exc_info=True)
        try:
            await _tick()
        except Exception:
            logger.error('chart alert scheduler tick failed', exc_info=True)
        await asyncio.sleep(_load_check_interval_seconds())
