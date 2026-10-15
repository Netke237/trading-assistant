from dotenv import load_dotenv
load_dotenv()  # Load root .env into os.environ before market.py reads TRADIER_API_TOKEN

from contextlib import asynccontextmanager
import asyncio
import logging
import os

import math

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.request_guards import NonFiniteJsonGuard
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
from app.routers.composite_watch import router as composite_watch_router
from app.routers.strategy_tuning import router as strategy_tuning_router
from app.routers.config          import router as config_router
from app.routers.symbols         import router as symbols_router
from app.routers.symbol_notes    import router as symbol_notes_router
from app.routers.scan_schedule   import router as scan_schedule_router
from app.routers.journal         import router as journal_router
from app.routers.backtest_artifacts import router as backtest_artifacts_router
from app.routers.scan_reports    import router as scan_reports_router


_portfolio_monitor_task: asyncio.Task | None = None
_regime_monitor_task: asyncio.Task | None = None
_chart_alert_scheduler_task: asyncio.Task | None = None

# Module-level so tests can monkeypatch it to a tmp_path fixture instead of
# touching the real repo settings.yaml — see test_continuous_scan_migration.py.
from pathlib import Path as _Path
_SETTINGS_YAML_PATH = _Path(__file__).parent.parent / "config" / "settings.yaml"


async def _migrate_continuous_scan_session_if_running(status: str | None) -> None:
    """One-shot startup migration (Part 3, §3.9) for the retired
    continuous-scan mechanism.

    If the old ScanSession(id="current") row was left status=="running" as
    of this restart (i.e. exactly the case the now-deleted startup-resume
    code existed to handle), build one `pattern='loop'` ScanScheduleEntry
    from it instead of silently dropping it, then mark the session
    "stopped" either way so this only ever migrates once. `restore_from_db()`
    (already called by the caller) only populates `app.routers.scan._last_request`
    when the row's `last_request_json` column is truthy — if it's null/
    unparseable (e.g. a crash between `_scheduler.start()` and the first
    completed scan, under the old mechanism), there's no request to build an
    entry from; skip the migration and just mark the session stopped."""
    if status != "running":
        return

    import app.routers.scan as _scan_module
    from app.database import AsyncSessionLocal

    last_request = _scan_module._last_request
    last_result = _scan_module._last_result

    if last_request is None:
        async with AsyncSessionLocal() as db:
            await _scan_module._upsert_session(db, req=None, result=None, status="stopped")
        logger.info(
            "startup migration: old continuous-scan session had status='running' but no "
            "usable last request — nothing to migrate, marked stopped"
        )
        return

    import uuid
    from datetime import datetime, timezone
    import yaml as _yaml
    from app.schemas.schedule import ScheduleConfig as _ScheduleConfig
    from app.schemas.scan_schedule import ScanScheduleEntry
    from app.services.scan_schedule_store import scan_schedule_store

    try:
        _raw = _yaml.safe_load(_SETTINGS_YAML_PATH.read_text()) or {} if _SETTINGS_YAML_PATH.exists() else {}
        sched_cfg = _ScheduleConfig(**_raw.get("scan", {}).get("schedule", {}))
    except Exception:
        sched_cfg = _ScheduleConfig()

    entry = ScanScheduleEntry(
        id=str(uuid.uuid4()),
        label="Migrated from continuous scan",
        mode="options",
        profile_id="",
        profile_name="Migrated from continuous scan",
        profile_synced_at=datetime.now(timezone.utc).isoformat(),
        resolved_request=last_request.model_dump(),
        pattern="loop",
        enabled=True,
        days_of_week=sched_cfg.days_of_week,
        cadence_minutes=sched_cfg.cadence_minutes,
        window_start_hour=sched_cfg.window_start_hour,
        window_end_hour=sched_cfg.window_end_hour,
    )
    scan_schedule_store.upsert(entry.model_dump())
    logger.info(
        "startup migration: created ScanScheduleEntry %s ('%s') from the old "
        "continuous-scan session", entry.id, entry.label,
    )

    async with AsyncSessionLocal() as db:
        await _scan_module._upsert_session(db, req=last_request, result=last_result, status="stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _portfolio_monitor_task, _regime_monitor_task, _chart_alert_scheduler_task
    # SQLite development bootstraps new additive tables; PostgreSQL uses Alembic.
    # A bootstrap failure aborts startup visibly, never advertises a working log.
    from app.database import engine
    if engine.dialect.name == 'sqlite':
        from app.models.scan_report import ScanReportBase
        async with engine.begin() as conn:
            await conn.run_sync(ScanReportBase.metadata.create_all)
    # ── Startup ──────────────────────────────────────────────────────────
    _web_concurrency = int(os.getenv("WEB_CONCURRENCY", "1"))
    if _web_concurrency > 1:
        logger.error(
            "WEB_CONCURRENCY=%d detected — strategy-tuning concurrency guard AND "
            "Part 3's scheduled-scan concurrency guard (_SCHEDULED_SCAN_SEMAPHORE, "
            "scan_schedule_scheduler.py) both use an in-process asyncio "
            "lock/semaphore invisible across workers. "
            "Run with --workers 1 or migrate both to a shared lock backend.",
            _web_concurrency,
        )
    # ── One-time settings migrations (see app/services/settings_migrations.py
    # for why these must run exactly once, ever, not on every startup) ────────
    try:
        from pathlib import Path as _Path
        from app.services.settings_migrations import migrate_structural_stop_breached_enabled_types
        migrate_structural_stop_breached_enabled_types(
            _Path(__file__).parent.parent / "config" / "settings.yaml"
        )
    except Exception as _exc:
        logger.warning("settings.yaml migration failed: %s", _exc)

    from app.services.scan_report_lifecycle import recover_interrupted
    await recover_interrupted()

    from app.routers.scan import restore_from_db
    from app.routers.stock_scan import restore_stock_from_db
    status = await restore_from_db()
    await restore_stock_from_db()
    # One-shot migration: if the retired continuous-scan mechanism (see Part
    # 3, §3.9) was left "running" as of this restart, migrate it into a
    # single Part-3 `loop`-pattern ScanScheduleEntry instead of silently
    # dropping it. Idempotent by construction — this marks the old session
    # "stopped" either way, so a second boot sees status != "running" and
    # skips this path entirely.
    try:
        await _migrate_continuous_scan_session_if_running(status)
    except Exception as _exc:
        logger.warning("continuous-scan migration failed: %s", _exc)
    # ── Part 3: profile-based scan scheduling ──────────────────────────────
    try:
        from app.services.scan_schedule_scheduler import sync_fixed_time_jobs, scan_schedule_loop_runner
        sync_fixed_time_jobs()
        await scan_schedule_loop_runner.start()
    except Exception as _exc:
        logger.warning("scan_schedule_scheduler startup failed: %s", _exc)
    # Keep strong references so the GC never collects background tasks.
    from app.services.portfolio_alert_monitor import run_portfolio_alert_monitor
    _portfolio_monitor_task = asyncio.create_task(run_portfolio_alert_monitor())
    from app.services.regime_monitor import run_regime_monitor
    _regime_monitor_task = asyncio.create_task(run_regime_monitor())
    from app.services.chart_alert_scheduler import run_chart_alert_scheduler
    _chart_alert_scheduler_task = asyncio.create_task(run_chart_alert_scheduler())
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
    # ── Fundamentals prefetch (background thread) ─────────────────────────
    try:
        import threading as _threading
        from app.services.fundamentals_store import prefetch_universe as _prefetch_fundamentals
        from app.data.universe_presets import expand_universe as _expand_universe
        _fund_universe = list(dict.fromkeys(
            _expand_universe(["SP500"]) + _expand_universe(["NDX100"]) + _expand_universe(["DOW30"])
        ))
        _threading.Thread(
            target=_prefetch_fundamentals, args=(_fund_universe,), daemon=True, name="fundamentals-prefetch"
        ).start()
        logger.info("startup: fundamentals prefetch started for %d symbols", len(_fund_universe))
    except Exception as _exc:
        logger.warning("fundamentals prefetch startup failed: %s", _exc)
    # ── EDGAR fundamentals scheduler ─────────────────────────────────────────
    try:
        from app.services.edgar_schedule_store import edgar_schedule_store as _edgar_store
        from app.services import edgar_scheduler as _edgar_sched
        _edgar_cfg = _edgar_store.get()
        _edgar_sched.configure(_edgar_cfg["enabled"], _edgar_cfg["time"])
        _edgar_sched.start()
    except Exception as _exc:
        logger.warning("edgar_scheduler startup failed: %s", _exc)
    # ── S&P 500 liquidity scheduler ───────────────────────────────────────────
    try:
        from app.services.sp500_schedule_store import sp500_schedule_store as _sp500_store
        from app.services import sp500_scheduler as _sp500_sched
        _sp500_cfg = _sp500_store.get()
        _sp500_sched.configure(_sp500_cfg["enabled"], _sp500_cfg["time"])
        _sp500_sched.start()
    except Exception as _exc:
        logger.warning("sp500_scheduler startup failed: %s", _exc)
    # ── Strategy tuning scheduler ─────────────────────────────────────────────
    try:
        from app.services.tuning_schedule_store import tuning_schedule_store as _tuning_store
        from app.services import tuning_scheduler as _tuning_sched
        _tuning_cfg = _tuning_store.get()
        _tuning_sched.configure(_tuning_cfg["enabled"], _tuning_cfg["time"], _tuning_cfg.get("days_of_week"))
        _tuning_sched.start()
    except Exception as _exc:
        logger.warning("tuning_scheduler startup failed: %s", _exc)
    # ── Strategy-watch scheduler ──────────────────────────────────────────
    try:
        from app.services.strategy_watch_scheduler import strategy_watch_scheduler
        await strategy_watch_scheduler.start()
    except Exception as _exc:
        logger.warning("strategy_watch_scheduler startup failed: %s", _exc)
    # ── IBKR keep-alive scheduler ──────────────────────────────────────────
    try:
        from app.services import ibkr_keepalive_scheduler as _ibkr_sched
        _ibkr_sched.start()
    except Exception as _exc:
        logger.warning("ibkr_keepalive_scheduler startup failed: %s", _exc)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    try:
        from app.services import ingestion_scheduler as _isched
        _isched.shutdown()
    except Exception:
        pass
    try:
        from app.services import edgar_scheduler as _edgar_sched
        _edgar_sched.shutdown()
    except Exception:
        pass
    try:
        from app.services import sp500_scheduler as _sp500_sched
        _sp500_sched.shutdown()
    except Exception:
        pass
    try:
        from app.services import tuning_scheduler as _tuning_sched
        _tuning_sched.shutdown()
    except Exception:
        pass
    try:
        from app.services.strategy_watch_scheduler import strategy_watch_scheduler
        await strategy_watch_scheduler.stop()
    except Exception:
        pass
    try:
        from app.services import ibkr_keepalive_scheduler as _ibkr_sched
        _ibkr_sched.shutdown()
    except Exception:
        pass
    try:
        # wait=False unblocks THIS lifespan/async-shutdown sequence specifically
        # (we don't await a running calibration here); cancel_futures=True drops
        # anything still queued. Note the interpreter's own atexit hook may still
        # briefly join the non-daemon worker thread on process exit — bounded by
        # one calibration's duration (~2s worst case).
        from app.routers.scan import _HESTON_EXECUTOR
        _HESTON_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    try:
        from app.services.scan_schedule_scheduler import shutdown_fixed_time_scheduler, scan_schedule_loop_runner
        shutdown_fixed_time_scheduler()
        await scan_schedule_loop_runner.stop()
    except Exception:
        pass
    for task in (_portfolio_monitor_task, _regime_monitor_task, _chart_alert_scheduler_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    # Cancel any in-flight WFO optimization task so it doesn't outlive the server.
    try:
        from app.routers import strategy_tuning as _st
        if _st._ACTIVE_TASK and not _st._ACTIVE_TASK.done():
            _st._ACTIVE_TASK.cancel()
            try:
                await _st._ACTIVE_TASK
            except asyncio.CancelledError:
                pass
    except Exception:
        pass


def _finite_or_str(value):
    """Replace every non-finite float, at any depth, by its string form."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)   # 'nan', 'inf', '-inf'
    if isinstance(value, dict):
        return {k: _finite_or_str(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_str(v) for v in value]
    return value


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422, minus the 500 it turns into on a NaN/Infinity input.

    P6 (G1-6 residual; decision P6-SCOPE-2026-09-30 authorised this file). The
    default handler echoes each error's `input` into `detail`, and Starlette's
    JSONResponse encodes with allow_nan=False -- so a body carrying NaN or
    Infinity was correctly REFUSED and the refusal itself raised, reaching the
    client as a 500. Same status, same `detail` list, same loc/msg/type
    (lib/api.ts apiError reads loc and msg); only a non-finite value becomes
    its string."""
    # Other errors (such as missing fields) can retain the whole rejected body.
    # Strip every input before normalization/encoding when depth was refused.
    errors = exc.errors()
    if any(error.get("type") == "payload_depth" for error in errors):
        errors = [
            {key: value for key, value in error.items() if key != "input"}
            for error in errors
        ]
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(_finite_or_str(errors))},
    )


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Trading Assistant API",
        version="0.1.0",
        description="Backend API for the Trading Assistant options screener.",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )
    app.add_exception_handler(RequestValidationError, request_validation_handler)

    # NUMERIC-API-INPUTS T1: refuse NaN/Infinity/overflowing JSON numbers with a
    # 422 before any endpoint runs. Added BEFORE CORSMiddleware on purpose:
    # Starlette makes the last-added middleware outermost, so CORS wraps the
    # guard and its 422 carries the CORS headers.
    app.add_middleware(NonFiniteJsonGuard)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3003"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Scan-Report-Run-Id", "X-Scan-Report-Generation", "X-Scan-Report-Persistence"],
    )

    app.include_router(health_router)

    app.include_router(watchlist_router)
    app.include_router(watched_contracts_router)
    app.include_router(contracts_router)
    app.include_router(candles_router)
    app.include_router(symbols_router)
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
    app.include_router(symbol_notes_router)
    app.include_router(ingestion_router)
    app.include_router(strategy_watch_router)
    app.include_router(composite_watch_router)
    app.include_router(strategy_tuning_router)
    app.include_router(config_router)
    app.include_router(scan_schedule_router)
    app.include_router(journal_router)
    app.include_router(scan_reports_router)
    app.include_router(backtest_artifacts_router)

    return app


app = create_app()
