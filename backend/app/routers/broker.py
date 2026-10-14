from __future__ import annotations

import asyncio
import html
import re
import threading
import time
import uuid
import logging
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.data.ibkr_paper import BrokerOrder
from app.data.order_errors import OrderAdmissionRefusedError
from app.data.option_symbol import option_right
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE
from app.services.broker_router import build_router_from_credentials
from app.services.audit import log_event, new_rec_id

router = APIRouter(prefix="/broker", tags=["broker"])


def _selected_adapter(router_, broker):
    return router_.resolve(broker)


def _dispatch_order(router_, broker, order, hooks, attempt_id):
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
    adapter = _selected_adapter(router_, broker)
    if order.effect == "OPEN":
        from app.services.portfolio_risk import account_value, AccountValueError
        try:
            account_value()
        except AccountValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        from app.services.daily_risk import DailyRiskError
        if order.sec_type == "OPT" and order.action != "BUY":
            raise HTTPException(status_code=422, detail="Daily risk budget refuses naked short option opens")
        instrument = order.option_symbol if order.sec_type == "OPT" else f"{order.symbol}|STOCK"
        try:
            hooks.reserve(attempt_id, instrument=instrument, quantity=order.quantity,
                          source="manual_option" if order.sec_type == "OPT" else "manual_stock",
                          multiplier=100 if order.sec_type == "OPT" else 1,
                          order_type=order.order_type, limit_price=order.limit_price)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Daily risk budget refused opening order: {exc}") from exc
    try:
        result = adapter.place_order(order)
    except OrderAdmissionRefusedError:
        if order.effect == "OPEN":
            hooks.resolve(attempt_id, definitely_not_submitted=True, outcome="not_submitted")
        raise
    except Exception:
        if order.effect == "OPEN":
            hooks.resolve(attempt_id, definitely_not_submitted=False, outcome="dispatch_error")
        raise
    if order.effect == "OPEN":
        from app.services.auto_trader import _is_rejected_status
        rejected = _is_rejected_status(result.status) or getattr(result, "awaiting_confirmation", False) is True
        hooks.resolve(attempt_id, definitely_not_submitted=rejected, outcome=str(result.status))
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


@router.post("/stock-order")
async def place_stock_order(req: StockOrderRequest) -> dict:
    """Place a paper stock order on the specified broker."""
    rec_id = new_rec_id()
    idem_key = _natural_order_key("stock", req)
    cached, claimed = await _claim_or_wait(idem_key)
    if not claimed:
        log_event("broker_order_deduped", rec_id, {
            "kind": "stock", "broker": req.broker, "symbol": req.symbol,
            "note": "duplicate submission within dedup window — returning cached result",
        })
        return cached
    log_event("broker_order_attempt", rec_id, {
        "kind": "stock", "broker": req.broker, "symbol": req.symbol,
        "action": req.action, "quantity": req.quantity,
        "order_type": req.order_type, "limit_price": req.limit_price, "tif": req.tif,
    })
    # response stays None unless execution succeeds — the finally below
    # releases the claim unconditionally (success, a handled ValueError/
    # RuntimeError, OR any other exception that escapes this block, e.g. a
    # malformed broker response or a cancelled request) so a stuck
    # reservation can never permanently wedge this natural key.
    response: dict | None = None
    try:
        try:
            router_ = build_router_from_credentials()
        except Exception as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "stock", "broker": req.broker, "symbol": req.symbol,
                "http_status": 503, "error": f"credentials: {exc}",
            })
            raise HTTPException(status_code=503, detail=f"Broker credentials unavailable: {exc}")
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
        try:
            from app.services.daily_risk_hooks import capture_daily_risk_hooks
            hooks = capture_daily_risk_hooks() if req.effect == "OPEN" else None
            result = await asyncio.to_thread(_dispatch_order, router_, req.broker, order, hooks, uuid.uuid4().hex)
        except HTTPException as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "stock", "broker": req.broker, "symbol": req.symbol,
                "http_status": exc.status_code,
                "error": "bearish unvalidated" if exc.detail == BEARISH_UNVALIDATED_MESSAGE else str(exc.detail),
            })
            raise
        except ValueError as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "stock", "broker": req.broker, "symbol": req.symbol,
                "http_status": 400, "error": str(exc),
            })
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "stock", "broker": req.broker, "symbol": req.symbol,
                "http_status": 502, "error": str(exc),
            })
            raise HTTPException(status_code=502, detail=str(exc))
        _raise_if_awaiting_confirmation(result, rec_id, "stock", req.symbol)
        log_event("broker_order_filled", rec_id, {
            "kind": "stock", "broker": result.broker, "symbol": req.symbol,
            "order_id": result.order_id, "status": result.status,
        })
        response = {"order_id": result.order_id, "status": result.status, "broker": result.broker, "deduped": False}
        return response
    finally:
        _release_claim(idem_key, response)


@router.post("/option-order")
async def place_option_order(req: OptionOrderRequest) -> dict:
    """Place a paper options order on the specified broker."""
    rec_id = new_rec_id()
    idem_key = _natural_order_key("option", req)
    cached, claimed = await _claim_or_wait(idem_key)
    if not claimed:
        log_event("broker_order_deduped", rec_id, {
            "kind": "option", "broker": req.broker, "symbol": req.symbol,
            "note": "duplicate submission within dedup window — returning cached result",
        })
        return cached
    log_event("broker_order_attempt", rec_id, {
        "kind": "option", "broker": req.broker, "symbol": req.symbol,
        "option_symbol": req.option_symbol, "action": req.action,
        "quantity": req.quantity, "order_type": req.order_type,
        "limit_price": req.limit_price, "tif": req.tif,
    })
    # See place_stock_order's matching comment — the finally below releases
    # the claim unconditionally so a stuck reservation can never permanently
    # wedge this natural key.
    response: dict | None = None
    try:
        try:
            router_ = build_router_from_credentials()
        except Exception as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "option", "broker": req.broker, "symbol": req.symbol,
                "http_status": 503, "error": f"credentials: {exc}",
            })
            raise HTTPException(status_code=503, detail=f"Broker credentials unavailable: {exc}")
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
        try:
            from app.services.daily_risk_hooks import capture_daily_risk_hooks
            hooks = capture_daily_risk_hooks() if req.effect == "OPEN" else None
            result = await asyncio.to_thread(_dispatch_order, router_, req.broker, order, hooks, uuid.uuid4().hex)
        except HTTPException as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "option", "broker": req.broker, "symbol": req.symbol,
                "http_status": exc.status_code,
                "error": "bearish unvalidated" if exc.detail == BEARISH_UNVALIDATED_MESSAGE else str(exc.detail),
            })
            raise
        except ValueError as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "option", "broker": req.broker, "symbol": req.symbol,
                "http_status": 400, "error": str(exc),
            })
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            log_event("broker_order_failed", rec_id, {
                "kind": "option", "broker": req.broker, "symbol": req.symbol,
                "http_status": 502, "error": str(exc),
            })
            raise HTTPException(status_code=502, detail=str(exc))
        _raise_if_awaiting_confirmation(result, rec_id, "option", req.symbol)
        log_event("broker_order_filled", rec_id, {
            "kind": "option", "broker": result.broker, "symbol": req.symbol,
            "order_id": result.order_id, "status": result.status,
        })
        response = {"order_id": result.order_id, "status": result.status, "broker": result.broker, "deduped": False}
        return response
    finally:
        _release_claim(idem_key, response)


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
