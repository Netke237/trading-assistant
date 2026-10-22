#!/usr/bin/env python3
"""Ping Kenneth on Telegram from a Board session (docs/agents/board.md, step 8).

    python3 scripts/board_notify.py "[claude] STOCK-PRES-P1: PR #150 ready for your go <link>"

Agents act through Kenneth's own GitHub token, and GitHub never notifies a user
of his own actions — so a new PR or question on the Board is silent unless
something else tells him. This is that something.

Reads the same variables as the app's notification dispatcher
(BAMENDJOU_TELEGRAM_BOT_TOKEN, BAMENDJOU_TELEGRAM_CHAT_ID). Without them it
prints the line and exits 0; a failed send also exits 0. Telegram is a
courtesy, never a reason for an agent to stop working. The token never
appears in output. Standard library only, so it runs in any container.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

API = "https://api.telegram.org"
MAX_LEN = 4096  # Telegram's limit for one message


def _post(url: str, payload: dict, timeout: float) -> int:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return resp.status


def main(argv: list[str]) -> int:
    text = " ".join(argv).strip()
    if not text:
        print("usage: board_notify.py <message>", file=sys.stderr)
        return 2
    token = os.getenv("BAMENDJOU_TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("BAMENDJOU_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print(f"[board-notify] Telegram not configured; message: {text}")
        return 0
    payload = {"chat_id": chat, "text": text[:MAX_LEN], "disable_web_page_preview": True}
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
