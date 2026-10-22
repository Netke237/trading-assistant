"""scripts/board_notify.py — the Board's Telegram ping (docs/agents/board.md step 8).

Loaded via importlib like test_claim_script.py. No test touches the network:
the HTTP call is replaced by a recorder.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "board_notify.py"
_spec = importlib.util.spec_from_file_location("board_notify", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url: str, payload: dict, timeout: float) -> int:
        calls.append((url, payload))
        return 200

    monkeypatch.setattr(_mod, "_post", fake_post)
    return calls


def test_without_credentials_it_prints_and_succeeds(monkeypatch, sent, capsys):
    monkeypatch.delenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BAMENDJOU_TELEGRAM_CHAT_ID", raising=False)
    assert _mod.main(["[claude] P1 PR ready"]) == 0
    assert sent == []
    assert "not configured" in capsys.readouterr().out


def test_with_credentials_it_sends_the_line_to_the_chat(monkeypatch, sent):
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")
    assert _mod.main(["[claude]", "P1", "PR", "ready"]) == 0
    url, payload = sent[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert payload == {"chat_id": "42", "text": "[claude] P1 PR ready",
                       "disable_web_page_preview": True}


def test_a_failed_send_never_fails_the_caller_and_never_prints_the_token(monkeypatch, capsys):
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:secret-token")
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")

    def boom(url, payload, timeout):
        raise OSError(f"connection refused to {url}")

    monkeypatch.setattr(_mod, "_post", boom)
    assert _mod.main(["hello"]) == 0
    out = capsys.readouterr()
    assert "secret-token" not in out.out + out.err
    assert "not sent" in out.out


def test_an_empty_message_is_a_usage_error(monkeypatch, sent):
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")
    assert _mod.main(["   "]) == 2
    assert sent == []


def test_long_messages_are_cut_to_telegram_limit(monkeypatch, sent):
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")
    assert _mod.main(["x" * 5000]) == 0
    assert len(sent[0][1]["text"]) == _mod.MAX_LEN
