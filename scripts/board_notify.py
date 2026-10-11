#!/usr/bin/env python3
"""Ping Kenneth on Telegram from a Board session (docs/agents/board.md, step 8).

    python3 scripts/board_notify.py "[claude] STOCK-PRES-P1: PR #150 ready for your go <link>"

Agents act through Kenneth's own GitHub token, and GitHub never notifies a user
of his own actions — so a new PR or question on the Board is silent unless
something else tells him. This is that something.

Every line Kenneth gets names its sender and carries a GitHub link, whatever
the caller wrote: a line without a leading [claude]/[codex] tag gets one from
the environment (Claude Code sets CLAUDECODE, Codex sets CODEX_* variables;
neither → [agent?]), and a line without a github.com link gets one to the first
#<n> it mentions (GitHub redirects an issue URL to the PR when <n> is a PR),
else to the Board. The link survives the length cut.

Reads the same variables as the app's notification dispatcher
(BAMENDJOU_TELEGRAM_BOT_TOKEN, BAMENDJOU_TELEGRAM_CHAT_ID). Without them it
prints the line and exits 0; a failed send also exits 0. Telegram is a
courtesy, never a reason for an agent to stop working. The token never
appears in output. Standard library only, so it runs in any container.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

API = "https://api.telegram.org"
MAX_LEN = 4096  # Telegram's limit for one message
REPO_URL = "https://github.com/Netke237/trading-assistant"
BOARD_ISSUE = 151  # docs/agents/board.md: the pinned Board issue

_TAG_RE = re.compile(r"^\[(claude|codex)\b", re.IGNORECASE)
_REF_RE = re.compile(r"#(\d+)\b")
_URL_RE = re.compile(r"https://github\.com/\S+")


def _sender_tag() -> str:
    if os.getenv("CLAUDECODE"):
        return "[claude]"
    if any(k.startswith("CODEX_") for k in os.environ):
        return "[codex]"
    return "[agent?]"


def normalise(text: str) -> str:
    """Tag the sender and make sure the line ends up with a GitHub link."""
    if not _TAG_RE.match(text):
        text = f"{_sender_tag()} {text}"
    url = _URL_RE.search(text)
    if url and len(text) <= MAX_LEN:
        return text
    if url and len(url.group(0)) <= 512:
        link = url.group(0)  # too long: keep the caller's own link past the cut
    else:
        ref = _REF_RE.search(text)
        link = f"{REPO_URL}/issues/{ref.group(1) if ref else BOARD_ISSUE}"
    if len(text) + 1 + len(link) <= MAX_LEN:
        return f"{text} {link}"
    return f"{text[:MAX_LEN - len(link) - 2]}… {link}"


def _post(url: str, payload: dict, timeout: float) -> int:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return resp.status


def main(argv: list[str]) -> int:
    text = " ".join(argv).strip()
    if not text or text in ("-h", "--help"):
        print("usage: board_notify.py <message>", file=sys.stderr)
        return 2
    text = normalise(text)
    token = os.getenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("BAMENDJOU_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print(f"[board-notify] Telegram not configured; message: {text}")
        return 0
    payload = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    try:
        status = _post(f"{API}/bot{token}/sendMessage", payload, timeout=10)
    except Exception as exc:  # network, DNS, HTTP error: report the kind, never the URL
        print(f"[board-notify] not sent ({type(exc).__name__}); message: {text}")
        return 0
    if status != 200:
        print(f"[board-notify] not sent (HTTP {status}); message: {text}")
        return 0
    print("[board-notify] sent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
