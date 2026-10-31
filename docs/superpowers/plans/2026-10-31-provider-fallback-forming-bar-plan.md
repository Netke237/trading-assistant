# PROVIDER-FALLBACK-FORMING-BAR — plan (#536)

Board item #536 · branch `board/provider-fallback-forming-bar-674c6d87` · cut from `origin/main` `c8f3b8a2` (after #534 REGIME-SERIES-LENGTH, PRs #568/#569).
Decision respected: `WATCH-RULE-BAR-PARITY-Q-H-FETCH-RULE-2026-09-28` (settled-day DB fetching unchanged; nothing here touches `historical_store`).

## 1. What the code does today (re-read on `c8f3b8a2`; the issue's line numbers predate #534)

- **Options scan, normal path.** `_execute_scan_core` prefetches `bars_map` from `historical_store.get_bars` (`backend/app/routers/scan.py:1863-1879`). Stored daily rows are settled only (16:00 ET + 2 h), so those candles never contain a forming bar.
- **Options scan, DB miss.** `_process_symbol` (`scan.py:632-655`) falls back to `fetch_candles_async(client, symbol)` (`backend/app/data/market.py:1695-1748`). That function requests Tradier history with `end = date.today()` and, on failure, yfinance; neither drops today's bar. During the session Tradier/yfinance return a today-dated bar whose OHLCV is still moving.
- **What the forming bar reaches now.** Since `25fb450f` (#534 unit 2) the *daily* regime is read from DB history only (`get_daily_regime_bars`, `scan.py:727-728`), so the fallback candles no longer feed the regime. They still feed the **scoring**: `_aligned_benchmark` (`:808`), both `score_stock` passes (`:812`, `:916`), `compute_confidence` (`:907`), the ATR stop (`:1130`) and `resolve_t1_target` (`:1221`). So a DB-miss symbol mid-session gets a score, confidence, stop and target computed on a partial bar — numbers in front of the user.
  - Side effect worth naming: with the relative-strength trend method on, the benchmark (DB, settled) ends at D-1 while the forming candles end at D, so `_aligned_benchmark` returns `None` and the trend is left unmeasured → the symbol is dropped as "no data". Trimming fixes that too.
- **The fire path.** The issue says the fire path drops a today-dated bar while `todays_bar_is_unclosed()` is true. That trim was in `auto_trader._fetch_scan_window_bars`; since `25fb450f` the fire path reads settled DB bars only, so it never sees a forming bar at all. The *rule* the issue asks for (no forming daily bar) is unchanged; only its old implementation moved.
- **Shared cache.** `market._candles_cache` is one dict keyed by symbol, written by both `fetch_candles` (sync) and `fetch_candles_async`, stamped with the host `date.today()`. A cache entry can hold a forming bar whoever wrote it.

## 2. The change

One read-side trim inside `fetch_candles_async`, applied to whatever it returns (cache hit, Tradier, yfinance):

```python
def _daily_bar_clock() -> datetime:
    """Now in MARKET_TZ; a seam so tests can pin the session clock."""
    from app.services.scheduling_tz import MARKET_TZ
    return datetime.now(MARKET_TZ)

def _completed_daily_candles(rows: list[dict]) -> list[dict]:
    # lazy import: market_session imports strategy_watch_scheduler, whose chain
    # reaches back into app.data -> a module-level import here would cycle.
    from app.services.composite_trigger_evaluator import completed_daily_rows
    return completed_daily_rows(rows, _daily_bar_clock())
```

`fetch_candles_async` returns `_completed_daily_candles(data)` on the cache hit and `_completed_daily_candles(rows)` at the end. **The cache keeps the raw provider rows** (written exactly as today); only the returned list is trimmed. Reason: the sync `fetch_candles` shares the entry and accepts it only `if len(data) >= bars`; caching a trimmed list would make the sync reader miss and rewrite it, and a trimmed cache stamped "today" would also hide the closed day-D bar after 16:00 for the rest of the day.

Why `completed_daily_rows` (`composite_trigger_evaluator.py:400`) and not a fresh `todays_bar_is_unclosed` check: it is the repo's existing trim for ISO-date daily rows (used by `composite_watch`), and it *is* the `todays_bar_is_unclosed` rule — it cuts every trailing row dated after `last_session_close(now)`, and `last_session_close` returns today's 16:00 close only when today is a weekday and `todays_bar_is_unclosed(now)` is False, else the previous weekday's close. On a weekday that is exactly "drop a today-dated bar while `todays_bar_is_unclosed()`". It also anchors "today" in `MARKET_TZ` rather than the host's `date.today()`, so the operator's Berlin host gives the same answer as a New York one (the old fire-path trim's documented host-date residual does not come back). It never mutates its input (`list(bars)`), so the cached list is safe. A row whose `time` is not an ISO date is dropped (fail closed, last row only) — provider rows here are always `YYYY-MM-DD`.

Behaviour by clock (NY time, weekday D): before 09:30 → a D-dated row is dropped; 09:30–16:00 inclusive → dropped; after 16:00 → kept; weekend → Friday's row kept. Inherited residuals, unchanged and not widened: no half-day/holiday calendar (a 13:00 early-close bar is still trimmed until 16:00); the 16:00:00.000000 inclusive edge; between 16:00 and the DB's 18:00 settle the fallback keeps day D while DB-path symbols end at D-1 (the mismatch decision Q-H accepted).

## 3. Every `fetch_candles_async` caller (the issue asks for this check)

| Caller | Uses candles for | Effect of the trim | Verdict |
|---|---|---|---|
| `scan.py:643`, `:650` — Options DB miss | score, confidence, ATR stop, T1, RS benchmark alignment | completed bars only, same as the DB path | **the fix** |
| `market.py:1773` `prewarm_candles_async` | warms the cache; counts non-empty | cache still raw; count unchanged except a symbol whose only row is today's | harmless |
| `contracts.py:759` `/contracts/structural-stop` | `find_structural_stop` over the list | a partial bar's low/high can no longer become the "swing" stop; matches the stop the scan computed from DB bars | apply (parity with the scan card) |
| `contracts.py:938` `/contracts/first-passage` | price history for the barrier model (`estimate_*_first_passage(candles=...)`) | history from completed bars | apply |
| `contracts.py:1158` `/contracts/exit-plan` | ATR + structural stop | same | apply |
| `stock_scan.py:2638` `/stocks/first-passage`, `:2858` `/stocks/exit-plan` | same as the contracts endpoints | same | apply |

All of these price off `req.stock_price` (live) for the entry; only the history changes, by at most one trailing bar, and only before the close. No caller reads the last candle as "today's price". The sync `fetch_candles` (regime router, regime monitor) is **not changed**: out of this item's scope (it is not the Options-scan fallback), recorded as a follow-up candidate in the state entry.

## 4. Ticket (one build unit)

**T1 — test-first trim in `fetch_candles_async`** (`backend/app/data/market.py`, new `backend/tests/test_provider_fallback_forming_bar.py`).

Failing tests first (must fail on `c8f3b8a2`, pass after):
1. Tradier history ending with a row dated NY-today, `_daily_bar_clock` pinned mid-session (e.g. 2026-06-10 11:00 ET, rows ending `2026-06-10`) → returned list ends `2026-06-09`.
2. Same rows, clock pre-open (08:00 ET) → dropped; clock 17:00 ET → kept.
3. Tradier fails, yfinance (`_fetch_daily_yf` patched) returns a today-dated row mid-session → dropped.
4. Cache hit: `_candles_cache[sym]` pre-filled (today's host stamp) with rows ending NY-today, mid-session → returned list trimmed, **and the cache entry is still the untrimmed list** (identity/length unchanged).
5. Host-zone independence: clock given as a UTC instant equal to 11:00 ET → same result as test 1.
6. **Acceptance test at the scan seam:** `_process_symbol` (or the narrowest existing scan test seam — follow `tests/test_scan_db_first.py`) with `bars_map` missing the symbol, the real `fetch_candles_async` over a mocked Tradier history ending NY-today, clock mid-session → the candles passed to `score_stock` end at D-1 (spy on the scorer). This is the issue's "a DB-miss symbol mid-session is measured on completed bars only".

Existing tests that call the real `fetch_candles_async` use past-dated rows (`tests/test_market_data_fixes.py`, `tests/test_tradier_governor_market.py`), so they are unaffected whatever the wall clock; the implementer confirms by running them.

Done = the six tests pass, `cd backend && pytest` full suite green on Python 3.11, no other file changed except the two above (plus the state/plan records the coordinator writes). No frontend change → typecheck not affected, run anyway for the record.

## 5. Audit and ship

Plan round (fresh gate-auditor) → T1 → `git merge origin/main` → code round 1 on `origin/main..branch` (cap 3 per stage) → PR `Closes #536` → board.md step 7 self-merge or `waiting-merge`.
Gate: a finding blocks only if it can put a wrong number in front of a user or on a broker order, or corrupt persisted data.
