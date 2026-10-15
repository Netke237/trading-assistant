from __future__ import annotations

import asyncio
import html
import json
import math
import re
import threading
import time
import logging
from decimal import Decimal
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.ibkr_paper import BrokerOrder
from app.data.order_errors import (
    OrderAdmissionRefusedError,
    OrderBeforeSubmissionError,
    OrderPreflightRefusedError,
)
from app.data.option_symbol import option_right
from app.database import get_db
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE
from app.services.broker_attempts import (
    BrokerAttemptConflict,
    BrokerAttemptNotFound,
    BrokerAttemptRejected,
    BrokerAttemptService,
    BrokerAttemptStorageError,
    coverage_note,
    outcome_label,
)
from app.services.broker_router import build_router_from_credentials
from app.services.audit import log_event, new_rec_id

router = APIRouter(prefix="/broker", tags=["broker"])


def _selected_adapter(router_, broker):
    return router_.resolve(broker)


def _bridged(hooks) -> bool:
    """True only for a real loop bridge. A test double answers every attribute."""
    return callable(getattr(type(hooks), "_run", None))


def _release_open_risk(order, hooks, attempt_id, reserved, definite, outcome, exposure_hooks=None, exposure_held=False):
    if order.effect == "OPEN" and reserved and hooks is not None:
        hooks.resolve(attempt_id, definitely_not_submitted=definite, outcome=outcome)
    if order.effect == "OPEN" and exposure_held and definite and exposure_hooks is not None:
        exposure_hooks.release(attempt_id)


def _exposure_price(order, hooks, instrument):
    """Price the hold outside the exposure transaction. Limit orders do not quote."""
    if order.order_type == "LMT":
        price = order.limit_price
    elif _bridged(hooks):
        from app.services.daily_risk_hooks import opening_price
        price = hooks._run(opening_price(instrument, order.order_type, order.limit_price))
    else:
        price = order.limit_price if order.limit_price is not None else 1
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise HTTPException(status_code=422, detail="Exposure admission refused opening order: price is not positive")
    return float(price)


def _reserve_open_budget(hooks, attempt_id, *, instrument, quantity, source, multiplier, order_type, limit_price, price):
    """Daily reservation after exposure has committed. A real bridge reuses the price already taken."""
    if _bridged(hooks):
        from app.services import daily_risk
        return hooks._run(daily_risk.reserve(
            attempt_id, instrument=instrument, quantity=quantity, price=price,
            source=source, multiplier=multiplier,
        ))
    return hooks.reserve(
        attempt_id, instrument=instrument, quantity=quantity, source=source,
        multiplier=multiplier, order_type=order_type, limit_price=limit_price,
    )


def _dispatch_order(router_, broker, order, hooks, attempt_id, saved_rec_id=None, exposure_hooks=None):
    """Validate current configuration in the worker immediately before dispatch."""
    if order.effect == "OPEN":
        bearish = order.sec_type == "STK" and order.action == "SELL"
        if order.sec_type == "OPT":
            try:
                right = option_right(order.option_symbol)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            bearish = (order.action == "BUY" and right == "P") or (order.action == "SELL" and right == "C")
        if bearish:
            raise HTTPException(status_code=422, detail=BEARISH_UNVALIDATED_MESSAGE)
    try:
        adapter = _selected_adapter(router_, broker)
    except ValueError as exc:
        raise OrderPreflightRefusedError(str(exc)) from exc
    reserved = False
    exposure_held = False
    if order.effect == "OPEN":
        from app.services.portfolio_exposure import ExposureRefused, LinkedExposureRefused
        from app.services.portfolio_risk import account_value, AccountValueError
        try:
            account_value()
        except AccountValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if order.sec_type == "OPT" and order.action != "BUY":
            raise HTTPException(status_code=422, detail="Daily risk budget refuses naked short option opens")
        instrument = order.option_symbol if order.sec_type == "OPT" else f"{order.symbol}|STOCK"
        multiplier = 100 if order.sec_type == "OPT" else 1
        source = "manual_option" if order.sec_type == "OPT" else "manual_stock"
        try:
            price = _exposure_price(order, hooks, instrument)
            if exposure_hooks is None:
                raise HTTPException(status_code=422, detail="Exposure admission has no originating event-loop bridge")
            exposure_hooks.admit(
                attempt_id=attempt_id,
                instrument=instrument,
                symbol=order.symbol,
                quantity=int(order.quantity),
                limit_price=price,
                multiplier=multiplier,
                effect=order.effect,
                action=order.action,
                order_type=order.order_type,
                saved_rec_id=saved_rec_id,
                gate="manual",
                broker=broker,
                tif=order.tif,
                kind="option" if order.sec_type == "OPT" else "stock",
                conid=order.conid,
            )
            exposure_held = True
        except LinkedExposureRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ExposureRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Exposure admission refused opening order: {exc}") from exc
        try:
            _reserve_open_budget(
                hooks, attempt_id, instrument=instrument, quantity=order.quantity,
                source=source, multiplier=multiplier, order_type=order.order_type,
                limit_price=order.limit_price, price=price,
            )
            reserved = True
        except Exception as exc:
            if exposure_held and exposure_hooks is not None:
                exposure_hooks.release(attempt_id)
            raise HTTPException(status_code=422, detail=f"Daily risk budget refused opening order: {exc}") from exc
    try:
        result = adapter.place_order(order)
    except OrderAdmissionRefusedError:
        _release_open_risk(order, hooks, attempt_id, reserved, True, "not_submitted", exposure_hooks, exposure_held)
        raise
    except OrderBeforeSubmissionError:
        _release_open_risk(order, hooks, attempt_id, reserved, True, "not_submitted", exposure_hooks, exposure_held)
        raise
    except OrderPreflightRefusedError:
        _release_open_risk(order, hooks, attempt_id, reserved, True, "not_submitted", exposure_hooks, exposure_held)
        raise
    except Exception:
        _release_open_risk(order, hooks, attempt_id, reserved, False, "dispatch_error", exposure_hooks, exposure_held)
        raise
    if order.effect == "OPEN":
        from app.services.auto_trader import _is_rejected_status
        rejected = _is_rejected_status(result.status) or getattr(result, "awaiting_confirmation", False) is True
        _release_open_risk(order, hooks, attempt_id, reserved, rejected, str(result.status), exposure_hooks, exposure_held)
    return result


BrokerKey = Literal["ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"]

# ── Idempotency guard ─────────────────────────────────────────────────────────
# Single-process, in-memory dedup keyed on the order's own fields. This is a
# local single-user tool talking to local paper-broker gateways — a client
# retry-on-timeout within a couple of seconds is the realistic failure mode,
# not distributed/concurrent clients. Window is intentionally short (~3s,
# roughly a client HTTP timeout) so a user who deliberately resubmits the
# same-shaped order seconds later (e.g. scaling into a position) is NOT
# treated as a duplicate. No frontend change (no client-supplied
# idempotency-key header) is required.
#
# Order execution runs in a worker thread (asyncio.to_thread — see the two
# route handlers below), which yields the event loop for the whole broker
# call. That means a second, near-simultaneous identical request can reach
# this guard before the first has finished — a plain check-then-later-record
# is not atomic across that yield. _claim_or_wait() closes that gap: the
# first request atomically reserves the key (under _idempotency_lock, a
# non-blocking dict operation) before it ever awaits anything, and any
# concurrent duplicate waits on that reservation's asyncio.Event instead of
# also passing the check and placing a second real order.
#
# Known limitation, accepted rather than solved here: asyncio.to_thread
# cannot forcibly stop its worker thread. If the request coroutine is ever
# cancelled (client disconnect, server shutdown) while router_.execute() is
# running in that thread, the claim is still released correctly (try/finally
# in the route handlers), but the abandoned thread keeps running and can
# still place a real order after the HTTP response is gone — and a
# subsequent identical request would become a new leader and could place a
# second one. This is a pre-existing property of thread-based execution, not
# a regression: before order execution moved off the event loop, a client
# couldn't even cancel a slow order call at all (the whole server was frozen
# for it). Revisit only if genuine concurrent/networked use emerges — not
# relevant for this tool's single local user today.
_IDEMPOTENCY_WINDOW_SECONDS = 3.0
_idempotency_lock = threading.Lock()
_idempotency_cache: dict[tuple, tuple[float, dict]] = {}     # natural_key -> (ts, response)
_idempotency_inflight: dict[tuple, asyncio.Event] = {}        # natural_key -> event, while a leader is executing


def _natural_order_key(kind: str, req: "StockOrderRequest | OptionOrderRequest") -> tuple:
    """Composite key from the order's own fields — two requests with the same
    key within the dedup window are treated as the same submission attempt."""
    base = (
        kind, req.broker, req.symbol, req.action, req.effect, req.quantity,
        req.order_type, req.limit_price, req.tif,
    )
    if isinstance(req, OptionOrderRequest):
        return base + (req.option_symbol, req.conid)
    return base


async def _claim_or_wait(key: tuple) -> tuple[dict | None, bool]:
    """Atomically claim leadership for `key`, or return a deduped cached
    response if one already exists.

    Returns (response, claimed):
    - (cached_response, False): caller should return cached_response as-is
      (already tagged deduped=True).
    - (None, True): caller is now the leader for this key and MUST call
      _release_claim(key, ...) exactly once when it finishes (success or
      failure) so waiters are released and future requests aren't stuck. Both
      route handlers below enforce this structurally via try/finally around
      the entire leader body — not just by convention — specifically because
      an exception type neither handler catches (anything other than the
      HTTPException/ValueError/RuntimeError cases each already handles, e.g.
      a malformed broker response or a cancelled request) must still release
      the claim; an enumerated except-clause allowlist alone would leave a
      permanently stuck reservation for that natural key.

    A concurrent duplicate that arrives while a leader is executing waits on
    that leader's event rather than racing it — if the leader succeeds, the
    waiter loops back around and finds the now-populated cache entry; if the
    leader fails (no cache entry gets written — see _release_claim), the
    waiter loops back, finds no reservation, and becomes the new leader
    itself.
    """
    while True:
        with _idempotency_lock:
            now = time.monotonic()
            for k in [k for k, (ts, _) in _idempotency_cache.items()
                      if now - ts > _IDEMPOTENCY_WINDOW_SECONDS]:
                del _idempotency_cache[k]
            hit = _idempotency_cache.get(key)
            if hit is not None:
                return {**hit[1], "deduped": True}, False
            event = _idempotency_inflight.get(key)
            if event is None:
                _idempotency_inflight[key] = asyncio.Event()
                return None, True
        await event.wait()


def _release_claim(key: tuple, response: dict | None) -> None:
    """Release leadership claimed via _claim_or_wait(). On success, pass the
    real response so it's cached for waiters (and future dedup hits) with
    `deduped: False` preserved as originally recorded. On failure, pass None
    so no cache entry is written — a waiter that loops back around will find
    no reservation and become the new leader, retrying the call itself."""
    with _idempotency_lock:
        if response is not None:
            _idempotency_cache[key] = (time.monotonic(), response)
        event = _idempotency_inflight.pop(key, None)
    if event is not None:
        event.set()


# ── IBKR's confirmation question (MANUAL-IBKR-CONFIRM-AS-ERROR, Kenneth 2026-09-25) ──
# IBKR can answer a submission with an "order reply message" -- a question to
# confirm -- instead of an order. The order is not placed until
# POST /iserver/reply/{id} confirms it, and nothing in this app sends that
# reply. ibkr_paper.place_order flags that reply (OrderResult.
# awaiting_confirmation); both routes below answer it as a 502 carrying the
# question, never as an empty-id "success" -- every frontend send path creates
# a Portfolio position on a 2xx.
_CONFIRMATION_QUESTION_MAX_CHARS = 500
_CONFIRMATION_QUESTION_FALLBACK = "IBKR asked for a confirmation"
# Tag-shaped runs only, so a question like "price < 5 and qty > 3" survives.
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")


def _confirmation_question(result) -> str | None:
    """IBKR's order-reply question when the broker asked instead of placing the
    order, else None. getattr: only ibkr_paper's OrderResult has the field
    (Tradier's result is its own class). `is True`, not truthiness, so a result
    whose attribute merely reads truthy (a mock, a future non-bool) is not
    mistaken for the reply."""
    if getattr(result, "awaiting_confirmation", False) is not True:
        return None
    text = _HTML_TAG_RE.sub(" ", str(getattr(result, "message", "") or ""))
    # Stripped again after unescaping: an entity-encoded tag ("&lt;br&gt;")
    # only becomes tag-shaped once decoded.
    text = _HTML_TAG_RE.sub(" ", html.unescape(text))
    text = " ".join(text.split())
    return (text or _CONFIRMATION_QUESTION_FALLBACK)[:_CONFIRMATION_QUESTION_MAX_CHARS]


def _raise_if_awaiting_confirmation(result, rec_id: str, kind: str, symbol: str) -> None:
    """Shared by both routes: log the reply as a failed order and answer it as
    a 502. Raised with `response` still None, so _release_claim caches nothing
    and a retry asks IBKR again (nothing was placed)."""
    question = _confirmation_question(result)
    if question is None:
        return
    log_event("broker_order_failed", rec_id, {
        "kind": kind, "broker": result.broker, "symbol": symbol,
        "http_status": 502, "awaiting_confirmation": True, "error": question,
    })
    raise HTTPException(
        status_code=502,
        detail=(
            "IBKR did not place the order: it asked for a confirmation this app "
            f"does not send. IBKR said: {question}"
        ),
    )


class StockOrderRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: gt=0 alone accepts +inf; the limit must be finite.
    model_config = ConfigDict(allow_inf_nan=False)

    broker: BrokerKey
    symbol: str
    action: Literal["BUY", "SELL"]
    effect: Literal["OPEN", "CLOSE"]
    quantity: int = Field(..., ge=1)
    order_type: Literal["MKT", "LMT"] = "LMT"
    # gt=0 -- ROUND 9. A limit price is the one field on this request whose
    # fat-finger is an EXECUTION error rather than an alerting one, and it was
    # an unvalidated Optional[float]: nothing between the request and the
    # broker rejected 0, a negative, or a mistyped magnitude. Round 8 bounded
    # the React input that feeds it and named this schema in the same breath as
    # the reason that finding was CRITICAL, then left it open -- and the card
    # is not this endpoint's only client. A non-positive limit is never a
    # price, on any client; magnitude stays the caller's judgement, since only
    # the caller knows the live quote.
    limit_price: Optional[float] = Field(default=None, gt=0)
    tif: Literal["DAY", "GTC"] = "DAY"
    attempt_id: Optional[str] = None
    saved_rec_id: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("saved_rec_id", "savedRecId"),
    )


class OptionOrderRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: gt=0 alone accepts +inf; the limit must be finite.
    model_config = ConfigDict(allow_inf_nan=False)

    broker: BrokerKey
    symbol: str
    option_symbol: str
    action: Literal["BUY", "SELL"]
    effect: Literal["OPEN", "CLOSE"]
    quantity: int = Field(..., ge=1)
    order_type: Literal["MKT", "LMT"] = "LMT"
    # gt=0 -- ROUND 9. A limit price is the one field on this request whose
    # fat-finger is an EXECUTION error rather than an alerting one, and it was
    # an unvalidated Optional[float]: nothing between the request and the
    # broker rejected 0, a negative, or a mistyped magnitude. Round 8 bounded
    # the React input that feeds it and named this schema in the same breath as
    # the reason that finding was CRITICAL, then left it open -- and the card
    # is not this endpoint's only client. A non-positive limit is never a
    # price, on any client; magnitude stays the caller's judgement, since only
    # the caller knows the live quote.
    limit_price: Optional[float] = Field(default=None, gt=0)
    tif: Literal["DAY", "GTC"] = "DAY"
    conid: Optional[int] = None
    attempt_id: Optional[str] = None
    saved_rec_id: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("saved_rec_id", "savedRecId"),
    )


_FILLED_STATUSES = frozenset({"filled", "fill"})
_UNKNOWN_STATUSES = frozenset({"", "unknown", "unknownstatus"})
_UNUSABLE_ORDER_IDS = frozenset({"", "unknown", "none", "null"})
_TERMINAL_ATTEMPT_STATES = frozenset({
    "proven-not-submitted", "submitted", "filled", "outcome-unknown",
})
_attempt_waiters: dict[str, asyncio.Future] = {}


def _attempt_service(db: AsyncSession) -> BrokerAttemptService:
    def factory():
        class _Bound:
            async def __aenter__(self):
                return db

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Bound()

    return BrokerAttemptService(factory)


def _canonical_order(kind: str, req) -> dict:
    if kind == "option":
        instrument = req.option_symbol
        conid = req.conid
    else:
        instrument = f"{req.symbol}|STOCK"
        conid = None
    limit = None
    if req.order_type == "LMT":
        if req.limit_price is None:
            raise BrokerAttemptRejected("limit order requires an exact limit")
        limit = format(Decimal(str(req.limit_price)).normalize(), "f")
    return {
        "kind": kind,
        "broker": req.broker,
        "symbol": req.symbol,
        "instrument": instrument,
        "action": req.action,
        "effect": req.effect,
        "quantity": req.quantity,
        "order_type": req.order_type,
        "limit": limit,
        "tif": req.tif,
        "conid": conid,
    }


def _supplied_attempt_id(req) -> str | None:
    value = req.attempt_id
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value:
        raise BrokerAttemptRejected("attempt id is inconsistent")
    return value


def _outcome_state(result) -> str:
    from app.services.auto_trader import _is_rejected_status
    if getattr(result, "awaiting_confirmation", False) is True:
        return "proven-not-submitted"
    status = str(getattr(result, "status", "") or "").strip().lower()
    if _is_rejected_status(status):
        return "proven-not-submitted"
    order_id = str(getattr(result, "order_id", "") or "").strip().lower()
    usable = order_id not in _UNUSABLE_ORDER_IDS
    if usable and status in _FILLED_STATUSES:
        return "filled"
    if usable and status not in _UNKNOWN_STATUSES:
        return "submitted"
    return "outcome-unknown"


def _pack_response(status: int, body: dict) -> str:
    return json.dumps(
        {"http_status": status, "body": body},
        separators=(",", ":"),
        default=str,
    )


def _stored_response(raw):
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
        status = parsed["http_status"]
        body = parsed["body"]
    except (TypeError, ValueError, KeyError):
        return None
    if isinstance(status, bool) or not isinstance(status, int) or not isinstance(body, dict):
        return None
    return status, body


def _client_response(status: int, body: dict, *, deduped: bool):
    replay = dict(body)
    if status == 200:
        if deduped:
            replay["deduped"] = True
        return replay
    return JSONResponse(status_code=status, content=replay)


async def _record_attempt(service, claim, state: str, status: int, body: dict, result=None):
    order_id = None if result is None else getattr(result, "order_id", None)
    broker_status = None if result is None else getattr(result, "status", None)
    await service.record_outcome(
        claim.attempt_id,
        state,
        expected_version=claim.verification_version,
        broker_order_id=None if order_id is None else str(order_id),
        broker_status=None if broker_status is None else str(broker_status),
        broker_response=_pack_response(status, body),
    )


def _audit_outcome(state: str, rec_id: str, kind: str, req, result, attempt_id: str) -> None:
    event = {
        "filled": "broker_order_filled",
        "submitted": "broker_order_submitted",
        "outcome-unknown": "broker_order_unknown",
        "proven-not-submitted": "broker_order_failed",
    }[state]
    order_id = getattr(result, "order_id", None)
    status = getattr(result, "status", None)
    log_event(event, rec_id, {
        "kind": kind,
        "broker": str(getattr(result, "broker", req.broker)),
        "symbol": req.symbol,
        "order_id": None if order_id is None else str(order_id),
        "status": None if status is None else str(status),
        "attempt_id": attempt_id,
    })


async def _replay_claim(service, claim, explicit: bool):
    del explicit
    stored = _stored_response(claim.broker_response)
    if claim.state in _TERMINAL_ATTEMPT_STATES:
        if stored is None:
            return JSONResponse(status_code=502, content={"detail": "submission outcome unknown"})
        return _client_response(*stored, deduped=True)
    fut = _attempt_waiters.get(claim.attempt_id)
    if fut is not None:
        status, body = await fut
        return _client_response(status, body, deduped=True)
    for _ in range(50):
        await asyncio.sleep(0.01)
        fut = _attempt_waiters.get(claim.attempt_id)
        if fut is not None:
            status, body = await fut
            return _client_response(status, body, deduped=True)
        try:
            fresh = await service.read(claim.attempt_id)
        except BrokerAttemptStorageError:
            return JSONResponse(status_code=503, content={"detail": "attempt storage failed closed"})
        if fresh.state in _TERMINAL_ATTEMPT_STATES:
            stored = _stored_response(fresh.broker_response)
            if stored is None:
                return JSONResponse(status_code=502, content={"detail": "submission outcome unknown"})
            return _client_response(*stored, deduped=True)
    return JSONResponse(status_code=502, content={"detail": "submission outcome unknown"})


async def _lead_submission(kind, req, order, service, claim, rec_id, exposure_sessions=None):
    fields = {
        "kind": kind, "broker": req.broker, "symbol": req.symbol,
        "action": req.action, "quantity": req.quantity,
        "order_type": req.order_type, "limit_price": req.limit_price,
        "tif": req.tif, "attempt_id": claim.attempt_id,
    }
    if kind == "option":
        fields["option_symbol"] = req.option_symbol
    log_event("broker_order_attempt", rec_id, fields)
    try:
        router_ = build_router_from_credentials()
    except Exception as exc:
        body = {"detail": f"Broker credentials unavailable: {exc}"}
        log_event("broker_order_failed", rec_id, {
            "kind": kind, "broker": req.broker, "symbol": req.symbol,
            "http_status": 503, "attempt_id": claim.attempt_id,
            "error": f"credentials: {exc}",
        })
        await _record_attempt(service, claim, "proven-not-submitted", 503, body)
        return 503, body
    from app.services.daily_risk_hooks import capture_daily_risk_hooks
    from app.services.portfolio_exposure_hooks import capture_exposure_hooks
    hooks = capture_daily_risk_hooks() if order.effect == "OPEN" else None
    exposure_hooks = capture_exposure_hooks(exposure_sessions) if order.effect == "OPEN" else None
    result = await asyncio.to_thread(
        _dispatch_order, router_, req.broker, order, hooks, claim.attempt_id,
        claim.saved_rec_id, exposure_hooks,
    )
    if _confirmation_question(result) is not None:
        _raise_if_awaiting_confirmation(result, rec_id, kind, req.symbol)
    state = _outcome_state(result)
    body = {
        "order_id": "" if getattr(result, "order_id", None) is None else str(result.order_id),
        "status": "" if getattr(result, "status", None) is None else str(result.status),
        "broker": "" if getattr(result, "broker", None) is None else str(result.broker),
        "deduped": False,
    }
    await _record_attempt(service, claim, state, 200, body, result)
    _audit_outcome(state, rec_id, kind, req, result, claim.attempt_id)
    return 200, body


def _failure_response(exc: Exception) -> tuple[int, str, dict]:
    proven = isinstance(exc, (
        OrderAdmissionRefusedError, OrderBeforeSubmissionError, OrderPreflightRefusedError,
    ))
    if isinstance(exc, OrderPreflightRefusedError) or (isinstance(exc, ValueError) and not proven):
        status = 400
    else:
        status = 502
    state = "proven-not-submitted" if proven else "outcome-unknown"
    return status, state, {"detail": str(exc)}


async def _submit(kind: str, req, order: BrokerOrder, db: AsyncSession):
    """Claim one durable attempt, then dispatch at most once."""
    from app.services.portfolio_exposure_hooks import sessions_for
    rec_id = new_rec_id()
    exposure_sessions = sessions_for(db)
    service = _attempt_service(db)
    explicit = req.attempt_id is not None
    try:
        claim = await service.claim_production(
            _canonical_order(kind, req),
            attempt_id=_supplied_attempt_id(req),
            saved_rec_id=req.saved_rec_id,
        )
    except BrokerAttemptConflict as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except BrokerAttemptRejected as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except BrokerAttemptStorageError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    if not claim.authorized:
        log_event("broker_order_deduped", rec_id, {
            "kind": kind, "broker": req.broker, "symbol": req.symbol,
            "attempt_id": claim.attempt_id,
            "note": "duplicate submission - returning the durable result",
        })
        return await _replay_claim(service, claim, explicit)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _attempt_waiters[claim.attempt_id] = fut
    holder = {"status": 502, "body": {"detail": "submission outcome unknown"}}
    try:
        try:
            status, body = await _lead_submission(
                kind, req, order, service, claim, rec_id, exposure_sessions,
            )
            holder["status"] = status
            holder["body"] = body
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            holder["status"] = exc.status_code
            holder["body"] = {"detail": detail}
            if not detail.startswith("IBKR did not place the order:"):
                log_event("broker_order_failed", rec_id, {
                    "kind": kind, "broker": req.broker, "symbol": req.symbol,
                    "http_status": exc.status_code, "attempt_id": claim.attempt_id,
                    "error": "bearish unvalidated" if detail == BEARISH_UNVALIDATED_MESSAGE else detail,
                })
            try:
                await _record_attempt(
                    service, claim, "proven-not-submitted", holder["status"], holder["body"],
                )
            except Exception:
                holder["status"] = 502
                holder["body"] = {"detail": "submission outcome unknown"}
                return JSONResponse(status_code=502, content=holder["body"])
            raise
        except asyncio.CancelledError:
            holder["status"] = 502
            holder["body"] = {"detail": "submission outcome unknown"}
            try:
                await asyncio.shield(_record_attempt(
                    service, claim, "outcome-unknown", 502, holder["body"],
                ))
            except Exception:
                pass
            raise
        except Exception as exc:
            status, state, body = _failure_response(exc)
            holder["status"] = status
            holder["body"] = body
            event = "broker_order_failed" if state == "proven-not-submitted" else "broker_order_unknown"
            log_event(event, rec_id, {
                "kind": kind, "broker": req.broker, "symbol": req.symbol,
                "http_status": status, "attempt_id": claim.attempt_id, "error": str(exc),
            })
            try:
                await _record_attempt(service, claim, state, status, body)
            except Exception:
                holder["status"] = 502
                holder["body"] = {"detail": "submission outcome unknown"}
    finally:
        if not fut.done():
            fut.set_result((holder["status"], dict(holder["body"])))
        _attempt_waiters.pop(claim.attempt_id, None)
    if holder["status"] == 200:
        return holder["body"]
    return JSONResponse(status_code=holder["status"], content=holder["body"])


@router.post("/stock-order")
async def place_stock_order(
    req: StockOrderRequest, db: AsyncSession = Depends(get_db),
):
    """Place a paper stock order on the specified broker."""
    order = BrokerOrder(
        symbol=req.symbol,
        action=req.action,
        effect=req.effect,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        tif=req.tif,
        sec_type="STK",
    )
    return await _submit("stock", req, order, db)


@router.post("/option-order")
async def place_option_order(
    req: OptionOrderRequest, db: AsyncSession = Depends(get_db),
):
    """Place a paper options order on the specified broker."""
    order = BrokerOrder(
        symbol=req.symbol,
        action=req.action,
        effect=req.effect,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        tif=req.tif,
        conid=req.conid,
        sec_type="OPT",
        option_symbol=req.option_symbol,
    )
    return await _submit("option", req, order, db)


class VerifyAttemptRequest(BaseModel):
    """A user assertion about an order already at the broker. Not a new send."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal[
        "submitted",
        "filled",
        "definitely-not-submitted",
        "canceled-after-submission",
        "partial",
    ]
    note: str = Field(..., min_length=1, max_length=4000)
    expected_version: int = Field(..., ge=0)


def _public_attempt(view) -> dict:
    return {
        "attempt_id": view.attempt_id,
        "state": view.state,
        "fingerprint": view.fingerprint,
        "verification_version": view.verification_version,
        "saved_rec_id": view.saved_rec_id,
        "broker_order_id": view.broker_order_id,
        "broker_status": view.broker_status,
        "broker_response": view.broker_response,
        "payload": json.loads(view.payload_canonical),
        "verification_outcome": view.verification_outcome,
        "verification_note": view.verification_note,
        "outcome_label": outcome_label(view.state, view.broker_status, view.verification_outcome),
        "coverage_note": coverage_note(view.verification_outcome),
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _attempt_http_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, BrokerAttemptNotFound):
        status = 404
    elif isinstance(exc, BrokerAttemptConflict):
        status = 409
    elif isinstance(exc, BrokerAttemptRejected):
        status = 422
    else:
        status = 503
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@router.get("/attempts")
async def list_broker_attempts(db: AsyncSession = Depends(get_db)):
    """Unresolved attempts, including close and unlinked orders. No broker call."""
    service = _attempt_service(db)
    try:
        rows = await service.list_unresolved()
    except (BrokerAttemptNotFound, BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError) as exc:
        return _attempt_http_error(exc)
    return {"attempts": [_public_attempt(row) for row in rows]}


@router.get("/attempts/{attempt_id}")
async def get_broker_attempt(attempt_id: str, db: AsyncSession = Depends(get_db)):
    service = _attempt_service(db)
    try:
        view = await service.get_attempt(attempt_id)
    except (BrokerAttemptNotFound, BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError) as exc:
        return _attempt_http_error(exc)
    return _public_attempt(view)


@router.post("/attempts/{attempt_id}/verify")
async def verify_broker_attempt(
    attempt_id: str, req: VerifyAttemptRequest, db: AsyncSession = Depends(get_db),
):
    """Compare-and-set a manual verification. Never calls an adapter or mints an id."""
    service = _attempt_service(db)
    try:
        view = await service.verify(attempt_id, req.outcome, req.note, req.expected_version)
    except (BrokerAttemptNotFound, BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError) as exc:
        return _attempt_http_error(exc)
    if req.outcome == "definitely-not-submitted":
        from app.services import daily_risk
        from app.services.daily_risk import DailyRiskError
        try:
            await daily_risk.resolve(
                view.attempt_id, definitely_not_submitted=True, outcome="verified-not-submitted",
            )
        except DailyRiskError as exc:
            if "not reserved" not in str(exc):
                logging.getLogger(__name__).exception(
                    "daily risk release failed for %s", view.attempt_id,
                )
    return _public_attempt(view)


@router.get("/status")
async def broker_status() -> dict:
    """Return which brokers are configured (no credentials exposed)."""
    r = build_router_from_credentials()
    ibkr_ok       = "ibkr_paper"       in r._adapters
    trad_ok       = "tradier_paper"    in r._adapters
    alpaca_ok     = "alpaca_paper"     in r._adapters
    tastytrade_ok = "tastytrade_paper" in r._adapters
    return {
        "ibkr_paper":       {"configured": ibkr_ok},
        "tradier_paper":    {"configured": trad_ok},
        "alpaca_paper":     {"configured": alpaca_ok},
        "tastytrade_paper": {"configured": tastytrade_ok},
        "ibkr_live":        {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "tradier_live":     {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "alpaca_live":      {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "tastytrade_live":  {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
    }
