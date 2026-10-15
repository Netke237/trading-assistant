"""Book the position an auto-trade fire just opened at the broker (O4 steps 4+5).

Plan: docs/superpowers/plans/2026-09-24-o4-step-4-5-book-the-fired-order-replan.md.
Spec: docs/superpowers/plans/2026-09-15-o4-auto-trade-books-a-position-spec.md.

Both triggers call `book_fired_order` with the `FiredOrder` that `fire()`
returned: POST /auto-trade/fire and POST /scan. It runs ON THE EVENT LOOP, with
the request's own session, and writes through `create_position` -- the one
writer every card send already uses -- with the pre-trade gates OFF (the order
is already at the broker, so a gate can only refuse to write down a trade that
happened) and `stop_required` ON (a booked position with no stop has no
invalidation and no STOP_REACHED alert).

IT NEVER RAISES (spec section 6.1). The order went through; the caller answers
200 / carries on with the scan whatever happens here. `asyncio.CancelledError`
is a BaseException and is left to propagate.

ONCE `create_position` HAS RETURNED, THE OUTCOME IS `booked=True` (re-plan
section 8, build rule 1). The row is committed by then, so a later failure --
the audit record, the history link, the alert -- is logged and nothing more.
Reporting it as not booked would page "add it by hand or close it at the
broker" about a position that is already on the books.

A WRONG-SIDE STOP PAGES TOO (Q12, P1a). The write runs with gates off, so a
user-set stop on the wrong side of the underlying is booked with a warning;
`WriteOutcome.wrong_side_stop` carries it and this module pages it as
AUTO_TRADE_BOOKED_WRONG_SIDE_STOP. Scope: only USER-SET stops are
direction-checked by the writer -- a plan-derived armed stop is re-anchored,
not checked -- and with no live price and no scan price there is no check.

AN UNAPPLIED DOLLAR PREMIUM STOP PAGES TOO (decision PREMIUM-STOP-FALLBACK-
USER-FRACTION-2026-10-03). When the armed dollar stop is a total loss or
sub-cent at the booked entry, the writer stores the arm-time fraction (or
nothing) and `WriteOutcome.premium_stop_unapplied` says so; this module pages
it as AUTO_TRADE_BOOKED_PREMIUM_STOP_UNAPPLIED.

A FAULT AFTER THE WRITER'S OWN COMMIT (P1a). If `create_position` raises
something other than its own decided 409/500, the row may already be
committed. The booking looks it up by its fresh rec_id and contract; if it is
there, the order IS booked -- it pages AUTO_TRADE_BOOKED_UNVERIFIED (the stop
side and exposure flags were lost) instead of "not booked".

EVERY REFUSAL PAGES, through `auto_trader._alert_refusal` (decision
O4-ROUTE-AND-ALERT-2026-09-24). That helper is sync, runs its own
`asyncio.run`, and DROPS the alert when a loop is already running in its thread
-- which this module's thread always has. So it is called through
`await asyncio.to_thread(...)`: a worker thread has no loop, the same shape the
scan trigger's refusals already run in. Called directly, every alert below
would be a logged no-op.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.auto_trader as auto_trader_module
from app.data.market import fetch_contract_quote_async, fetch_price_async
from app.models.portfolio import PortfolioPositionModel
from app.schemas import PortfolioPositionCreate
from app.services.audit import log_approval
from app.services.auto_trader import FiredOrder, _is_rejected_status
from app.services.config_loader import load_exit_plan_cfg
from app.services.position_writer import create_position
from app.services.scheduling_tz import MARKET_TZ

logger = logging.getLogger(__name__)

_ALERT_TYPE_NOT_BOOKED = "AUTO_TRADE_NOT_BOOKED"
_ALERT_TYPE_OVER_EXPOSURE = "AUTO_TRADE_BOOKED_OVER_EXPOSURE"
_REC_ID_NOT_BOOKED = "auto-trade-not-booked"
_REC_ID_OVER_EXPOSURE = "auto-trade-over-exposure"
_ALERT_TYPE_WRONG_SIDE_STOP = "AUTO_TRADE_BOOKED_WRONG_SIDE_STOP"
_REC_ID_WRONG_SIDE_STOP = "auto-trade-wrong-side-stop"
_ALERT_TYPE_UNVERIFIED = "AUTO_TRADE_BOOKED_UNVERIFIED"
_REC_ID_UNVERIFIED = "auto-trade-booked-unverified"
_ALERT_TYPE_PREMIUM_STOP_UNAPPLIED = "AUTO_TRADE_BOOKED_PREMIUM_STOP_UNAPPLIED"
_REC_ID_PREMIUM_STOP_UNAPPLIED = "auto-trade-premium-stop-unapplied"

# A dashed ISO date only. `date.fromisoformat` alone accepts the basic format
# `20261218` on Python 3.11. `option_symbol._PIPE_RE` is NOT reused: its
# `[A-Z]{1,6}` symbol group would refuse `BRK.B`, which is accepted today.
_DASHED_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# The rejection words live in `auto_trader._REJECTED_STATUSES`, read through
# `_is_rejected_status` -- one set for this refusal and for `fire()`'s daily-loss
# booking (decision A9-REJECTED-BOOKS-ZERO-2026-09-24).

# "No order id": IBKR's confirmation-question reply yields "" for an order never
# transmitted; Alpaca's adapter defaults a missing id to "unknown".
_NO_ORDER_IDS = frozenset({"", "unknown"})

_RIGHT_FOR_DIRECTION = {"Bullish": "C", "Bearish": "P"}


@dataclass(frozen=True)
class BookingOutcome:
    booked:        bool
    rec_id:        Optional[str]
    error:         Optional[str]   # human-readable; always names the order id
    over_exposure: bool
    wrong_side_stop: bool = False   # Q12: booked with a wrong-side user stop (paged)
    premium_stop_unapplied: bool = False   # the armed dollar stop was not stored (paged)


class _Refused(Exception):
    """A refusal decided here. `broker_live` picks the alert's wording."""

    def __init__(self, reason: str, *, broker_live: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.broker_live = broker_live


def _order_label(fired: FiredOrder) -> str:
    oid = fired.result.order_id
    # Whitespace-only counts as no id, the same as refusal 1.
    return f"order {oid}" if oid is not None and str(oid).strip() else "an order with no order id"


def _check_refusals(fired: FiredOrder) -> None:
    """Spec section 6.3 / re-plan section 2.4, in order. Touches nothing."""
    result, s = fired.result, fired.strategy

    oid = result.order_id
    if oid is None or str(oid).strip().lower() in _NO_ORDER_IDS:
        raise _Refused(
            f"the broker returned no order id ({oid!r}), so the order reads as "
            "never transmitted", broker_live=False,
        )
    if _is_rejected_status(result.status):
        raise _Refused(
            f"the broker's status {result.status!r} is a rejection",
            broker_live=False,
        )

    if s.stop is None or s.stop <= 0:
        raise _Refused("no invalidation was armed (no stop)")

    parts = s.option_symbol.split("|")
    if len(parts) != 4:
        raise _Refused(
            f"the contract {s.option_symbol!r} is not SYMBOL|STRIKE|EXPIRY|RIGHT"
        )
    sym, strike, expiry, right = parts
    if sym != s.symbol:
        raise _Refused(
            f"the contract {s.option_symbol!r} is not on the armed symbol {s.symbol!r}"
        )
    try:
        strike_ok = math.isfinite(float(strike)) and float(strike) > 0
    except ValueError:
        strike_ok = False
    if not strike_ok:
        raise _Refused(f"the contract {s.option_symbol!r} has no usable strike")
    try:
        if not _DASHED_DATE.fullmatch(expiry):
            raise ValueError(expiry)
        date.fromisoformat(expiry)
    except ValueError:
        raise _Refused(f"the contract {s.option_symbol!r} has no usable expiry") from None
    if right not in ("C", "P"):
        raise _Refused(f"the contract {s.option_symbol!r} is neither a call nor a put")
    if right != _RIGHT_FOR_DIRECTION[s.direction]:
        # With `action` fixed at BUY, a Bullish put is a malformed arm, and the
        # stop would be compared on the wrong side -- a stop that never fires.
        raise _Refused(
            f"the contract's right {right!r} disagrees with the armed direction "
            f"{s.direction!r}"
        )

    if s.entry_premium <= 0:
        # Defence in depth: `arm()` refuses this, so no armed strategy has one.
        raise _Refused(f"no entry premium was armed ({s.entry_premium!r})")


def _new_rec_id() -> str:
    return f"REC-AT-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8].upper()}"


def _build_body(fired: FiredOrder, rec_id: str) -> PortfolioPositionCreate:
    """Re-plan section 2.6. The containers are deep-copied: frozen is shallow,
    `_dc_replace` shares them with the pre-sizing object, and the JSON columns
    would otherwise hold the strategy's own objects."""
    s = fired.strategy
    return PortfolioPositionCreate(
        recId=rec_id,
        symbol=s.symbol,
        contract=s.option_symbol,
        direction=s.direction,
        entryPrice=s.entry_premium,
        qty=s.quantity,
        # MARKET_TZ, not UTC: a fire is a US-market event, and UTC reads a day
        # late after 20:00 ET. Display and holding period only.
        entryDate=datetime.now(MARKET_TZ).date().isoformat(),
        portfolioValue=s.portfolio_value,
        premiumStopPct=s.premium_stop_pct,
        stop=s.stop,
        stopIsUserSet=s.stop_is_user_set,
        scanStockPrice=s.scan_stock_price,
        structuralStop=s.structural_stop,
        dteTotal=s.dte_total,
        premiumStopDollar=s.premium_stop_dollar,
        exitPlan=copy.deepcopy(s.exit_plan),
        targets=copy.deepcopy(s.targets),
        maxLossOverride=copy.deepcopy(s.max_loss_override),
        tradeCardSnapshot=copy.deepcopy(s.trade_card_snapshot),
        pickedMethod=s.picked_method,
        pickedRowStockPrice=s.picked_row_stock_price,
        pickedRowOptionPrice=s.picked_row_option_price,
        pickedStopBasis=s.picked_stop_basis,
        pickedAt=s.picked_at,
        # Audit round 1, F1: the order that was placed. Since round 2 (R2-F6)
        # an LMT arm's cap basis is passed to `create_position` as `cap_basis`
        # (`auto_trader.armed_cap_basis`, the fire's), so for LMT these two are
        # only the record of the order. For a MKT arm (round 3, R3-F1) the
        # armed basis is a floor and `create_position` still derives the
        # booking-time fill basis from `orderType` and the live quote.
        orderType=s.order_type,
        # Audit round 5, R5-F1: a MKT order carries no limit at the broker
        # (every adapter drops it), so none is recorded.
        orderLimitPrice=s.limit_price if s.order_type == "LMT" else None,
    )


async def _rollback(db: AsyncSession, why: str) -> None:
    """Leave the session usable for the caller -- on the scan path,
    `_upsert_session` runs on it next (spec section 5.3)."""
    try:
        await db.rollback()
    except Exception:
        logger.error("auto-trade booking: rollback after %s failed", why, exc_info=True)


async def _page(symbol: str, what: str, reason: str, rec_id_key: str,
                alert_type: str) -> None:
    # `auto_trader_module` is looked up at call time so a test patch lands.
    try:
        await asyncio.to_thread(
            auto_trader_module._alert_refusal,
            symbol, what, reason, rec_id_key, alert_type, discrete=True,
        )
    except Exception:
        logger.error("auto-trade booking: could not raise the %s alert for %s",
                     what, symbol, exc_info=True)


async def _alert_not_booked(fired: FiredOrder, reason: str, broker_live: bool,
                            remedy_included: bool = False) -> None:
    s, r = fired.strategy, fired.result
    if remedy_included:
        # The reason carries its own remedy; the generic "Add it by hand" would
        # contradict it (a duplicate contract must NOT be added as a second row).
        text = f"{_order_label(fired).capitalize()} for {s.option_symbol}: {reason}"
    elif broker_live:
        text = (
            f"The broker ACCEPTED {_order_label(fired)} ({r.status}) for "
            f"{s.option_symbol} x{s.quantity}, but NO position was booked, so there "
            f"is no stop alert and no P&L for it: {reason}. Add it by hand or "
            "close it at the broker."
        )
    else:
        text = (
            f"The broker's answer to {_order_label(fired)} ({r.status}) for "
            f"{s.option_symbol} x{s.quantity} reads as NOT live: {reason}. Nothing "
            "was booked. Verify at the broker."
        )
    await _page(
        s.symbol, "auto-trade booking refusal", text,
        auto_trader_module._per_symbol_rec_id(_REC_ID_NOT_BOOKED, s.symbol),
        _ALERT_TYPE_NOT_BOOKED,
    )


async def _alert_over_exposure(fired: FiredOrder, rec_id: str) -> None:
    s = fired.strategy
    text = (
        f"{_order_label(fired).capitalize()} for {s.option_symbol} was booked as "
        f"{rec_id} at the ordered qty {s.quantity}, which is past the exposure "
        "cap. Nothing was resized -- the books match the broker."
    )
    await _page(
        s.symbol, "auto-trade booking over the exposure cap", text,
        auto_trader_module._per_symbol_rec_id(_REC_ID_OVER_EXPOSURE, s.symbol),
        _ALERT_TYPE_OVER_EXPOSURE,
    )


async def _alert_wrong_side_stop(fired: FiredOrder, rec_id: str, detail: str) -> None:
    s = fired.strategy
    text = (
        f"{_order_label(fired).capitalize()} for {s.option_symbol} was booked as "
        f"{rec_id} with a stop warning: {detail} Correct or verify the stop in Portfolio."
    )
    await _page(
        s.symbol, "auto-trade booking with a stop warning", text,
        auto_trader_module._per_symbol_rec_id(_REC_ID_WRONG_SIDE_STOP, s.symbol),
        _ALERT_TYPE_WRONG_SIDE_STOP,
    )


async def _alert_unverified(fired: FiredOrder, rec_id: str) -> None:
    s = fired.strategy
    text = (
        f"{_order_label(fired).capitalize()} for {s.option_symbol} was booked as "
        f"{rec_id}, but the write failed after its commit, so its stop side, "
        "premium stop and exposure were NOT checked — verify all three in Portfolio."
    )
    await _page(
        s.symbol, "auto-trade booking not verified", text,
        auto_trader_module._per_symbol_rec_id(_REC_ID_UNVERIFIED, s.symbol),
        _ALERT_TYPE_UNVERIFIED,
    )


async def _alert_premium_stop_unapplied(fired: FiredOrder, rec_id: str, detail: str) -> None:
    # Decision PREMIUM-STOP-FALLBACK-USER-FRACTION-2026-10-03: the booking
    # cannot tell anyone on screen, so the dollar stop that was not stored pages.
    s = fired.strategy
    text = (
        f"{_order_label(fired).capitalize()} for {s.option_symbol} was booked as "
        f"{rec_id}, but {detail} Check the premium stop in Portfolio."
    )
    await _page(
        s.symbol, "auto-trade booking with its premium stop not applied", text,
        auto_trader_module._per_symbol_rec_id(_REC_ID_PREMIUM_STOP_UNAPPLIED, s.symbol),
        _ALERT_TYPE_PREMIUM_STOP_UNAPPLIED,
    )


def _duplicate_contract_reason(fired: FiredOrder) -> str:
    # ONE remedy only. "Raise that position's Contracts in Portfolio" is NOT
    # offered (P1a code round 1): the drawer PATCH cannot change entry_price
    # and does not average it, so the added contracts would be stored at the
    # existing row's entry, not this fill -- a wrong P&L, a PREMIUM_STOP
    # anchored to the old premium, and an exposure check on the wrong capital.
    q = fired.strategy.quantity
    return (
        "a position for this contract is already open, so this order was NOT booked "
        f"as a second row, and its {q} contract(s) are untracked. Close the extra "
        f"{q} at the broker. Do not raise that position's Contracts to cover them: "
        "Portfolio would book them at that position's entry price, not this fill."
    )


async def _refuse(fired: FiredOrder, reason: str, broker_live: bool,
                  remedy_included: bool = False) -> BookingOutcome:
    error = f"{_order_label(fired)} was not booked: {reason}"
    logger.error("auto-trade booking: %s (%s)", error, fired.strategy.symbol)
    await _alert_not_booked(fired, reason, broker_live, remedy_included)
    return BookingOutcome(booked=False, rec_id=None, error=error, over_exposure=False)


async def _committed_row_exists(db: AsyncSession, rec_id: str, contract: str) -> bool:
    """Did the failed write commit anyway? Raises if the lookup itself fails."""
    row = (await db.execute(
        select(PortfolioPositionModel.id).where(
            PortfolioPositionModel.rec_id == rec_id,
            PortfolioPositionModel.contract == contract,
        )
    )).first()
    return row is not None


async def book_fired_order(fired: FiredOrder, db: AsyncSession) -> BookingOutcome:
    """Book `fired` as a PortfolioPosition. Never raises -- see the module."""
    booked_rec_id: Optional[str] = None
    over_exposure = False
    wrong_side_stop: Optional[str] = None
    premium_stop_unapplied: Optional[str] = None
    try:
        try:
            _check_refusals(fired)
        except _Refused as ref:
            return await _refuse(fired, ref.reason, ref.broker_live)

        rec_id = _new_rec_id()
        try:
            body = _build_body(fired, rec_id)
        except Exception as exc:
            return await _refuse(fired, f"the position did not build: {exc}", True)

        # Audit round 2, R2-F6 / round 3, R3-F1: the basis the FIRE judged this
        # order at -- same function, same armed inputs. An LMT arm is judged at
        # exactly that (it cannot fill above its limit). A MKT arm fills at the
        # BOOKING-time price, which can have drifted far above the armed mid
        # (the manual fire has no age bound), so its armed basis is only a
        # floor under the basis derived from the booking-time live quote.
        armed_basis = auto_trader_module.armed_cap_basis(fired.strategy)
        if fired.strategy.order_type == "MKT":
            basis_kwargs = {"cap_basis_floor": armed_basis}
        else:
            basis_kwargs = {"cap_basis": armed_basis}
        try:
            outcome = await create_position(
                body, db,
                # This module's names, looked up at call time and passed
                # explicitly: a keyword default binds at definition time, so a
                # patch on this module would otherwise miss.
                quote_fetcher=fetch_contract_quote_async,
                price_fetcher=fetch_price_async,
                exit_plan_cfg_loader=load_exit_plan_cfg,
                enforce_pre_trade_gates=False,
                stop_required=True,
                exposure_attempt_id=fired.attempt_id,
                **basis_kwargs,
            )
        except Exception as exc:
            await _rollback(db, "a refused write")
            if isinstance(exc, HTTPException) and exc.status_code == 409:
                return await _refuse(fired, _duplicate_contract_reason(fired), True,
                                     remedy_included=True)
            decided = isinstance(exc, HTTPException) and exc.status_code == 500
            if not decided:
                # The writer may have committed before it failed. Its own 409/500
                # are decided outcomes (nothing of THIS rec_id was written), so
                # only anything else is looked up.
                try:
                    committed = await _committed_row_exists(db, rec_id, body.contract)
                except Exception:
                    await _rollback(db, "a failed recovery lookup")
                    logger.error("auto-trade booking: could not check whether %s was "
                                 "committed", rec_id, exc_info=True)
                    committed = False
                if committed:
                    logger.error(
                        "auto-trade booking: %s is booked as %s, but the write failed "
                        "after its commit -- the outcome flags were lost",
                        _order_label(fired), rec_id, exc_info=exc,
                    )
                    try:
                        auto_trader_module.auto_trader.record_booking(fired.attempt_id, rec_id)
                    except Exception:
                        logger.error("auto-trade booking: could not link %s to its "
                                     "history row", rec_id, exc_info=True)
                    await _alert_unverified(fired, rec_id)
                    return BookingOutcome(booked=True, rec_id=rec_id, error=None,
                                          over_exposure=False)
            detail = exc.detail if isinstance(exc, HTTPException) else repr(exc)
            return await _refuse(fired, f"the position write failed: {detail}", True)

        # COMMITTED. From here the outcome is booked=True, whatever fails.
        booked_rec_id = rec_id
        over_exposure = outcome.over_exposure
        wrong_side_stop = outcome.wrong_side_stop
        premium_stop_unapplied = outcome.premium_stop_unapplied
        logger.info(
            "auto-trade booking: %s booked as %s (%s x%s%s)",
            _order_label(fired), rec_id, fired.strategy.option_symbol,
            fired.strategy.quantity, ", OVER the exposure cap" if over_exposure else "",
        )

        if body.tradeCardSnapshot:
            try:
                await log_approval(rec_id, body.tradeCardSnapshot, db)
            except Exception:
                await _rollback(db, "a failed audit record")
                logger.error("auto-trade booking: log_approval failed for %s", rec_id,
                             exc_info=True)

        try:
            auto_trader_module.auto_trader.record_booking(fired.attempt_id, rec_id)
        except Exception:
            logger.error("auto-trade booking: could not link %s to its history row",
                         rec_id, exc_info=True)

        if over_exposure:
            await _alert_over_exposure(fired, rec_id)
        if wrong_side_stop:
            await _alert_wrong_side_stop(fired, rec_id, wrong_side_stop)
        if premium_stop_unapplied:
            await _alert_premium_stop_unapplied(fired, rec_id, premium_stop_unapplied)

        return BookingOutcome(booked=True, rec_id=rec_id, error=None,
                              over_exposure=over_exposure,
                              wrong_side_stop=bool(wrong_side_stop),
                              premium_stop_unapplied=bool(premium_stop_unapplied))
    except Exception as exc:
        if booked_rec_id is not None:
            logger.error("auto-trade booking: %s is booked, but a later step failed",
                         booked_rec_id, exc_info=True)
            return BookingOutcome(booked=True, rec_id=booked_rec_id, error=None,
                                  over_exposure=over_exposure,
                                  wrong_side_stop=bool(wrong_side_stop),
                                  premium_stop_unapplied=bool(premium_stop_unapplied))
        logger.error("auto-trade booking: unexpected failure", exc_info=True)
        try:
            return await _refuse(fired, f"unexpected failure: {exc!r}", True)
        except Exception:
            return BookingOutcome(
                booked=False, rec_id=None,
                error=f"{_order_label(fired)} was not booked: unexpected failure",
                over_exposure=False,
            )
