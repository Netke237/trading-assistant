# Quote Sanity Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a single glitched Tradier quote from firing a false Critical portfolio alert (STOP_REACHED / TP_HIT) by rejecting any quote whose `last` price disagrees with its own live bid/ask before that price ever reaches the alert engine.

**Architecture:** `backend/app/data/market.py::fetch_quotes()` is the single shared quote path used by both the headless `portfolio_alert_monitor` loop and the browser-triggered `GET /api/alerts` route. Add one pure-function sanity check, `_quote_is_sane()`, called inline for every symbol before it's added to the returned dict. The check compares `last` against the live bid/ask midpoint from the *same* Tradier response (a same-snapshot consistency check, not a historical one) — a real price move updates bid/ask together with `last`, so this catches data-quality glitches without delaying genuine large moves. When bid/ask aren't available (Tradier reports 0/0 outside market hours), it falls back to a much looser comparison against `prevclose`, which only catches egregiously corrupted values. A rejected quote is simply excluded from the result dict for that tick — `generate_alerts()` already treats a missing price as "skip this position's price-based checks," so no changes are needed there. Every rejection is written to the existing `audit.log` JSONL trail via `log_event()`, same mechanism the prior logging fix (commit `fc2f0c8`) already wired up for alert fires.

**Tech Stack:** Python 3, pytest + pytest-asyncio, PyYAML (already a dependency — used by `alert_generator.py`'s `_load_risk_config()`), the existing `app.services.audit.log_event()` JSONL logger.

---

## Background — why bid/ask, not a historical threshold

The incident this fixes: a Telegram alert claimed AAPL hit a stop at $283.35 while AAPL was actually trading ~$300-301 (confirmed via Tradier's own 1-minute trade history — the real price never went near $283.35). The bad `last` was roughly 5-6% away from the real price at that moment.

A naive guard comparing `last` against **yesterday's close (`prevclose`)** doesn't work well here: ordinary intraday moves of 5-10% happen routinely (earnings, news), so a threshold tight enough to catch a 5-6% glitch would also block, or at minimum delay, real stop-outs on ordinary volatile days — which is the opposite of what a stop-loss alert system is for.

Comparing `last` against the **live bid/ask midpoint from the same quote response** avoids that trade-off. Bid/ask reflects the current market in real time — a genuine price move updates bid/ask right along with `last`, so the deviation between `last` and `mid(bid, ask)` stays small (typically well under 1%) regardless of how far the stock has moved from yesterday's close. A `last` that's 5%+ away from its own bid/ask snapshot is a same-instant internal contradiction, not just an unusual price — and that's exactly the failure mode this incident showed.

## What this does and does not fix

**Fixes:**
- A `last` that diverges from its own quote's live bid/ask by more than `max_bidask_deviation_pct` (default 5%) is excluded from `fetch_quotes()`'s result and logged as `quote_sanity_reject` in `audit.log`, so it can never drive a STOP_REACHED/TP_HIT alert.
- Applies to both the headless monitor and the browser-triggered `/api/alerts` route, since both call the same `fetch_quotes()`.

**Does not fix (explicitly out of scope for this plan):**
- **PREMIUM_STOP** — option premium prices come from a different path (`fetch_contract_quote_async` → `fetch_option_chain_async`, which computes mid from the *option contract's* own bid/ask, not the underlying stock's). Not touched here; a future plan could extend a similar check there if a premium-side false alert is ever observed.
- **Closed-market glitches** — when Tradier reports bid=ask=0 (a known, already-documented behavior in this file outside market hours — see the comment in `fetch_option_chain`), the check falls back to a loose 50%-vs-prevclose comparison that only catches egregiously corrupted values, not subtler percentage-level glitches during closed hours.
- **A bad live bid/ask itself** — if Tradier's bid/ask snapshot is *itself* wrong (not just `last`), this check can't detect it. No defense against that failure mode exists here.
- The default thresholds (5% bid/ask deviation, 50% prevclose fallback) are estimates, not derived from the exact bad tick value (the original glitch's raw quote payload was never captured — logging for that gap was closed by commit `fc2f0c8`, but it postdates this incident). Kenneth should watch `audit.log` for `quote_sanity_reject` events over the following weeks and tune `backend/config/risk_rules.yaml`'s `quote_sanity` block if it's rejecting real moves (too strict) or still letting bad data through (too loose).

---

## File Structure

- Modify: `backend/config/risk_rules.yaml` — add a `quote_sanity` config block (two tunable thresholds).
- Modify: `backend/app/data/market.py` — add a config loader, the `_quote_is_sane()` helper, and wire it into `fetch_quotes()`.
- Modify: `backend/tests/test_market_data_fixes.py` — add tests covering accept/reject/fallback behavior.

No other files change. `generate_alerts()` and `portfolio_alert_monitor.py` need no changes — they already treat a symbol missing from `current_prices` as "no price-based alert this tick" (see `backend/app/services/alert_generator.py:90` and `:113`, both guarded by `price is not None`).

---

### Task 1: Add `quote_sanity` config block

**Files:**
- Modify: `backend/config/risk_rules.yaml`

- [ ] **Step 1: Add the config block**

Open `backend/config/risk_rules.yaml`. Find the existing `reward_risk:` block (it ends right before `auto_trade:`). Insert a new `quote_sanity:` block between them:

```yaml
# Quote sanity guard for portfolio alerts (backend/app/data/market.py::fetch_quotes).
# Rejects a Tradier quote whose `last` disagrees with its own live bid/ask
# midpoint by more than max_bidask_deviation_pct — guards against a bad/stale
# tick firing a false Critical alert (see the 2026-08-01 AAPL false
# STOP_REACHED incident: last read ~$283 while bid/ask and real trades were
# ~$300-301). Falls back to the much looser max_move_pct_no_quote vs.
# prevclose when bid/ask are unavailable (Tradier reports 0/0 outside market
# hours).
quote_sanity:
  max_bidask_deviation_pct: 0.05
  max_move_pct_no_quote: 0.50
```

The full file should now read, in order: `portfolio:`, `sizing:`, `reward_risk:`, `quote_sanity:`, `auto_trade:`.

- [ ] **Step 2: Verify the YAML parses**

Run:
```bash
cd "F:\Git\GitHub\Trading assistant\backend" && python -c "import yaml; print(yaml.safe_load(open('config/risk_rules.yaml'))['quote_sanity'])"
```
Expected output: `{'max_bidask_deviation_pct': 0.05, 'max_move_pct_no_quote': 0.5}`

- [ ] **Step 3: Commit**

```bash
git add backend/config/risk_rules.yaml
git commit -m "config: add quote_sanity thresholds for the quote sanity guard"
```

---

### Task 2: Write failing tests for the quote sanity guard

**Files:**
- Modify: `backend/tests/test_market_data_fixes.py`

- [ ] **Step 1: Add the new tests**

Open `backend/tests/test_market_data_fixes.py`. Append these tests at the end of the file (after the last test, `test_fetch_option_chain_async_falls_back_to_tastytrade_when_ibkr_unavailable`):

```python
# ── Quote sanity guard (fetch_quotes) ─────────────────────────────────────────


def _quote_json(**fields) -> dict:
    """Build a Tradier /v1/markets/quotes response with one quote. Defaults
    describe a normal, sane AAPL quote; override individual fields per test."""
    quote = {
        "symbol": "AAPL",
        "last": 301.00,
        "close": 301.00,
        "prevclose": 299.50,
        "bid": 300.95,
        "ask": 301.05,
    }
    quote.update(fields)
    return {"quotes": {"quote": [quote]}}


def test_fetch_quotes_last_near_bidask_mid_is_accepted():
    """A quote whose last tracks its own live bid/ask midpoint is returned
    normally — this is the common case and must not be affected by the guard."""
    from app.data.market import fetch_quotes

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = _quote_json()

    with patch("app.data.market.httpx.get", return_value=mock_resp):
        result = fetch_quotes(["AAPL"])

    assert result == {"AAPL": {"last": 301.00, "prevclose": 299.50}}


def test_fetch_quotes_last_far_from_bidask_mid_is_rejected():
    """Reproduces the 2026-08-01 AAPL false STOP_REACHED incident: `last` reads
    ~$283 while the same quote's live bid/ask (and real trades) are ~$300-301.
    The bad quote must be excluded from fetch_quotes' result so it can never
    drive a Critical alert, and the rejection must be logged for diagnosis."""
    from app.data.market import fetch_quotes

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = _quote_json(last=283.35, close=283.35)

    with (
        patch("app.data.market.httpx.get", return_value=mock_resp),
        patch("app.data.market.log_event") as mock_log,
    ):
        result = fetch_quotes(["AAPL"])

    assert result == {}, "Implausible quote must not be usable for alert pricing"

    reject_calls = [c for c in mock_log.call_args_list if c.args[0] == "quote_sanity_reject"]
    assert len(reject_calls) == 1
    _, symbol, payload = reject_calls[0].args
    assert symbol == "AAPL"
    assert payload["check"] == "bid_ask"
    assert payload["last"] == 283.35
    assert payload["deviation_pct"] > 0.05


def test_fetch_quotes_small_bidask_deviation_is_accepted():
    """A last that's within the bid/ask deviation threshold must NOT be
    rejected — guards against an overly strict check blocking normal quotes."""
    from app.data.market import fetch_quotes

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    # mid = 300.90; last = 302.00 -> deviation = 1.65/300.90 = 0.0055 (0.55%), well under 5%
    mock_resp.json.return_value = _quote_json(last=302.00, close=302.00, bid=300.80, ask=301.00)

    with (
        patch("app.data.market.httpx.get", return_value=mock_resp),
        patch("app.data.market.log_event") as mock_log,
    ):
        result = fetch_quotes(["AAPL"])

    assert result == {"AAPL": {"last": 302.00, "prevclose": 299.50}}
    assert not any(c.args[0] == "quote_sanity_reject" for c in mock_log.call_args_list)


def test_fetch_quotes_falls_back_to_prevclose_when_bidask_unavailable():
    """Outside market hours Tradier reports bid=ask=0 (documented precedent:
    see the comment in fetch_option_chain). The guard must fall back to the
    looser prevclose comparison instead of skipping the check entirely, and
    still accept a quote that's within that looser threshold."""
    from app.data.market import fetch_quotes

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    # last vs prevclose deviation = 5.5/299.50 = 0.0184 (1.84%), well under the 50% fallback threshold
    mock_resp.json.return_value = _quote_json(last=305.00, close=305.00, bid=0, ask=0)

    with patch("app.data.market.httpx.get", return_value=mock_resp):
        result = fetch_quotes(["AAPL"])

    assert result == {"AAPL": {"last": 305.00, "prevclose": 299.50}}


def test_fetch_quotes_prevclose_fallback_rejects_egregious_garbage():
    """When bid/ask are unavailable AND last is wildly off prevclose (>50%),
    the fallback must still reject it rather than let anything through."""
    from app.data.market import fetch_quotes

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = _quote_json(last=1.00, close=1.00, bid=0, ask=0)

    with (
        patch("app.data.market.httpx.get", return_value=mock_resp),
        patch("app.data.market.log_event") as mock_log,
    ):
        result = fetch_quotes(["AAPL"])

    assert result == {}
    reject_calls = [c for c in mock_log.call_args_list if c.args[0] == "quote_sanity_reject"]
    assert len(reject_calls) == 1
    assert reject_calls[0].args[2]["check"] == "prevclose_fallback"
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:
```bash
cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_market_data_fixes.py -k "quote_sanity or bidask or prevclose_fallback" -v
```
Expected: All 5 new tests **FAIL** (the accept-case tests will currently pass by coincidence since no guard exists yet to reject anything — but `test_fetch_quotes_last_far_from_bidask_mid_is_rejected` and `test_fetch_quotes_prevclose_fallback_rejects_egregious_garbage` must fail with `assert {'AAPL': {...}} == {}`, proving the guard doesn't exist yet).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_market_data_fixes.py
git commit -m "test(market): add failing tests for the quote sanity guard"
```

---

### Task 3: Implement the quote sanity guard

**Files:**
- Modify: `backend/app/data/market.py`

- [ ] **Step 1: Add imports and the config loader**

In `backend/app/data/market.py`, find the existing imports block (lines 1-17):

```python
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")
from typing import Literal, Optional

import httpx
import pandas as pd

from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS
```

Replace it with (adding `functools.lru_cache`, `pathlib.Path`, `yaml`, and the `log_event` import already added by commit `fc2f0c8`):

```python
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")
from typing import Literal, Optional

import httpx
import pandas as pd
import yaml

from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS
from app.services.audit import log_event
```

Note: `from app.services.audit import log_event` should already be present from commit `fc2f0c8` — if it's already there, don't duplicate it; just add the `functools`, `pathlib`, and `yaml` imports.

Now find the caches section (around line 48-57, `# ── In-process caches ──`) and add the config loader right after `_headers()` (around line 74), before the `# ── Original synchronous functions` comment:

```python
def _headers() -> dict:
    token, _ = get_tradier_creds()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"


@lru_cache(maxsize=1)
def _load_quote_sanity_config() -> dict:
    try:
        with open(_RISK_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return cfg.get("quote_sanity", {})


def _quote_sanity_bidask_pct() -> float:
    return float(_load_quote_sanity_config().get("max_bidask_deviation_pct", 0.05))


def _quote_sanity_fallback_pct() -> float:
    return float(_load_quote_sanity_config().get("max_move_pct_no_quote", 0.50))


def _quote_is_sane(symbol: str, last: float, bid: float, ask: float, prevclose: float) -> bool:
    """True if *last* should be trusted for alert pricing.

    Primary check: last vs. the live bid/ask midpoint from the same quote
    snapshot — a real price move updates bid/ask right along with last, so
    this catches a same-instant data-quality glitch without penalizing
    genuine large moves (see the 2026-08-01 AAPL false STOP_REACHED
    incident: last read ~$283 while bid/ask and real trades were ~$300-301).

    Falls back to a much looser prevclose comparison when bid/ask are
    unavailable (Tradier reports bid=ask=0 outside market hours) — that
    fallback only catches egregiously corrupted data, not ordinary moves.
    """
    if bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2
        deviation = abs(last - mid) / mid
        if deviation > _quote_sanity_bidask_pct():
            log_event("quote_sanity_reject", symbol, {
                "last": last, "bid": bid, "ask": ask, "mid": round(mid, 2),
                "deviation_pct": round(deviation, 4),
                "threshold_pct": _quote_sanity_bidask_pct(),
                "check": "bid_ask",
            })
            return False
        return True

    if prevclose > 0:
        deviation = abs(last - prevclose) / prevclose
        if deviation > _quote_sanity_fallback_pct():
            log_event("quote_sanity_reject", symbol, {
                "last": last, "prevclose": prevclose,
                "deviation_pct": round(deviation, 4),
                "threshold_pct": _quote_sanity_fallback_pct(),
                "check": "prevclose_fallback",
            })
            return False

    return True
```

- [ ] **Step 2: Wire the guard into `fetch_quotes()`**

Find `fetch_quotes()` (currently around line 625, after commit `fc2f0c8`'s changes):

```python
def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    try:
        resp = httpx.get(
            f"{_tradier_base()}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": ",".join(symbols)},
            timeout=10,
        )
        resp.raise_for_status()
        quote_data = resp.json().get("quotes", {}).get("quote", [])
        if isinstance(quote_data, dict):
            quote_data = [quote_data]
        result = {}
        for q in quote_data:
            sym = q.get("symbol", "")
            raw_last = q.get("last")
            raw_close = q.get("close")
            last = raw_last or raw_close or 0
            prev = q.get("prevclose") or last
            if sym and not raw_last and raw_close:
                log_event("quote_fallback_to_close", sym, {
                    "raw_last": raw_last,
                    "raw_close": raw_close,
                    "used_price": float(last),
                })
            if sym and last:
                result[sym] = {"last": float(last), "prevclose": float(prev)}
        return result
    except Exception:
        return {}
```

Replace the loop body so the sanity check runs right before a quote is added to `result`:

```python
def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    try:
        resp = httpx.get(
            f"{_tradier_base()}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": ",".join(symbols)},
            timeout=10,
        )
        resp.raise_for_status()
        quote_data = resp.json().get("quotes", {}).get("quote", [])
        if isinstance(quote_data, dict):
            quote_data = [quote_data]
        result = {}
        for q in quote_data:
            sym = q.get("symbol", "")
            raw_last = q.get("last")
            raw_close = q.get("close")
            last = raw_last or raw_close or 0
            prev = q.get("prevclose") or last
            if sym and not raw_last and raw_close:
                log_event("quote_fallback_to_close", sym, {
                    "raw_last": raw_last,
                    "raw_close": raw_close,
                    "used_price": float(last),
                })
            if not (sym and last):
                continue
            bid = float(q.get("bid") or 0)
            ask = float(q.get("ask") or 0)
            if not _quote_is_sane(sym, float(last), bid, ask, float(prev)):
                continue
            result[sym] = {"last": float(last), "prevclose": float(prev)}
        return result
    except Exception:
        return {}
```

- [ ] **Step 3: Run the new tests and confirm they pass**

Run:
```bash
cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_market_data_fixes.py -k "quote_sanity or bidask or prevclose_fallback" -v
```
Expected: All 5 tests **PASS**.

- [ ] **Step 4: Commit**

```bash
git add backend/app/data/market.py
git commit -m "fix(market): reject quotes whose last disagrees with live bid/ask

Guards against a single bad/stale Tradier tick firing a false Critical
portfolio alert (2026-08-01 AAPL false STOP_REACHED: last read ~\$283
while bid/ask and real trades were ~\$300-301). fetch_quotes now excludes
any quote whose last deviates from its own bid/ask midpoint by more than
risk_rules.yaml's quote_sanity.max_bidask_deviation_pct (default 5%),
falling back to a looser prevclose comparison when bid/ask are
unavailable outside market hours. Rejections are logged to audit.log as
quote_sanity_reject for diagnosis and threshold tuning."
```

---

### Task 4: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full market + alerts test suites**

Run:
```bash
cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_market_data_fixes.py tests/test_alerts.py -v
```
Expected: All tests pass except the 4 pre-existing `ModuleNotFoundError: No module named 'tastytrade'` failures (confirmed pre-existing and unrelated to this work — see the prior session's handoff notes).

- [ ] **Step 2: Run the full backend suite**

Run:
```bash
cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest -q
```
Expected: Same pass/fail counts as before this change, plus the 5 new tests passing. If any *other* test now fails, read its failure carefully — the most likely cause would be a test that mocks `httpx.get` for `/v1/markets/quotes` with a payload lacking `bid`/`ask`/`prevclose` fields, which would now hit the prevclose-fallback branch. Check `tests/test_scan_endpoint.py`, `tests/test_stock_scan_persistence.py`, `tests/test_stock_scan_router.py`, `tests/test_analyze_stock.py` first — these mock `fetch_quotes` directly (grep confirmed no other test file exercises `fetch_quotes`'s internals), so they should be unaffected, but verify.

- [ ] **Step 3: No commit needed** — this task is verification-only, no files changed.

---

## Self-Review Notes

- **Spec coverage:** The task was "sanity guard to reject/flag implausible price jumps before they fire a Critical alert." Task 3 implements the reject; Task 2 proves it against the exact reproduction values from the original incident; the "What this does and does not fix" section above documents the two alert types this covers (STOP_REACHED, TP_HIT via `fetch_quotes`) and the one it doesn't (PREMIUM_STOP, different data path — explicitly deferred, matching how the original logging plan deferred this same guard).
- **Existing reserved config note:** `risk_rules.yaml` already has an unrelated reserved key, `auto_trade.gap_threshold_pct` ("reserved: future percentage buffer around stop"). That's a different mechanism (how far past the stop to require before firing) from this guard (whether the quote itself is trustworthy) — intentionally left untouched, not reused, to avoid conflating two different concerns under one config key.
- **No changes needed in `alert_generator.py` or `portfolio_alert_monitor.py`** — verified both already treat a symbol absent from `current_prices` as "skip price-based alerts this tick" (`price is not None` guards at `alert_generator.py:90` and `:113`), so excluding a bad quote from `fetch_quotes()`'s result is sufficient on its own.
