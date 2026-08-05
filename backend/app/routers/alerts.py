from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market import fetch_quotes
from app.database import get_db
from app.models.portfolio import PortfolioPositionModel
from app.schemas import AlertItem
from app.services.alert_generator import generate_alerts
from app.services.notifications.alert_notifier import notify_alert
from app.services.position_alert_log import log_position_alert

router = APIRouter(prefix='/api', tags=['alerts'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertItem]:
    result = await db.execute(select(PortfolioPositionModel))
    symbols = list({p.symbol for p in result.scalars().all()})
    quotes = fetch_quotes(symbols)
    current_prices = {sym: q["last"] for sym, q in quotes.items()}
    return await generate_alerts(db, current_prices)


class AlertNotifyRequest(BaseModel):
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


_REFERENCE_KIND_BY_TYPE = {
    "TP_HIT": "price",
    "STOP_REACHED": "price",
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

    await log_position_alert(
        db,
        rec_id=req.recId,
        symbol=position.symbol,
        alert_type=req.alertType,
        source="frontend",
        price=req.price,
        reference_value=req.referenceValue,
        reference_kind=_REFERENCE_KIND_BY_TYPE.get(req.alertType),
        direction=position.direction,
        contract=position.contract,
        note=req.note,
    )

    sent = notify_alert(position.symbol, req.alertType, req.reason, req.recId, req.timestamp)
    return {'sent': sent}