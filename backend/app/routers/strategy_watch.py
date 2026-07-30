# backend/app/routers/strategy_watch.py
"""REST API for strategy-watch entries + schedule + manual evaluation."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas import Direction
from app.services.strategy_watch_store import strategy_watch_store, VALID_STRATEGIES
from app.services.strategy_watch_scheduler import strategy_watch_scheduler

router = APIRouter(prefix="/api/strategy-watch", tags=["strategy-watch"])


class AddWatch(BaseModel):
    symbol: str
    strategy_key: str
    params_override: dict | None = None
    direction: Direction = "Bullish"


class BulkAdd(BaseModel):
    symbols: list[str]
    strategy_key: str
    direction: Direction = "Bullish"


class EnabledPatch(BaseModel):
    enabled: bool


class ScheduleIn(BaseModel):
    enabled: bool
    mode: str = Field(pattern="^(eod|poll)$")
    eod_time: str = "16:15"
    poll_hours: int = Field(default=4, ge=1, le=24)
    sustain_minutes: int = Field(default=0, ge=0, le=1440)


@router.get("/")
async def list_watches() -> list[dict]:
    return strategy_watch_store.list_watches()


@router.post("/", status_code=201)
async def add_watch(body: AddWatch) -> dict:
    try:
        return strategy_watch_store.add_watch(
            body.symbol, body.strategy_key, body.params_override, body.direction
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=409 if "already watched" in msg else 400, detail=msg)


@router.post("/bulk", status_code=201)
async def bulk_add(body: BulkAdd) -> dict:
    if body.strategy_key not in VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"unknown strategy: {body.strategy_key}")
    added = strategy_watch_store.add_watches_bulk(body.symbols, body.strategy_key, body.direction)
    return {"added": len(added), "watches": added}


@router.delete("/{watch_id}")
async def remove_watch(watch_id: str) -> dict:
    if not strategy_watch_store.remove_watch(watch_id):
        raise HTTPException(status_code=404, detail="watch not found")
    return {"removed": watch_id}


@router.patch("/{watch_id}")
async def set_enabled(watch_id: str, body: EnabledPatch) -> dict:
    if not strategy_watch_store.set_enabled(watch_id, body.enabled):
        raise HTTPException(status_code=404, detail="watch not found")
    return {"id": watch_id, "enabled": body.enabled}


@router.get("/schedule")
async def get_schedule() -> dict:
    return strategy_watch_store.get_schedule()


@router.put("/schedule")
async def set_schedule(body: ScheduleIn) -> dict:
    return strategy_watch_store.set_schedule(body.model_dump())


@router.post("/evaluate")
async def evaluate_now() -> dict:
    events = await strategy_watch_scheduler.run_now()
    serialized = [asdict(e) if is_dataclass(e) else getattr(e, "__dict__", {}) for e in events]
    return {"fired": len(events), "events": serialized}


@router.get("/status")
async def status() -> dict:
    return strategy_watch_scheduler.get_status()
