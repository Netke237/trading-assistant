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
    line = "[claude] P1 PR ready https://github.com/Netke237/trading-assistant/pull/150"
    assert _mod.main(line.split(" ")) == 0
    url, payload = sent[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert payload == {"chat_id": "42", "text": line, "disable_web_page_preview": True}


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


@pytest.mark.parametrize("argv", [["   "], ["--help"], ["-h"]])
def test_an_empty_message_or_help_is_a_usage_error(monkeypatch, sent, argv):
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")
    assert _mod.main(argv) == 2
    assert sent == []


def test_long_messages_are_cut_to_telegram_limit(monkeypatch, sent):
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")
    assert _mod.main(["x" * 5000]) == 0
    assert len(sent[0][1]["text"]) == _mod.MAX_LEN


# ── Every line names its sender and carries a GitHub link ───────────────────

_REPO = "https://github.com/Netke237/trading-assistant"


@pytest.fixture
def as_agent(monkeypatch):
    """Clear both agent markers; each test sets the one it needs."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("CODEX_")]:
        monkeypatch.delenv(key)
    return monkeypatch


def test_an_untagged_line_from_claude_gets_the_claude_tag_and_its_item_link(as_agent):
    as_agent.setenv("CLAUDECODE", "1")
    # The 2026-10-11 #169 line that reached Kenneth with neither tag nor link.
    assert _mod.normalise("Board #169 TRADIER-GOVERNOR: plan stage hit its cap") == (
        f"[claude] Board #169 TRADIER-GOVERNOR: plan stage hit its cap {_REPO}/issues/169")


def test_an_untagged_line_from_codex_gets_the_codex_tag(as_agent):
    as_agent.setenv("CODEX_SANDBOX", "seatbelt")
    assert _mod.normalise("#163 needs you").startswith("[codex] #163 needs you")


def test_an_unknown_sender_is_marked_not_guessed(as_agent):
    assert _mod.normalise("#163 needs you").startswith("[agent?] #163 needs you")


@pytest.mark.parametrize("line", [
    "[claude] #150 PR ready https://github.com/Netke237/trading-assistant/pull/224",
    "[codex · merge coordinator] #204 merged https://github.com/Netke237/trading-assistant/pull/204",
    "[Claude · board-worker] #149 waiting-merge https://github.com/Netke237/trading-assistant/pull/186",
])
def test_a_tagged_line_with_a_link_is_sent_unchanged(as_agent, line):
    as_agent.setenv("CODEX_SANDBOX", "x")  # the caller's own tag wins over the environment
    assert _mod.normalise(line) == line


def test_a_line_with_no_reference_links_to_the_board(as_agent):
    as_agent.setenv("CLAUDECODE", "1")
    assert _mod.normalise("[claude] Board: nothing ready") == (
        f"[claude] Board: nothing ready {_REPO}/issues/151")


def test_the_cut_keeps_the_generated_link(as_agent):
    as_agent.setenv("CLAUDECODE", "1")
    out = _mod.normalise("#42 " + "x" * 5000)
    assert len(out) == _mod.MAX_LEN
    assert out.endswith(f"… {_REPO}/issues/42")


def test_the_cut_keeps_the_callers_own_link(as_agent):
    link = f"{_REPO}/pull/224"
    out = _mod.normalise(f"[claude] #150 {link} " + "x" * 5000)
    assert len(out) == _mod.MAX_LEN
    assert out.endswith(f"… {link}")


def test_the_sent_text_is_the_normalised_line(as_agent, sent):
    as_agent.setenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "123:abc")
    as_agent.setenv("BAMENDJOU_TELEGRAM_CHAT_ID", "42")
    as_agent.setenv("CLAUDECODE", "1")
    assert _mod.main(["#161", "needs", "your", "decision"]) == 0
    assert sent[0][1]["text"] == f"[claude] #161 needs your decision {_REPO}/issues/161"
