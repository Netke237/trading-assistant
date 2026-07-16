from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import app

import app.routers.symbols as symbols_module

client = TestClient(app)


def test_symbol_info_known_ticker():
    """AAPL is in KNOWN_NAMES — endpoint must return Apple's name without an HTTP call."""
    resp = client.get("/api/symbol/AAPL/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert "Apple" in data["name"]


def test_symbol_info_case_insensitive():
    """Symbol should be uppercased before lookup."""
    resp = client.get("/api/symbol/aapl/info")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AAPL"


def test_symbol_info_unknown_ticker_falls_back_to_symbol():
    """Unknown symbols must return the symbol itself as the name (never crash)."""
    resp = client.get("/api/symbol/ZZZNOTREAL/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "ZZZNOTREAL"
    assert data["name"] == "ZZZNOTREAL"


# ── yfinance fallback + negative-cache split (mocked — no real network calls) ──
# _fetch_name_yf returns (ok, name): ok=True with name=None is a DEFINITIVE
# "yfinance has no name for this ticker" and IS cached; ok=False is a
# TRANSIENT failure (network/rate-limit) and must NOT be cached, so a later
# request can retry instead of being stuck echoing the symbol forever.

def setup_function(_):
    symbols_module._NAME_CACHE.clear()


def test_ticker_outside_known_names_resolves_via_yfinance_fallback():
    """e.g. KMX — not in the curated table, but yfinance has a real name for it."""
    with patch.object(symbols_module, "_fetch_name_yf", return_value=(True, "CarMax Inc")):
        resp = client.get("/api/symbol/KMX/info")
    assert resp.status_code == 200
    assert resp.json() == {"symbol": "KMX", "name": "CarMax Inc"}


def test_resolved_yfinance_name_is_cached_across_requests():
    with patch.object(symbols_module, "_fetch_name_yf", return_value=(True, "CarMax Inc")) as mock_fetch:
        client.get("/api/symbol/KMX/info")
        client.get("/api/symbol/KMX/info")
    mock_fetch.assert_called_once()


def test_definitive_no_name_is_cached():
    with patch.object(symbols_module, "_fetch_name_yf", return_value=(True, None)) as mock_fetch:
        client.get("/api/symbol/ZZZZ/info")
        client.get("/api/symbol/ZZZZ/info")
    mock_fetch.assert_called_once()   # second call served from cache


def test_transient_yfinance_failure_is_not_cached_and_retries_next_request():
    with patch.object(symbols_module, "_fetch_name_yf", return_value=(False, None)) as mock_fetch:
        r1 = client.get("/api/symbol/KMX/info")
        r2 = client.get("/api/symbol/KMX/info")
    assert r1.json() == {"symbol": "KMX", "name": "KMX"}
    assert r2.json() == {"symbol": "KMX", "name": "KMX"}
    assert mock_fetch.call_count == 2   # not cached — retried both times
