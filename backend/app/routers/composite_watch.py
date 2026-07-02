# backend/app/routers/composite_watch.py
"""CRUD endpoints for composite (Markov + N-of-M) watch entries."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.strategy_watch_store import strategy_watch_store
from app.services.strategy_param_store import get_composite_trigger_defaults

router = APIRouter(prefix="/api/composite-watches", tags=["composite-watch"])


class CompositeWatchCreate(BaseModel):
    symbol: str
    trigger_def: dict
    direction: str = "Bullish"
    interval: str = "1D"


class EnabledPatch(BaseModel):
    enabled: bool


@router.get("/defaults")
async def get_defaults() -> dict:
    """Return default composite trigger thresholds from strategy_params.yaml."""
    return get_composite_trigger_defaults()


@router.get("/regime-snapshot")
async def get_regime_snapshot(
    symbol: str,
    model: str = "OMM",
    direction: str = "Bullish",
    interval: str = "15m",
) -> dict:
    """Live OMM/HMM snapshot for a single symbol.

    Used by the regime-alert dialog to show the user the symbol's CURRENT
    conviction/P(stay) before they pick alert threshold sliders — the sliders
    themselves are thresholds, not live values, so without this the user is
    picking blind.
    """
    from datetime import date, timedelta
    from app.services.historical_store import get_bars
    from app.services.regime_omm import compute_omm

    if direction not in ("Bullish", "Bearish"):
        raise HTTPException(status_code=400, detail=f"direction must be 'Bullish' or 'Bearish', got {direction!r}")

    end = date.today()
    start = end - timedelta(days=400)
    bars = await get_bars(symbol, start, end)
    if not bars:
        raise HTTPException(status_code=404, detail=f"no price history for {symbol}")

    if model == "OMM":
        closes = [b["close"] for b in bars]
        result = compute_omm(closes, direction=direction)
        if result is None:
            raise HTTPException(status_code=422, detail="insufficient history to classify OMM regime")
        return {
            "model": "OMM",
            "state": result.state,
            "p_stay": result.p_stay,
            "conviction_pct": result.conviction_pct,
            "conviction_label": result.conviction_label,
        }

    if model in ("HMM_daily", "HMM_intraday"):
        from app.services.regime_hmm import compute_intraday_hmm
        if model == "HMM_intraday":
            from app.data.market import fetch_intraday_candles
            hmm_bars = fetch_intraday_candles(symbol, interval=interval, days=55)
        else:
            hmm_bars = bars
        result_hmm = compute_intraday_hmm(hmm_bars)
        if result_hmm is None:
            raise HTTPException(status_code=422, detail="insufficient history to classify HMM regime")
        return {
            "model": model,
            "state": result_hmm.state,
            "p_stay": result_hmm.p_stay,
            "p_transition": result_hmm.p_transition,
        }

    raise HTTPException(status_code=400, detail=f"unknown model {model!r}")


@router.get("/")
async def list_composite_watches() -> list[dict]:
    """List all composite watches."""
    return [w for w in strategy_watch_store.list_watches()
            if w.get("watch_type") == "composite"]


@router.post("/", status_code=201)
async def add_composite_watch(body: CompositeWatchCreate) -> dict:
    """Create a new composite watch entry. No deduplication — each call creates a new entry."""
    try:
        return strategy_watch_store.add_composite_watch(
            symbol=body.symbol,
            trigger_def=body.trigger_def,
            direction=body.direction,
            interval=body.interval,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{watch_id}")
async def get_composite_watch(watch_id: str) -> dict:
    watches = [w for w in strategy_watch_store.list_watches() if w["id"] == watch_id]
    if not watches:
        raise HTTPException(status_code=404, detail="composite watch not found")
    return watches[0]


@router.delete("/{watch_id}", status_code=204)
async def delete_composite_watch(watch_id: str) -> None:
    if not strategy_watch_store.remove_watch(watch_id):
        raise HTTPException(status_code=404, detail="composite watch not found")


@router.patch("/{watch_id}")
async def set_enabled(watch_id: str, body: EnabledPatch) -> dict:
    if not strategy_watch_store.set_enabled(watch_id, body.enabled):
        raise HTTPException(status_code=404, detail="composite watch not found")
    return {"id": watch_id, "enabled": body.enabled}
