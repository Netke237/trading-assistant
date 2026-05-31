"""Persistent JSONL record of email/Telegram messages actually sent, with
date-based retention. Kept SEPARATE from audit.log so retention pruning never
touches scan/approval history."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/app/services/notifications/ -> 4 parents = backend/
_SENT_LOG_PATH = Path(__file__).parent.parent.parent.parent / 'sent_messages.log'


def log_sent(channel: str, recipient: str, subject: str) -> None:
    """Append one record for a message that was actually delivered."""
    entry = {
        'ts': datetime.now(tz=timezone.utc).isoformat(),
        'channel': channel,
        'recipient': recipient,
        'subject': subject,
    }
    try:
        with open(_SENT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        logger.debug('Could not write sent-message log', exc_info=True)


def prune_sent_log(retention_days: int) -> None:
    """Drop records older than retention_days. Unparseable lines are kept."""
    if retention_days <= 0 or not _SENT_LOG_PATH.exists():
        return
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
    try:
        with open(_SENT_LOG_PATH, encoding='utf-8') as f:
            lines = f.readlines()
        kept: list[str] = []
        for line in lines:
            try:
                ts = datetime.fromisoformat(json.loads(line)['ts'])
                if ts >= cutoff:
                    kept.append(line)
            except Exception:
                kept.append(line)
        with open(_SENT_LOG_PATH, 'w', encoding='utf-8') as f:
            f.writelines(kept)
    except Exception:
        logger.debug('Could not prune sent-message log', exc_info=True)
