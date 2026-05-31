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


@router.post('/alerts/notify')
async def post_alert_notify(req: AlertNotifyRequest) -> dict:
    """Dispatch a single in-app alert to email/Telegram.

    Called by the browser when a NEW portfolio alert is shown, so what the user
    sees gets delivered. Deduped server-side (shared with the headless monitor).
    """
    sent = notify_alert(req.symbol, req.alertType, req.reason, req.recId, req.timestamp)
    return {'sent': sent}