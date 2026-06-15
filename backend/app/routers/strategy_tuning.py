"""Strategy-tuning router — run walk-forward optimization, poll jobs, adopt proposals."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Body, HTTPException

from app.services import strategy_param_store as store

router = APIRouter(prefix="/api/strategy-tuning", tags=["strategy-tuning"])

_JOBS: dict[str, dict] = {}
_ACTIVE: str | None = None


@router.post("/run")
async def run_job(body: dict = Body(default={})) -> dict:
    global _ACTIVE
    if _ACTIVE and _JOBS.get(_ACTIVE, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="An optimization run is already active.")
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "proposals": {}}
    _ACTIVE = job_id

    async def _work():
        try:
            from app.services.strategy_param_optimizer import run_optimization

            def progress(done: int, total: int) -> None:
                _JOBS[job_id].update(done=done, total=total)

            cfg = store._load()
            strategies = list(cfg.get("strategies", {}).keys())
            basket_symbols = cfg.get("basket", {}).get("symbols", [])
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

    asyncio.create_task(_work())
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail="unknown job")
    return _JOBS[job_id]


@router.post("/adopt")
async def adopt(body: dict = Body(...)) -> dict:
    store.adopt(body["strategy"], body["params"])
    return {"ok": True, "active": store.get_active(body["strategy"])}
