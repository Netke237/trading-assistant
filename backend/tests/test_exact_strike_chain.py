"""EXACT-STRIKE ES-1.4: chain rows and quote matching keep fractional strikes.

Before ES-1 both chain builders wrote `int(strike)` into the row id and the
`strike` field, so a 22.5 row shared id `XYZ|22|...` with the 22 row and the
dedup dropped one of them (D1), its yfinance IV backfill read the 22.0 key
(D2), and `fetch_contract_quote_async` matched `int(float(strike_str))` (D5).

Run through the REAL builders and the REAL quote helper; only Tradier (the
HTTP client), the IBKR/tastytrade IV-rank sources and yfinance are stubbed.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.data.market as mkt

_EXP = (date.today() + timedelta(days=30)).isoformat()


def _option(strike, *, ask=1.10, bid=1.00, iv=0.30):
    row = {
        "option_type": "call",
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "volume": 100,
        "open_interest": 500,
        "greeks": {"delta": 0.5, "theta": -0.02},
    }
    if iv is not None:
        row["implied_volatility"] = iv
    return row


def _responses(options):
    exp_resp = MagicMock()
    exp_resp.status_code = 200
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_EXP]}}
    chain_resp = MagicMock()
    chain_resp.status_code = 200
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": [dict(o) for o in options]}}
    return exp_resp, chain_resp


def _client(options):
    exp_resp, chain_resp = _responses(options)

    async def _get(url, *args, **kwargs):
        return exp_resp if "expirations" in url else chain_resp

    client = AsyncMock()
    client.get = AsyncMock(side_effect=_get)
    return client


@pytest.fixture(autouse=True)
def _isolated_sources():
    """No IV-rank source, a cold expirations cache, restored afterwards."""
    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    with (
        patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
        patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
    ):
        yield
    mkt._expirations_cache.clear()
    mkt._expirations_cache.update(saved)


def _async_chain(options, **patches):
    import asyncio

    with patch("app.data.market._yf_iv_for_chain", patches.get("yf", MagicMock(return_value={}))):
        return asyncio.run(mkt.fetch_option_chain_async(_client(options), "XYZ", expiry=_EXP))


def _sync_chain(options, yf=None):
    exp_resp, chain_resp = _responses(options)

    def _get(url, *args, **kwargs):
        return exp_resp if "expirations" in url else chain_resp

    with (
        patch("app.data.market.httpx.get", side_effect=_get),
        patch("app.data.market._yf_iv_for_chain", yf or MagicMock(return_value={})),
    ):
        return mkt.fetch_option_chain("XYZ", expiry=_EXP)


def _quote(contract_id, options):
    import asyncio

    with patch("app.data.market._yf_iv_for_chain", MagicMock(return_value={})):
        return asyncio.run(mkt.fetch_contract_quote_async(_client(options), contract_id))


# ── chain rows (both builders) ───────────────────────────────────────────────

_BUILDERS = {"async": _async_chain, "sync": _sync_chain}


@pytest.mark.parametrize("builder", _BUILDERS)
def test_22_and_22_5_and_23_are_three_rows_with_exact_ids_and_strikes(builder):
    rows = _BUILDERS[builder]([_option(22, ask=1.30), _option(22.5, ask=1.10), _option(23, ask=0.90)])

    assert [r["id"] for r in rows] == [f"XYZ|22|{_EXP}|C", f"XYZ|22.5|{_EXP}|C", f"XYZ|23|{_EXP}|C"]
    assert [r["strike"] for r in rows] == [22, 22.5, 23]
    assert [type(r["strike"]) for r in rows] == [int, float, int]
    # I1: the integer rows serialise exactly as the old int(strike) did.
    assert [json.dumps(r["strike"]) for r in rows] == ["22", "22.5", "23"]


@pytest.mark.parametrize("builder", _BUILDERS)
def test_a_float_integral_strike_from_tradier_keeps_the_integer_id(builder):
    (row,) = _BUILDERS[builder]([_option(185.0)])
    assert row["id"] == f"XYZ|185|{_EXP}|C"
    assert row["strike"] == 185 and type(row["strike"]) is int


@pytest.mark.parametrize("builder", _BUILDERS)
@pytest.mark.parametrize("bad", [None, 0, -5, "nan", "inf", "abc", True])
def test_a_row_without_a_valid_strike_is_dropped_not_written_as_strike_0(builder, bad):
    opt = _option(22)
    bad_opt = _option(bad)
    if bad is None:
        del bad_opt["strike"]
    rows = _BUILDERS[builder]([bad_opt, opt])
    assert [r["id"] for r in rows] == [f"XYZ|22|{_EXP}|C"]


@pytest.mark.parametrize("builder", _BUILDERS)
def test_yfinance_backfill_reads_the_exact_fractional_key(builder):
    yf = MagicMock(return_value={22.0: 0.20, 22.5: 0.35, 23.0: 0.40})
    options = [_option(22.5, iv=None), _option(23, iv=None)]
    if builder == "async":
        rows = _async_chain(options, yf=yf)
    else:
        rows = _sync_chain(options, yf=yf)
    by_strike = {r["strike"]: r for r in rows}
    assert set(by_strike) == {22.5, 23}
    assert by_strike[22.5]["iv"] == 35.0
    assert by_strike[22.5]["implied_volatility"] == 0.35
    assert by_strike[23]["iv"] == 40.0


# ── quote matching ───────────────────────────────────────────────────────────

_THREE = [_option(22, bid=1.20, ask=1.30), _option(22.5, bid=1.00, ask=1.10), _option(23, bid=0.80, ask=0.90)]


def test_quote_for_22_5_is_the_22_5_rows_price():
    q = _quote(f"XYZ|22.5|{_EXP}|C", _THREE)
    assert q is not None
    assert (q["strike"], q["price"]) == (22.5, 1.05)


def test_quote_for_22_is_the_22_rows_price():
    q = _quote(f"XYZ|22|{_EXP}|C", _THREE)
    assert q is not None
    assert (q["strike"], q["price"]) == (22, 1.25)


def test_quote_for_22_is_none_when_the_chain_lists_only_22_5():
    assert _quote(f"XYZ|22|{_EXP}|C", [_option(22.5)]) is None


def test_quote_for_22_0_is_the_22_row():
    q = _quote(f"XYZ|22.0|{_EXP}|C", _THREE)
    assert q is not None
    assert (q["id"], q["price"]) == (f"XYZ|22|{_EXP}|C", 1.25)


@pytest.mark.parametrize("strike_text", ["22.5x", "1e3", "-22", "nan", "22.5000", ""])
def test_quote_for_a_malformed_strike_is_none(strike_text):
    assert _quote(f"XYZ|{strike_text}|{_EXP}|C", _THREE) is None
