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


def test_post_notifications_password_not_cleared_when_empty(client, tmp_path, monkeypatch):
    """Sending empty password should not overwrite an existing saved password."""
    # Use same tmp_path as the autouse fixture — monkeypatch already set _SETTINGS_PATH
    # First save with a password
    client.post("/settings/notifications", json={
        "gmail": {"enabled": True, "to": "a@b.com", "smtp_user": "u@b.com", "smtp_password": "secret"},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    })
    # Then save again with empty password
    r = client.post("/settings/notifications", json={
        "gmail": {"enabled": True, "to": "a@b.com", "smtp_user": "u@b.com", "smtp_password": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    })
    assert r.status_code == 200
    # Verify the YAML on disk still has the original password
    saved_path = ns_module._SETTINGS_PATH
    saved = yaml.safe_load(saved_path.read_text())
    assert saved["notifications"]["gmail"]["smtp_password"] == "secret"
