"""Step 6 grades contracts with the rules the scan graded them with.

A scan records the contract-rule overrides it applied (ScanResult.contract_rules)
and Step 6 sends them back to /api/contracts. Before this, /api/contracts always
graded on contract_rules.yaml: a Loose-profile scan (vol >= 20, OI >= 75,
spread <= 30%) picked a contract with vol 47 / OI 162 for its trade card, and
Step 6 listed that same contract as REJECT, score 0 (YAML floor: vol 50, OI 200).
"""

import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest

from app.scoring.contract_validator import CONTRACT_OVERRIDE_KEYS, effective_contract_overrides
from tests.test_shortlist import _MOCK_CANDLES, _pass_card

_LOOSE = {"min_volume": 20, "min_open_interest": 75, "max_bid_ask_spread_pct": 0.3}

_EXPIRY = (date.today() + timedelta(days=45)).isoformat()

# Thin but inside the Loose rules; below the YAML floor on volume AND OI.
_THIN = {
    "id": f"XOM|190|{_EXPIRY}|C", "symbol": "XOM", "strike": 190, "expiry": _EXPIRY,
    "right": "C", "dte": 45, "dteTotal": 45, "price": 2.50, "spread": 0.10,
    "delta": 0.45, "theta": -0.05, "ivRank": 40, "volume": 47, "open_interest": 162,
}


# Swapped per test via monkeypatch: both the scan and /api/contracts
# are handed a fresh copy of the same chain.
_CURRENT_CHAIN = [_THIN]


def _chain():
    return [dict(c) for c in _CURRENT_CHAIN]


# No vendor IV at all: both sides must fill it by Black-Scholes inversion.
_THIN_NO_IV = {k: v for k, v in _THIN.items() if k != "ivRank"}


def _scan_patches():
    """The scan's fetchers and stock scorer, but the REAL contract validator.

    The batch pre-fetches are pinned too. `historical_store.get_bars` falls back
    to live providers (Alpaca, Tiingo, yfinance) on an empty test DB, and the
    scan then prices the symbol off the REAL last close instead of the patched
    185 -- which the no-IV cases feed into the Black-Scholes fill, so on a
    networked CI runner the scan and /api/contracts saw different stock prices."""
    stack = ExitStack()
    stack.enter_context(patch("app.services.historical_store.get_bars",      AsyncMock(return_value=[])))
    stack.enter_context(patch("app.routers.scan.fetch_quotes",               return_value={}))
    stack.enter_context(patch("app.routers.scan.fetch_price_async",          AsyncMock(return_value=185.0)))
    stack.enter_context(patch("app.routers.scan.fetch_candles_async",        AsyncMock(return_value=_MOCK_CANDLES)))
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async",   AsyncMock(side_effect=lambda *a, **k: _chain())))
    stack.enter_context(patch("app.routers.scan.fetch_company_name_async",   AsyncMock(return_value=None)))
    stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)))
    stack.enter_context(patch("app.routers.scan.score_stock",                side_effect=_pass_card))
    return stack


def _contracts_patches():
    stack = ExitStack()
    stack.enter_context(patch("app.routers.contracts.fetch_option_chain_async", AsyncMock(side_effect=lambda *a, **k: _chain())))
    stack.enter_context(patch("app.routers.contracts.fetch_price_async",        AsyncMock(return_value=185.0)))
    return stack


def _get_contracts(client, stock_score, rules=None):
    url = f"/api/contracts?symbol=XOM&right=C&stock_score={stock_score}&direction=Bullish"
    if rules is not None:
        url += "&contract_rules=" + quote(json.dumps(rules))
    with _contracts_patches():
        return client.get(url)


# ── The recorded rules ────────────────────────────────────────────────────────

def test_effective_overrides_keep_only_contract_keys_cast_as_the_validator_casts():
    got = effective_contract_overrides({
        "min_volume": 20.9, "max_bid_ask_spread_pct": "0.3", "preferred_oi_min": 0.5,
        "event_reject_days": 7, "rr_bullish_target_pct": 0.1,
    })
    assert got == {"min_volume": 20, "max_bid_ask_spread_pct": 0.3, "preferred_oi_min": 1}
    assert effective_contract_overrides(None) == {}


def test_every_override_key_replaces_a_real_config_entry():
    """A key whose target does not exist in contract_rules.yaml would be
    recorded, sent back and applied to nothing the scorer reads."""
    import app.scoring.contract_validator as cv
    base = cv._load_config()
    for key in CONTRACT_OVERRIDE_KEYS:
        section = cv._CONTRACT_OVERRIDES[key][0]
        assert key in base[section], key


def test_scan_records_the_contract_rules_it_applied(client):
    with _scan_patches():
        r = client.post("/api/scan", json={
            "universe": ["XOM"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {**_LOOSE, "event_reject_days": 7},
        })
    assert r.status_code == 200
    assert r.json()["contract_rules"] == _LOOSE


def test_a_non_finite_rule_is_not_recorded(client):
    """float() takes "inf"; it would serialise as null and /api/contracts would
    refuse it, so the scan records no rules and Step 6 says so."""
    with _scan_patches():
        r = client.post("/api/scan", json={
            "universe": ["XOM"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {**_LOOSE, "max_iv_abs": "inf"},
        })
    assert r.status_code == 200
    assert r.json()["contract_rules"] is None


def test_scan_without_contract_overrides_records_an_empty_rule_set(client):
    with _scan_patches():
        r = client.post("/api/scan", json={
            "universe": ["XOM"], "direction": "Bullish", "horizon": "Swing",
        })
    assert r.status_code == 200
    assert r.json()["contract_rules"] == {}


# ── Scan and Step 6 agree ─────────────────────────────────────────────────────

@pytest.mark.parametrize("contract", [_THIN, _THIN_NO_IV], ids=["vendor-iv", "no-iv"])
@pytest.mark.parametrize("hold", [None, (20, 25)], ids=["no-hold-days", "hold-days"])
def test_step6_grades_the_scans_contract_as_the_trade_card_does(client, monkeypatch, contract, hold):
    """Same contract, same score and status, on the path Step 6 actually takes:
    the UI always sends hold days, so the DTE widening is applied on top of
    the recorded rules on both sides."""
    monkeypatch.setitem(globals(), "_CURRENT_CHAIN", [contract])  # restored after the test
    hold_body = {"hold_min_days": hold[0], "hold_max_days": hold[1]} if hold else {}
    with _scan_patches():
        scan = client.post("/api/scan", json={
            "universe": ["XOM"], "direction": "Bullish", "horizon": "Swing",
            "overrides": _LOOSE, **hold_body,
        }).json()
    assert scan["candidates"], scan["rejected"]  # else nothing below is exercised
    card = scan["candidates"][0]

    url = (f"/api/contracts?symbol=XOM&right=C&stock_score={card['stockScore']}&direction=Bullish"
           f"&contract_rules={quote(json.dumps(scan['contract_rules']))}")
    if hold:
        url += f"&hold_min_days={hold[0]}&hold_max_days={hold[1]}"
    with _contracts_patches():
        r = client.get(url)
    assert r.status_code == 200
    row = next(c for c in r.json() if c["strike"] == contract["strike"])
    assert row["score"] == card["contractScore"]
    assert row["contractConfidence"] == card["contractConfidence"]
    assert row["contractConfidence"] != "REJECT"


def test_without_the_rules_step6_still_grades_on_the_yaml(client):
    """Unchanged for every caller that sends none (Watchlist, older results)."""
    r = _get_contracts(client, 80)
    assert r.status_code == 200
    assert r.json()[0]["score"] == 0
    assert r.json()[0]["contractConfidence"] == "REJECT"


def test_an_empty_rule_set_is_the_yaml(client):
    # A regression guard, not evidence for the fix: it passed before it too.
    assert _get_contracts(client, 80, {}).json() == _get_contracts(client, 80).json()


def test_recorded_rules_are_widened_for_hold_days_as_the_scan_widens_them(client):
    """A recorded min_dte is replaced by the hold-days window on both sides."""
    url = ("/api/contracts?symbol=XOM&right=C&stock_score=80&hold_min_days=20&hold_max_days=25"
           "&contract_rules=" + quote(json.dumps({**_LOOSE, "min_dte": 200})))
    with _contracts_patches():
        r = client.get(url)
    assert r.status_code == 200
    assert r.json()[0]["contractConfidence"] != "REJECT", r.json()[0]


# ── Malformed rules are refused, not silently dropped ─────────────────────────

@pytest.mark.parametrize("raw", [
    "not json", "[1, 2]", '{"min_volume": "20"}', '{"min_volume": true}',
    '{"min_volume": NaN}', '{"max_bid_ask_spread_pct": Infinity}', '{"min_volume": null}',
    '{"min_volume": 1' + '0' * 400 + '}', '[' * 5000,
], ids=lambda raw: raw[:40])
def test_malformed_rules_are_a_422(client, raw):
    with _contracts_patches():
        r = client.get("/api/contracts?symbol=XOM&right=C&contract_rules=" + quote(raw))
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["query", "contract_rules"]


def test_unknown_keys_are_ignored_as_the_scan_ignores_them(client):
    r = _get_contracts(client, 80, {**_LOOSE, "event_reject_days": "whatever"})
    assert r.status_code == 200
    assert r.json()[0]["contractConfidence"] != "REJECT"


@pytest.mark.parametrize("rules, floor", [(None, 21), ({"min_dte": 45}, 45)])
def test_without_hold_days_the_fetch_floor_is_the_rules_min_dte(client, rules, floor):
    """Step 6's fetch, like the scan's, must not pick an expiry below the
    min_dte it then grades with, or every row comes back dte_too_short."""
    seen = []

    async def _fetch(*_a, **kw):
        seen.append((kw.get("dte_bounds"), kw.get("min_dte_floor")))
        return _chain()

    url = "/api/contracts?symbol=XOM&right=C&stock_score=80&direction=Bullish"
    if rules is not None:
        url += "&contract_rules=" + quote(json.dumps(rules))
    with _contracts_patches() as stack:
        stack.enter_context(patch("app.routers.contracts.fetch_option_chain_async", side_effect=_fetch))
        r = client.get(url)
    assert r.status_code == 200, r.text
    assert seen == [(None, floor)]
