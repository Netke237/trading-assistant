# TG-1 — Route every Tradier call through the governor's rate limiter

Status: open (separate from NLQ; does not block NLQ merge)
Blocked by: NLQ-3 (shares the sync acquire it adds)
Why: Kenneth, 2026-10-09: "use the rate limiter for tradier, we don't want my account blocked or flagged".
Found: `governor.py` defines a `tradier` bucket (120/min) but no Tradier call uses it; market.py,
routers and data adapters call api.tradier.com directly with httpx (sync and async).
Scope: inventory every Tradier HTTP call site; route each through the bucket (async: `get_governor().call`;
sync: the thread-safe acquire from NLQ-3); 429 handling with Retry-After; measure the effect on an options
scan's duration; Kenneth decides whether the slower scan is acceptable before merge.
Needs its own short plan + audit (touches the scan's throughput).
