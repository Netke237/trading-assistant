import asyncio

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market import fetch_contract_quote_async, fetch_quotes
from app.database import get_db
from app.models.portfolio import PortfolioPositionModel
from app.schemas import AlertItem
from app.services.alert_generator import effective_enabled, generate_alerts
from app.services.notifications.alert_notifier import notify_alert
from app.services.position_alert_log import log_position_alert
from app.services.premium_stop import premium_stop_side

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
    sent = await notify_alert(
        position.symbol, req.alertType, req.reason, req.recId, req.timestamp,
        type_enabled=effective_enabled(position.alert_overrides, req.alertType),
        stop_side=stop_side,
    )
    return {'sent': sent}
