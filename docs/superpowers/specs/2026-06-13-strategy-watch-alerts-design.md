# Strategy Watch & Alerts — Design Spec

**Date:** 2026-06-13
**Status:** Approved (brainstorming) — ready for implementation planning

## Goal

Let Kenneth pin a strategy to a stock ("watch AAPL with Pullback EMA") and receive a
Gmail/Telegram alert when that strategy produces a **buy setup**, when an entered trade
hits its **stop or target** (exit), or when an **opposite signal** appears (reversal).
Conceptually mirrors TradingView's "apply a strategy to a chart and alert me", adapted
to Bamendjou's daily-bar, EOD-first data model.

## Scope

**In scope (this build):**
- A persisted list of (symbol, strategy) watch entries — add one with a strategy pick, or
  bulk-apply one strategy to many stocks.
- A background evaluator that runs each watched strategy on the latest daily bars and
  classifies state transitions into **entry / exit / reversal** events.
- Notification on *new* transitions only (no repeat alerts for a standing signal), delivered
  through the existing Gmail/Telegram dispatcher.
- A scheduler supporting **EOD** (run once after the close) and **intraday-poll** (every N
  hours during market hours) cadences.
- REST CRUD + manual "evaluate now" endpoint.
- A frontend "Strategy Watch" page to manage the list and see each watch's current state.

**Deferred (documented seam, not built):**
- **Real-time streaming alerts** via `tradier_stream.py`. This is a different delivery
  mechanism, depends on a configured live Tradier feed, and is built as a follow-on.
- **Reversal alerts are wired but dormant**: all four strategy functions currently emit
  `Bullish` signals only, so the opposite-signal branch never fires today. It activates
  automatically if/when bearish signal variants are added. (Kept in the state machine so no
  rework is needed later.)

## Reused building blocks (no changes needed)

| Piece | What it gives us |
|---|---|
| `app/services/strategy_engine.py` | `pullback_ema_signal`, `breakout_base_signal`, `ma_crossover_signal`, `mean_reversion_rsi_signal` → each `(bars, **kwargs) -> StrategySignal | None`. `StrategySignal` carries `direction`, `entry_price`, `stop_price`, `target_price`, `atr`, `rr_ratio`. |
| `app/routers/stock_scan.py:_SIGNAL_FNS` | The canonical strategy-key → function registry (and `_SIGNAL_KWARGS` default param shapes). |
| `app/services/historical_store.py:get_bars(symbol, start, end)` | DB-first daily bars (Alpaca → Tiingo → yfinance). |
| `app/services/notifications/dispatch.py:notify_enabled_channels(subject, plain, html)` | Sends to every enabled channel (Gmail/Telegram) and logs to `sent_log`. |
| `app/services/scan_scheduler.py:ScanScheduler` | Template for the background loop (`bind/start/stop/get_status`). |
| `app/services/credential_store.py:CredentialStore` | Template for a thread-safe, YAML-backed persisted store with a module singleton. |
| `app/services/historical_store.py:most_recent_trading_day()` | Trading-day awareness for the EOD trigger. |

## Architecture

Five new units, each with one job:

### 1. `app/services/strategy_watch_store.py` — persistence
Thread-safe, YAML-backed store (mirrors `CredentialStore`). File: `config/strategy_watches.yaml`.

Two blocks: a `watches` list and a `schedule` config.

```yaml
schedule:
  enabled: false
  mode: eod            # eod | poll
  eod_time: "16:15"    # local HH:MM, weekdays only
  poll_hours: 4        # used when mode == poll
watches:
  - id: "wch_<uuid4hex>"
    symbol: "AAPL"
    strategy_key: "pullback_ema"
    params_override: {}        # optional kwargs that override strategy defaults
    enabled: true
    created_at: "2026-06-13T18:00:00Z"
    last_state:
      phase: "idle"            # idle | armed | exited
      direction: null          # Bullish | Bearish | null
      entry_price: null
      stop_price: null
      target_price: null
      last_event: null         # entry | exit_target | exit_stop | reversal
      last_event_at: null
```

API: `list_watches()`, `add_watch(symbol, strategy_key, params_override=None)`,
`add_watches_bulk(symbols, strategy_key)`, `remove_watch(id)`, `set_enabled(id, bool)`,
`update_state(id, new_state)`, `get_schedule()`, `set_schedule(cfg)`. Symbols upper-cased;
strategy_key validated against `_SIGNAL_FNS` keys; duplicate (symbol, strategy_key) pairs
are rejected.

### 2. `app/services/strategy_watch_evaluator.py` — the signal state machine
`async def evaluate_all() -> list[WatchEvent]` iterates enabled watches; per entry:

1. `bars = await get_bars(symbol, today - 2y, today)` (2y covers the 200-SMA strategy).
2. `signal = _SIGNAL_FNS[strategy_key](bars, **merged_params)` (defaults from `_SIGNAL_KWARGS`-style
   base merged with `params_override`).
3. `close = bars[-1]["close"]`.
4. State machine on `last_state.phase`:
   - **idle** → if `signal` is not `None`: emit **entry** event; set phase `armed`, store
     direction/entry/stop/target.
   - **armed** →
     - `close <= stop_price` → **exit_stop** event; reset to `idle`.
     - `close >= target_price` → **exit_target** event; reset to `idle`.
     - fresh signal with opposite direction → **reversal** event; re-arm to new direction
       (dormant until bearish signals exist).
     - otherwise → no event (standing position; suppresses repeat alerts).
   - **exited** is transient — collapsed back to `idle` on write.
5. Persist new `last_state` via `store.update_state`. Return a `WatchEvent` per fired transition.

`WatchEvent` dataclass: `watch_id, symbol, strategy_key, event_type, direction, entry, stop,
target, rr_ratio, close, reason`. Pure (no network beyond `get_bars`) and unit-testable by
feeding synthetic bars.

A thin `async def evaluate_and_notify()` calls `evaluate_all()`, formats each event into a
subject + plain/HTML body, and calls `notify_enabled_channels`. Dedup is structural: the
state machine only returns *transitions*, so the same standing setup never re-notifies.

### 3. `app/services/strategy_watch_scheduler.py` — cadence loop
One asyncio loop (template: `ScanScheduler`) ticking every 5 min. Each tick reads
`store.get_schedule()`:
- **mode == poll**: run `evaluate_and_notify()` if `now - last_run >= poll_hours` and the
  market is open.
- **mode == eod**: run once per trading day if `now >= today's eod_time` and we have not run
  since the last close.

Exposes `start()`, `stop()`, `get_status()`, `run_now()`. Disabled schedule → loop idles.
Started from `main.py` lifespan alongside the other background tasks; stopped on shutdown.

### 4. `app/routers/strategy_watch.py` — REST API
`prefix="/api/strategy-watch"`:
- `GET    /`              → list watches (+ current state)
- `POST   /`              → add one `{symbol, strategy_key, params_override?}`
- `POST   /bulk`          → add many `{symbols: [...], strategy_key}`
- `DELETE /{id}`          → remove
- `PATCH  /{id}`          → `{enabled}`
- `GET    /schedule`      → schedule config
- `PUT    /schedule`      → update `{enabled, mode, eod_time, poll_hours}`
- `POST   /evaluate`      → run `evaluate_and_notify()` now; return fired events
- `GET    /status`        → scheduler status
Registered in `main.py`.

### 5. Frontend — Strategy Watch page
- `app/(frame)/strategy-watch/page.tsx` + `.module.css` — list of watches with state pills
  (Waiting / Buy setup live / In trade / Exited), an "Add watch" row (symbol + strategy
  dropdown), a "Bulk apply" control (one strategy → comma-separated symbols), a schedule
  panel (mode + time/interval + enable toggle), and an "Evaluate now" button.
- `lib/strategyWatchStore.ts` — Zustand store fronting the API, following the project SSR
  pattern (SSR guard + `skipHydration` + `StoreHydration`; avoid `?? []` in selectors).
- `lib/api.ts` — `getStrategyWatches`, `addStrategyWatch`, `addStrategyWatchesBulk`,
  `removeStrategyWatch`, `setStrategyWatchEnabled`, `getStrategyWatchSchedule`,
  `setStrategyWatchSchedule`, `evaluateStrategyWatches`, `getStrategyWatchStatus`.
- Nav entry added to reach the page.

## Data flow

```
Scheduler tick ──> evaluate_and_notify()
                      └─> evaluate_all()
                            └─ per watch: get_bars ─> strategy fn ─> state machine ─> WatchEvent
                      └─> notify_enabled_channels(subject, plain, html)  [Gmail/Telegram]
                      └─> store.update_state(...)                        [persist last_state]

Frontend page ──(REST)──> strategy_watch router ──> strategy_watch_store / evaluator
```

## Error handling
- `get_bars` failure or too-few-bars for a symbol → that watch is skipped this cycle, logged
  at WARNING, no state change, no alert. One bad symbol never aborts the batch.
- Unknown `strategy_key` on add → 400. Duplicate (symbol, strategy_key) → 409.
- Notification send failures are already swallowed/logged by `dispatch._safe_notify`.
- Scheduler loop catches per-tick exceptions and stays alive (same contract as `ScanScheduler`).
- Store writes are atomic (temp-file + replace, as in `CredentialStore.save`).

## Testing
- **`test_strategy_watch_store.py`** — add/bulk/remove/enable, dup rejection, validation,
  persistence round-trip (load from a tmp file).
- **`test_strategy_watch_evaluator.py`** — state machine with synthetic bars: idle→entry,
  armed→exit_stop, armed→exit_target, standing position emits nothing, get_bars failure is
  skipped. Strategy fns mocked to return controlled `StrategySignal`s.
- **`test_strategy_watch_scheduler.py`** — eod trigger fires once/day; poll respects interval
  and market-open; disabled schedule idles.
- **`test_strategy_watch_router.py`** — each endpoint, dup 409, unknown-strategy 400, evaluate
  returns events (evaluator mocked).
- Frontend: `npm run typecheck` clean; manual visual verification of the page.

## Out of scope (explicit)
- Auto-execution of orders from these alerts (a separate concern; `AutoTradeService` already
  exists for manual arming).
- Options-contract-level strategy watching (stocks only, matching the strategy engine).
- Real-time streaming (deferred seam above).
- Per-user accounts/multi-tenancy (single-user app).
