"""The one writer of a PortfolioPositionModel from a create request.

O4 step 1 (spec docs/superpowers/plans/2026-09-15-o4-auto-trade-books-a-position-spec.md
section 5.1). This is `routers/portfolio.py:add_position`'s body -- from the
duplicate-contract 409 through `await db.refresh(position)` -- MOVED VERBATIM so
that an auto-trade fire can later book its position through the SAME code every
card send already goes through, instead of a second writer that drifts from it.
The router keeps the two things that are the router's: `log_approval` and the
response schema.

VERBATIM MEANS VERBATIM. The only step-1 edits are the three injected callables
below and the return value; step 2 added `enforce_pre_trade_gates` and steps
4+5 `stop_required` (both below), and nothing else. Nothing was tidied in
passing: the existing POST /api/portfolio suite, run UNEDITED, is the proof that
the move changed nothing, and a tidy-up would spend that proof.

THE THREE INJECTED CALLABLES exist for that same proof. The router suite patches
`app.routers.portfolio.fetch_contract_quote_async` / `fetch_price_async` /
`load_exit_plan_cfg`; a plain move would bind this module's own imports, the
patches would miss, and the unedited suite would reach the network. The router
passes its module-level names, looked up at call time, so its patches still
land. Any other caller that passes nothing gets THIS module's globals, also
looked up at call time (P1a): the defaults are None and resolve inside the
call, so a patch on `app.services.position_writer.fetch_contract_quote_async`
(or `fetch_price_async` / `load_exit_plan_cfg`) lands too. A default bound at
import time would have kept the real function and silently reached the network.

CREATE IS SERIALISED AGAINST CREATE (P1a). `_booking_lock()` is held from the
in-lock duplicate re-check through the portfolio SELECT, the risk check, the
commit, the IntegrityError handling and `refresh`, so two concurrent creates
judge the exposure caps in turn and the second sees the first's committed row.
The live fetches (up to 8s) stay OUTSIDE the lock. The read snapshot from the
pre-fetch contract check is closed before those fetches, so a later wait on
the exposure guard cannot keep a snapshot that hides the commit it waited
for. Inside the lock that database guard is taken before the portfolio is
read again. The guard, not this asyncio lock, also serialises PATCH, delete
and close, and pending exposure holds count in the snapshot. SCOPE of the
asyncio lock: one process -- the backend runs a single uvicorn process, and
the auto-trader singleton already assumes one -- and `create_position`
against `create_position` only. The /fire pre-broker snapshot race is not
covered here.

THIS FUNCTION COMMITS. It calls `db.commit()`, `db.rollback()` on a unique
collision, and `db.refresh()`, so its caller must own the transaction or expect
it to end -- on the scan path that matters (spec section 5.3).

IT RAISES HTTPException exactly as the router did (409 duplicate, 422 wrong-side
stop, 422 exposure, 500 rec_id collision), because those raises are part of the
moved body. A non-HTTP caller must catch them. With `enforce_pre_trade_gates=False`
the two 422s become warnings; the 409 and the 500 still raise. The exposure 422
now also covers an OPTION quantity above `max_contracts_per_trade`, which the
risk check refuses instead of clamping (Q18, P1-CLAMP-AT-SOURCE-2026-09-25).

`enforce_pre_trade_gates` (O4 step 2, spec section 5.2). Default True, which is
the card path, byte-for-byte. False is for a caller whose order is ALREADY AT
THE BROKER (the auto-trade fire path, from step 4): re-running a pre-trade gate
there can only refuse to write down a trade that already happened. It turns off
exactly three things:
  - the exposure 422: an unapproved position is booked, with a warning, and
    `WriteOutcome.over_exposure` is True so the caller can put the breach in
    front of a human (spec section 6.5) -- a log line alone would hide it.
    `over_exposure` is also True when the check APPROVED a quantity smaller
    than the one booked (see `WriteOutcome`);
  - the exposure RESIZE: `qty` is `body.qty`, the quantity that was ordered.
    The books match the broker, not the gate;
  - the wrong-side-stop 422: warned instead of raised, and reported in
    `WriteOutcome.wrong_side_stop` so the caller can page it (Q12). With gates
    off only, when the live underlying fetch returned nothing, the direction is
    checked against `scanStockPrice` instead (when > 0). GAPS, stated: no live
    price and no scanStockPrice means no check; and only USER-SET stops are
    checked at all -- a plan-derived stop is re-anchored, not direction-checked.
It does NOT turn off the duplicate-contract 409, the live refetch, the
re-anchor, the entryPrice replacement, the premium-stop derivation or
`seed_tp_from_pick`. The risk check itself still RUNS in both modes -- it is
what `over_exposure` and `adjusted_size` are read from.

`stop_required` (O4 steps 4+5, spec section 6.2). Default False, which is the
card path, unchanged. True raises 422 when there is no usable stop AFTER the
live re-anchor -- none sent, or one the `(live - scan)` shift drove to <= 0,
which would otherwise be stored as NULL. It raises before the risk-check
SELECT, so nothing is written. The auto-trade booking passes True: a position
with no stop there has no invalidation and no STOP_REACHED alert at all.
"""
from __future__ import annotations

import math

import asyncio
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market import fetch_contract_quote_async, fetch_price_async
from app.models.portfolio import PortfolioPositionModel
from app.schemas import PortfolioPositionCreate
from app.services.config_loader import load_exit_plan_cfg
from app.services.picked_method import seed_tp_from_pick
from app.services.portfolio_exposure import (
    capacity_positions, load_holds, lock_exposure, restart_read, transfer_hold,
)
from app.services.portfolio_performance import _contract_multiplier
from app.services.premium_stop import is_short_stock_position, premium_stop_is_sub_cent
from app.services.portfolio_risk import (
    EXCEEDS_MAX_CONTRACTS,
    account_value, AccountValueError, RiskCheckResult,
    check_position_risk,
    premium_cap_basis,
)

import logging as _logging
_log = _logging.getLogger(__name__)


# A stock price is never <= 0, so a non-positive stop/structuralStop can only
# mean "unset". Moved with the body; the router keeps its own copy for PATCH.
def _floor_stop(value: Optional[float]) -> Optional[float]:
    return value if value is not None and value > 0 else None


# One lock per running event loop. A module-level `asyncio.Lock()` would bind to
# the first loop that awaits it, and the test suite runs many loops -- a lock
# bound to a dead loop raises. Weak keys, so a finished loop takes its lock with it.
_BOOKING_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


def _booking_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _BOOKING_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _BOOKING_LOCKS[loop] = lock
    return lock


@dataclass
class WriteOutcome:
    """What `create_position` did, beyond the row itself (spec section 5.1).

    `adjusted_size` is `risk.adjusted_size` as the check computed it (None
    if it computed none). The gate APPLIES it only with gates on and only when
    the check approved; a refusal can carry one too. With gates off the row's
    `qty` is `body.qty` whatever this says.

    `over_exposure` means the booked position went past a cap. It is
    computed only with gates off; with gates on it is False by construction --
    an unapproved result (which now includes a qty above the per-trade cap)
    raises 422, and an approved soft resize is applied to qty. With gates off
    it is True when ANY of these holds, because each means the booked quantity
    was never judged within the caps:
      - `not risk.approved` -- read from `approved`, never inferred from
        `adjusted_size`: the two are set independently (max-concurrent refuses
        with no resize). An option qty above `max_contracts_per_trade` lands
        here: the check refuses it with `exceeds_max_contracts_per_trade`;
      - `risk.adjusted_size is not None` -- an APPROVED soft resize. The check
        judged the total-exposure cap on the RESIZED capital, so booking the
        ordered quantity is over the single-position cap and can be over the
        total cap with `approved` still True;
      - `risk.judged_size != body.qty` -- the check judged a different quantity
        from the one booked. No path produces this today (STOCK-SENDS removed
        the |STOCK share clamp, the last one); kept as a guard.
    This is wider than spec section 5.1's comment "risk.approved was False";
    it is that comment's own gloss, "the booking went past a cap", made true
    (O4 step 2, round 1).

    `wrong_side_stop` (Q12) is the wrong-side detail when a user-set stop on
    the wrong side of the underlying was booked with gates off (None
    otherwise). With gates on that stop raises 422 instead. The caller must
    put it in front of a human; a log line alone hides it.

    `premium_stop_unapplied` (decision PREMIUM-STOP-FALLBACK-USER-FRACTION-
    2026-10-03) is set when a `premiumStopDollar` was sent and the stored
    `premium_stop_pct` is NOT its ratio to the persisted entry -- a total loss
    at that entry, a non-positive entry, or a sub-cent threshold. It names
    what was stored instead: the client's fraction, or nothing (the global).
    The auto-trade booking pages it; the card path reads the same fact off the
    201 itself.
    """
    position:      PortfolioPositionModel
    adjusted_size: Optional[int]
    over_exposure: bool
    wrong_side_stop: Optional[str] = None
    premium_stop_unapplied: Optional[str] = None


def _rescale_rung_shares(targets: list, asked: int, stored: int) -> list:
    """STOCK-SENDS (plan B3): scale a resized stock row's per-rung
    `contractsToSell` from the `asked` share count to the `stored` one, so the
    sell-to-close plan never sells more than the position holds.

    Proportional, so a partial ladder stays partial (its runner is kept):
    S = sum of the rung shares, target = min(stored, floor(S * stored / asked));
    each rung gets floor(c * stored / asked), and the `target - sum(floors)`
    leftover units go one each to the largest fractional parts (ties: the
    earlier rung). 50/30/20 of 100 -> 20/12/8 of 40; 33/33 of 100 -> 13/13 of 40.
    A rung rounded to 0 keeps its price with `contractsToSell: 0`. Rungs without
    a positive integer `contractsToSell` are left untouched and not counted."""
    if asked <= 0 or stored >= asked:
        return targets
    idx = [
        i for i, t in enumerate(targets)
        if isinstance(t, dict) and isinstance(t.get("contractsToSell"), int)
        and not isinstance(t.get("contractsToSell"), bool) and t["contractsToSell"] > 0
    ]
    if not idx:
        return targets
    shares = {i: targets[i]["contractsToSell"] for i in idx}
    total = sum(shares.values())
    target_sum = min(stored, (total * stored) // asked)
    new = {i: (c * stored) // asked for i, c in shares.items()}
    leftover = target_sum - sum(new.values())
    # Largest fractional part first; ties keep the earlier rung.
    for i in sorted(idx, key=lambda i: (-((shares[i] * stored) % asked), i))[:max(leftover, 0)]:
        new[i] += 1
    return [
        {**t, "contractsToSell": new[i]} if i in new else t
        for i, t in enumerate(targets)
    ]


def _prepared_marker(body: PortfolioPositionCreate, stored_qty: int) -> dict:
    """Gates-on save-before-order identity. Gates-off booking must not call this."""
    from decimal import Decimal
    if str(body.contract).endswith("|STOCK") and body.direction == "Bearish":
        action = "SELL"
    else:
        action = "BUY"
    limit = None
    if body.orderType == "LMT" and body.orderLimitPrice is not None:
        limit = format(Decimal(str(body.orderLimitPrice)).normalize(), "f")
    return {
        "instrument": body.contract,
        "symbol": body.symbol,
        "action": action,
        "effect": "OPEN",
        "quantity": int(stored_qty),
        "order_type": body.orderType,
        "limit": limit,
    }


async def create_position(
    body: PortfolioPositionCreate,
    db: AsyncSession,
    *,
    quote_fetcher: Optional[Callable[..., Awaitable[object]]] = None,
    price_fetcher: Optional[Callable[..., Awaitable[object]]] = None,
    exit_plan_cfg_loader: Optional[Callable[[], dict]] = None,
    enforce_pre_trade_gates: bool = True,
    stop_required: bool = False,
    cap_basis: Optional[float] = None,
    cap_basis_floor: Optional[float] = None,
    exposure_attempt_id: Optional[str] = None,
) -> WriteOutcome:
    """Persist a position from a create request. See the module docstring.

    `cap_basis`: the per-contract premium the D5 cap is judged at, when the
    caller has ALREADY judged the order at one -- the auto-trade booking passes
    the fire's `auto_trader.armed_cap_basis` for an LMT arm so the two cannot
    disagree (audit round 2, R2-F6). None (every other caller): derived here
    from the stored entry, the order fields and the save-time live spread.

    `cap_basis_floor`: judge at max(floor, the basis derived here) instead --
    the auto-trade booking of a MKT arm (audit round 3, R3-F1). A market order
    fills at the booking-time price, which can be far above the armed mid the
    fire judged (the manual fire has no age bound), so the derived basis must
    still be read; the armed basis is the floor so a quote that fell never
    judges below what the fire approved. Mutually exclusive with `cap_basis`.

    The STORED entry is unaffected either way.
    """
    if cap_basis is not None and cap_basis_floor is not None:
        raise ValueError("create_position: pass cap_basis OR cap_basis_floor, not both")
    # Call-time defaults (P1a): the module globals, looked up NOW, so a patch
    # on this module's names lands. See the module docstring.
    if quote_fetcher is None:
        quote_fetcher = fetch_contract_quote_async
    if price_fetcher is None:
        price_fetcher = fetch_price_async
    if exit_plan_cfg_loader is None:
        exit_plan_cfg_loader = load_exit_plan_cfg

    # Duplicate contract check → 409. Drop that read snapshot before the live
    # fetches: holding it across the exposure-guard wait would miss the writer
    # this transaction waited for.
    await _raise_if_contract_exists(db, body.contract)
    await restart_read(db)

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
    # ROUND 10 -- the underlying price is ALSO needed to direction-check a
    # user-set stop, and that check must not depend on whether the caller
    # happened to send `scanStockPrice`.
    #
    # Round 9 added the wrong-side guard below and gated it on `live_price`,
    # which was only ever fetched when `need_reanchor` was true. Since
    # `scanStockPrice` is Optional and defaults to None, omitting one field
    # skipped the guard entirely -- `{"stop": 1400, "stopIsUserSet": true}` on
    # a $145 stock returned 201 and stored 1400. Round 9's own justification
    # for the guard was "any other client, a replayed request, or a future call
    # site", every one of which controls that field; and the project's OWN
    # basket path is already such a client, because `positionFromOrder` never
    # sets `scanStockPrice`. The guard had therefore never run on it.
    need_live_price = need_reanchor or bool(body.stopIsUserSet)
    # For a stock position (SYMBOL|STOCK), fetch_contract_quote_async's quote
    # price IS the underlying price — fetching it separately via
    # fetch_price_async as well would just duplicate the same call.
    is_stock = body.contract.endswith("|STOCK")
    try:
        async with httpx.AsyncClient(timeout=8) as _cl:
            _quote_task = quote_fetcher(_cl, body.contract)
            if need_live_price and not is_stock:
                live_quote, live_price = await asyncio.gather(
                    _quote_task, price_fetcher(_cl, body.symbol),
                )
            else:
                live_quote = await _quote_task
                live_price = (
                    (live_quote or {}).get("price") if need_live_price and is_stock and isinstance(live_quote, dict)
                    else None
                )
    except Exception:
        live_quote, live_price = None, None
        _log.warning(
            "create_position: live save-time refetch failed for %s; keeping frontend values",
            body.contract, exc_info=True,
        )

    if need_reanchor and live_price and live_price > 0:
        delta = live_price - body.scanStockPrice
        # A USER-TYPED stop is an absolute price against today's quote, not a
        # plan level that scales with the underlying, so it must be stored as
        # sent. Re-anchoring it added (live - scan) to a number the user chose
        # while looking at `live`: a $180 stop typed on a $200 stock scanned at
        # $145 became $235, ABOVE spot, and alert_generator's bullish
        # `price <= pos.stop` then raised a Critical STOP_REACHED (with Gmail
        # and Telegram behind it) on the first backend scan. The everyday
        # non-stale case is the same defect smaller: scanned 150, saved at 152,
        # typed 147 -> stored 149.
        #
        # structuralStop and the targets below are NOT exempted -- those are
        # still plan-derived and still have to move with the underlying.
        if adjusted_stop is not None and not body.stopIsUserSet:
            adjusted_stop = round(adjusted_stop + delta, 2)
            if body.stop and body.stop > 0 and adjusted_stop <= 0:
                # _floor_stop below will silently store this as None (a stock
                # price is never <= 0, so a non-positive value can't be a real
                # stop) -- log it so a user-specified stop being dropped is
                # traceable instead of just vanishing.
                _log.warning(
                    "create_position: live-price reanchor pushed stop non-positive for %s "
                    "(requested %.2f, reanchored %.2f, delta %.2f) -- stored as unset",
                    body.contract, body.stop, adjusted_stop, delta,
                )
        if adjusted_structural_stop is not None:
            adjusted_structural_stop = round(adjusted_structural_stop + delta, 2)
            if body.structuralStop and body.structuralStop > 0 and adjusted_structural_stop <= 0:
                _log.warning(
                    "create_position: live-price reanchor pushed structuralStop non-positive for %s "
                    "(requested %.2f, reanchored %.2f, delta %.2f) -- stored as unset",
                    body.contract, body.structuralStop, adjusted_structural_stop, delta,
                )
        adjusted_targets = [
            {
                **t,
                "stockPrice":  round((t.get("stockPrice")  or 0) + delta, 2),
                "targetPrice": round((t.get("targetPrice") or 0) + delta, 2),
            }
            for t in adjusted_targets
        ]
        entry_stock_price = live_price

    # O4 steps 4+5 (spec section 6.2, the write half): a caller that must not
    # book a position without an invalidation refuses HERE, after the
    # re-anchor and before the risk-check SELECT -- so no row and no pending
    # write can exist when it raises. Without the flag, a stop the re-anchor
    # drives to <= 0 is stored as NULL by `_floor_stop` below (logged above).
    if stop_required and _floor_stop(adjusted_stop) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"No usable stop after the re-anchor for {body.contract} "
                f"(sent {body.stop!r}, re-anchored {adjusted_stop!r}); a position "
                "without an invalidation is not booked."
            ),
        )

    # ROUND 9 -- a USER-TYPED stop on the wrong side of the underlying is
    # refused here, not just in the React input that usually produces it.
    #
    # The card bounds this field directionally against the live quote, and
    # round 8 recorded why the two failure modes are asymmetric: a bullish stop
    # ABOVE spot fires STOP_REACHED Critical on the first scan (loud, and
    # wrong), while one far BELOW never fires at all (silent, and worse). The
    # card was the sole guard for both -- the schema had no bound and no
    # direction check, so `stop: 1400` on a $145 stock was accepted and stored
    # by any other client, a replayed request, or a future call site.
    #
    # Only the DIRECTION is checked, never the magnitude: how wide a stop
    # should be is the caller's judgement, and only the caller knows what it is
    # trading around. Only user-set stops are checked, because a plan-derived
    # one is re-anchored above and is the plan's business, not this guard's.
    #
    # Q12 (P1a), GATES OFF ONLY: when the live fetch returned nothing, check
    # against the scan-time underlying price instead, so a wrong-side stop on
    # an order already at the broker is still reported. With gates on nothing
    # changes: the card path refuses only against a live price.
    wrong_side_stop: Optional[str] = None
    check_price, check_suffix = None, ""
    if live_price and live_price > 0:
        check_price = live_price
    elif not enforce_pre_trade_gates and body.scanStockPrice and body.scanStockPrice > 0:
        check_price = body.scanStockPrice
        check_suffix = f" (against the scan price {body.scanStockPrice:.2f}; the live fetch failed)"
    if body.stopIsUserSet and adjusted_stop is not None and check_price is not None:
        wrong_side = (
            adjusted_stop >= check_price if body.direction == "Bullish"
            else adjusted_stop <= check_price
        )
        if wrong_side:
            wrong_side_detail = (
                f"A {body.direction.lower()} stop of {adjusted_stop:.2f} is on the wrong "
                f"side of the underlying at {check_price:.2f}; it would fire immediately."
                f"{check_suffix}"
            )
            if enforce_pre_trade_gates:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=wrong_side_detail,
                )
            # O4 step 2 (spec section 5.2): the order is already at the broker.
            # A stop that fires on the first scan is loud, visible in the drawer
            # and one edit to correct; refusing leaves no position at all.
            _log.warning(
                "create_position: %s -- booking %s anyway, pre-trade gates are off",
                wrong_side_detail, body.contract,
            )
            wrong_side_stop = wrong_side_detail

    live_entry = (live_quote or {}).get("price") if isinstance(live_quote, dict) else None
    # ROUND FIRST, THEN TEST. `float(live_entry) > 0` on the raw quote let a
    # sub-cent live price (0.004) pass the guard and then round to 0.0, which
    # is the one value `entryPrice`'s own `gt=0` bound exists to keep out --
    # the bound validates what the CLIENT sent, and this line overwrites it
    # afterwards, so the bound never sees this value. A stored 0.0 entry is
    # silently unprotected: alert_generator gates PREMIUM_STOP on
    # `pos.entry_price > 0`, so the position can never raise a stop alert at
    # all, and the derived per-position stop below divides by it.
    live_entry_rounded = round(float(live_entry), 2) if live_entry is not None else None
    if live_entry_rounded and live_entry_rounded > 0:
        entry_price = live_entry_rounded
    else:
        # %s (not %.2f) — entryPrice is a required float, but keep %s here
        # since this just logs whatever the frontend sent verbatim.
        _log.info(
            "create_position: no live quote for %s; storing frontend entryPrice %s",
            body.contract, body.entryPrice,
        )

    # CREATE vs CREATE (P1a): everything from here to `refresh` runs under the
    # booking lock -- see the module docstring. The exposure guard is taken
    # first, then the duplicate check is re-run, so a same-contract race
    # answers 409, never 422.
    async with _booking_lock():
        # Guard before the fresh snapshot. This contract check is the second
        # and last one before commit (the collision test counts those two).
        await lock_exposure(db)
        db.expire_all()
        await _raise_if_contract_exists(db, body.contract)

        result = await db.execute(select(PortfolioPositionModel))
        db_positions = result.scalars().all()
        holds = await load_holds(db)
        if exposure_attempt_id:
            # This booking is the held order. Counting the hold beside it would
            # treat one fill as two exposures; the transfer below keeps the hold.
            holds = [hold for hold in holds if hold.attempt_id != exposure_attempt_id]
        portfolio = capacity_positions(db_positions, holds)

        # Audit round 1, F1: the cap is judged at the price the order this
        # save precedes can FILL at, not at the mid stored as the entry. The
        # spread is read only from the live quote that set `entry_price`; with
        # no live quote a MKT order is judged at the mid (premium_cap_basis
        # documents that understatement). No order fields -> the mid, as before.
        live_spread = (
            live_quote.get("spread")
            if isinstance(live_quote, dict) and live_entry_rounded and live_entry_rounded > 0
            else None
        )
        if cap_basis is None:
            cap_basis = premium_cap_basis(
                entry_price, body.orderType, body.orderLimitPrice, spread=live_spread,
            )
            if cap_basis_floor is not None:
                cap_basis = max(float(cap_basis_floor), cap_basis)
        try:
            risk = check_position_risk(
                symbol=body.symbol,
                contract_id=body.contract,
                proposed_contracts=body.qty,
                entry_premium=cap_basis,
                current_price=cap_basis,
                portfolio=portfolio,
                portfolio_value=account_value(),
            )
        except AccountValueError as exc:
            if enforce_pre_trade_gates:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            risk = RiskCheckResult(approved=False, reasons=[str(exc)])
        if not risk.approved and enforce_pre_trade_gates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_refusal_detail(risk, body.qty),
            )
        # O4 step 2 (spec section 5.2). With gates on this stays False: a refusal
        # raised above, and an approved resize is applied to `qty` below. With
        # gates off `qty` is `body.qty`, and every way the check can have judged a
        # quantity other than that one is a breach -- see `WriteOutcome`.
        over_exposure = False
        if not enforce_pre_trade_gates:
            # The resize is listed ONCE: as its own sentence below, never also as
            # the `size_reduced_to_fit_exposure_limit` code. No config read here --
            # every number comes from the check's own result.
            breaches = [r for r in risk.reasons if r != "size_reduced_to_fit_exposure_limit"]
            if risk.adjusted_size is not None:
                breaches.append(f"the check would have resized to {risk.adjusted_size}")
            if risk.judged_size is not None and risk.judged_size != body.qty:
                breaches.append(f"the check judged {risk.judged_size}, not the ordered {body.qty}")
            over_exposure = (not risk.approved) or bool(breaches)
            if over_exposure:
                # This log is not the record of the breach -- `over_exposure` is,
                # and the caller must surface it.
                _log.warning(
                    "create_position: booking %s OVER the exposure gate (%s) at the ordered "
                    "qty %s -- pre-trade gates are off",
                    body.contract, "; ".join(breaches), body.qty,
                )

        # Piece 4 — derive the premium-stop FRACTION here, not on the client.
        # `entry_price` above may have just been replaced with the live quote, and
        # the alert compares `opt_price <= entry_price * (1 - pct)` against exactly
        # that stored value. A fraction computed against the card's mid would mean
        # a $3.12 stop on a $5.20 premium quietly becoming a $2.40 stop after a
        # fill at $4.00. Deriving here is the only place both numbers are known.
        #
        # The dollar amount wins when both are sent: it is what the user typed on
        # the card, while a client-sent fraction is at best a stale estimate of it.
        resolved_premium_stop_pct = body.premiumStopPct
        # Set only where the dollar's own ratio is stored; cleared again by the
        # sub-cent check below. Read for `WriteOutcome.premium_stop_unapplied`.
        dollar_applied = False
        dollar_unapplied_why: Optional[str] = None
        if body.premiumStopDollar is not None and entry_price <= 0:
            dollar_unapplied_why = "the persisted entry is not positive"
            # DEFENCE IN DEPTH, not a live path. `entryPrice` is gt=0 on the create
            # schema and the live re-anchor above now rounds BEFORE testing, so
            # `entry_price` is positive by here on every route currently known. The
            # branch stays because it is the last thing between a future
            # non-positive entry and a division, and because falling back silently
            # is the failure this endpoint is least able to explain: the user typed
            # a dollar stop and the position would inherit the global instead, a
            # different threshold from the one they asked for with nothing on
            # screen to say so. Do not read its presence as evidence that a
            # zero-entry path exists.
            _log.warning(
                "create_position: cannot derive a premium stop from premiumStopDollar %.2f for %s "
                "-- the persisted entry price is %.2f; this position inherits the global",
                body.premiumStopDollar, body.contract, entry_price,
            )
        if body.premiumStopDollar is not None and entry_price > 0:
            ratio = body.premiumStopDollar / entry_price
            if 0 < ratio < 1:
                resolved_premium_stop_pct = ratio
                dollar_applied = True
            else:
                dollar_unapplied_why = "it is a total loss at that entry"
                # A stop at or above the whole premium is a total loss, which is
                # unreachable-by-definition rather than a stop, and there is no
                # representation for it: the column's contract is (0, 1).
                # `entry_price` may have just been replaced with a live quote a few
                # lines up, so this stays reachable through the FILL: typing $4.50
                # and filling at $4.20. (Typing $6.00 on a $5.20 mid no longer
                # reaches it -- round 6 bounded the card's field to 10-99% of the
                # mid -- but the card is not this endpoint's only client, and the
                # fill path does not go through that field at all.)
                #
                # LOGGED, like the sibling stop paths above (which warn when a
                # live-price re-anchor pushes a structural stop non-positive).
                # Falling back silently is worse here than there: the position
                # inherits the 60% global, which is a TIGHTER stop than the one
                # asked for, so PREMIUM_STOP fires earlier than intended and
                # nothing on screen says why.
                _log.warning(
                    "create_position: premiumStopDollar %.2f is %.0f%% of the persisted entry %.2f for %s "
                    "-- at or beyond a total loss, so no per-position stop is stored; "
                    "this position inherits the global",
                    body.premiumStopDollar, ratio * 100, entry_price, body.contract,
                )
                # Falls back to whatever fraction the client sent, not to None: the
                # dollar amount winning is about PREFERENCE between two ways of
                # saying the same thing, and an unusable dollar is no reason to
                # discard a fraction that is independently valid.
                resolved_premium_stop_pct = body.premiumStopPct

        # STOP-SEMANTICS-2026-10-02 (b): a stop below $0.01 at the PERSISTED
        # entry can never fire. Checked on the FINAL value, so a sub-cent client
        # fraction arriving as the fallback above is caught too. Never refuse
        # the create -- on the broker and auto-trade paths the order may already
        # be at the broker -- so this falls back exactly as the ratio >= 1
        # branch does: to the client's fraction when that is itself usable,
        # else None (inherit the global). The client reads the drop off the
        # response's null `premiumStopPct` and says why.
        short_stock = is_short_stock_position(body.contract, body.direction)
        if resolved_premium_stop_pct is not None and premium_stop_is_sub_cent(
            entry_price, resolved_premium_stop_pct, short_stock,
        ):
            _log.warning(
                "create_position: premium stop %.6f at the persisted entry %.4f for %s fires below $0.01 "
                "and could never fire -- not stored",
                resolved_premium_stop_pct, entry_price, body.contract,
            )
            if dollar_applied:
                dollar_applied = False
                dollar_unapplied_why = "it would fire below $0.01 at that entry"
            fallback = body.premiumStopPct
            if fallback is not None and premium_stop_is_sub_cent(entry_price, fallback, short_stock):
                fallback = None
            resolved_premium_stop_pct = fallback

        premium_stop_unapplied: Optional[str] = None
        if body.premiumStopDollar is not None and not dollar_applied:
            kept = (
                f"{resolved_premium_stop_pct * 100:.2f}% of the premium (the fraction sent with it) is stored instead"
                if resolved_premium_stop_pct is not None
                else "no per-position stop is stored, so it inherits the global premium stop"
            )
            premium_stop_unapplied = (
                f"the ${body.premiumStopDollar:.2f}/share premium stop could not be applied at the "
                f"booked entry ${entry_price:.2f} ({dollar_unapplied_why or 'reason unavailable'}); {kept}."
            )

        # Phase G (piece 5) — seed the post-trade alert basis from the trader's
        # pre-trade pick, so TP_HIT starts life agreeing with the card the trade was
        # sent from instead of defaulting to the ladder.
        #
        # THE PAIR IS RETURNED AS ONE VALUE and assigned as one, because a non-ladder
        # `active_tp_method` with a NULL `resolved_tp_price` is a state the drawer's
        # own writer cannot produce and is gate-level when it happens: the drawer
        # renders that method as selected with a null price while TP_HIT silently
        # fires on the ladder (spec §2.7). Do not split this into two assignments.
        #
        # `body.exitPlan` is passed UNCHANGED and the picked price is stored
        # UNCHANGED — neither is re-anchored by the live-price `delta` above, and
        # that is deliberate rather than an oversight. The exit plan is persisted
        # verbatim and never recomputed, so the picked row and the plan row it came
        # from must stay in the SAME frame: shifting one and not the other would put
        # a price on screen in the drawer that differs from the one that actually
        # fires, which is the very disagreement §2.7 forbids. The ladder `targets`
        # ARE re-anchored, and are allowed to differ — they are a different method.
        #
        # A body with no pick (a pre-G client, or the exempt after-scan
        # auto-executor) yields ('ladder', None), which is today's default and
        # exactly what those positions got before G.
        #
        # The config read is GUARDED, and for the reason §4.4 gives about this
        # endpoint specifically: every send path places the broker order FIRST and
        # persists second, so an exception raised here does not prevent a trade —
        # it loses the RECORD of a trade that already happened, leaving a real
        # filled position with no stop and no TP alert. A malformed or unreadable
        # risk_rules.yaml must therefore degrade the arithmetic mapping (to the
        # ladder, which is where the alert fired before G) and never 500 the create.
        try:
            _rr_ratios = exit_plan_cfg_loader().get("target", {}).get("rr_ratios")
            _shown = body.exitPlan.get("targets") if isinstance(body.exitPlan, dict) else None
            if isinstance(_shown, list) and _shown and all(
                isinstance(row, dict) and isinstance(row.get("rrRatio"), (int, float))
                and not isinstance(row["rrRatio"], bool) and math.isfinite(row["rrRatio"])
                for row in _shown
            ):
                _rr_ratios = [row["rrRatio"] for row in _shown]
        except Exception:
            _rr_ratios = None
            _log.warning(
                "create_position: could not load exit_plan.target.rr_ratios for %s; "
                "an arithmetic method pick degrades to the ladder for this position",
                body.contract, exc_info=True,
            )
        active_tp_method, resolved_tp_price = seed_tp_from_pick(
            body.pickedMethod,
            body.pickedRowStockPrice,
            exit_plan=body.exitPlan,
            # Prefer the ratios on the shown rows; config is the legacy fallback.
            rr_ratios=_rr_ratios,
        )

        # Gates off: the quantity that was ORDERED, never the gate's resize
        # (spec section 5.2) -- booking 3 when the broker traded 5 puts every
        # downstream P&L and exposure number on a quantity that never happened.
        stored_qty = (risk.adjusted_size or body.qty) if enforce_pre_trade_gates else body.qty
        if body.contract.endswith("|STOCK") and stored_qty < body.qty:
            # STOCK-SENDS (plan B3): the rung shares follow the resize.
            adjusted_targets = _rescale_rung_shares(adjusted_targets, body.qty, stored_qty)

        position = PortfolioPositionModel(
            rec_id=body.recId,
            symbol=body.symbol,
            contract=body.contract,
            direction=body.direction,
            entry_price=entry_price,
            qty=stored_qty,
            entry_date=body.entryDate,
            stop=_floor_stop(adjusted_stop),
            structural_stop=_floor_stop(adjusted_structural_stop),
            exit_plan=body.exitPlan,
            targets=adjusted_targets,
            dte_total=body.dteTotal,
            entry_stock_price=entry_stock_price,
            # Feature 5 — pre-trade max-loss override, set on the Arithmetic
            # Profit Target card and carried through here at creation time.
            max_loss_override=body.maxLossOverride,
            # Piece 4 — per-position premium stop, set at creation so a trade sent
            # from the card carries the stop the user chose on it. None persists as
            # NULL, meaning "inherit the global".
            premium_stop_pct=resolved_premium_stop_pct,
            # Phase G — the RECORD of the human decision, stored as sent. NULL is a
            # real state ("nobody picked"), and `picked_method` is what the
            # portfolio displays; `active_tp_method` below is the alert driver
            # seeded from it, and the two are allowed to disagree (a barrier-race
            # pick records 'barrier_race' here and seeds 'ladder' there).
            picked_method=body.pickedMethod,
            picked_row_stock_price=body.pickedRowStockPrice,
            # RECORD ONLY. This is a PREMIUM and must never reach
            # `resolved_tp_price`, which is compared against the stock quote.
            picked_row_option_price=body.pickedRowOptionPrice,
            picked_stop_basis=body.pickedStopBasis,
            picked_at=body.pickedAt,
            # STOCKS-HORIZON-T1 H6 -- the scan's hold; NULL = no time stop.
            hold_max_days=body.holdMaxDays,
            active_tp_method=active_tp_method,
            resolved_tp_price=resolved_tp_price,
            # Stamped ONLY when a price was actually seeded. The drawer's writer
            # stamps it on both branches, but doing that here would give every
            # pre-G and every no-pick create a timestamp where it gets NULL today,
            # for a field that exists to show "as of" staleness on a resolved price
            # that in those cases does not exist. No pick -> byte-identical to
            # today's behaviour; a seeded pick -> carries its vintage.
            resolved_tp_updated_at=(
                datetime.now(timezone.utc) if resolved_tp_price is not None else None
            ),
        )
        if enforce_pre_trade_gates and body.orderType:
            position.prepared_order = _prepared_marker(body, stored_qty)
        if exposure_attempt_id:
            position.order_attempt_id = exposure_attempt_id
            await transfer_hold(db, exposure_attempt_id, body.recId, stored_qty)
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

        return WriteOutcome(
            position=position,
            adjusted_size=risk.adjusted_size,
            over_exposure=over_exposure,
            wrong_side_stop=wrong_side_stop,
            premium_stop_unapplied=premium_stop_unapplied,
        )


async def _raise_if_contract_exists(db: AsyncSession, contract: str) -> None:
    """The duplicate-contract 409. Run once before the live fetches and once
    again under the booking lock (P1a)."""
    existing = await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.contract == contract)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Position with contract '{contract}' already exists.",
        )


def _refusal_detail(risk, qty: int) -> str:
    """The gates-on 422 detail. A qty above the per-trade cap (Q18) gets a
    sentence the user can act on, followed by any other hard reason's code;
    every other refusal keeps the raw codes, which the Portfolio page and
    SendToBrokerDialog map."""
    if EXCEEDS_MAX_CONTRACTS not in risk.reasons:
        return " ".join(risk.reasons)
    cap = risk.max_contracts
    detail = (
        f"{qty} contracts is above the {cap}-contract limit per trade "
        f"(max_contracts_per_trade). Lower Contracts to {cap} or fewer and send again."
    )
    others = [
        r for r in risk.reasons
        if r not in (EXCEEDS_MAX_CONTRACTS, "size_reduced_to_fit_exposure_limit")
    ]
    if others:
        detail += " Also: " + " ".join(others)
    return detail
