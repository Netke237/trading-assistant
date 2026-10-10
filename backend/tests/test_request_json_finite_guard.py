# backend/tests/test_request_json_finite_guard.py
"""NUMERIC-API-INPUTS T1 -- the JSON boundary guard (app/request_guards.py).

Plan: docs/superpowers/plans/2026-10-10-numeric-api-inputs-plan.md, section 3 T1.

FastAPI parses request bodies with `json.loads`, which accepts the literals
NaN / Infinity / -Infinity and turns an overflowing number such as 1e999 into
inf. Inside an untyped `dict` field nothing validates the value, so it reaches
the endpoint (and, for the portfolio JSON columns, storage). The guard refuses
such a body with a 422 `finite_number` before any endpoint runs; every other
body passes through byte-identical.

  1. NaN / Infinity / -Infinity / 1e999 in an untyped dict -> 422, endpoint not called.
  2. The same literal in a nested list inside an untyped dict -> 422.
  3. A `+json` content type is guarded; `text/plain` is not inspected.
  4. The STRING "NaN" in an untyped dict passes the guard (residual, plan section 5).
  5. A finite body reaches the endpoint byte-identical; chunked bodies are reassembled.
  6. The 422 carries CORS headers for an allowed origin (CORS wraps the guard).
  7. An integer literal that overflows a double (309+ digits, incl. one beyond
     Python's 4300-digit int-string limit) -> 422; a large finite one passes.

TestClient is used WITHOUT a `with` block, so the app lifespan (schedulers,
monitors) never starts; every request is either refused before the endpoint
or hits the trivial echo route mounted below.
"""
from __future__ import annotations

import json

import pytest
from fastapi import Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

import app.routers.portfolio as portfolio_router_mod
from app.main import create_app

_ALLOWED_ORIGIN = "http://localhost:3000"
_PREFIX = (
    '{"rec_id":"REC-T1","symbol":"AAPL","contract":"AAPL|185|2026-12-18|C",'
    '"direction":"Bullish","entry_date":"2026-10-10","entry_price":2.5,'
)


def _portfolio_body(exit_plan_json: str) -> str:
    """A valid POST /api/portfolio body whose untyped `exit_plan` dict is the
    given raw JSON text (hand-written: json.dumps/JSON.stringify never emit
    NaN, a hand-written body is exactly the caller this guards against)."""
    return _PREFIX + '"exit_plan":' + exit_plan_json + "}"


@pytest.fixture
def calls(monkeypatch):
    """Patch the portfolio writer so the test fails loudly if the endpoint
    body runs: it records the call and raises."""
    seen: list = []

    async def _must_not_run(*args, **kwargs):
        seen.append((args, kwargs))
        raise AssertionError("endpoint reached: the guard did not refuse the body")

    monkeypatch.setattr(portfolio_router_mod, "create_position", _must_not_run)
    return seen


@pytest.fixture
def client():
    app = create_app()

    async def _echo(request: Request) -> Response:
        body = await request.body()
        return Response(content=body, media_type="application/octet-stream")

    app.add_api_route("/__t1_echo", _echo, methods=["POST", "PUT", "PATCH", "DELETE"])
    return TestClient(app, raise_server_exceptions=False)


def _assert_finite_422(resp, literal: str) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json() == {
        "detail": [{
            "type": "finite_number",
            "loc": ["body"],
            "msg": "Input should be a finite number",
            "input": literal,
        }]
    }


# 1 ---------------------------------------------------------------------------
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_non_finite_literal_in_untyped_dict_is_refused_before_endpoint(client, calls, literal):
    resp = client.post(
        "/api/portfolio",
        content=_portfolio_body('{"t1": ' + literal + "}"),
        headers={"content-type": "application/json"},
    )
    _assert_finite_422(resp, literal)
    assert calls == []


# 2 ---------------------------------------------------------------------------
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_literal_in_nested_list_is_refused(client, calls, literal):
    resp = client.post(
        "/api/portfolio",
        content=_portfolio_body('{"levels": [[1.0, {"p": ' + literal + "}]]}"),
        headers={"content-type": "application/json"},
    )
    _assert_finite_422(resp, literal)
    assert calls == []


# 3 ---------------------------------------------------------------------------
def test_plus_json_content_type_is_guarded(client, calls):
    resp = client.post(
        "/api/portfolio",
        content=_portfolio_body('{"t1": NaN}'),
        headers={"content-type": "application/merge-patch+json; charset=utf-8"},
    )
    _assert_finite_422(resp, "NaN")
    assert calls == []


def test_text_plain_is_not_inspected(client, calls):
    """FastAPI does not parse a text/plain body as JSON; the guard does not
    inspect it either, so FastAPI's own (non-finite_number) error stands."""
    body = _portfolio_body('{"t1": NaN}')
    resp = client.post("/api/portfolio", content=body, headers={"content-type": "text/plain"})
    assert resp.status_code == 422, resp.text
    assert all(e["type"] != "finite_number" for e in resp.json()["detail"])
    assert calls == []
    # And on the echo route the bytes arrive untouched.
    echo = client.post("/__t1_echo", content=body, headers={"content-type": "text/plain"})
    assert echo.status_code == 200
    assert echo.content == body.encode()


# 4 ---------------------------------------------------------------------------
def test_string_nan_in_untyped_dict_passes_the_guard(client):
    """Documented residual (plan section 5): the guard cannot know a string is
    meant as a number, and refusing the text "NaN" anywhere would break free
    text and tickers."""
    body = _portfolio_body('{"t1": "NaN", "note": "Infinity", "big": "1e999"}')
    resp = client.post("/__t1_echo", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.content == body.encode()


# 5 ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_finite_body_reaches_endpoint_byte_identical(client, method):
    # Odd spacing, key order, a float with trailing zeros and a unicode escape:
    # anything a re-serialisation would change must survive untouched.
    body = b'{ "b":1.50 ,"a" : [1e3, -0.0, 12345678901234567890], "s":"\\u00e9" }\n'
    resp = client.request(method, "/__t1_echo", content=body,
                          headers={"content-type": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.content == body


@pytest.mark.parametrize("body", [
    b'{"a": 1.5',          # truncated
    b'{"a": NaN',          # truncated AFTER a NaN: still a decode error, not a refusal
    b'{"a": 1e999} x',     # trailing garbage after an overflowing number
    b'\xff\xfe{"a": 1}',   # bad encoding
])
def test_invalid_json_passes_through_to_fastapi(client, body):
    resp = client.post("/__t1_echo", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.content == body


def test_invalid_json_keeps_fastapis_own_error(client, calls):
    """A body FastAPI cannot parse keeps FastAPI's json_invalid 422, even when
    the scanner meets a NaN before the syntax error."""
    resp = client.post("/api/portfolio", content=_portfolio_body('{"t1": NaN'),
                       headers={"content-type": "application/json"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["type"] == "json_invalid"
    assert calls == []


@pytest.mark.asyncio
async def test_chunked_body_is_reassembled_and_replayed_once():
    from app.request_guards import NonFiniteJsonGuard

    seen: dict = {}

    async def inner(scope, receive, send):
        msgs = []
        while True:
            m = await receive()
            msgs.append(m)
            if m["type"] != "http.request" or not m.get("more_body", False):
                break
        seen["msgs"] = msgs
        seen["after"] = await receive()   # delegates to the original receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunks = [b'{"a": [1.5,', b' 2.25], "b"', b': {"c": -3e2}}']
    incoming = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
                for i, c in enumerate(chunks)] + [{"type": "http.disconnect"}]

    async def receive():
        return incoming.pop(0)

    sent: list = []

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": "POST", "path": "/x",
             "headers": [(b"content-type", b"application/json")]}
    await NonFiniteJsonGuard(inner)(scope, receive, send)

    assert seen["msgs"] == [{"type": "http.request", "body": b"".join(chunks), "more_body": False}]
    assert seen["after"] == {"type": "http.disconnect"}
    assert sent[0]["status"] == 200

    # The same chunking with a non-finite number split across chunks is refused.
    seen.clear()
    chunks = [b'{"a": [1.5, 1e', b'999]}']
    incoming[:] = [{"type": "http.request", "body": c, "more_body": i == 0}
                   for i, c in enumerate(chunks)]
    sent.clear()
    await NonFiniteJsonGuard(inner)(scope, receive, send)
    assert "msgs" not in seen
    assert sent[0]["status"] == 422
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert json.loads(body)["detail"][0] == {
        "type": "finite_number", "loc": ["body"],
        "msg": "Input should be a finite number", "input": "1e999",
    }


@pytest.mark.asyncio
async def test_non_http_and_get_are_passed_through_untouched():
    from app.request_guards import NonFiniteJsonGuard

    calls: list = []

    async def inner(scope, receive, send):
        calls.append(scope["type"])
        assert receive is sentinel_receive

    async def sentinel_receive():  # pragma: no cover - never awaited
        raise AssertionError

    async def send(m):  # pragma: no cover
        raise AssertionError

    guard = NonFiniteJsonGuard(inner)
    await guard({"type": "websocket", "headers": []}, sentinel_receive, send)
    await guard({"type": "lifespan"}, sentinel_receive, send)
    await guard({"type": "http", "method": "GET",
                 "headers": [(b"content-type", b"application/json")]}, sentinel_receive, send)
    assert calls == ["websocket", "lifespan", "http"]


# 6 ---------------------------------------------------------------------------
def test_refusal_carries_cors_headers_for_allowed_origin(client, calls):
    resp = client.post(
        "/api/portfolio",
        content=_portfolio_body('{"t1": Infinity}'),
        headers={"content-type": "application/json", "origin": _ALLOWED_ORIGIN},
    )
    _assert_finite_422(resp, "Infinity")
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN
    assert calls == []


# 7 ---------------------------------------------------------------------------
# Python's json routes an integer literal (no fraction, no exponent) to
# parse_int, not parse_float, and keeps it an exact int -- so a 309+ digit
# integer was never seen by the float hook. It overflows to inf in the
# browser's JSON.parse exactly like 1e999 does, so it is refused the same way.
_INT_400 = "1" + "0" * 400
_INT_5000 = "1" + "0" * 4999   # beyond sys.get_int_max_str_digits() (4300)


@pytest.mark.parametrize("literal", [_INT_400, "-" + _INT_400], ids=["int400", "neg-int400"])
def test_overflowing_integer_literal_in_untyped_dict_is_refused(client, calls, literal):
    resp = client.post(
        "/api/portfolio",
        content=_portfolio_body('{"t1": [{"price": ' + literal + ', "pct": 50}]}'),
        headers={"content-type": "application/json"},
    )
    _assert_finite_422(resp, literal)
    assert calls == []


def test_integer_literal_beyond_int_str_digit_limit_is_refused_as_non_finite(client, calls):
    """A 5000-digit integer exceeds Python's int-string conversion limit, so a
    plain json.loads raises ValueError on it. It must still be the guard's
    finite_number 422 -- not FastAPI's json_invalid, not a 500."""
    resp = client.post(
        "/api/portfolio",
        content=_portfolio_body('{"t1": ' + _INT_5000 + "}"),
        headers={"content-type": "application/json"},
    )
    _assert_finite_422(resp, _INT_5000)
    assert calls == []


@pytest.mark.parametrize("literal", ["1" + "0" * 300, "-" + "1" + "0" * 300, "12345", "0", "-7"])
def test_large_but_finite_integer_passes_byte_identical(client, literal):
    body = ('{"a": ' + literal + ', "b": [' + literal + "]}").encode()
    resp = client.post("/__t1_echo", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.content == body
