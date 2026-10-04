"""Strategy-tuning router — run walk-forward optimization, poll jobs, adopt proposals."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.services import strategy_param_store as store

router = APIRouter(prefix="/api/strategy-tuning", tags=["strategy-tuning"])

_JOBS: dict[str, dict] = {}
_ACTIVE: str | None = None
_ACTIVE_TASK: asyncio.Task | None = None
# Single-worker design: only one optimization run at a time.
# The lock makes the 409 check + job creation atomic within an asyncio event loop.
_LOCK: asyncio.Lock = asyncio.Lock()


class AdoptRequest(BaseModel):
    strategy: str
    params: dict[str, Any]
    direction: Literal["Bullish", "Bearish"]   # REQUIRED -- fix #1: the old
    # "Bullish" default wrote bearish-tuned params into active.bullish.

    @field_validator("direction", mode="before")
    @classmethod
    def _norm_direction(cls, v):
        from app.services.strategy_backtest import normalize_direction
        return normalize_direction(v)

    @field_validator("params")
    @classmethod
    def params_must_be_scalars(cls, v: dict) -> dict:
        for key, val in v.items():
            if not isinstance(val, (bool, int, float, str)):
                raise ValueError(
                    f"params[{key!r}] must be a scalar (bool, int, float, str), "
                    f"got {type(val).__name__}"
                )
        return v


def _evict_old_jobs(max_completed: int) -> None:
    """Drop oldest finished jobs beyond max_completed; evict completed before failed.

    Failure evidence is preserved longer so the user can diagnose issues after
    the session fills up with completed runs.
    """
    completed = [jid for jid, j in _JOBS.items() if j.get("status") == "completed"]
    failed = [jid for jid, j in _JOBS.items() if j.get("status") == "failed"]
    candidates = completed + failed  # completed are eviction candidates first
    excess = len(candidates) - max_completed
    if excess > 0:
        for jid in candidates[:excess]:
            del _JOBS[jid]


async def _run_optimization_job(job_id: str) -> None:
    """Core WFO work — runs as a task; job_id must already exist in _JOBS."""
    try:
        from app.services.strategy_param_optimizer import run_optimization

        def progress(done: int, total: int) -> None:
            _JOBS[job_id].update(done=done, total=total)

        cfg = store._load()
        strategies = list(cfg.get("strategies", {}).keys())
        basket_symbols = cfg.get("basket", {}).get("symbols", [])
        if not basket_symbols:
            from app.services.strategy_basket import propose_basket
            per_sector = cfg.get("basket", {}).get("per_sector", 5)
            basket_symbols = propose_basket(per_sector=per_sector)
        opt_cfg = store.get_optimization_config()
        proposals = await run_optimization(
            strategies,
            basket_symbols,
            store.get_windows(),
            store.get_costs(),
            progress,
            direction=store.get_direction(),
            min_trades=opt_cfg.get("min_trades", 20),
            min_consistency=opt_cfg.get("min_consistency", 0.5),
            min_symbols=opt_cfg.get("min_symbols", 3),
        )
        _JOBS[job_id].update(status="completed", proposals=proposals)
        _evict_old_jobs(store.get_job_retention().get("max_completed", 100))
    except Exception as exc:  # noqa: BLE001
        _JOBS[job_id].update(status="failed", error=str(exc))
        _evict_old_jobs(store.get_job_retention().get("max_completed", 100))


async def start_if_idle() -> str | None:
    """Start a WFO job unless one is already running. Returns job_id or None if busy."""
    global _ACTIVE, _ACTIVE_TASK
    async with _LOCK:
        if _ACTIVE and _JOBS.get(_ACTIVE, {}).get("status") == "running":
            return None
        job_id = uuid.uuid4().hex
        _JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "proposals": {}}
        _ACTIVE = job_id
        _ACTIVE_TASK = asyncio.create_task(_run_optimization_job(job_id))
    _JOBS[job_id]["task"] = None
    return job_id


@router.post("/run")
async def run_job(body: dict = Body(default={})) -> dict:
    job_id = await start_if_idle()
    if job_id is None:
        raise HTTPException(status_code=409, detail="An optimization run is already active.")
    return {"job_id": job_id}


@router.get("/jobs")
async def list_jobs() -> dict:
    """Return a count summary of all in-memory job records."""
    statuses = [j.get("status") for j in _JOBS.values()]
    return {
        "count": len(_JOBS),
        "completed": statuses.count("completed"),
        "failed": statuses.count("failed"),
        "running": statuses.count("running"),
    }


@router.delete("/jobs")
async def clear_jobs() -> dict:
    """Remove all completed and failed job records from memory. Running jobs are kept."""
    global _ACTIVE
    to_delete = [jid for jid, j in _JOBS.items() if j.get("status") in ("completed", "failed")]
    for jid in to_delete:
        del _JOBS[jid]
    # Reset _ACTIVE if it pointed to a job that was just cleared
    if _ACTIVE and _ACTIVE not in _JOBS:
        _ACTIVE = None
    return {"cleared": len(to_delete)}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail="unknown job")
    # Exclude internal keys not safe to serialise
    job = {k: v for k, v in _JOBS[job_id].items() if k != "task"}
    return job


_TIME_RE_ST = __import__("re").compile(r"^\d{2}:\d{2}$")


class TuningScheduleUpdate(BaseModel):
    enabled: bool
    time: str = Field(description="HH:MM in 24-hour format, e.g. '05:00'")
    days_of_week: list[int] = Field(
        default_factory=lambda: [5],
        description="0=Mon…6=Sun. Default Saturday-only (compute-heavy, weekly cadence).",
    )


@router.get("/schedule")
async def get_tuning_schedule() -> dict:
    from app.services.tuning_schedule_store import tuning_schedule_store
    from app.services import tuning_scheduler
    cfg = tuning_schedule_store.get()
    return {**cfg, "next_run": tuning_scheduler.next_run_time()}


@router.post("/schedule")
async def update_tuning_schedule(body: TuningScheduleUpdate) -> dict:
    if not _TIME_RE_ST.match(body.time):
        raise HTTPException(status_code=422, detail="time must be HH:MM, e.g. '05:00'")
    h, m = int(body.time[:2]), int(body.time[3:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise HTTPException(status_code=422, detail="time out of range")
    if not body.days_of_week or any(d < 0 or d > 6 for d in body.days_of_week):
        raise HTTPException(status_code=422, detail="days_of_week must be non-empty ints in 0..6")
    from app.services.tuning_schedule_store import tuning_schedule_store
    from app.services import tuning_scheduler
    tuning_schedule_store.set(body.enabled, body.time, body.days_of_week)
    tuning_scheduler.configure(body.enabled, body.time, body.days_of_week)
    return {
        "ok": True, "enabled": body.enabled, "time": body.time,
        "days_of_week": body.days_of_week, "next_run": tuning_scheduler.next_run_time(),
    }


@router.post("/adopt")
async def adopt(body: AdoptRequest) -> dict:
    if not body.params:
        raise HTTPException(status_code=422, detail="params must not be empty — aborting to avoid wiping active config")
    store.adopt(body.strategy, body.params, direction=body.direction)
    return {"ok": True, "active": store.get_active(body.strategy, body.direction)}
