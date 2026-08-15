from __future__ import annotations

import asyncio
import threading
import time
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.data.ibkr_paper import BrokerOrder
from app.services.broker_router import build_router_from_credentials
from app.services.audit import log_event, new_rec_id

router = APIRouter(prefix="/broker", tags=["broker"])

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


class StockOrderRequest(BaseModel):
    broker: BrokerKey
    symbol: str
    action: Literal["BUY", "SELL"]
    effect: Literal["OPEN", "CLOSE"]
    quantity: int = Field(..., ge=1)
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: Optional[float] = None
    tif: Literal["DAY", "GTC"] = "DAY"


class OptionOrderRequest(BaseModel):
    broker: BrokerKey
    symbol: str
    option_symbol: str
    action: Literal["BUY", "SELL"]
    effect: Literal["OPEN", "CLOSE"]
    quantity: int = Field(..., ge=1)
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: Optional[float] = None
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
            result = await asyncio.to_thread(router_.execute, req.broker, order)
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
            result = await asyncio.to_thread(router_.execute, req.broker, order)
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
