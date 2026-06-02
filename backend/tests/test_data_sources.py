"""Tests for GET /api/data-sources."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app

client = TestClient(app)


def test_data_sources_returns_list():
    """Endpoint always returns a list of 3 source objects."""
    with (
        patch("app.routers.data_sources._probe_tradier", return_value=("ok", None)),
        patch("app.routers.data_sources._probe_ibkr",    return_value=("ok", None)),
        patch("app.routers.data_sources._probe_yfinance", return_value=("ok", None)),
    ):
        resp = client.get("/api/data-sources")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3
    ids = {d["id"] for d in data}
    assert ids == {"tradier", "ibkr", "yfinance"}


def test_data_sources_fields():
    """Each item has id, label, status, provides, detail."""
    with (
        patch("app.routers.data_sources._probe_tradier", return_value=("ok", None)),
        patch("app.routers.data_sources._probe_ibkr",    return_value=("unavailable", "Gateway unreachable")),
        patch("app.routers.data_sources._probe_yfinance", return_value=("ok", None)),
    ):
        resp = client.get("/api/data-sources")
    assert resp.status_code == 200
    ibkr = next(d for d in resp.json() if d["id"] == "ibkr")
    assert ibkr["status"] == "unavailable"
    assert ibkr["detail"] == "Gateway unreachable"
    assert isinstance(ibkr["provides"], list)
    assert len(ibkr["provides"]) > 0


def test_data_sources_never_raises_on_probe_exception():
    """If a probe throws, the endpoint still returns 200 with status=error."""
    with (
        patch("app.routers.data_sources._probe_tradier", side_effect=Exception("boom")),
        patch("app.routers.data_sources._probe_ibkr",    return_value=("ok", None)),
        patch("app.routers.data_sources._probe_yfinance", return_value=("ok", None)),
    ):
        resp = client.get("/api/data-sources")
    assert resp.status_code == 200
    tradier = next(d for d in resp.json() if d["id"] == "tradier")
    assert tradier["status"] == "error"
