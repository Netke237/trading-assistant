# Alert Price Audit Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a portfolio alert (TP_HIT, STOP_REACHED, PREMIUM_STOP) fires, record the exact price data that triggered it to a persistent, greppable audit trail, and make the STOP_REACHED alert text show the actual triggering price instead of only the static stop level — so a future false-positive (like the AAPL "Stop hit at $283.35" alert that fired despite AAPL trading at ~$301 the whole time) can be diagnosed after the fact instead of being unprovable.

**Context:** Root-caused in this session: `backend/app/services/portfolio_alert_monitor.py` polls Tradier's live quotes endpoint every 60s via `fetch_quotes()` in `backend/app/data/market.py`, and `generate_alerts()` in `backend/app/services/alert_generator.py` compares the returned price to each position's stop/target. Verified against Tradier's own 1-minute trade history that AAPL never dropped near the $283.35 stop during the relevant window — the live quote used at that one poll was bad, but nothing was logged, so the actual bad number is unrecoverable. Two gaps caused that: (1) `fetch_quotes()` silently falls back from `last` to `close` with no record of when/why, and (2) `generate_alerts()` never records what price it used when an alert fires, and the STOP_REACHED message itself only ever shows the stop level, never the price that breached it.

**Architecture:** Reuse the project's existing structured audit trail (`app.services.audit.log_event`, JSONL lines appended to `backend/audit.log`, already gitignored) rather than inventing a new logging mechanism. Two call sites get instrumented: the quote fallback path in `market.py`, and each alert-fired branch in `alert_generator.py`. The STOP_REACHED reason string (backend and its frontend mirror in `alertEngine.ts`) gets the triggering price appended so the message is self-explanatory without needing to check logs at all.

**Tech Stack:** Python (FastAPI backend), pytest + `unittest.mock`, TypeScript (frontend), Jest.

---

### Task 1: Log quote fallback anomalies in `fetch_quotes()`

**Files:**
- Modify: `backend/app/data/market.py:17` (import) and `backend/app/data/market.py:625-646` (`fetch_quotes`)
- Test: `backend/tests/test_market_data_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `backend/tests/test_market_data_fixes.py`:

```python
def test_fetch_quotes_logs_fallback_to_close():
    """When Tradier's quote has no 'last' price and we fall back to 'close',
    that fallback must be recorded via log_event so a bad/stale price used
    by an alert can be traced back after the fact."""
    from app.data import market

    with (
        patch("app.data.market.TRADIER_TOKEN", "fake-token"),
        patch("app.data.market.httpx.get") as mock_get,
        patch("app.data.market.log_event") as mock_log_event,
    ):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": None, "close": 283.35, "prevclose": 282.0},
                ]
            }
        }
        mock_get.return_value = mock_resp

        result = market.fetch_quotes(["AAPL"])

    assert result["AAPL"]["last"] == 283.35
    mock_log_event.assert_called_once()
    event_type, rec_id, payload = mock_log_event.call_args.args
    assert event_type == "quote_fallback_to_close"
    assert rec_id == "AAPL"
    assert payload["raw_last"] is None
    assert payload["raw_close"] == 283.35
    assert payload["used_price"] == 283.35


def test_fetch_quotes_does_not_log_when_last_present():
    """A normal quote (last present) must not trigger the fallback log."""
    from app.data import market

    with (
        patch("app.data.market.TRADIER_TOKEN", "fake-token"),
        patch("app.data.market.httpx.get") as mock_get,
        patch("app.data.market.log_event") as mock_log_event,
    ):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": 301.05, "close": 300.90, "prevclose": 299.80},
                ]
            }
        }
        mock_get.return_value = mock_resp

        result = market.fetch_quotes(["AAPL"])

    assert result["AAPL"]["last"] == 301.05
    mock_log_event.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_market_data_fixes.py::test_fetch_quotes_logs_fallback_to_close -v`
Expected: FAIL — `AttributeError: <module 'app.data.market'> does not have the attribute 'log_event'` (nothing imports `log_event` into `market.py` yet).

- [ ] **Step 3: Add the import and instrument `fetch_quotes()`**

In `backend/app/data/market.py`, add the import after the existing `from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS` line (line 17):

```python
from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS
from app.services.audit import log_event
```

Replace the body of `fetch_quotes()` (currently lines 625-646):

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_market_data_fixes.py -v -k fetch_quotes`
Expected: PASS (both new tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_data_fixes.py
git commit -m "feat(alerts): log quote fallback-to-close anomalies for diagnosability"
```

---

### Task 2: Log alert-fired events and show the triggering price in STOP_REACHED

**Files:**
- Modify: `backend/app/services/alert_generator.py`
- Test: `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests**

Add near the top of `backend/tests/test_alerts.py`, after the existing imports (after line 16 `from app.models.portfolio import PortfolioPositionModel`):

```python
from unittest.mock import patch
```

Add these test functions to the end of the file:

```python
# ── Test: STOP_REACHED message includes the triggering price, not just stop ──

@pytest.mark.asyncio
async def test_stop_reached_reason_includes_triggering_price(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", stop=180.0)
    prices = {"AAPL": 175.0}
    alerts = await generate_alerts(db_session, prices)
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert "$175.00" in stop_alerts[0].reason
    assert "$180.00" in stop_alerts[0].reason


# ── Test: STOP_REACHED writes a structured audit event with price + stop ─────

@pytest.mark.asyncio
async def test_stop_reached_writes_audit_event(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(db_session, symbol="AAPL", stop=180.0, rec_id="REC-AUDIT-1")
    prices = {"AAPL": 175.0}
    with patch("app.services.alert_generator.log_event") as mock_log_event:
        await generate_alerts(db_session, prices)
    calls = [c for c in mock_log_event.call_args_list if c.args[0] == "alert_fired"]
    assert len(calls) == 1
    event_type, rec_id, payload = calls[0].args
    assert rec_id == "REC-AUDIT-1"
    assert payload["alertType"] == "STOP_REACHED"
    assert payload["symbol"] == "AAPL"
    assert payload["price"] == 175.0
    assert payload["stop"] == 180.0


# ── Test: TP_HIT and PREMIUM_STOP also write audit events ────────────────────

@pytest.mark.asyncio
async def test_all_alert_types_write_audit_events(db_session):
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, rec_id="REC-TP", symbol="TPX", contract="TPX|1|2026-05-16|C",
        targets=[{"stockPrice": 100.0, "stock_price": 100.0}], stop=None,
    )
    await _insert_position(
        db_session, rec_id="REC-STOP", symbol="STOPX", contract="STOPX|1|2026-05-16|C",
        stop=50.0, targets=[],
    )
    await _insert_position(
        db_session, rec_id="REC-PREM", symbol="PREMX", contract="PREMX|1|2026-05-16|C",
        entry_price=5.0, stop=None, targets=[],
    )
    prices = {"TPX": 105.0, "STOPX": 45.0, "PREMX": 200.0}
    opt_prices = {"PREMX|1|2026-05-16|C": 2.0}  # 2.0 <= 5.0 * 0.60 = 3.0

    with patch("app.services.alert_generator.log_event") as mock_log_event:
        await generate_alerts(db_session, prices, opt_prices)

    fired_types = {
        c.args[2]["alertType"]
        for c in mock_log_event.call_args_list
        if c.args[0] == "alert_fired"
    }
    assert fired_types == {"TP_HIT", "STOP_REACHED", "PREMIUM_STOP"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_alerts.py -v -k "triggering_price or writes_audit_event or all_alert_types"`
Expected: FAIL — `test_stop_reached_reason_includes_triggering_price` fails because the reason string doesn't contain `$175.00`; the two audit-event tests fail with `AttributeError: <module 'app.services.alert_generator'> does not have the attribute 'log_event'`.

- [ ] **Step 3: Add the import and instrument `generate_alerts()`**

In `backend/app/services/alert_generator.py`, add the import after the existing `from app.schemas import AlertItem` line (line 13):

```python
from app.schemas import AlertItem
from app.services.audit import log_event
```

Replace the TP_HIT block (currently lines 88-106):

```python
        # TP_HIT — direction-aware: bullish targets are above current price, bearish below
        is_bearish = pos.direction == "Bearish"
        if targets and price is not None:
            first_target = targets[0]
            target_stock_price = (
                first_target.get("stock_price") or first_target.get("stockPrice") or 0
            )
            hit_raw = (price <= target_stock_price) if is_bearish else (price >= target_stock_price)
            if _sustained("TP_HIT", hit_raw):
                counter += 1
                log_event("alert_fired", pos.rec_id, {
                    "symbol": symbol,
                    "alertType": "TP_HIT",
                    "price": price,
                    "target": target_stock_price,
                    "direction": pos.direction,
                })
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Target reached — {symbol} at ${price:.2f}",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TP_HIT",
                ))
```

Replace the STOP_REACHED block (currently lines 108-123):

```python
        # STOP_REACHED — direction-aware: puts are invalidated when stock rises above stop
        stop_breached_raw = (
            (price >= pos.stop) if is_bearish
            else (price <= pos.stop)
        ) if (pos.stop is not None and price is not None) else False
        if pos.stop is not None and price is not None and _sustained("STOP_REACHED", stop_breached_raw):
            counter += 1
            log_event("alert_fired", pos.rec_id, {
                "symbol": symbol,
                "alertType": "STOP_REACHED",
                "price": price,
                "stop": pos.stop,
                "direction": pos.direction,
            })
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Stop breached — {symbol} {'above' if is_bearish else 'below'} ${pos.stop:.2f} (price ${price:.2f})",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STOP_REACHED",
            ))
```

Replace the PREMIUM_STOP block (currently lines 125-140):

```python
        # PREMIUM_STOP
        premium_hit_raw = bool(
            opt_price is not None and pos.entry_price > 0
            and opt_price <= pos.entry_price * _premium_stop_pct()
        )
        if _sustained("PREMIUM_STOP", premium_hit_raw):
            counter += 1
            log_event("alert_fired", pos.rec_id, {
                "symbol": symbol,
                "alertType": "PREMIUM_STOP",
                "optPrice": opt_price,
                "entryPrice": pos.entry_price,
                "thresholdPct": _premium_stop_pct(),
            })
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Premium stop — {symbol} option at ${opt_price:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="PREMIUM_STOP",
            ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_alerts.py -v`
Expected: PASS — all tests in the file, including the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alert_generator.py backend/tests/test_alerts.py
git commit -m "feat(alerts): audit-log alert triggers and show live price in STOP_REACHED text"
```

---

### Task 3: Mirror the STOP_REACHED price text in the frontend alert engine

**Files:**
- Modify: `frontend/lib/alertEngine.ts:71-80`
- Test: `frontend/lib/__tests__/alertEngine.test.ts`

- [ ] **Step 1: Write the failing test**

In `frontend/lib/__tests__/alertEngine.test.ts`, replace the existing test at line 25-29:

```ts
  it('fires STOP_REACHED even when the symbol is flagged as a scan conflict', () => {
    useScanStore.getState().setConflictedSymbols(['NVDA']);
    const out = scanPortfolio([pos()]);
    expect(out.some((a) => a.symbol === 'NVDA' && a.alertType === 'STOP_REACHED')).toBe(true);
  });
```

with:

```ts
  it('fires STOP_REACHED even when the symbol is flagged as a scan conflict', () => {
    useScanStore.getState().setConflictedSymbols(['NVDA']);
    const out = scanPortfolio([pos()]);
    expect(out.some((a) => a.symbol === 'NVDA' && a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('STOP_REACHED reason includes the triggering price, not just the stop', () => {
    // Deliberately non-default values (makePosition defaults to currentPrice:
    // 90, stop: 95) so this test can't pass by coincidentally matching them.
    const out = scanPortfolio([pos({ currentPrice: 80, stop: 85 })]);
    const stopAlert = out.find((a) => a.alertType === 'STOP_REACHED');
    expect(stopAlert?.reason).toContain('$85.00');
    expect(stopAlert?.reason).toContain('$80.00');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=alertEngine`
Expected: FAIL — `STOP_REACHED reason includes the triggering price, not just the stop` fails because the reason string is currently `Stop breached — NVDA below $95.00` with no `$90.00`.

- [ ] **Step 3: Update the reason string**

In `frontend/lib/alertEngine.ts`, replace line 71-80:

```ts
    const stopBreached = p.stop > 0 && (isBearish ? p.currentPrice >= p.stop : p.currentPrice <= p.stop);
    if (stopBreached) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STOP_REACHED',
        reason: `Stop breached — ${p.symbol} ${isBearish ? 'above' : 'below'} $${p.stop.toFixed(2)} (price $${p.currentPrice.toFixed(2)})`,
      });
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=alertEngine`
Expected: PASS — all tests in `alertEngine.test.ts`.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/alertEngine.ts frontend/lib/__tests__/alertEngine.test.ts
git commit -m "fix(alerts): show triggering price in STOP_REACHED alert text (frontend)"
```

---

### Task 4: Full verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest`
Expected: PASS — no regressions in `test_alerts.py`, `test_market_data_fixes.py`, or any other file (in particular `test_alert_notifier.py`, which constructs its own literal reason strings and is unaffected by the generator's format change).

- [ ] **Step 2: Run the full frontend test suite and typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean, no errors.

Run: `cd frontend && npm run test`
Expected: PASS — no regressions, in particular `alertStore.test.ts` (uses hand-written literal reasons, unaffected).

- [ ] **Step 3: Commit is already done per-task — no additional commit needed here.**

---

## What this does and does not fix

- **Does:** gives every future TP_HIT/STOP_REACHED/PREMIUM_STOP alert a permanent, greppable record (`backend/audit.log`, JSONL) of the exact price/stop/target used, plus flags every quote that had to fall back from `last` to `close`. Makes the STOP_REACHED Telegram/toast text show the actual price that breached the stop, not just the stop level.
- **Does not:** prevent a bad quote from firing a false alert in the first place (that was the separately-proposed "sanity guard" — out of scope here per your "for logging" instruction). If you want that too, say so and I'll plan it separately.
- **Known limitation (inherited, not introduced by this plan):** the fallback-detection condition (`not raw_last and raw_close`) can't distinguish a missing `last` from a legitimate `last: 0` print — both look identical to the pre-existing `last = raw_last or raw_close or 0` chain this plan builds on. A real $0 print is not a realistic scenario for a liquid stock, so this is left as-is rather than reworking the underlying fallback semantics, which is out of scope for a logging-only change.
- **Known limitation (pre-existing, shared infrastructure):** `backend/audit.log` is an append-only JSONL file with no rotation or retention policy, already used by `log_approval`/`log_rejection`/`log_override` for other event types. This plan adds more write volume (every alert fire, potentially every 60s poll cycle) to that same file but does not add rotation — changing that would affect all existing audit event types, not just alerts, so it's left for a separate plan if it becomes a problem.
