"""Tests for GET/POST /settings/notifications."""
from __future__ import annotations

import yaml
import pytest
import app.routers.notification_settings as ns_module


@pytest.fixture(autouse=True)
def _isolated_yaml(monkeypatch, tmp_path):
    """Redirect settings.yaml writes to a temp dir so tests don't mutate the real file."""
    monkeypatch.setattr(ns_module, '_SETTINGS_PATH', tmp_path / 'settings.yaml')


def test_get_notifications_returns_structure(client):
    r = client.get("/settings/notifications")
    assert r.status_code == 200
    data = r.json()
    assert "gmail" in data
    assert "telegram" in data
    assert "enabled" in data["gmail"]
    assert "to" in data["gmail"]
    assert "smtp_user" in data["gmail"]
    assert "smtp_password" not in data["gmail"]  # password must be masked


def test_post_notifications_saves_enabled_flag(client):
    payload = {
        "gmail": {"enabled": True, "to": "test@example.com", "smtp_user": "test@gmail.com", "smtp_password": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    }
    r = client.post("/settings/notifications", json=payload)
    assert r.status_code == 200
    assert r.json()["gmail"]["enabled"] is True
    assert r.json()["gmail"]["to"] == "test@example.com"
    assert "smtp_password" not in r.json()["gmail"]


def test_post_notifications_password_never_written_to_yaml(client):
    """smtp_password is never persisted to yaml regardless of what the client sends."""
    # Post with a non-empty password — it should be silently ignored
    r = client.post("/settings/notifications", json={
        "gmail": {"enabled": True, "to": "a@b.com", "smtp_user": "u@b.com", "smtp_password": "secret"},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    })
    assert r.status_code == 200
    # Verify the YAML on disk has NO smtp_password key at all
    saved_path = ns_module._SETTINGS_PATH
    saved = yaml.safe_load(saved_path.read_text())
    assert "smtp_password" not in saved.get("notifications", {}).get("gmail", {})


def test_alert_delivery_roundtrips_retention_days(client):
    """POST /settings/alert-delivery echoes retentionDays and GET returns the same value."""
    resp = client.post('/settings/alert-delivery', json={
        'masterEnabled': True,
        'enabledTypes': ['STOP_REACHED'],
        'dedupWindowMinutes': 15,
        'reminderIntervalHours': 4,
        'retentionDays': 45,
    })
    assert resp.status_code == 200
    assert resp.json()['retentionDays'] == 45

    get_resp = client.get('/settings/alert-delivery')
    assert get_resp.status_code == 200
    assert get_resp.json()['retentionDays'] == 45
