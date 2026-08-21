import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from app.database import get_db
from app.data.market import fetch_price_async
from app.models.portfolio import PortfolioPositionModel
from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel
from app.schemas import (
    PortfolioPositionCreate, PortfolioPositionSchema, PortfolioPositionUpdate,
    ClosePositionRequest, ClosedPositionSchema,
    PerformanceResponse, PerformancePoint,
)
from app.services.portfolio_risk import check_position_risk, orm_positions_to_risk, PortfolioPosition as RiskPosition
from app.services.portfolio_performance import (
    realized_pnl, bucket_realized_by_calendar, cumulative_curve, _contract_multiplier,
)
from app.data.market import fetch_contract_quote_async
from app.services.audit import log_approval
from app.models.audit_event import AuditEventModel

router = APIRouter(prefix='/api', tags=['trading'])

import logging as _logging
_log = _logging.getLogger(__name__)


# A stock price is never <= 0, so a non-positive stop/structuralStop can only
# mean "unset" — used at both the creation (POST) and edit (PATCH) boundaries
# so neither can persist a value that would make STOP_REACHED / STRUCTURAL_
# STOP_BREACHED's `is not None` gate treat a Bearish position as permanently
# breached (referencePrice >= 0 is true for any real price).
def _floor_stop(value: Optional[float]) -> Optional[float]:
    return value if value is not None and value > 0 else None


# ── Broker integration (NOT ACTIVE YET) ───────────────────────────────────────
# Future feature: when a trade is closed, optionally route the closing order to
# the connected broker — mirrors the "Send basket to broker" flow in Step 7,
# which is wired in the UI but not yet executed against a live broker. This stub
# is intentionally a no-op so the request shape (ClosePositionRequest.sendToBroker)
# and call site already exist; flip the body on when the broker API lands.
def _maybe_send_close_to_broker(closed: ClosedPositionModel, send: bool) -> None:
    if not send:
        return
    # Broker routing not yet implemented — log a warning so callers aren't misled.
    _log.warning(
        "sendToBroker=True for %s but broker close-routing is not yet implemented — order NOT sent",
        closed.contract,
    )


@router.get('/portfolio', response_model=list[PortfolioPositionSchema])
async def get_portfolio(db: AsyncSession = Depends(get_db)) -> list[PortfolioPositionSchema]:
    try:
        result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    except (OperationalError, ProgrammingError) as exc:
        # Belt-and-suspenders: if the table is schema-drifted (a model column with no
        # migration), degrade to empty instead of a hard 500. SQLite raises
        # OperationalError ("no such column"); asyncpg/Postgres raises ProgrammingError
        # (UndefinedColumnError). The real fix is the migration; this stops a FUTURE
        # drift from taking the endpoint (and the portfolio rail) down.
        _log.error("get_portfolio schema error, returning empty: %s", exc)
        return []
    positions = result.scalars().all()
    schemas = [PortfolioPositionSchema.from_orm_model(p) for p in positions]

    if not schemas:
        return schemas

    # Enrich with live option quotes — all positions fetched concurrently. Also fetch a live
    # underlying stock price for every distinct symbol with an open OPTION position: `stop` is
    # always a stock price, but currentPrice for an option leg is the premium — the frontend
    # STOP_REACHED check needs the real stock price to compare against, not the premium (see
    # currentStockPrice below). Deduped by symbol so multiple contracts on the same underlying
    # fetch it once. Both fetch groups run concurrently in one AsyncClient context, same pattern
    # as add_position's live save-time refetch.
    today = date.today()
    option_symbols = sorted({s.symbol for s in schemas if not s.contract.endswith("|STOCK")})
    async with httpx.AsyncClient(timeout=10) as client:
        quotes, stock_price_results = await asyncio.gather(
            asyncio.gather(
                *[fetch_contract_quote_async(client, s.contract) for s in schemas],
                return_exceptions=True,
            ),
            asyncio.gather(
                *[fetch_price_async(client, sym) for sym in option_symbols],
                return_exceptions=True,
            ),
        )
    stock_prices = {
        sym: (price if isinstance(price, (int, float)) else None)
        for sym, price in zip(option_symbols, stock_price_results)
    }

    for schema, quote in zip(schemas, quotes):
        # dteRemaining from contract string: SYMBOL|STRIKE|EXPIRY|C/P
        parts = schema.contract.split("|")
        if len(parts) >= 3:
            try:
                schema.dteRemaining = max(0, (date.fromisoformat(parts[2]) - today).days)
            except ValueError:
                pass

        if isinstance(quote, dict) and quote:
            schema.currentPrice = quote.get("price") or 0.0
            schema.delta        = quote.get("delta")
            schema.theta        = quote.get("theta")
            schema.ivRank       = int(round(iv)) if (iv := quote.get("ivRank")) is not None else None
            if schema.entryPrice:
                mult = _contract_multiplier(schema.contract)
                schema.pnlDollar = round(
                    (schema.currentPrice - schema.entryPrice) * mult * schema.qty, 2
                )
                schema.pnlPct = round(
                    (schema.currentPrice - schema.entryPrice) / schema.entryPrice * 100, 2
                )

        schema.currentStockPrice = (
            schema.currentPrice if schema.contract.endswith("|STOCK")
            else stock_prices.get(schema.symbol)
        )

    open_value = sum(s.currentPrice * _contract_multiplier(s.contract) * s.qty for s in schemas)
    open_pnl = sum(s.pnlDollar or 0.0 for s in schemas)
    await _upsert_equity_snapshot(db, open_value, open_pnl)
    return schemas


@router.post('/portfolio', response_model=PortfolioPositionSchema, status_code=status.HTTP_201_CREATED)
async def add_position(
    body: PortfolioPositionCreate,
    db: AsyncSession = Depends(get_db),
) -> PortfolioPositionSchema:
    # Duplicate contract check → 409
    existing = await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.contract == body.contract)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Position with contract '{body.contract}' already exists.",
        )

    # Two live fetches at save time, run CONCURRENTLY (one save = one round-trip
    # latency, not two sequential ones):
    #   1. underlying price → re-anchor stop/targets to the fill-time price.
    #   2. contract quote   → set entry_price to the live premium (option) or
    #      price (stock) so PREMIUM_STOP / P&L are measured against the market
    #      NOW, not the — possibly stale — value captured when the scan ran.
    # Both fall back to the frontend-supplied values when a live quote is
    # unavailable (after hours / data source down). fetch_contract_quote_async
    # handles both SYMBOL|STRIKE|EXPIRY|C/P and SYMBOL|STOCK shapes.
    #
    # This MUST happen before the risk check below: the risk check's capital-at-
    # risk / exposure math has to be evaluated against the price that actually
    # gets persisted, not the frontend's (possibly stale) entryPrice — otherwise
    # a position could be approved against one price and stored at a materially
    # different one, silently bypassing the exposure gate.
    adjusted_stop = body.stop
    adjusted_structural_stop = body.structuralStop
    adjusted_targets = list(body.targets or [])
    entry_stock_price = body.scanStockPrice
    entry_price = body.entryPrice

    need_reanchor = bool(body.scanStockPrice and body.scanStockPrice > 0)
    # For a stock position (SYMBOL|STOCK), fetch_contract_quote_async's quote
    # price IS the underlying price — fetching it separately via
    # fetch_price_async as well would just duplicate the same call.
    is_stock = body.contract.endswith("|STOCK")
    try:
        async with httpx.AsyncClient(timeout=8) as _cl:
            _quote_task = fetch_contract_quote_async(_cl, body.contract)
            if need_reanchor and not is_stock:
                live_quote, live_price = await asyncio.gather(
                    _quote_task, fetch_price_async(_cl, body.symbol),
                )
            else:
                live_quote = await _quote_task
                live_price = (
                    (live_quote or {}).get("price") if need_reanchor and is_stock and isinstance(live_quote, dict)
                    else None
                )
    except Exception:
        live_quote, live_price = None, None
        _log.warning(
            "add_position: live save-time refetch failed for %s; keeping frontend values",
            body.contract, exc_info=True,
        )

    if need_reanchor and live_price and live_price > 0:
        delta = live_price - body.scanStockPrice
        if adjusted_stop is not None:
            adjusted_stop = round(adjusted_stop + delta, 2)
        if adjusted_structural_stop is not None:
            adjusted_structural_stop = round(adjusted_structural_stop + delta, 2)
        adjusted_targets = [
            {
                **t,
                "stockPrice":  round((t.get("stockPrice")  or 0) + delta, 2),
                "targetPrice": round((t.get("targetPrice") or 0) + delta, 2),
            }
            for t in adjusted_targets
        ]
        entry_stock_price = live_price

    live_entry = (live_quote or {}).get("price") if isinstance(live_quote, dict) else None
    if live_entry and float(live_entry) > 0:
        entry_price = round(float(live_entry), 2)
    else:
        # %s (not %.2f) — entryPrice is a required float, but keep %s here
        # since this just logs whatever the frontend sent verbatim.
        _log.info(
            "add_position: no live quote for %s; storing frontend entryPrice %s",
            body.contract, body.entryPrice,
        )

    # Fetch existing portfolio for risk check
    result = await db.execute(select(PortfolioPositionModel))
    db_positions = result.scalars().all()
    portfolio = [
        RiskPosition(
            symbol=p.symbol,
            contract_id=p.contract,
            contracts=p.qty,
            entry_premium=p.entry_price,
            current_price=p.entry_price,
            capital_at_risk=p.entry_price * p.qty * _contract_multiplier(p.contract),
        )
        for p in db_positions
    ]

    risk = check_position_risk(
        symbol=body.symbol,
        contract_id=body.contract,
        proposed_contracts=body.qty,
        entry_premium=entry_price,
        current_price=entry_price,
        portfolio=portfolio,
        portfolio_value=body.portfolioValue,
    )
    if not risk.approved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=" ".join(risk.reasons),
        )

    position = PortfolioPositionModel(
        rec_id=body.recId,
        symbol=body.symbol,
        contract=body.contract,
        direction=body.direction,
        entry_price=entry_price,
        qty=risk.adjusted_size or body.qty,
        entry_date=body.entryDate,
        stop=_floor_stop(adjusted_stop),
        structural_stop=_floor_stop(adjusted_structural_stop),
        targets=adjusted_targets,
        dte_total=body.dteTotal,
        entry_stock_price=entry_stock_price,
    )
    db.add(position)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent duplicate: two POSTs for the same contract (e.g. addPosition's
        # own POST racing syncFromBackend's pending-retry) both pass the SELECT
        # existence pre-check above, then the loser trips a unique constraint.
        # `contract` and `rec_id` are BOTH unique — re-check which one actually
        # collided before answering, so a rec_id collision (this row genuinely
        # never persisted) is never reported the same way as a contract collision
        # (the row IS safely saved under the other request). The client treats
        # any 409 here as "already saved" and promotes its local row to synced —
        # doing that for an unpersisted rec_id collision would silently lose data.
        await db.rollback()
        contract_exists = (await db.execute(
            select(PortfolioPositionModel.id).where(
                PortfolioPositionModel.contract == body.contract
            )
        )).first()
        if contract_exists is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Position with contract '{body.contract}' already exists.",
            )
        # The contract collision above didn't happen — this was a rec_id
        # collision instead, and the position was NOT persisted. A 500 correctly
        # tells the client this is a hard failure to retry, not a safe duplicate.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save position: duplicate rec_id '{body.recId}'.",
        )
    await db.refresh(position)

    if body.tradeCardSnapshot:
        # Wrapped: log_approval does its own commit — a failure here must never
        # turn an already-persisted position into an apparent 500 for the client.
        try:
            await log_approval(body.recId, body.tradeCardSnapshot, db)
        except Exception:
            _log.error("log_approval failed for %s", body.recId, exc_info=True)

    resp = PortfolioPositionSchema.from_orm_model(position)
    if risk.adjusted_size is not None:
        resp.adjustedQty = risk.adjusted_size
    return resp


@router.patch('/portfolio/{rec_id}', response_model=PortfolioPositionSchema)
async def update_position(
    rec_id: str,
    body: PortfolioPositionUpdate,
    db: AsyncSession = Depends(get_db),
) -> PortfolioPositionSchema:
    position = (await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
    )).scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Position with rec_id '{rec_id}' not found.")

    # exclude_unset (not exclude_none) so a field the client never sent is left
    # alone, while `{"structuralStop": null}` still clears it — the drawer's
    # "0 means none" control relies on being able to null this back out.
    updates = body.model_dump(exclude_unset=True)
    # Set only when the risk gate approved a qty increase at a SMALLER size
    # than requested — mirrors POST /api/portfolio's resp.adjustedQty above,
    # which exists so a caller is never silently shown a size the backend
    # didn't actually persist.
    adjusted_qty: Optional[int] = None
    # A rejected qty must NOT block stop/structuralStop/targets from saving.
    # The frontend debounces edits per recId and merges whatever fields
    # changed within the same ~600ms window into one PATCH — a user who
    # tweaks Stop and then, moments later, types a Contracts value that fails
    # the exposure gate would otherwise have BOTH edits silently dropped by a
    # single early `raise`, with no indication the valid Stop edit was ever
    # lost. Instead: apply every other field unconditionally, commit, and
    # only raise for qty at the very end — so a qty rejection still reports
    # as a 422 (the frontend must not treat it as success), but the fields
    # that WERE valid are durably saved either way.
    qty_error: Optional[str] = None

    if "qty" in updates:
        qty = updates["qty"]
        if qty is None or qty < 1:
            qty_error = "qty must be an integer of at least 1."
        elif qty > position.qty:
            # Increasing size is new risk, not a correction — re-run the same
            # exposure gate POST /api/portfolio enforces at creation. A decrease
            # only ever reduces exposure, so it skips this gate entirely and
            # doesn't need portfolioValue at all.
            if body.portfolioValue is None:
                qty_error = "portfolioValue is required to increase qty."
            else:
                others = (await db.execute(
                    select(PortfolioPositionModel).where(PortfolioPositionModel.id != position.id)
                )).scalars().all()
                risk = check_position_risk(
                    symbol=position.symbol,
                    contract_id=position.contract,
                    proposed_contracts=qty,
                    entry_premium=position.entry_price,
                    current_price=position.entry_price,
                    portfolio=orm_positions_to_risk(others),
                    portfolio_value=body.portfolioValue,
                )
                if not risk.approved:
                    qty_error = " ".join(risk.reasons)
                else:
                    if risk.adjusted_size is not None:
                        adjusted_qty = risk.adjusted_size
                        qty = risk.adjusted_size
                    position.qty = qty
        else:
            position.qty = qty
    if "stop" in updates:
        position.stop = _floor_stop(updates["stop"])
    if "structuralStop" in updates:
        position.structural_stop = _floor_stop(updates["structuralStop"])
    if "targets" in updates:
        position.targets = updates["targets"]

    await db.commit()
    await db.refresh(position)

    if qty_error is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=qty_error)

    resp = PortfolioPositionSchema.from_orm_model(position)
    if adjusted_qty is not None:
        resp.adjustedQty = adjusted_qty
    return resp


@router.delete('/portfolio/history', status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_history_early(db: AsyncSession = Depends(get_db)) -> None:
    """Delete all closed trade history and equity snapshots (full reset).

    Registered BEFORE /portfolio/{rec_id} so FastAPI does not greedily match
    the literal path segment 'history' as a rec_id value.
    """
    from app.services.history_cleanup import clear_all_history as _clear
    await _clear(db)


@router.delete('/portfolio/{rec_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(rec_id: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position with rec_id '{rec_id}' not found.",
        )
    # A hard delete (unlike close_position) never creates a closed_positions
    # row, so prune_old_history's audit_events cascade — which only looks at
    # rec_ids it finds via closed_positions — can never reach this rec_id.
    # Clean it up here instead: the position is gone entirely, so there's no
    # "why was this bought" left to explain.
    await db.execute(delete(AuditEventModel).where(AuditEventModel.rec_id == rec_id))
    await db.delete(position)
    await db.commit()


@router.post('/portfolio/{rec_id}/close',
             response_model=ClosedPositionSchema,
             status_code=status.HTTP_201_CREATED)
async def close_position(
    rec_id: str,
    body: ClosePositionRequest,
    db: AsyncSession = Depends(get_db),
) -> ClosedPositionSchema:
    position = (await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
    )).scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Position with rec_id '{rec_id}' not found.")

    # qty to close: default = full; clamp 1..position.qty
    qty_to_close = body.qtyToClose if body.qtyToClose is not None else position.qty
    qty_to_close = max(1, min(int(qty_to_close), position.qty))

    # exit price: explicit, else fetch the live quote, else 422
    exit_price = body.exitPrice
    if exit_price is None:
        async with httpx.AsyncClient(timeout=10) as client:
            quote = await fetch_contract_quote_async(client, position.contract)
        exit_price = (quote or {}).get("price") if isinstance(quote, dict) else None
        if not exit_price:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Could not fetch a live exit price — please enter one.",
            )

    exit_date = body.exitDate or date.today().isoformat()
    dollar, pct = realized_pnl(position.entry_price, float(exit_price), qty_to_close, position.contract)

    closed = ClosedPositionModel(
        id=uuid.uuid4().hex,
        rec_id=position.rec_id,
        symbol=position.symbol,
        contract=position.contract,
        direction=position.direction,
        entry_price=position.entry_price,
        entry_date=position.entry_date,
        exit_price=float(exit_price),
        exit_date=exit_date,
        qty_closed=qty_to_close,
        realized_pnl_dollar=dollar,
        realized_pnl_pct=pct,
        source=getattr(position, "source", None),
    )
    db.add(closed)

    # Reduce or remove the open position
    if qty_to_close >= position.qty:
        await db.delete(position)
    else:
        position.qty -= qty_to_close

    await db.commit()
    await db.refresh(closed)

    _maybe_send_close_to_broker(closed, body.sendToBroker)
    return ClosedPositionSchema.from_orm_model(closed)


@router.get('/portfolio/history', response_model=list[ClosedPositionSchema])
async def get_history(db: AsyncSession = Depends(get_db)) -> list[ClosedPositionSchema]:
    rows = (await db.execute(
        select(ClosedPositionModel).order_by(ClosedPositionModel.closed_at.desc())
    )).scalars().all()
    return [ClosedPositionSchema.from_orm_model(r) for r in rows]


@router.delete('/portfolio/history/{history_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_history(history_id: str, db: AsyncSession = Depends(get_db)) -> None:
    row = (await db.execute(
        select(ClosedPositionModel).where(ClosedPositionModel.id == history_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"History entry '{history_id}' not found.")
    await db.delete(row)
    await db.commit()


async def _upsert_equity_snapshot(db: AsyncSession, open_value: float, open_pnl: float) -> None:
    """Record/refresh today's total-account-value point (one row per calendar day)."""
    today = date.today().isoformat()
    realized_cum = (
        await db.execute(select(func.sum(ClosedPositionModel.realized_pnl_dollar)))
    ).scalar() or 0.0
    total = round(realized_cum + open_value, 2)
    snap = (await db.execute(
        select(EquitySnapshotModel).where(EquitySnapshotModel.snapshot_date == today)
    )).scalar_one_or_none()
    if snap is None:
        db.add(EquitySnapshotModel(
            id=uuid.uuid4().hex, snapshot_date=today,
            realized_cumulative=round(realized_cum, 2),
            open_value=round(open_value, 2), open_pnl=round(open_pnl, 2),
            total_value=total,
        ))
    else:
        snap.realized_cumulative = round(realized_cum, 2)
        snap.open_value = round(open_value, 2)
        snap.open_pnl = round(open_pnl, 2)
        snap.total_value = total
    await db.commit()


@router.get('/portfolio/performance', response_model=PerformanceResponse)
async def get_performance(db: AsyncSession = Depends(get_db)) -> PerformanceResponse:
    closed = (await db.execute(
        select(ClosedPositionModel.exit_date, ClosedPositionModel.realized_pnl_dollar)
    )).all()
    rows = [{"exit_date": c.exit_date, "realized_pnl_dollar": c.realized_pnl_dollar}
            for c in closed]
    buckets = bucket_realized_by_calendar(rows, today=date.today())
    realized_curve = cumulative_curve(rows)

    snaps = (await db.execute(
        select(EquitySnapshotModel).order_by(EquitySnapshotModel.snapshot_date)
    )).scalars().all()
    equity_curve = [PerformancePoint(date=s.snapshot_date, value=s.total_value) for s in snaps]
    open_pnl_curve = [PerformancePoint(date=s.snapshot_date, value=s.open_pnl) for s in snaps]

    return PerformanceResponse(
        realizedToday=buckets["today"], realizedWeek=buckets["week"],
        realizedMonth=buckets["month"], realizedYear=buckets["year"],
        realizedCurve=[PerformancePoint(**p) for p in realized_curve],
        equityCurve=equity_curve,
        openPnlCurve=open_pnl_curve,
    )
