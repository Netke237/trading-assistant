"""Tests for GET /api/scan/last — exposes the already-persisted last scan over HTTP."""

from __future__ import annotations

import app.routers.scan as scan_module


def test_get_last_scan_returns_none_when_no_scan_yet(client, monkeypatch):
    monkeypatch.setattr(scan_module, "_last_result", None)
    r = client.get("/api/scan/last")
    assert r.status_code == 200
    assert r.json() is None


def test_get_last_scan_returns_the_last_result(client, monkeypatch):
    from app.schemas import ScanResult
    fake = ScanResult(scan_id="SCAN-1", timestamp="2026-07-24T10:00:00", candidates=[], rejected=[])
    monkeypatch.setattr(scan_module, "_last_result", fake)
    r = client.get("/api/scan/last")
    assert r.status_code == 200
    assert r.json()["scan_id"] == "SCAN-1"
