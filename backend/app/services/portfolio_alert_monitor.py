"""Background monitor that checks portfolio positions for alert conditions every 15 min
and dispatches enabled alerts via Telegram / Gmail."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.portfolio import PortfolioPositionModel
from app.routers.regime import compute_overall_regime
from app.schemas import AlertItem
from app.services.alert_episodes import EpisodeStart, current_episodes
from app.services.alert_generator import POSITION_ALERT_TYPES, effective_enabled, generate_alerts
from app.services.alert_service import alert_service
from app.services.notifications.alert_notifier import (
    ACTION_TYPES,
    SummaryItem,
    forget_alerts,
    notify_alert,
    notify_daily_summary,
    summary_deadline_passed,
    summary_due,
)
from app.services.position_alert_log import log_position_alert, prune_position_alert_history

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'
_DEFAULT_CHECK_INTERVAL = 60  # seconds — used until alert_delivery.checkIntervalSeconds overrides it

# Tracks which recIds were in the portfolio last tick so we can detect closures.
_known_rec_ids: set[str] = set()

# Regime flip tracking
_last_regime: str | None = None


def _load_settings() -> dict:
    """Return the full settings.yaml content (or {} on error)."""
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        logger.debug('Could not load settings config', exc_info=True)
    return {}


def _load_delivery_config() -> dict:
    return _load_settings().get('alert_delivery', {})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _position_label(symbol: str, contract: str | None) -> str:
    """'COP 100C 2026-12-18' for an option contract, else the symbol."""
    parts = (contract or '').split('|')
    if len(parts) == 4:
        return f'{parts[0]} {parts[1]}{parts[3]} {parts[2]}'
    return symbol


async def _maybe_send_daily_summary(
    now: datetime,
    alerts: list[AlertItem],
    episodes: dict,
    unquoted: dict[str, str],
    overrides_by_rec_id: dict[str, dict],
    enabled_types: list[str],
) -> None:
    """Daily 09:00 Berlin summary (PORTFOLIO-ALERT-ACTION §2). The caller has
    already established that generation succeeded this tick; ``unquoted`` maps
    rec_id -> label for positions missing a stock or option quote. Before 12:00
    Berlin any unquoted position defers the summary to a later tick."""
    if not summary_due(now):
        return
    if unquoted and not summary_deadline_passed(now):
        return
    items: list[SummaryItem] = []
    for alert in alerts:
        if alert.alertType not in ACTION_TYPES or alert.recId in unquoted:
            continue
        override = effective_enabled(overrides_by_rec_id.get(alert.recId), alert.alertType)
        enabled = override if override is not None else alert.alertType in enabled_types
        if not enabled:
            continue
        view = episodes.get((alert.recId, alert.alertType))
        items.append(SummaryItem(
            rec_id=alert.recId, symbol=alert.symbol, alert_type=alert.alertType,
            start=view.start if view is not None else None,
            truncated=view.truncated if view is not None else False,
            stop_side=alert.stopSide,
        ))
    await notify_daily_summary(items, now, unquoted=sorted(unquoted.values()))


async def _run_once() -> None:
    global _last_regime, _known_rec_ids

    cfg = _load_settings()
    delivery = cfg.get('alert_delivery', {})
    retention_years = int(cfg.get('history_retention_years', 10))

    # Prune the sent-message log to its retention window (default 30 days).
    try:
        from app.services.notifications.sent_log import prune_sent_log
        prune_sent_log(int(delivery.get('retentionDays', 30)))
    except Exception:
        logger.debug('sent-message log prune failed', exc_info=True)

    # Prune old trade history rows that exceed the configured retention window.
    try:
        from app.services.history_cleanup import prune_old_history
        async with AsyncSessionLocal() as db:
            await prune_old_history(db, retention_years)
    except Exception:
        logger.debug('History prune failed', exc_info=True)

    # Prune position_alert_history to its own (shorter, high-volume) retention window.
    try:
        async with AsyncSessionLocal() as db:
            await prune_position_alert_history(db, int(delivery.get('positionAlertRetentionDays', 30)))
    except Exception:
        logger.debug('position_alert_history prune failed', exc_info=True)

    if not delivery.get('masterEnabled', True):
        return

    enabled_types: list[str] = delivery.get('enabledTypes', [
        'TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP', 'TIME_STOP', 'REGIME_CHANGE',
    ])

    alerts: list[AlertItem] = []
    current_rec_ids: set[str] = set()
    # recId -> that position's per-type alert overrides (Feature D), captured
    # while the positions are already loaded below so the dispatch loop can
    # resolve `override ?? global` without a second query.
    overrides_by_rec_id: dict[str, dict] = {}
    # Daily summary inputs: generation succeeded this tick (no exception), and
    # which positions lacked a stock quote or (option) contract quote.
    generation_ok = False
    unquoted: dict[str, str] = {}

    # ── 1. Portfolio position alerts ─────────────────────────────────────────
    try:
        import httpx

        from app.data.market import fetch_contract_quote_async, fetch_quotes
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PortfolioPositionModel))
            positions = result.scalars().all()
            current_rec_ids = {p.rec_id for p in positions if p.rec_id}
            overrides_by_rec_id = {
                p.rec_id: (p.alert_overrides or {}) for p in positions if p.rec_id
            }
            symbols = list({p.symbol for p in positions})
            if symbols:
                quotes = await asyncio.to_thread(fetch_quotes, symbols)
                current_prices = {sym: q['last'] for sym, q in quotes.items()}

                # Live option prices — same source as the portfolio enrichment
                # path — so PREMIUM_STOP works headless (browser closed) too.
                option_prices: dict[str, float] = {}
                contracts = [p.contract for p in positions if p.contract]
                if contracts:
                    async with httpx.AsyncClient(timeout=10) as client:
                        results = await asyncio.gather(
                            *[fetch_contract_quote_async(client, c) for c in contracts],
                            return_exceptions=True,
                        )
                    for contract, quote in zip(contracts, results):
                        if isinstance(quote, dict) and quote.get('price') is not None:
                            option_prices[contract] = quote['price']

                position_sustain_minutes = int(delivery.get('positionSustainMinutes', 0))
                alerts.extend(await generate_alerts(
                    db, current_prices, option_prices or None, position_sustain_minutes))
                await db.commit()

                for p in positions:
                    is_option = bool(p.contract) and not str(p.contract).upper().endswith('|STOCK')
                    if (current_prices.get(p.symbol) is None
                            or (is_option and option_prices.get(p.contract) is None)):
                        unquoted[p.rec_id] = _position_label(p.symbol, p.contract)
            generation_ok = True
    except Exception:
        logger.error('Portfolio alert generation failed', exc_info=True)

    # Current history episodes for this tick's position alerts, read in a new
    # session after the generation commit (so this tick's rows count). A failed
    # lookup leaves every alert without a start (the notifier then falls back
    # to its own record, or to now for a brand-new one).
    now = _utcnow()
    episodes: dict = {}
    episode_rec_ids = {a.recId for a in alerts if a.alertType in POSITION_ALERT_TYPES}
    if episode_rec_ids:
        try:
            async with AsyncSessionLocal() as db:
                episodes = await current_episodes(
                    db, sorted(episode_rec_ids), now, POSITION_ALERT_TYPES,
                    delivery_cfg=delivery)
        except Exception:
            logger.warning('Alert episode lookup failed', exc_info=True)
            episodes = {}

    # Clear dedup entries for positions that have been closed/removed so a
    # future re-entry (new trade) can alert again.
    closed_rec_ids = _known_rec_ids - current_rec_ids
    if closed_rec_ids:
        forget_alerts(closed_rec_ids)
    _known_rec_ids = current_rec_ids

    # ── 2. Regime flip detection ─────────────────────────────────────────────
    # Detection (and persistence) always runs, independent of enabledTypes —
    # only the notification dispatch below is gated by it, matching the
    # position-alert branches above (generate_alerts computes every GLOBALLY
    # gated type unconditionally and lets notify_alert filter on enabledTypes;
    # the one thing it does drop up front is a type a specific position
    # explicitly muted via alert_overrides, which is per-position and so has no
    # equivalent for an account-wide regime flip).
    try:
        from datetime import datetime, timezone
        current_regime = await asyncio.to_thread(compute_overall_regime)
        if _last_regime is not None and current_regime != _last_regime:
            note = f'{_last_regime} -> {current_regime}'
            try:
                async with AsyncSessionLocal() as db:
                    await log_position_alert(
                        db, rec_id='regime', symbol='MARKET', alert_type='REGIME_CHANGE',
                        source='backend', reference_kind='regime', note=note,
                    )
                    # log_position_alert no longer commits its (possibly shared)
                    # session itself — this session is dedicated to this one
                    # call, so it owns the final commit.
                    await db.commit()
            except Exception:
                logger.error('Failed to persist regime flip', exc_info=True)

            if 'REGIME_CHANGE' in enabled_types:
                alerts.append(AlertItem(
                    id='regime-flip',
                    kind='Action',
                    symbol='MARKET',
                    reason=f'Regime flip — {_last_regime} → {current_regime}',
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    recId='regime',
                    alertType='REGIME_CHANGE',
                ))
        _last_regime = current_regime
    except Exception:
        logger.error('Regime flip check failed', exc_info=True)

    # ── 3. Dispatch (shared dedup with the browser path) ─────────────────────
    # notify_alert enforces masterEnabled/enabledTypes and dedups by
    # recId|alertType across BOTH this monitor and the browser POST, so an
    # alert the user already saw in-app won't be emailed twice from here.
    for alert in alerts:
        # generate_alerts already dropped anything a position explicitly muted,
        # so the only override left to honour here is an explicit True — which
        # must beat a globally-disabled type. `None` (no override) keeps
        # notify_alert on the global enabledTypes list, exactly as before.
        view = episodes.get((alert.recId, alert.alertType))
        await notify_alert(alert.symbol, alert.alertType, alert.reason,
                     alert.recId, alert.timestamp,
                     type_enabled=effective_enabled(
                         overrides_by_rec_id.get(alert.recId), alert.alertType),
                     stop_side=alert.stopSide,
                     episode_start=(EpisodeStart(view.start, view.truncated)
                                    if view is not None else None))

        try:
            await alert_service.broadcast([alert.model_dump()])
        except Exception:
            logger.debug('WS broadcast failed for %s|%s',
                         alert.recId, alert.alertType, exc_info=True)

    # ── 4. Daily summary (once per Berlin day from 09:00) ───────────────────
    if generation_ok:
        try:
            await _maybe_send_daily_summary(
                now, alerts, episodes, unquoted, overrides_by_rec_id, enabled_types)
        except Exception:
            logger.error('Daily alert summary failed', exc_info=True)


def _check_interval_seconds() -> int:
    try:
        return max(15, int(_load_delivery_config().get('checkIntervalSeconds', _DEFAULT_CHECK_INTERVAL)))
    except (TypeError, ValueError):
        return _DEFAULT_CHECK_INTERVAL


async def run_portfolio_alert_monitor() -> None:
    """Long-running loop started in app lifespan. Interval is re-read from
    alert_delivery.checkIntervalSeconds every tick, so a settings change takes
    effect on the next cycle without a restart."""
    logger.info('Portfolio alert monitor started (default interval=%ds)', _DEFAULT_CHECK_INTERVAL)
    while True:
        try:
            await _run_once()
        except Exception:
            logger.error('Portfolio alert monitor tick failed', exc_info=True)
        await asyncio.sleep(_check_interval_seconds())
