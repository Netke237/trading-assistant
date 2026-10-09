"""Pure verified-seam checks and event-loop-local serialization of history writers."""
import asyncio
import hashlib
import json
import math
from datetime import timezone
from weakref import WeakKeyDictionary, WeakValueDictionary

_locks = WeakKeyDictionary()


def history_lock(symbol: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _locks.setdefault(loop, WeakValueDictionary())
    lock = locks.get(symbol)
    if lock is None:
        lock = asyncio.Lock()
        locks[symbol] = lock
    return lock


def seam_signature(left, right) -> str:
    def values(row):
        fetched = row[6]
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return [row[0].isoformat(), float(row[1]), float(row[2]), row[5],
                fetched.astimezone(timezone.utc).isoformat()]
    return hashlib.sha256(json.dumps([values(left), values(right)], separators=(",", ":")).encode()).hexdigest()


def verified_boundary(rows, seam: dict | None) -> int | None:
    """Return the right-hand row index of the exact recorded source boundary."""
    if (not seam or not seam.get("seam_date") or not seam.get("seam_signature")
            or seam.get("old_source") not in {"tiingo", "yfinance"}):
        return None
    boundary = next((i for i, row in enumerate(rows) if row[0] == seam["seam_date"]), None)
    if boundary is None or boundary == 0:
        return None
    for i, row in enumerate(rows):
        expected = seam["old_source"] if i < boundary else "alpaca"
        if row[5] != expected or row[2] is None or row[6] is None:
            return None
        factor = float(row[2])
        if not math.isfinite(factor) or factor <= 0:
            return None
    if seam_signature(rows[boundary - 1], rows[boundary]) != seam["seam_signature"]:
        return None
    return boundary
