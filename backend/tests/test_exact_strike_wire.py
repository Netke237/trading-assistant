"""EXACT-STRIKE ES-2.5: the strike on the wire, in /api/contracts, /api/quote/option
and on a scan card (plan docs/superpowers/plans/2026-10-09-exact-strike-plan.md
sections 2 and 3, ES-2).

ES-1 made the chain rows exact (a 22.5 row is strike 22.5, id `X|22.5|...`).
Before ES-2 the layer above still truncated:
  - `OptionContract`, `ContractDetails`, `AlternativeContract` were `strike: int`;
  - `/api/contracts` built `OptionContract(strike=int(...))` and `strikes=` took
    integers only, so a fractional star was a 422 (D6);
  - `/api/quote/option` took `strike: int`, a 422 for 22.5 (D6);
  - the scan card's id was `f"{symbol}|{int(strike)}|..."` and its
    `ContractDetails.strike=int(strike)`, so a 22.5 card sent OCC `...C00022000`,
    the 22 contract, to the broker (D3/D4); alternatives were `int(alt_strike)`.

I1 (byte identity for integer strikes) is pinned next to every fractional case:
an integer strike is `"strike":185` on the wire and `X|185|...` in every id,
exactly as before, so persisted ids and `last_result_json` keep matching.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import AfterValidator, ValidationError

import app.data.market as mkt
from app.data.option_symbol import pipe_to_occ
from app.data.strike import canonical_strike
from app.schemas import AlternativeContract, ContractDetails, OptionContract, ScanResult, SCAN_RESULT_SCHEMA_VERSION
from app.scoring.stop_cost import compute_stop_cost
from app.scoring.exit_plan import compute_final_stop
from app.scoring.stock_scorer import _atr
from app.services.config_loader import load_exit_plan_cfg

# Real-builder helpers from ES-1's chain tests; `_isolated_sources` is that
# module's autouse fixture (no IV-rank source, cold expirations cache), imported
# so it applies to the quote tests below too.
from tests.test_exact_strike_chain import _EXP, _client, _isolated_sources, _option  # noqa: F401
from tests.test_scan_stop_cost import _HORIZON, _candidates, _candles
from tests.test_scan_result_vintage import _StubDb, _blob, _card


# ── I4: the shared `Strike` wire type ────────────────────────────────────────

_MODELS = (OptionContract, ContractDetails, AlternativeContract)


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
def test_every_strike_field_is_the_canonical_strike_type(model):
    field = model.model_fields["strike"]
    assert any(isinstance(m, AfterValidator) and m.func is canonical_strike for m in field.metadata), (
        f"{model.__name__}.strike must be the shared Strike type, got {field!r}"
    )


def _details(strike):
    return ContractDetails(strike=strike, expiry="2026-12-01", right="C", mid=2.0,
                           delta=0.5, theta=-0.05, dte=60)


@pytest.mark.parametrize("raw", [185, 185.0])
def test_an_integer_strike_stays_an_int_on_the_wire(raw):
    cd = _details(raw)
    assert cd.strike == 185 and type(cd.strike) is int
    assert cd.model_dump_json().startswith('{"strike":185,"expiry"')
    assert "185.0" not in cd.model_dump_json()


@pytest.mark.parametrize("raw, expected", [(22.5, 22.5), (182.5, 182.5), (7.125, 7.125), (22.5000001, 22.5)])
def test_a_fractional_strike_is_kept_exactly(raw, expected):
    cd = _details(raw)
    assert cd.strike == expected and type(cd.strike) is float
    assert cd.model_dump_json().startswith(f'{{"strike":{expected},"expiry"')


@pytest.mark.parametrize("bad", [0, -5, -0.0004, float("nan"), float("inf")])
def test_an_invalid_strike_is_refused(bad):
    with pytest.raises(ValidationError):
        _details(bad)


def _alternative(strike) -> dict:
    return {
        "symbol": "AAPL", "strike": strike, "expiry": "2026-12-01", "right": "C",
        "dte": 60, "mid": 1.5, "delta": 0.4, "theta": -0.04, "score": 65,
        "contractConfidence": "PASS",
        "contractBreakdown": {"dteFit": 70, "delta": 70, "ivAttractiveness": 70,
                              "liquidity": 70, "spread": 70},
        "rrRatio": 1.8, "rrModel": "BS repriced (IV-derived)", "reason": "higher strike",
    }


def test_an_old_last_result_json_with_integer_strikes_still_reloads_byte_identical():
    """I4 / below-gate note (e): the integer-strike `last_result_json` every
    existing database holds validates under `Strike`, through the real
    `restore_from_db`, and re-serialises byte-identically."""
    from app.routers import scan as scan_module

    card = _card("AAPL", ivRank=None, iv=42.0, ivPercentile=None)
    card["alternatives"] = [_alternative(190)]
    blob = json.dumps(_blob(candidates=[card], schema_version=SCAN_RESULT_SCHEMA_VERSION))
    row = type("R", (), {"last_result_json": blob, "last_request_json": None,
                         "status": "complete", "updated_at": None})()

    saved = (scan_module._last_result, scan_module.AsyncSessionLocal,
             scan_module._last_status, scan_module._last_updated_at)
    scan_module._last_result = None
    scan_module.AsyncSessionLocal = lambda: _StubDb(row)
    try:
        assert asyncio.run(scan_module.restore_from_db()) == "complete"
        restored = scan_module._last_result
        assert restored is not None
        (c,) = restored.candidates
        assert c.contractDetails.strike == 185 and type(c.contractDetails.strike) is int
        assert c.alternatives[0].strike == 190 and type(c.alternatives[0].strike) is int
        once = restored.model_dump_json()
        assert '"strike":185,' in once and '"strike":190,' in once
        assert '"strike":185.0' not in once and '"strike":190.0' not in once
        assert ScanResult.model_validate_json(once).model_dump_json() == once
    finally:
        (scan_module._last_result, scan_module.AsyncSessionLocal,
         scan_module._last_status, scan_module._last_updated_at) = saved


@pytest.mark.parametrize("strike, text", [
    (185, "185"), (185.0, "185"), (22.5, "22.5"),
    (None, ""), (0, "0"), ("abc", "abc"), (float("nan"), "nan"),
])
def test_the_evidence_id_formats_the_strike_and_never_raises(strike, text):
    """`_contract_id` is a label: exact for a valid strike, the old text for an
    invalid one (never a ValueError inside scoring), "" when absent."""
    from app.scoring.contract_validator import _contract_id

    contract = {"symbol": "XYZ", "expiry": "2026-12-01", "is_call": True}
    if strike is not None:
        contract["strike"] = strike
    assert _contract_id(contract) == f"XYZ|{text}|2026-12-01|C"


# ── /api/contracts ───────────────────────────────────────────────────────────

_CE = (date.today() + timedelta(days=45)).isoformat()


def _crow(strike, *, price=0.60):
    dte = (date.fromisoformat(_CE) - date.today()).days
    text = str(strike)
    return {
        "id": f"XYZ|{text}|{_CE}|C", "symbol": "XYZ", "strike": strike, "expiry": _CE,
        "right": "C", "dte": dte, "dteTotal": dte, "price": price, "spread": 0.05,
        "delta": 0.45, "theta": -0.02, "volume": 500, "open_interest": 2000, "ivRank": 40,
    }


_FRACTIONAL_CHAIN = [_crow(22, price=0.80), _crow(22.5, price=0.60), _crow(23, price=0.45)]


def _contracts(client, chain, query, *, stock_price=22.6):
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.contracts.fetch_option_chain_async",
                                  AsyncMock(side_effect=lambda *a, **k: [dict(c) for c in chain])))
        stack.enter_context(patch("app.routers.contracts.fetch_price_async",
                                  AsyncMock(return_value=stock_price)))
        return client.get("/api/contracts?symbol=XYZ&right=C&stock_score=80&direction=Bullish" + query)


def test_contracts_rows_carry_the_exact_fractional_strike(client):
    r = _contracts(client, _FRACTIONAL_CHAIN, "")
    assert r.status_code == 200, r.text
    by_id = {c["id"]: c for c in r.json()}
    assert set(by_id) == {f"XYZ|22|{_CE}|C", f"XYZ|22.5|{_CE}|C", f"XYZ|23|{_CE}|C"}
    assert by_id[f"XYZ|22.5|{_CE}|C"]["strike"] == 22.5
    assert type(by_id[f"XYZ|22|{_CE}|C"]["strike"]) is int
    assert type(by_id[f"XYZ|23|{_CE}|C"]["strike"]) is int


def test_strikes_22_5_returns_only_the_22_5_row(client):
    r = _contracts(client, _FRACTIONAL_CHAIN, f"&expiry={_CE}&strikes=22.5")
    assert r.status_code == 200, r.text
    (row,) = r.json()
    assert (row["id"], row["strike"], row["price"]) == (f"XYZ|22.5|{_CE}|C", 22.5, 0.60)


def test_strikes_22_returns_only_the_22_row_never_the_22_5_row(client):
    r = _contracts(client, _FRACTIONAL_CHAIN, f"&expiry={_CE}&strikes=22")
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()] == [f"XYZ|22|{_CE}|C"]


def test_strikes_matches_canonical_values(client):
    """I3: `22.0` is the 22 row, `22.50` the 22.5 row."""
    r = _contracts(client, _FRACTIONAL_CHAIN, f"&expiry={_CE}&strikes=22.0,22.50")
    assert r.status_code == 200, r.text
    assert sorted(c["strike"] for c in r.json()) == [22, 22.5]


@pytest.mark.parametrize("bad", ["22.5x", "22,abc", "-22", "%2B22", "1e3", "2_2", "22.5000", "123456", "nan"])
def test_a_malformed_strike_is_a_422_with_the_plans_message(client, bad):
    r = _contracts(client, _FRACTIONAL_CHAIN, "&strikes=" + bad)
    assert r.status_code == 422, r.text
    (detail,) = r.json()["detail"]
    assert detail["loc"] == ["query", "strikes"]
    assert detail["type"] == "value_error"
    assert detail["msg"] == "Value error, strikes must be comma-separated strikes, e.g. 187 or 187.5"


def test_integer_strike_contracts_response_is_byte_identical(client):
    """I1: an integer strike serialises exactly as `int(strike)` did."""
    chain = [_crow(185, price=2.5)]
    r = _contracts(client, chain, f"&expiry={_CE}&strikes=185", stock_price=185.0)
    assert r.status_code == 200, r.text
    assert f'"id":"XYZ|185|{_CE}|C","symbol":"XYZ","strike":185,"expiry"' in r.text
    assert "185.0" not in r.text


# ── /api/quote/option ────────────────────────────────────────────────────────

_THREE = [_option(22, bid=1.20, ask=1.30), _option(22.5, bid=1.00, ask=1.10), _option(23, bid=0.80, ask=0.90)]


def _quote(client, strike_text, options=_THREE):
    """The REAL `fetch_contract_quote_async` matching against a stubbed Tradier
    chain; only the HTTP client is replaced. Returns (response, ids asked for)."""
    real = mkt.fetch_contract_quote_async
    asked: list[str] = []

    async def _through_stub(_client_unused, contract_id):
        asked.append(contract_id)
        return await real(_client(options), contract_id)

    with (
        patch("app.routers.contracts.fetch_contract_quote_async", side_effect=_through_stub),
        patch("app.data.market._yf_iv_for_chain", MagicMock(return_value={})),
    ):
        r = client.get(f"/api/quote/option?symbol=xyz&strike={strike_text}&expiry={_EXP}&right=C")
    return r, asked


def test_quote_for_22_5_is_the_22_5_rows_price(client):
    r, asked = _quote(client, "22.5")
    assert r.status_code == 200, r.text
    assert asked == [f"XYZ|22.5|{_EXP}|C"]
    assert r.json()["price"] == 1.05


@pytest.mark.parametrize("text", ["22", "22.0", "22.000"])
def test_quote_for_22_is_the_22_rows_price_with_the_integer_id(client, text):
    r, asked = _quote(client, text)
    assert r.status_code == 200, r.text
    assert asked == [f"XYZ|22|{_EXP}|C"]
    assert r.json()["price"] == 1.25


def test_quote_for_22_is_404_when_only_22_5_is_listed(client):
    r, _ = _quote(client, "22", options=[_option(22.5)])
    assert r.status_code == 404


def test_integer_strike_quote_is_byte_identical(client):
    """I1: the id the endpoint asks for is the one it always asked for."""
    r, asked = _quote(client, "185", options=[_option(185, bid=2.00, ask=2.20, iv=0.30)])
    assert r.status_code == 200, r.text
    assert asked == [f"XYZ|185|{_EXP}|C"]
    assert r.json()["price"] == 2.1


@pytest.mark.parametrize("bad", ["22.5x", "1e3", "-22", "nan", "22.5000", "123456", "%2B22", "2_2", "%20"])
def test_quote_with_a_malformed_strike_is_a_422(client, bad):
    r, asked = _quote(client, bad)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["query", "strike"]
    assert asked == []


# ── scan card ────────────────────────────────────────────────────────────────

# Just under 22.5, so the 22.5 call is out of the money and the 22 call's
# intrinsic value stays below the synthetic premium (both price a stop cost).
_SCAN_PRICE = 22.3


def _scaled_candles(close: float) -> list[dict]:
    """MSFT's real history scaled to a ~$22 stock, where 0.5-wide strikes list."""
    candles = _candles("MSFT")
    k = close / candles[-1]["close"]
    return [{**c, **{f: round(c[f] * k, 4) for f in ("open", "high", "low", "close")}} for c in candles]


def _scan_row(strike, price, *, dte=45):
    premium = round(max(0.0, price - strike) + price * 0.02, 2)
    expiry = (date.today() + timedelta(days=dte)).isoformat()
    return {
        "id": f"MSFT|{strike}|{expiry}|C", "symbol": "MSFT",
        "strike": strike, "expiry": expiry,
        "price": premium, "bid": round(premium - 0.02, 2), "ask": round(premium + 0.02, 2),
        "spread": 0.04, "delta": 0.55, "theta": -0.02, "ivRank": 50, "dte": dte,
        "right": "C", "volume": 5000, "open_interest": 8000,
    }


def _scan(client, chain, candles):
    price = candles[-1]["close"]
    cards, _, _ = _candidates(client, extra_patches=(
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)),
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles)),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)),
    ))
    return cards, price


def test_a_22_5_chain_builds_a_22_5_card_and_orders_the_22_5_contract(client):
    candles = _scaled_candles(_SCAN_PRICE)
    row = _scan_row(22.5, _SCAN_PRICE)
    (card,), price = _scan(client, [row], candles)

    assert card["contract"] == f"MSFT|22.5|{row['expiry']}|C"
    assert card["contractDetails"]["strike"] == 22.5
    # D4: the broker order symbol is the 22.5 contract, not the 22.
    assert pipe_to_occ(card["contract"]).endswith("C00022500")
    # The card's id is the scored contract's own evidence id.
    assert card["contractExplanation"]["contract_id"] == card["contract"]

    # D3: the strike-priced numbers on the card are computed from 22.5. A
    # single-leg card carries no breakeven field; its stop cost is the
    # strike-priced figure (Black-Scholes at the structural stop).
    atr = _atr(candles, 14)
    final = compute_final_stop(candles, "Bullish", price, atr, load_exit_plan_cfg()["stop"]["atr_multiplier"])
    cd = card["contractDetails"]

    def cost_at(strike):
        return compute_stop_cost(
            stop_price=round(final.price, 2), stock_price=price, strike=strike,
            dte=int(cd["dte"]), premium=float(cd["mid"]), is_call=True,
            iv_pct=None, horizon_preset=_HORIZON,
        )

    exact, truncated = cost_at(22.5), cost_at(22.0)
    assert exact is not None and truncated is not None
    assert round(exact.fraction * 100, 1) != round(truncated.fraction * 100, 1), (
        "22 and 22.5 price identically here, so this cannot tell them apart"
    )
    assert card["stopCostPct"] == pytest.approx(round(exact.fraction * 100, 1))


def test_alternatives_carry_exact_fractional_strikes(client):
    candles = _scaled_candles(_SCAN_PRICE)
    chain = [_scan_row(s, _SCAN_PRICE) for s in (22, 22.5, 23)]
    (card,), _ = _scan(client, chain, candles)

    assert card["alternativesCount"] == 2
    strikes = [card["contractDetails"]["strike"]] + [a["strike"] for a in card["alternatives"]]
    assert sorted(strikes) == [22, 22.5, 23]
    for alt in card["alternatives"]:
        want = 22.5 if alt["strike"] == 22.5 else int(alt["strike"])
        assert alt["strike"] == want and type(alt["strike"]) is type(want)
        assert alt["contractExplanation"]["contract_id"] == f"MSFT|{alt['strike']}|{alt['expiry']}|C"


def test_an_integer_strike_card_is_byte_identical(client):
    """I1: the standard MSFT fixture card (integer strike) keeps its id and an
    int `contractDetails.strike`, so persisted ids and stars keep matching."""
    cards, price = _candidates(client)[:2]
    card = cards[0]
    strike = card["contractDetails"]["strike"]
    assert type(strike) is int
    assert card["contract"] == f"MSFT|{strike}|{card['contractDetails']['expiry']}|C"
    assert pipe_to_occ(card["contract"]).endswith(f"C{strike * 1000:08d}")


def test_the_scan_never_turns_a_stock_price_into_a_strike():
    """ES-2.4: both `.get("strike", price)` fallbacks are gone."""
    import inspect
    from app.routers import scan as scan_module

    src = inspect.getsource(scan_module._process_symbol)
    assert 'contract.get("strike", price)' not in src
    assert 'alt_c.get("strike", price)' not in src
    assert "int(strike)" not in src and "int(alt_strike)" not in src
