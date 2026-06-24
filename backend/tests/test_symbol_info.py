import pytest
from fastapi.testclient import TestClient
from app.main import app

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
