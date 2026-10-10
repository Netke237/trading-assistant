"""Request-boundary guards (NUMERIC-API-INPUTS T1, board #164).

`NonFiniteJsonGuard` refuses a JSON request body that carries a non-finite
number -- the literals NaN / Infinity / -Infinity, or a number literal that
overflows a double to +-inf, whether written as a float (1e999) or as an
integer of 309+ digits (the browser's JSON.parse reads both as Infinity) --
with FastAPI's standard 422 shape, before any endpoint runs. FastAPI parses bodies with `json.loads`, which accepts all of
these; inside an untyped `dict` field nothing validates them afterwards, so
without this guard they reach calculations and storage.

Plan: docs/superpowers/plans/2026-10-10-numeric-api-inputs-plan.md section 3 T1.

Design:
  * Pure ASGI, not BaseHTTPMiddleware (which mishandles body replay and
    background tasks).
  * Only http POST/PUT/PATCH/DELETE with a content-type FastAPI itself would
    parse as JSON (application/json or application/*+json). Everything else,
    websockets and lifespan included, passes through untouched.
  * Any other decode problem (invalid JSON, bad UTF-8, ...) is NOT handled
    here: the original bytes go through so FastAPI keeps its current error.
    The guard never changes what valid finite JSON means.
  * Strings are not inspected: "NaN" as text is a residual (plan section 5).
"""
from __future__ import annotations

import email.message
import json
import math

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _NonFinite(Exception):
    """Raised from the json.loads hooks; carries the literal text."""

    def __init__(self, literal: str) -> None:
        super().__init__(literal)
        self.literal = literal


def _reject_constant(literal: str):
    # json.loads calls this for exactly NaN, Infinity and -Infinity.
    raise _NonFinite(literal)


def _finite_float(literal: str) -> float:
    value = float(literal)
    if not math.isfinite(value):   # e.g. 1e999 -> inf
        raise _NonFinite(literal)
    return value


def _finite_int(literal: str) -> int:
    # json.loads routes an integer literal (no fraction, no exponent) here, not
    # to parse_float. float() of a huge digit string returns +-inf rather than
    # raising, and has no digit limit, so the finiteness check comes FIRST:
    # int() of a literal beyond sys.get_int_max_str_digits() (4300) raises
    # ValueError, which would otherwise read as invalid JSON.
    if not math.isfinite(float(literal)):   # e.g. 10**400 written out
        raise _NonFinite(literal)
    return int(literal)


def _syntax_only(_literal: str) -> int:
    # The re-parse below only asks "is this valid JSON?": numbers are not
    # converted, so an integer beyond the int-string digit limit is not
    # mistaken for a syntax error.
    return 0


def _is_json_content_type(scope: Scope) -> bool:
    """Mirror FastAPI 0.141 routing.py: a missing content-type is not parsed as
    JSON (strict_content_type defaults to True); otherwise maintype must be
    `application` and the subtype `json` or `*+json`."""
    value = None
    for name, raw in scope.get("headers") or ():
        if name.lower() == b"content-type":
            value = raw.decode("latin-1")
            break
    if not value:
        return False
    message = email.message.Message()
    message["content-type"] = value
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


class NonFiniteJsonGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in _GUARDED_METHODS
            or not _is_json_content_type(scope)
        ):
            await self.app(scope, receive, send)
            return

        # Buffer the whole body (every http.request until more_body is false).
        chunks: list[bytes] = []
        pending: list[Message] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # e.g. http.disconnect mid-body: hand it to the app as-is.
                pending.append(message)
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)

        if not pending and body:
            try:
                json.loads(body, parse_constant=_reject_constant,
                           parse_float=_finite_float, parse_int=_finite_int)
            except _NonFinite as exc:
                refuse = True
                try:
                    # The hook fires as soon as the scanner meets the number,
                    # possibly before a later syntax error. Refuse only a body
                    # that is syntactically valid JSON; otherwise keep
                    # FastAPI's error. Number conversion is skipped so a
                    # 4300+ digit integer (plain json.loads raises ValueError
                    # on it) is still refused as non-finite.
                    json.loads(body, parse_int=_syntax_only,
                               parse_float=_syntax_only, parse_constant=_syntax_only)
                except Exception:
                    refuse = False
                if refuse:
                    await self._refuse(exc.literal, scope, receive, send)
                    return
            except Exception:
                pass   # not our concern: FastAPI reports it as it does today

        if pending:
            # Incomplete body: replay what arrived (still marked more_body),
            # then the message that cut it short.
            replay: list[Message] = (
                [{"type": "http.request", "body": body, "more_body": True}] if body else []
            ) + pending
        else:
            replay = [{"type": "http.request", "body": body, "more_body": False}]

        async def replay_receive() -> Message:
            if replay:
                return replay.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _refuse(literal: str, scope: Scope, receive: Receive, send: Send) -> None:
        """FastAPI's standard 422 shape, with pydantic's type and message."""
        response = JSONResponse(
            status_code=422,
            content={"detail": [{
                "type": "finite_number",
                "loc": ["body"],
                "msg": "Input should be a finite number",
                "input": literal,
            }]},
        )
        await response(scope, receive, send)
