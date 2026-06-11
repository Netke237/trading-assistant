"""Tests for the rewritten GET /api/data-sources — real probes, 4-state status."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.routers.data_sources import (
    _probe_tradier,
    _probe_alpaca,
    _status_for_probe,
    _PROBE_CACHE,
)


def _resp(status_code: int, json_body=None):
    request = httpx.Request("GET", "https://example.test")
    return httpx.Response(status_code, json=json_body or {}, request=request)


def test_tradier_probe_makes_real_call_not_env_check():
    # token present AND real call returns 200 → connected
    with (
        patch.dict("os.environ", {"TRADIER_API_TOKEN": "tok"}),
        patch("app.routers.data_sources.httpx.get", return_value=_resp(200, {"clock": {}})) as m,
    ):
        status, _ = _probe_tradier()
    assert status == "connected"
    assert m.called  # proves it actually called the API, not just read the env var


def test_tradier_probe_reports_down_on_401():
    with (
        patch.dict("os.environ", {"TRADIER_API_TOKEN": "bad"}),
        patch("app.routers.data_sources.httpx.get", return_value=_resp(401, {"fault": {}})),
    ):
        status, detail = _probe_tradier()
    assert status == "down"
    assert "401" in (detail or "")


def test_tradier_probe_unconfigured_without_token():
    with patch.dict("os.environ", {"TRADIER_API_TOKEN": ""}, clear=False):
        status, _ = _probe_tradier()
    assert status == "unconfigured"


def test_alpaca_probe_connected_with_keys():
    fake_creds = {"key_id": "PK", "secret_key": "SK", "base_url": "https://paper-api.alpaca.markets"}
    with (
        patch("app.routers.data_sources.credential_store.get", return_value=fake_creds),
        patch("app.routers.data_sources.httpx.get", return_value=_resp(200, {"status": "ACTIVE"})),
    ):
        status, _ = _probe_alpaca("alpaca_paper")
    assert status == "connected"


def test_status_for_probe_prefers_governor_degraded():
    # If the Governor says the circuit is open, report degraded regardless of probe.
    with patch("app.routers.data_sources.get_governor") as gov:
        gov.return_value.health.return_value = "degraded"
        status = _status_for_probe("alpaca", probe_status="connected")
    assert status == "degraded"
