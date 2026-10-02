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
from app.data.augment import opt_float, opt_int
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
from app.services.config_loader import load_exit_plan_cfg
from app.services.picked_method import seed_tp_from_pick
from app.services.position_writer import create_position, _rescale_rung_shares
from app.services.premium_stop import is_short_stock_position, premium_stop_is_sub_cent
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
            # Two quantities, kept apart. `ivRank` is a percentile and is
            # usually absent; `iv` is the absolute level, which is what this
            # row in fact showed before 2026-09-06
            # (PHASE-A-NULL-IVRANK-2026-09-06).
            schema.ivRank       = opt_int(quote.get("ivRank"))
            schema.iv           = opt_float(quote.get("iv"))
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
    # O4 step 1: the body moved VERBATIM to services/position_writer.py so the
    # auto-trade fire path can book through the same writer. The three names
    # below are this module's, looked up at call time, so patches on
    # `app.routers.portfolio.*` still reach the writer -- see its docstring.
    outcome = await create_position(
        body, db,
        quote_fetcher=fetch_contract_quote_async,
        price_fetcher=fetch_price_async,
        exit_plan_cfg_loader=load_exit_plan_cfg,
    )
    position = outcome.position

    if body.tradeCardSnapshot:
        # Wrapped: log_approval does its own commit — a failure here must never
        # turn an already-persisted position into an apparent 500 for the client.
        try:
            await log_approval(body.recId, body.tradeCardSnapshot, db)
        except Exception:
            _log.error("log_approval failed for %s", body.recId, exc_info=True)

    resp = PortfolioPositionSchema.from_orm_model(position)
    if outcome.adjusted_size is not None:
        resp.adjustedQty = outcome.adjusted_size
    return resp


def _cap_rungs_to_qty(targets, qty: int):
    """Scale rungs down by the overflow only: rungs whose integer
    `contractsToSell` sum fits `qty` are returned as sent; above it, they are
    scaled proportionally to sum exactly `qty` (position_writer's rounding
    rule, asked = the rung sum). Non-list targets and non-integer counts are
    left as they are, as _rescale_rung_shares does."""
    if not isinstance(targets, list):
        return targets
    total = sum(
        t["contractsToSell"] for t in targets
        if isinstance(t, dict) and isinstance(t.get("contractsToSell"), int)
        and not isinstance(t.get("contractsToSell"), bool) and t["contractsToSell"] > 0
    )
    if total <= qty:
        return targets
    return _rescale_rung_shares(targets, total, qty)


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
    # P6 (G1-5, spec §2.7): the take-profit method and its price are ONE fact
    # and are written together or not at all. Two independent ifs below let a
    # method arrive alone and sit beside a stale or NULL price -- a drawer
    # naming one basis while TP_HIT fires on the ladder. Refused BEFORE
    # anything is written: unlike `qty`'s late raise, which exists to save the
    # OTHER valid fields of a debounced patch, a half pair has no such
    # companion -- the product's only writer (`tpMethodPatch`) always sends both.
    has_method = "activeTpMethod" in updates
    has_price = "resolvedTpPrice" in updates
    if has_method != has_price:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="activeTpMethod and resolvedTpPrice must be sent together.")
    if has_method:
        if updates["activeTpMethod"] is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail="activeTpMethod cannot be null.")
        if updates["activeTpMethod"] != "ladder" and _floor_stop(updates["resolvedTpPrice"]) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                                detail=f"activeTpMethod '{updates['activeTpMethod']}' needs a positive resolvedTpPrice.")
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
                elif risk.adjusted_size is not None and risk.adjusted_size <= position.qty:
                    # STOCK-SENDS: an INCREASE must never save a smaller position.
                    # The soft resize fits the cap below what is already held
                    # (the cap or portfolio value moved since the row was
                    # booked -- reachable for stocks now that they are judged at
                    # their real share count), so the increase is refused and
                    # the held qty stays.
                    qty_error = (
                        f"size_reduced_to_fit_exposure_limit: the position is already at or over "
                        f"its exposure cap ({position.qty} held; the cap allows {risk.adjusted_size}). "
                        f"Quantity not increased."
                    )
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
    if "targets" in updates or "qty" in updates:
        # Open question 54: the stored rungs must never plan to sell more than
        # the row holds -- after a raise the gate booked smaller, a decrease,
        # or a rung edit sent separately from the size it was typed against.
        position.targets = _cap_rungs_to_qty(position.targets, position.qty)
    # Exit-plan pipeline scaffolding (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
    # — later phases compute these values; this endpoint just persists
    # whatever they send, same exclude_unset/explicit-null-clears pattern as
    # stop/structuralStop/targets above.
    if "exitPlan" in updates:
        position.exit_plan = updates["exitPlan"]
    if "maxLossOverride" in updates:
        position.max_loss_override = updates["maxLossOverride"]
    # Validated as a pair at the top of this handler, so both keys are here or
    # neither is.
    if "activeTpMethod" in updates:
        position.active_tp_method = updates["activeTpMethod"]
    if "resolvedTpPrice" in updates:
        # Same non-positive-means-unset floor as stop/structuralStop above —
        # generate_alerts()'s TP_HIT check tests `resolved_tp_price or
        # ladder_price` (Python truthiness only catches 0, not negative), so
        # an unfloored negative value here made TP_HIT fire on every tick for
        # a Bullish position (price >= negative is always true) and never
        # fire for a Bearish one (price <= negative is never true).
        position.resolved_tp_price = _floor_stop(updates["resolvedTpPrice"])
    if "resolvedTpUpdatedAt" in updates:
        raw = updates["resolvedTpUpdatedAt"]
        position.resolved_tp_updated_at = datetime.fromisoformat(raw) if raw else None
    if "alertOverrides" in updates:
        position.alert_overrides = updates["alertOverrides"]
    # Piece 4 — an explicit null CLEARS the per-position premium stop and
    # returns this position to inheriting the global, same exclude_unset /
    # explicit-null-clears contract as stop/structuralStop above. Not floored:
    # the schema's (0, 1) bound already rejects every meaningless value, and a
    # floor here would silently rewrite one rather than reject it.
    #
    # STOP-SEMANTICS-2026-10-02 (b): a stop whose threshold is below $0.01 at
    # this position's entry can never fire, so it is refused -- late, like
    # qty, so the fields sent alongside it in the same debounced PATCH still
    # save. An explicit null (clear -> inherit) is never refused.
    premium_stop_refused = False
    if "premiumStopPct" in updates:
        requested_pct = updates["premiumStopPct"]
        if requested_pct is not None and premium_stop_is_sub_cent(
            position.entry_price, requested_pct,
            is_short_stock_position(position.contract, position.direction),
        ):
            premium_stop_refused = True
        else:
            position.premium_stop_pct = requested_pct

    await db.commit()
    await db.refresh(position)

    # The 422 detail is ` | `-joined segments: qty_error verbatim (risk codes OR
    # free text), then the premium code, then the trimmed qty that WAS saved
    # (which the 422 would otherwise lose). A single segment is exactly the
    # pre-STOP-SEMANTICS detail. `frontend/lib/portfolioRejection.ts` maps it.
    if qty_error is not None or premium_stop_refused:
        segments = [qty_error] if qty_error is not None else []
        if premium_stop_refused:
            segments.append("premium_stop_below_one_cent")
            if adjusted_qty is not None:
                segments.append(f"qty_saved_as_{adjusted_qty}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=" | ".join(segments))

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
