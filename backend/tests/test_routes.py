"""Baseline route tests — all 9 trading endpoints must return HTTP 200 with correct shape."""

import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_watchlist_length_and_shape(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 10
    first = data[0]
    assert first["symbol"] == "AAPL"
    assert first["score"] == 82
    assert first["status"] == "PASS"
    assert "breakdown" in first


def test_watchlist_last_row(client):
    r = client.get("/api/watchlist")
    last = r.json()[-1]
    assert last["symbol"] == "INTC"
    assert last["status"] == "REJECT"


def test_regime_shape(client):
    r = client.get("/api/regime")
    assert r.status_code == 200
    data = r.json()
    assert data["overall"] == "PASS"
    assert len(data["metrics"]) == 8


def test_sectors_length(client):
    r = client.get("/api/sectors")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 11
    assert data[0]["key"] == "XLK"


def test_contracts_length_and_id(client):
    r = client.get("/api/contracts")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 6
    assert data[0]["id"] == "AAPL|190|2026-05-15|C"


def test_portfolio_length(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_alerts_length(client):
    r = client.get("/api/alerts")
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_events_length(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert len(r.json()) == 39


def test_tradecards_length(client):
    r = client.get("/api/tradecards")
    assert r.status_code == 200
    assert len(r.json()) == 10


def test_candles_aapl(client):
    r = client.get("/api/candles/AAPL")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 120
    first = data[0]
    assert set(first.keys()) == {"time", "open", "high", "low", "close", "volume"}


def test_candles_unknown_symbol(client):
    r = client.get("/api/candles/XXXXINVALID")
    assert r.status_code == 200
    assert len(r.json()) == 120
