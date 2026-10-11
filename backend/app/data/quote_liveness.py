"""Is an option chain row's quote live? (NO-LIVE-QUOTE, plan 3a.)

Pure: standard library only, no app imports, no clock reads. The caller passes
`now_s`, the session flag, the feed lag and the age limit, so one chain fetch
classifies every row against the same instant (market.py takes them once per
fetch).

WHY THIS SHAPE, from the Step 0 measurements (plan section 1, five raw Tradier
samples committed under backend/scripts/out/tradier_chain_raw/):
  - Off-hours rows are NOT zeroed. They carry the last close's quotes,
    two-sided and non-zero, so `bid > 0 and ask > 0` cannot tell stale from
    live.
  - Tradier re-stamps every bid_date/ask_date to 08:00 ET without new prices,
    so a pre-market quote reads young; the closing quotes are young from
    16:00 to 16:15 too. Only a wall-clock session test separates those
    windows, so it comes before any age rule.
  - In session one side of a quiet far-OTM strike can sit still for a long
    time while the other moves. The FRESHER side is the one judged: judging
    the older side false-rejected 24 of 741 live rows.
  - The host clock ran about 5 s behind Tradier, so a negative age is live,
    not an error.
Bid/ask sizes are not read: with the session test in place they add no window.
"""
from __future__ import annotations

import math
from typing import Any, Literal

QuoteState = Literal["live", "one_sided", "session_closed", "stale"]


def _stamp_s(value: Any) -> float | None:
    """A Tradier `bid_date`/`ask_date` (epoch MILLISECONDS) in seconds, or
    None when it is missing, non-numeric, non-finite or <= 0 (absent)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value <= 0:
            return None
    except OverflowError:  # an int too large for a float
        return None
    return value / 1000.0


def classify_quote(
    bid: float,
    ask: float,
    bid_date_ms: Any,
    ask_date_ms: Any,
    *,
    now_s: float,
    session_open: bool,
    feed_lag_s: float,
    max_age_s: float,
) -> tuple[QuoteState, float | None]:
    """(state, age_s) for one chain row.

    Rules, first match wins:
      1. bid <= 0                -> one_sided (a row with ask <= 0 is dropped by
                                    the chain builders and never gets here)
      2. not session_open        -> session_closed
      3. no usable stamp at all  -> stale
      4. age_s > max_age_s       -> stale
      5. otherwise               -> live

    `age_s` is the FRESHER side's age, `now_s - max(stamps)/1000 - feed_lag_s`,
    or None when neither stamp is usable. It is returned with every state
    (a one-sided or after-close row still says how old its quote is); only
    rules 3-4 read it. `feed_lag_s` is the feed's own delay (900 on the Tradier
    sandbox), so a delayed feed's quotes are not all read as stale.
    """
    stamps = [s for s in (_stamp_s(bid_date_ms), _stamp_s(ask_date_ms)) if s is not None]
    age_s = (now_s - max(stamps) - feed_lag_s) if stamps else None

    if bid <= 0:
        return "one_sided", age_s
    if not session_open:
        return "session_closed", age_s
    if age_s is None:
        return "stale", None
    if age_s > max_age_s:
        return "stale", age_s
    return "live", age_s
