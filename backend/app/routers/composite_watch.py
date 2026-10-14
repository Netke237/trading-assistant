# backend/app/routers/composite_watch.py
"""CRUD endpoints for composite (Markov + N-of-M) watch entries."""
from __future__ import annotations

from app.schemas.payload_depth import validate_payload_depth

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import field_validator, BaseModel, Field

from app.schemas import Direction
from app.services.strategy_watch_store import strategy_watch_store
from app.services.strategy_param_store import get_composite_trigger_defaults
from app.services.strategy_watch_evaluator import set_enabled_and_expire

router = APIRouter(prefix="/api/composite-watches", tags=["composite-watch"])


class CompositeWatchCreate(BaseModel):
    symbol: str
    trigger_def: dict
    direction: Direction = "Bullish"
    interval: str = "1D"

    _validate_payload_depth = field_validator('trigger_def', mode="before")(validate_payload_depth)


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
    interval: str = "15min",
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

    if model not in ("OMM", "HMM_daily", "HMM_intraday"):
        raise HTTPException(status_code=400, detail=f"unknown model {model!r}")

    if model in ("OMM", "HMM_daily"):
        # WATCH-RULE-BAR-PARITY 2.4: the rows a composite watch reads -- 730
        # days of completed get_bars sessions -- and OMM in the trigger's
        # direction, the value both the watch and the rule now compare.
        from datetime import datetime
        from app.services.composite_trigger_evaluator import completed_daily_rows
        from app.services.scheduling_tz import MARKET_TZ
        end = date.today()
        start = end - timedelta(days=730)
        bars = completed_daily_rows(await get_bars(symbol, start, end), datetime.now(MARKET_TZ))
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
            from app.data.market import completed_bars_for_interval, fetch_intraday_candles
            from app.services.composite_trigger_evaluator import intraday_history_days
            # A4c: the value the watch will compare against -- completed bars only.
            # P4b (D4): the same series and history (4h: 180 days) the composite
            # watch evaluator fetches; W2-INTERVAL: both use the chart spelling.
            iv = interval
            # Off the event loop (TRADIER-GOVERNOR T3): a sync Tradier fetch.
            hmm_bars = completed_bars_for_interval(
                await asyncio.to_thread(
                    fetch_intraday_candles, symbol, interval=iv, days=intraday_history_days(iv),
                ),
                iv,
            )
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


@router.get("/")
async def list_composite_watches() -> list[dict]:
    """List all composite watches."""
    return [w for w in strategy_watch_store.list_watches()
            if w.get("watch_type") == "composite"]


@router.post("/", status_code=201)
async def add_composite_watch(body: CompositeWatchCreate) -> dict:
    """Create a new composite watch entry. No deduplication — each call creates a new entry."""
    # COMPOSITE-MOMENTUM Q10c: refuse a momentum confirmation that could never
    # fire (422; the store's ValueError -> 400 mapping below is unchanged).
    from app.services.composite_trigger_evaluator import momentum_confirmation_error
    _err = momentum_confirmation_error(body.trigger_def)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
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
    expired = await set_enabled_and_expire(watch_id, body.enabled, store=strategy_watch_store)
    if expired is None:
        raise HTTPException(status_code=404, detail="composite watch not found")
    return {"id": watch_id, "enabled": body.enabled, "expired_alerts": expired}
