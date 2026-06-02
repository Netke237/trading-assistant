"""Background monitor that checks portfolio positions for alert conditions every 15 min
and dispatches enabled alerts via Telegram / Gmail."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.portfolio import PortfolioPositionModel
from app.routers.regime import compute_overall_regime
from app.schemas import AlertItem
from app.services.alert_generator import generate_alerts
from app.services.alert_service import alert_service
from app.services.notifications.alert_notifier import forget_alerts, notify_alert

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'
_CHECK_INTERVAL = 15 * 60  # seconds

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

    if not delivery.get('masterEnabled', True):
        return

    enabled_types: list[str] = delivery.get('enabledTypes', [
        'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP', 'REGIME_CHANGE',
    ])

    alerts: list[AlertItem] = []
    current_rec_ids: set[str] = set()

    # ── 1. Portfolio position alerts ─────────────────────────────────────────
    try:
        import httpx

        from app.data.market import fetch_contract_quote_async, fetch_quotes
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PortfolioPositionModel))
            positions = result.scalars().all()
            current_rec_ids = {p.rec_id for p in positions if p.rec_id}
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

                alerts.extend(await generate_alerts(
                    db, current_prices, option_prices or None))
    except Exception:
        logger.error('Portfolio alert generation failed', exc_info=True)

    # Clear dedup entries for positions that have been closed/removed so a
    # future re-entry (new trade) can alert again.
    closed_rec_ids = _known_rec_ids - current_rec_ids
    if closed_rec_ids:
        forget_alerts(closed_rec_ids)
    _known_rec_ids = current_rec_ids

    # ── 2. Regime flip detection ─────────────────────────────────────────────
    if 'REGIME_CHANGE' in enabled_types:
        try:
            from datetime import datetime, timezone
            current_regime = await asyncio.to_thread(compute_overall_regime)
            if _last_regime is not None and current_regime != _last_regime:
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
        notify_alert(alert.symbol, alert.alertType, alert.reason,
                     alert.recId, alert.timestamp)

        try:
            await alert_service.broadcast([alert.model_dump()])
        except Exception:
            logger.debug('WS broadcast failed for %s|%s',
                         alert.recId, alert.alertType, exc_info=True)


async def run_portfolio_alert_monitor() -> None:
    """Long-running loop started in app lifespan. Checks every 15 min."""
    logger.info('Portfolio alert monitor started (interval=%ds)', _CHECK_INTERVAL)
    while True:
        try:
            await _run_once()
        except Exception:
            logger.error('Portfolio alert monitor tick failed', exc_info=True)
        await asyncio.sleep(_CHECK_INTERVAL)
