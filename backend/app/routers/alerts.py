import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market import fetch_contract_quote_async, fetch_quotes
from app.database import get_db
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel
from app.schemas import (
    AlertEpisodeItem,
    AlertEpisodesResponse,
    AlertHistoryResponse,
    AlertHistoryRow,
    AlertItem,
)
from app.services import alert_episodes
from app.services.alert_generator import (
    POSITION_ALERT_TYPES,
    effective_enabled,
    generate_alerts,
    stamp_target_first_hit,
)
from app.services.notifications.alert_notifier import notify_alert
from app.services.position_alert_log import log_position_alert
from app.services.premium_stop import premium_stop_side

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['alerts'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertItem]:
    positions = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    symbols = list({p.symbol for p in positions})
    # fetch_quotes is synchronous (a blocking httpx.get, up to its own
    # timeout) — run it off the event loop thread, same as
    # portfolio_alert_monitor.py's identical call, so one slow/unresponsive
    # upstream quote doesn't stall every other concurrent request this
    # single-threaded server is handling (other users' API calls, WS alert
    # ticks, background schedulers) for the duration of this call.
    quotes = await asyncio.to_thread(fetch_quotes, symbols)
    current_prices = {sym: q["last"] for sym, q in quotes.items()}

    # Live option prices — same source as portfolio_alert_monitor.py's
    # headless dispatch loop — so PREMIUM_STOP can actually fire through
    # this endpoint too. Without this, current_option_prices stayed None
    # forever and PREMIUM_STOP could never surface on the Dashboard's
    # "Latest Alert" rail (fed exclusively by this endpoint), even though
    # the same condition correctly emails/Telegrams via the background job.
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

    alerts = await generate_alerts(db, current_prices, option_prices or None)
    # generate_alerts() writes position_alert_history rows (log_position_alert)
    # and updates PortfolioPositionModel.alert_state, neither of which self-
    # commits any more (see log_position_alert's docstring) — get_db() only
    # closes the session without committing, so this endpoint owns the commit.
    # Without this, both were silently discarded on every poll through here.
    await db.commit()
    return alerts


class AlertNotifyRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: a non-finite price/referenceValue is a 422.
    model_config = ConfigDict(allow_inf_nan=False)

    # symbol is accepted but intentionally unused below (post_alert_notify
    # derives it from the DB row instead) — kept on the wire schema since the
    # frontend already sends it and it's harmless input.
    symbol: str
    alertType: str
    reason: str
    recId: str
    timestamp: str | None = None
    price: float | None = None
    referenceValue: float | None = None
    direction: str | None = None
    contract: str | None = None
    note: str | None = None
    # STOP-SEMANTICS-2026-10-02. NOT trusted as a value -- the side is derived
    # from the DB row below. Its PRESENCE is the signal: a tab still running
    # the pre-deploy engine sends none, and its PREMIUM_STOP for a short is a
    # fall-side fire that must keep the legacy key and label.
    stopSide: str | None = None


_REFERENCE_KIND_BY_TYPE = {
    "TP_HIT": "price",
    "STOP_REACHED": "price",
    "STRUCTURAL_STOP_BREACHED": "price",
    "PREMIUM_STOP": "price",
    "TIME_STOP": "days",
    "EVENT_RISK": "days",
    "REGIME_CHANGE": "regime",
}


# ── Alert episodes / history (PORTFOLIO-ALERT-ACTION, #672) ─────────────────
# Read-only: no writes, no flush, no commit.

_HISTORY_ROW_CAP = 500


def _iso_utc(dt: datetime | None) -> str | None:
    return None if dt is None else alert_episodes.as_utc(dt).isoformat()


def _episode_item(view: alert_episodes.EpisodeView, symbol: str) -> AlertEpisodeItem:
    return AlertEpisodeItem(
        recId=view.rec_id,
        symbol=symbol,
        alertType=view.alert_type,
        startedAt=_iso_utc(view.start),
        lastFiredAt=_iso_utc(view.last),
        fireCount=view.count,
        startTruncated=view.truncated,
    )


@router.get('/alerts/episodes', response_model=AlertEpisodesResponse)
async def get_alert_episodes(db: AsyncSession = Depends(get_db)) -> AlertEpisodesResponse:
    """Current episodes of the position alert types for OPEN positions only.

    gapHours/retentionDays are the exact values the episodes were computed
    with (one config read), so the UI never guesses them.
    """
    now = datetime.now(timezone.utc)
    cfg = alert_episodes.load_delivery_config()
    gap = alert_episodes.effective_gap(cfg)
    positions = (await db.execute(
        select(PortfolioPositionModel.rec_id, PortfolioPositionModel.symbol)
    )).all()
    symbol_by_rec = {rec_id: symbol for rec_id, symbol in positions}
    current = await alert_episodes.current_episodes(
        db, list(symbol_by_rec), now, POSITION_ALERT_TYPES, delivery_cfg=cfg,
    )
    views = sorted(current.values(), key=lambda v: (v.start, v.rec_id, v.alert_type))
    return AlertEpisodesResponse(
        gapHours=gap.total_seconds() / 3600,
        retentionDays=alert_episodes.retention_days(cfg),
        generatedAt=_iso_utc(now),
        episodes=[_episode_item(v, symbol_by_rec[v.rec_id]) for v in views],
    )


@router.get('/alerts/history/{rec_id}', response_model=AlertHistoryResponse)
async def get_alert_history(rec_id: str, db: AsyncSession = Depends(get_db)) -> AlertHistoryResponse:
    """One open position's alert log (newest first, capped) and every episode
    of every alert type for it (computed from all rows, not the capped page).
    404 when rec_id is not an open position."""
    position = (await db.execute(
        select(PortfolioPositionModel.symbol).where(PortfolioPositionModel.rec_id == rec_id)
    )).first()
    if position is None:
        raise HTTPException(status_code=404, detail='position_not_found')
    symbol = position[0]

    now = datetime.now(timezone.utc)
    cfg = alert_episodes.load_delivery_config()
    rows = (await db.execute(
        select(PositionAlertHistoryModel)
        .where(PositionAlertHistoryModel.rec_id == rec_id)
        .order_by(PositionAlertHistoryModel.triggered_at.desc(), PositionAlertHistoryModel.id)
        .limit(_HISTORY_ROW_CAP)
    )).scalars().all()
    episodes = await alert_episodes.all_episodes(db, rec_id, now, delivery_cfg=cfg)
    return AlertHistoryResponse(
        recId=rec_id,
        symbol=symbol,
        rows=[
            AlertHistoryRow(
                alertType=r.alert_type,
                source=r.source,
                price=r.price,
                referenceValue=r.reference_value,
                referenceKind=r.reference_kind,
                note=r.note,
                triggeredAt=_iso_utc(r.triggered_at),
            )
            for r in rows
        ],
        episodes=[_episode_item(v, symbol) for v in episodes],
    )


@router.post('/alerts/notify')
async def post_alert_notify(
    req: AlertNotifyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Persist the frontend engine's alert fire, then separately dispatch it
    to email/Telegram.

    Called by the browser when a NEW portfolio alert is shown. Guarded: the
    alert is only recorded/dispatched when its recId is a currently-open
    position in the DB, so a stale localStorage phantom in the browser cannot
    write history or email alerts for a position the backend does not hold.
    symbol/contract/direction are derived from the authoritative DB row, not
    trusted from the request body, so a buggy tab can't misattribute a fire to
    the wrong symbol/contract. price/referenceValue ARE taken from the request
    — they're the frontend engine's own observed values, which is the point of
    a source="frontend" row.

    Persistence (log_position_alert) is independent of notify_alert's
    masterEnabled/enabledTypes dispatch gating, so a muted alert type still
    gets an audit row even when it isn't emailed/Telegrammed.
    """
    position = (await db.execute(
        select(PortfolioPositionModel).where(
            PortfolioPositionModel.rec_id == req.recId
        )
    )).scalar_one_or_none()
    if position is None:
        return {'sent': False, 'reason': 'position_not_found'}

    # Only tag a reference_kind when there's an actual reference_value to go
    # with it — e.g. the frontend engine has no dollar price/threshold in
    # scope for PREMIUM_STOP (only pnlPct), so both are left None rather than
    # stamping "price" on a row with nothing to measure.
    reference_kind = _REFERENCE_KIND_BY_TYPE.get(req.alertType) if req.referenceValue is not None else None

    await log_position_alert(
        db,
        rec_id=req.recId,
        symbol=position.symbol,
        alert_type=req.alertType,
        source="frontend",
        price=req.price,
        reference_value=req.referenceValue,
        reference_kind=reference_kind,
        direction=position.direction,
        contract=position.contract,
        note=req.note,
    )
    # PORTFOLIO-ALERT-ACTION: the first TP_HIT stamps target_first_hit_at on
    # this open position (never overwritten; see stamp_target_first_hit).
    if req.alertType == 'TP_HIT':
        await stamp_target_first_hit(db, req.recId, datetime.now(timezone.utc))
    # log_position_alert no longer commits the (shared, request-scoped) session
    # itself — see its docstring — so this endpoint owns the final commit.
    await db.commit()

    # Honour the position's per-type override (Feature D) over the global
    # enabledTypes list — `None` when it has none, which leaves notify_alert on
    # the global list exactly as before. The browser engine already suppresses
    # a muted type before it ever POSTs here, so in practice this carries an
    # explicit True; passing the full three-way result anyway keeps this path
    # correct on its own rather than relying on the caller having filtered.
    # The side comes from the authoritative row, like symbol/contract/direction
    # above. A request with no stopSide came from a pre-deploy engine (see
    # AlertNotifyRequest.stopSide) and keeps the legacy key and label.
    stop_side = (
        premium_stop_side(position.contract, position.direction)
        if req.alertType == 'PREMIUM_STOP' and req.stopSide is not None
        else None
    )
    # PORTFOLIO-ALERT-ACTION: the key's current history episode, read after the
    # commit above so this fire's row counts. A failed lookup passes None (the
    # notifier then falls back to its own record, or to now for a new one).
    episode_start = None
    if req.alertType in POSITION_ALERT_TYPES:
        try:
            episode_start = await alert_episodes.episode_start(
                db, req.recId, req.alertType, datetime.now(timezone.utc))
        except Exception:
            logger.warning('Alert episode lookup failed for %s|%s',
                           req.recId, req.alertType, exc_info=True)
    sent = await notify_alert(
        position.symbol, req.alertType, req.reason, req.recId, req.timestamp,
        type_enabled=effective_enabled(position.alert_overrides, req.alertType),
        stop_side=stop_side,
        episode_start=episode_start,
    )
    return {'sent': sent}
