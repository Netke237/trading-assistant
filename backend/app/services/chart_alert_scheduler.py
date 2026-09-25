# backend/app/services/chart_alert_scheduler.py
"""Background loop that evaluates chart-drawn alert rules even when no chart
is open in a browser. Mirrors the candle-close evaluation chart.py's
websocket already does, but runs unconditionally on a configurable cadence.
"""
from __future__ import annotations

import asyncio
import logging
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

    if not pairs:
        return

    from app.routers.chart_alerts import closed_candle_structure, evaluate_and_notify_for_symbol

    for symbol, interval in pairs:
        try:
            candles, fetched_at = await get_intraday_with_fetched_at(symbol, interval)
            if not candles or len(candles) < 2:
                continue
            closed = candles[-2]
            key = (symbol, interval)
            if _last_seen_candle.get(key) == closed['time']:
                continue  # already evaluated this closed candle
            _last_seen_candle[key] = closed['time']

            ht_candles = await get_intraday(symbol, '1D') if interval == '1h' else None
            # A4e: structure for the alert decision stops at the closed candle.
            signals = await asyncio.to_thread(closed_candle_structure, candles, closed, interval, symbol, ht_candles)

            await evaluate_and_notify_for_symbol(symbol, interval, closed, candles, signals, as_of=fetched_at)
        except Exception:
            logger.warning('chart alert background check failed for %s [%s]', symbol, interval, exc_info=True)


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
            from app.routers import chart_alerts as _chart_alerts
            try:
                await _chart_alerts.migrate_hmm_intraday_rule_intervals()
                rules_migrated = True
            except Exception:
                logger.error('A4f: HMM_intraday rule interval migration failed; retrying next tick', exc_info=True)
        try:
            await _tick()
        except Exception:
            logger.error('chart alert scheduler tick failed', exc_info=True)
        await asyncio.sleep(_load_check_interval_seconds())
