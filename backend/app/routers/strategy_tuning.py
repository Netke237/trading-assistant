"""Strategy-tuning router — run walk-forward optimization, poll jobs, adopt proposals."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from app.services import strategy_param_store as store

router = APIRouter(prefix="/api/strategy-tuning", tags=["strategy-tuning"])

_JOBS: dict[str, dict] = {}
_ACTIVE: str | None = None
_ACTIVE_TASK: asyncio.Task | None = None


class AdoptRequest(BaseModel):
    strategy: str
    params: dict[str, Any]


@router.post("/run")
async def run_job(body: dict = Body(default={})) -> dict:
    global _ACTIVE, _ACTIVE_TASK
    if _ACTIVE and _JOBS.get(_ACTIVE, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="An optimization run is already active.")
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "proposals": {}}
    _ACTIVE = job_id

    async def _work() -> None:
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
            proposals = await run_optimization(
                strategies,
                basket_symbols,
                store.get_windows(),
                store.get_costs(),
                progress,
            )
            _JOBS[job_id].update(status="completed", proposals=proposals)
        except Exception as exc:  # noqa: BLE001
            _JOBS[job_id].update(status="failed", error=str(exc))

    _ACTIVE_TASK = asyncio.create_task(_work())
    _JOBS[job_id]["task"] = None  # placeholder; actual Task not JSON-serialisable
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


@router.post("/adopt")
async def adopt(body: AdoptRequest) -> dict:
    if not body.params:
        raise HTTPException(status_code=422, detail="params must not be empty — aborting to avoid wiping active config")
    store.adopt(body.strategy, body.params)
    return {"ok": True, "active": store.get_active(body.strategy)}
