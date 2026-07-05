# backend/tests/test_portfolio_alert_monitor.py
from __future__ import annotations

import app.services.portfolio_alert_monitor as monitor


def test_check_interval_seconds_uses_configured_value(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 90})
    assert monitor._check_interval_seconds() == 90


def test_check_interval_seconds_falls_back_to_default_when_missing(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {})
    assert monitor._check_interval_seconds() == monitor._DEFAULT_CHECK_INTERVAL


def test_check_interval_seconds_enforces_floor_of_15(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 1})
    assert monitor._check_interval_seconds() == 15


def test_check_interval_seconds_handles_garbage_value(monkeypatch):
    monkeypatch.setattr(monitor, '_load_delivery_config', lambda: {'checkIntervalSeconds': 'oops'})
    assert monitor._check_interval_seconds() == monitor._DEFAULT_CHECK_INTERVAL
