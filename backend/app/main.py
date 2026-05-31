from dotenv import load_dotenv
load_dotenv()  # Load root .env into os.environ before market.py reads TRADIER_API_TOKEN

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.health import router as health_router

from app.routers.watchlist          import router as watchlist_router
from app.routers.watched_contracts  import router as watched_contracts_router
from app.routers.contracts  import router as contracts_router
from app.routers.candles    import router as candles_router
from app.routers.regime     import router as regime_router
from app.routers.sectors    import router as sectors_router
from app.routers.tradecards import router as tradecards_router
from app.routers.portfolio  import router as portfolio_router
from app.routers.alerts     import router as alerts_router
from app.routers.events     import router as events_router
from app.routers.ws_alerts  import router as ws_alerts_router
from app.routers.scan       import router as scan_router
from app.routers.news       import router as news_router
from app.routers.chart      import router as chart_router
from app.routers.chart_alerts import router as chart_alerts_router
from app.routers.notification_settings import router as notification_settings_router


_notification_worker_task: asyncio.Task | None = None
_portfolio_monitor_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _notification_worker_task, _portfolio_monitor_task
    # ── Startup ──────────────────────────────────────────────────────────
    from app.routers.scan import restore_from_db, _scheduler, _scheduled_scan
    status = await restore_from_db()
    if status == "running":
        _scheduler.bind(_scheduled_scan)
        await _scheduler.start()
    # Keep strong references so the GC never collects background tasks.
    from app.services.notifications.queue import notification_worker
    _notification_worker_task = asyncio.create_task(notification_worker())
    from app.services.portfolio_alert_monitor import run_portfolio_alert_monitor
    _portfolio_monitor_task = asyncio.create_task(run_portfolio_alert_monitor())
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    if _scheduler._running:
        await _scheduler.stop()
    for task in (_notification_worker_task, _portfolio_monitor_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Trading Assistant API",
        version="0.1.0",
        description="Backend API for the Trading Assistant options screener.",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else ["http://localhost:3001", "http://localhost:3003"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)

    app.include_router(watchlist_router)
    app.include_router(watched_contracts_router)
    app.include_router(contracts_router)
    app.include_router(candles_router)
    app.include_router(regime_router)
    app.include_router(sectors_router)
    app.include_router(tradecards_router)
    app.include_router(portfolio_router)
    app.include_router(alerts_router)
    app.include_router(events_router)
    app.include_router(ws_alerts_router)
    app.include_router(scan_router)
    app.include_router(news_router)
    app.include_router(chart_router)
    app.include_router(chart_alerts_router)
    app.include_router(notification_settings_router)

    return app


app = create_app()
