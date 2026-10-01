"""GET /api/contracts `expiry` and `strikes` (WATCHLIST-SCAN-CONTRACT-RULES).

The Watchlist asks for a starred contract's own expiry and strikes. Before
this, it made one default call per (symbol, right) and matched stars against
the result: `limit` 10, `max_price` 50 and the moving first->=21-day expiry
made stars silently vanish. Both parameters absent = unchanged behaviour.
"""

import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest

from tests.test_step6_contract_rules import _LOOSE

_E = (date.today() + timedelta(days=45)).isoformat()
_OTHER = (date.today() + timedelta(days=52)).isoformat()


def _row(strike, expiry=_E, *, price=2.50, spread=0.10, iv=True, volume=47, oi=162):
    dte = (date.fromisoformat(expiry) - date.today()).days
    row = {
        "id": f"XOM|{strike}|{expiry}|C", "symbol": "XOM", "strike": strike, "expiry": expiry,
        "right": "C", "dte": dte, "dteTotal": dte, "price": price, "spread": spread,
        "delta": 0.45, "theta": -0.05, "volume": volume, "open_interest": oi,
    }
    if iv:
        row["ivRank"] = 40
    return row


def _patches(chain, price=185.0):
    """Returns (stack, chain_mock): every case stubs the price, so the existing
    no-price 503 can never stand in for the new empty-chain one."""
    stack = ExitStack()
    chain_mock = AsyncMock(side_effect=lambda *a, **k: [dict(c) for c in chain])
    stack.enter_context(patch("app.routers.contracts.fetch_option_chain_async", chain_mock))
    stack.enter_context(patch("app.routers.contracts.fetch_price_async", AsyncMock(return_value=price)))
    return stack, chain_mock


def _get(client, chain, query):
    stack, chain_mock = _patches(chain)
    with stack:
        r = client.get("/api/contracts?symbol=XOM&right=C&stock_score=80&direction=Bullish" + query)
    return r, chain_mock


def _rules_q(rules=_LOOSE):
    return "&contract_rules=" + quote(json.dumps(rules))


# ── 6b: expiry is forwarded and filters ───────────────────────────────────────

def test_expiry_reaches_the_chain_fetch_and_filters_other_expiries(client):
    chain = [_row(185), _row(190, _OTHER)]
    r, m = _get(client, chain, f"&expiry={_E}")
    assert r.status_code == 200
    assert m.call_args.kwargs["expiry"] == _E
    assert [c["expiry"] for c in r.json()] == [_E]


def test_absent_expiry_leaves_the_call_unchanged(client):
    chain = [_row(185), _row(190, _OTHER)]
    r, m = _get(client, chain, "")
    assert r.status_code == 200
    assert "expiry" not in m.call_args.kwargs
    assert {c["expiry"] for c in r.json()} == {_E, _OTHER}


def test_empty_expiry_is_absent(client):
    chain = [_row(185)]
    r_empty, m = _get(client, chain, "&expiry=")
    r_none, _ = _get(client, chain, "")
    assert "expiry" not in m.call_args.kwargs
    assert r_empty.json() == r_none.json()


# ── 6c: parity with the call without expiry/strikes ───────────────────────────

def _by_id(rows):
    return {c["id"]: (c["score"], c["contractConfidence"], c["iv"]) for c in rows}


def test_expiry_and_strikes_grade_exactly_as_the_plain_call(client):
    chain = [_row(k) for k in (175, 180, 185, 190, 195)]
    q = _rules_q() + "&hold_min_days=20&hold_max_days=25"
    plain, _ = _get(client, chain, q)
    pinned, _ = _get(client, chain, q + f"&expiry={_E}&strikes=175,180,185,190,195")
    assert plain.status_code == pinned.status_code == 200
    assert len(plain.json()) == 5
    assert _by_id(pinned.json()) == _by_id(plain.json())


def test_strike_filter_runs_after_the_atm_iv_fill(client):
    """No vendor IV: the ATM Black-Scholes inversion fills every strike. A
    filter before it would leave a non-ATM star with iv None and a neutral
    IV sub-score."""
    chain = [_row(k, iv=False) for k in (175, 180, 185, 190, 195)]
    q = _rules_q() + "&hold_min_days=20&hold_max_days=25"
    plain, _ = _get(client, chain, q)
    pinned, _ = _get(client, chain, q + f"&expiry={_E}&strikes=195")
    want = next(c for c in plain.json() if c["strike"] == 195)
    (got,) = pinned.json()
    assert want["iv"] is not None
    assert (got["iv"], got["score"]) == (want["iv"], want["score"])


# ── 6d: strikes disables limit and max_price ──────────────────────────────────

def _wide_chain():
    """150 strikes that all score the same; those priced above max_price keep
    spread/mid constant by scaling the spread with the price."""
    rows = []
    for i in range(150):
        price = 2.50 if i < 120 else 60.0
        rows.append(_row(100 + i, price=price, spread=0.04 * price))
    return rows


def test_a_starred_strike_last_in_order_and_above_max_price_is_returned(client):
    chain = _wide_chain()
    assert len({(_get(client, chain, "")[0].json()[0]["score"])}) == 1
    r, _ = _get(client, chain, f"&expiry={_E}&strikes=249")
    assert r.status_code == 200
    assert [c["strike"] for c in r.json()] == [249]


def test_twelve_tied_strikes_are_all_returned(client):
    chain = _wide_chain()
    scores = {c["score"] for c in _get(client, chain, "&limit=100&max_price=500")[0].json()}
    assert len(scores) == 1  # all tied, so a leftover [:limit] would cut in strike order
    last12 = list(range(238, 250))
    r, _ = _get(client, chain, f"&expiry={_E}&strikes=" + ",".join(map(str, last12)))
    assert sorted(c["strike"] for c in r.json()) == last12


def test_a_non_int_strike_is_a_422(client):
    r, _ = _get(client, [_row(185)], "&strikes=185,abc")
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["query", "strikes"]


@pytest.mark.parametrize("q", ["&strikes=", "&strikes=,", "&strikes=%20"])
def test_an_empty_strike_list_is_absent(client, q):
    chain = [_row(185), _row(190)]
    assert _get(client, chain, q)[0].json() == _get(client, chain, "")[0].json()


@pytest.mark.parametrize("raw", ["187,", "187,%20190"])
def test_strike_lists_tolerate_spaces_and_trailing_commas(client, raw):
    chain = [_row(187), _row(190), _row(195)]
    r, _ = _get(client, chain, "&strikes=" + raw)
    assert r.status_code == 200
    want = {187} if raw == "187," else {187, 190}
    assert {c["strike"] for c in r.json()} == want


# ── 6f: a star's DTE decays into its hold-days floor ──────────────────────────

@pytest.mark.parametrize("dte,rejected", [(79, True), (95, False)])
def test_hold_days_set_the_floor_a_star_decays_into(client, monkeypatch, dte, rejected):
    monkeypatch.setattr("app.routers.contracts.dte_holding_multiplier", lambda: 2.0)
    e = (date.today() + timedelta(days=dte)).isoformat()
    chain = [_row(185, e, volume=5000, oi=10000)]
    r, _ = _get(client, chain, f"&expiry={e}&hold_min_days=45&hold_max_days=60&strikes=185")
    assert r.status_code == 200
    (row,) = r.json()
    assert row["breakdown"]["dteDetail"]["preferred_min"] == 80
    assert (row["contractConfidence"] == "REJECT") is rejected, row


# ── 6g: empty chains and the fetch's expiry choice ────────────────────────────

def test_expiry_with_an_empty_chain_is_a_503(client):
    r, _ = _get(client, [], f"&expiry={_E}")
    assert r.status_code == 503
    assert r.json()["detail"].startswith("Option chain unavailable")


def test_expiry_with_a_chain_of_another_expiry_is_an_empty_200(client):
    """An unlisted expiry falls back to the default chain: not the star's rows."""
    r, _ = _get(client, [_row(185, _OTHER)], f"&expiry={_E}")
    assert r.status_code == 200
    assert r.json() == []


def test_expiry_ignores_the_hold_window_for_the_fetch_but_not_for_grading(client, monkeypatch):
    monkeypatch.setattr("app.routers.contracts.dte_holding_multiplier", lambda: 2.0)
    e = (date.today() + timedelta(days=95)).isoformat()
    r, m = _get(client, [_row(185, e)], f"&expiry={e}&hold_min_days=45&hold_max_days=60")
    assert r.status_code == 200
    assert m.call_args.kwargs["dte_bounds"] is None
    assert m.call_args.kwargs.get("min_dte_floor") is None
    assert r.json()[0]["breakdown"]["dteDetail"]["preferred_min"] == 80


def test_without_expiry_an_empty_chain_is_still_an_empty_200(client):
    r, _ = _get(client, [], "")
    assert r.status_code == 200
    assert r.json() == []
