from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.schemas import Direction, PickedMethod, PickedStopBasis, Horizon
from app.services.auto_trader import auto_trader, ArmedStrategy
from app.services.auto_trade_booking import book_fired_order

router = APIRouter(prefix="/auto-trade", tags=["auto-trade"])


class ArmRequest(BaseModel):
    broker:          Literal["ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"]
    symbol:          str
    option_symbol:   str
    # NARROWED TO "BUY" -- ROUND 1 finding 3. `effect` is not a field here;
    # `execute_option_order` hardcodes effect="OPEN", so "SELL" on this endpoint
    # was a SELL-TO-OPEN: a naked short option, which nothing in this app ever
    # intends. The frontend has only ever sent "BUY" (AutoTradeArm/index.tsx),
    # and no other caller exists, so this narrowing removes a door rather than
    # a feature.
    #
    # It also settles an inconsistency this piece created. Once sizing stopped
    # reading `action`, the old expression's incidental damping of the SELL
    # branch (`100 - conviction`) went away, so a naked short would have been
    # sized at FULL conviction. Keeping `action` wide while declaring it
    # meaningless was the worst of both: meaningless for sizing, still able to
    # open an unintended position.
    action:          Literal["BUY"]
    # REQUIRED, NO DEFAULT -- this is the whole point of the field.
    #
    # `action` never encoded direction and cannot: a bearish options trade in
    # this app is a LONG PUT, which is BUY, and AutoTradeArm/index.tsx hardcodes
    # `action: 'BUY'` for every arm. So `_apply_vol_sizing` inferring direction
    # from `action` sized every bearish trade off the BULLISH conviction frame --
    # the ramp exactly inverted, largest into the regime that opposes the trade.
    #
    # A default of "Bullish" would reintroduce precisely that silent
    # mis-direction, and it is the same failure shape as the documented G5-1
    # hole (extra='ignore' letting a misspelled key arm with NULLs). Required
    # means a body without `direction` is a 422 AT ARM TIME -- loud, before
    # anything is armed -- rather than a wrong size at fire time.
    #
    # ROLLOUT: the two sides must deploy together. A backend ahead of the
    # frontend, or a cached older client bundle, turns every Arm click into a
    # 422 with no fallback. That is the accepted cost of failing loudly at arm.
    #
    # "Loudly" is now literally true on screen, which ROUND 1 finding 8 caught it
    # not being: `apiError` in frontend/lib/api.ts dropped pydantic's `loc`, so
    # this 422 rendered as `API /auto-trade/arm → 422: Field required` naming no
    # field at all. It now reads `direction: Field required`. The backend test
    # asserts "direction" in resp.text; that assertion was true all along and the
    # only consumer was throwing the information away.
    direction:       Direction
    quantity:        int = Field(..., ge=1)
    order_type:      Literal["MKT", "LMT"] = "LMT"
    # gt=0 -- ROUND 9, same reasoning as broker.py's two order schemas: a
    # non-positive limit is never a price, and this endpoint reaches a broker
    # without passing through either of them.
    limit_price:     Optional[float] = Field(default=None, gt=0)
    conid:           Optional[int] = None
    entry_premium:   float = 0.0   # set to actual option mid; exposure check is skipped if 0
    portfolio_value: float = 50_000.0
    # Piece 4 — the per-trade premium stop from the card being armed. Omitted
    # or null inherits auto_trade.premium_stop_pct. Bounded here as well as on
    # the portfolio schemas: this endpoint reaches the same sizing arithmetic
    # without ever passing through PortfolioPositionCreate.
    premium_stop_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    # Phase G (piece 5), build step 5 -- the trader's explicit method pick for
    # the card being armed. The SAME five fields PortfolioPositionCreate
    # carries, and for the same reason premium_stop_pct is here: this endpoint
    # reaches the trade without ever passing through that schema, so a pick made
    # on the card would otherwise stop at the Arm button.
    #
    # CAPTURED AT ARM AND NOT READ AGAIN (spec S3.2/S8, Q2). `fire_now()` takes
    # no body and re-fires whatever ArmedStrategy was booked here, so a later
    # edit on the card cannot retroactively change what "Fire now" records --
    # exactly the rule quantity and premium_stop_pct already follow.
    #
    # snake_case with NO alias, unlike PortfolioPositionCreate's camelCase-with-
    # snake-alias: every other field on THIS schema is snake_case, the frontend
    # posts snake_case to this endpoint, and `ArmedStrategy(**req.model_dump())`
    # at :39 keys off field NAMES.
    #
    # BOTH HALVES MEASURED, because the loud half is not the dangerous one and
    # an earlier draft of this comment only stated the loud one. DECLARING a
    # camelCase field here is loud: model_dump() would emit `pickedMethod` and
    # the dataclass raises TypeError ("unexpected keyword argument"). But a
    # camelCase KEY arriving ON THE WIRE is SILENT -- this schema inherits
    # pydantic's default `extra='ignore'`, so a body carrying pickedMethod /
    # pickedRowStockPrice / ... returns 200 and arms with all five NULL.
    # Verified by posting exactly that body.
    #
    # The silent half is why the frontend has a SEPARATE snake_case mapping
    # (`armPickedFieldsFrom`) instead of reusing the portfolio path's camelCase
    # one: a mix-up there does not fail, it arms a trade whose pick was thrown
    # away -- precisely the "gate passed, record NULL" defect c41145ba had to go
    # back and close on the other seven send paths.
    #
    # All five are Optional and default to None, and NULL IS A REAL STATE: it
    # means nobody picked. The send gate (build step 4) already refuses an
    # unpicked card at the Arm button, so None reaching here means a pre-G
    # client or a direct API call -- never a gated path that lost the pick.
    picked_method:           Optional[PickedMethod]    = None
    # gt=0 on both, and the units are in the names, for the reason
    # PortfolioPositionCreate states at length: only a STOCK price may ever seed
    # resolved_tp_price, and zero is never a price.
    picked_row_stock_price:  Optional[float]           = Field(default=None, gt=0)
    picked_row_option_price: Optional[float]           = Field(default=None, gt=0)
    picked_stop_basis:       Optional[PickedStopBasis] = None
    picked_at:               Optional[str]             = None
    # ── The regime gate's inputs, frozen at arm ─────────────────────────────
    # AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19.
    #
    # REQUIRED, NO DEFAULT, for the reason `direction` above is: the fire path
    # measures this symbol's own regime through the `regime.<horizon>` window
    # (lookback / window / min_obs), and the three horizons are genuinely
    # different measurements -- Intraday 26/1000/60 against Position 50/750/100.
    # A default would pick one of them silently for a trade that meant another.
    #
    # THE ROLLOUT COST IS THE SAME ONE `direction` ACCEPTED and is stated again
    # rather than assumed known: a backend ahead of the frontend, or a cached
    # older client bundle, turns every Arm click into a 422. Both sides ship
    # together. Failing loudly at arm beats measuring the wrong window at fire.
    horizon:         Horizon
    # The Step-3 Regime Gate thresholds this card's scan was run with. Omitted
    # or null means "the scan used the scoring_rules.yaml value", which is what
    # an untouched Step-3 control means -- so an omission is a real state here
    # and not a missing field.
    #
    # UNBOUNDED ON PURPOSE, and deliberately unlike `premium_stop_pct` and
    # `limit_price` above. Those tighten against a schema this endpoint
    # bypasses. These two must be able to carry EXACTLY what the scan carried:
    # `ScanRequest` and `StockScanRequest` both declare them as plain
    # `Optional[float]`, and a bound here that the scan does not have would
    # refuse to arm a card the scan itself produced -- which is the same
    # scan-versus-fire disagreement this field exists to remove.
    regime_headwind_caution_pct: Optional[float] = None
    regime_headwind_reject_pct:  Optional[float] = None
    # ── O4 step 3: the fields a fired trade will book its position from ─────
    # Plan: docs/superpowers/plans/2026-09-24-o4-step-3-arm-fields-replan.md.
    #
    # THEY TRAVEL, NOTHING READS THEM YET. Step 4 maps them onto
    # PortfolioPositionCreate (same snake_case names as that schema's ALIASES)
    # when a fired order books a position. Same carry as the pick above:
    # snake_case, no alias, `ArmedStrategy(**req.model_dump())` keys off names,
    # and a camelCase key on the wire is silently dropped (extra='ignore', G5-1).
    #
    # TIGHTER THAN PortfolioPositionCreate ON FOUR (stop, scan_stock_price,
    # structural_stop, dte_total), ON PURPOSE: a 422 at arm is the only refusal
    # that costs no order -- refusing at booking happens after a real fill.
    # Never looser, so nothing accepted here can be refused by the create
    # schema on these bounds. A client must send null, never 0, for an absent
    # price, and [] (not null) for no targets.
    #
    # The four dicts are untyped and uncapped, exactly as on the create path:
    # the card path is the reference and step 3 does not tighten it.
    stop:                Optional[float] = Field(default=None, gt=0)
    stop_is_user_set:    Optional[bool]  = None
    scan_stock_price:    Optional[float] = Field(default=None, gt=0)
    structural_stop:     Optional[float] = Field(default=None, gt=0)
    exit_plan:           Optional[dict]  = None
    targets:             list[dict]      = []
    dte_total:           Optional[int]   = Field(default=None, ge=0)
    premium_stop_dollar: Optional[float] = Field(default=None, gt=0)
    max_loss_override:   Optional[dict]  = None
    trade_card_snapshot: Optional[dict]  = None


@router.post("/arm")
async def arm(req: ArmRequest) -> dict:
    """Arm the auto-trader with the given option order. Fires on next trigger."""
    auto_trader.arm(ArmedStrategy(**req.model_dump()))
    return {"armed": True, "symbol": req.symbol, "option_symbol": req.option_symbol}


@router.delete("/arm")
async def disarm() -> dict:
    """Disarm — cancel the pending auto-trade."""
    auto_trader.disarm()
    return {"armed": False}


@router.post("/fire")
async def fire_now(db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger #1: manually fire the armed strategy with a live exposure check."""
    from app.models.portfolio import PortfolioPositionModel
    from app.services.portfolio_risk import orm_positions_to_risk
    _armed_state = auto_trader.get_state()
    if not _armed_state.armed or _armed_state.strategy is None:
        raise HTTPException(status_code=400, detail="AutoTrader not armed — cannot fire")
    result_q = await db.execute(select(PortfolioPositionModel))
    orm_positions = result_q.scalars().all()
    portfolio_snapshot = orm_positions_to_risk(orm_positions)
    try:
        fired = auto_trader.fire(
            portfolio_snapshot=portfolio_snapshot,
            portfolio_value=None,  # fire() reads portfolio_value from strategy under lock
            # FIRE THE ORDER THIS REQUEST CHECKED, OR NOTHING — the same
            # contract `maybe_fire_on_scan` passes, and for the same reason.
            # This handler reads the armed slot, decides something about what
            # it read (the 400 above), and only then calls: exactly the caller
            # shape `fire()`'s docstring says `expect` exists for. Without it,
            # `fire()`'s halt check runs on the symbol read in its first lock
            # block and the submission happens on whatever the second one
            # finds, so a re-arm in that window — which spans a 3s network
            # call — authorizes order B on order A's halt decision.
            #
            # NOT REACHABLE OVER HTTP TODAY, and recorded here so the next
            # reader does not decide it is therefore pointless: `fire_now` is
            # `async def` but calls `fire()` synchronously, blocking the loop,
            # so no second request can be parsed inside the window. That is an
            # accident of this endpoint's shape, not a guard. It stops holding
            # the moment `fire()` moves behind `asyncio.to_thread` (which this
            # codebase is already doing for broker order execution), a second
            # worker shares the state, or any non-HTTP producer calls `arm()`.
            # A mismatch raises `ArmPreservedError`, which is a RuntimeError,
            # so the handler below already maps it to the 400 it should be.
            expect=_armed_state.strategy,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # O4 steps 4+5: book the position the order just opened. OUTSIDE the try
    # above, and ALWAYS 200 once the order went through (spec section 6.1):
    # `book_fired_order` never raises, and a refused booking is reported in the
    # four keys below AND paged, so it reaches a human whatever client asked.
    booking = await book_fired_order(fired, db)
    result = fired.result
    return {
        "order_id":      result.order_id,
        "status":        result.status,
        "broker":        result.broker,
        "booked":        booking.booked,
        "rec_id":        booking.rec_id,
        "book_error":    booking.error,
        "over_exposure": booking.over_exposure,
    }


@router.get("/status")
async def status() -> dict:
    state = auto_trader.get_state()
    return {
        "armed":  state.armed,
        "symbol": state.strategy.symbol if state.strategy else None,
        "option": state.strategy.option_symbol if state.strategy else None,
        "broker": state.strategy.broker if state.strategy else None,
        # Once direction decides position size, a WRONG direction on an armed
        # trade is otherwise undetectable until the fill. This is the
        # observability half of arming loudly.
        #
        # KNOWN GAP, deliberately not closed here: the history entries appended
        # in auto_trader.py carry no `direction`, so `last_order` below will not
        # show it -- do not mistake `last_order` for direction evidence. Since
        # O4 steps 4+5 a BOOKED fire's row carries `rec_id`, and the position
        # it names records the direction; the row itself stays as it is.
        "direction": state.strategy.direction if state.strategy else None,
        "history_count": len(state.history),
        "last_order": state.history[-1] if state.history else None,
    }
