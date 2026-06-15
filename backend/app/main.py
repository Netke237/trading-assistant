from dotenv import load_dotenv
load_dotenv()  # Load root .env into os.environ before market.py reads TRADIER_API_TOKEN

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)
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
from app.routers.risk_settings import router as risk_settings_router
from app.routers.data_sources  import router as data_sources_router
from app.routers.credentials   import router as credentials_router
from app.routers.broker        import router as broker_router
from app.routers.stock_scan    import router as stock_scan_router
from app.routers.auto_trade    import router as auto_trade_router
from app.routers.historical_data import router as historical_data_router
from app.routers.chart_drawings  import router as chart_drawings_router
from app.routers.ingestion       import router as ingestion_router
from app.routers.strategy_watch  import router as strategy_watch_router
from app.routers.strategy_tuning import router as strategy_tuning_router


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
    # ── Nightly ingestion scheduler ──────────────────────────────────────
    try:
        from app.services.ingestion_schedule_store import ingestion_schedule_store as _sched_store
        from app.services import ingestion_scheduler as _isched
        _sched_cfg = _sched_store.get()
        _isched.configure(_sched_cfg["enabled"], _sched_cfg["time"])
        _isched.start()
    except Exception as _exc:
        logger.warning("ingestion_scheduler startup failed: %s", _exc)
    # ── Startup catch-up: ingest if DB is stale ───────────────────────────
    try:
        from app.services.ingestion_job import _should_ingest, start_ingestion_task
        from app.services.historical_store import _last_stored_date
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as _db:
            _last = await _last_stored_date("SPY", _db)
        if _should_ingest(_last):
            try:
                from app.data.universe_presets import expand_universe
                _universe = list(dict.fromkeys(
                    expand_universe(["SP500"]) + expand_universe(["NDX100"]) + expand_universe(["DOW30"])
                ))
            except Exception:
                _universe = ["SPY"]
            start_ingestion_task(_universe, years=6)
            logger.info(
                "startup: DB stale (last SPY date=%s), started ingestion for %d symbols",
                _last, len(_universe),
            )
    except Exception as _exc:
        logger.warning("startup catch-up failed: %s", _exc)
    # ── Strategy-watch scheduler ──────────────────────────────────────────
    try:
        from app.services.strategy_watch_scheduler import strategy_watch_scheduler
        await strategy_watch_scheduler.start()
    except Exception as _exc:
        logger.warning("strategy_watch_scheduler startup failed: %s", _exc)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    try:
        from app.services import ingestion_scheduler as _isched
        _isched.shutdown()
    except Exception:
        pass
    try:
        from app.services.strategy_watch_scheduler import strategy_watch_scheduler
        await strategy_watch_scheduler.stop()
    except Exception:
        pass
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
    app.include_router(risk_settings_router)
    app.include_router(data_sources_router)
    # Credential store singleton loads from local_credentials.yaml on import (side-effect).
    # Importing credentials_router above already triggers this.
    app.include_router(credentials_router)
    app.include_router(broker_router)
    app.include_router(stock_scan_router)
    app.include_router(auto_trade_router)
    app.include_router(historical_data_router)
    app.include_router(chart_drawings_router)
    app.include_router(ingestion_router)
    app.include_router(strategy_watch_router)
    app.include_router(strategy_tuning_router)

    return app


app = create_app()
