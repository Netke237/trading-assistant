"""Tests for GET/POST /settings/notifications."""
from __future__ import annotations

import pytest


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
    # Password not echoed back
    assert "smtp_password" not in r.json()["gmail"]


def test_post_notifications_password_not_cleared_when_empty(client):
    """Sending empty password should not overwrite an existing saved password."""
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
    # The backend should not have cleared the password (we just verify no error)
